from __future__ import annotations

import builtins
import json
import os
import platform
import sqlite3
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from taskflows.common import ensure_data_dir, logger, services_data_dir
from taskflows.exceptions import RevisionConflict

from .models import ScheduledTask, ScheduleSpec, parse_datetime, utc_now

SCHEMA_VERSION = 5


@dataclass(frozen=True)
class HistoryPruneResult:
    """Summary of one terminal run-history retention pass."""

    runs_deleted: int
    log_files_deleted: int
    log_errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class QueuedOccurrence:
    """One durable scheduler occurrence waiting for a worker."""

    run_id: str
    task_id: str
    revision: int
    scheduled_for: datetime


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(UTC).isoformat() if value else None


def _dt(value: str | None) -> datetime | None:
    return parse_datetime(value) if value else None


def _pid_is_running(pid: int | None) -> bool:
    """Return whether a recorded runner process still exists."""
    if pid is None or pid <= 0:
        return False
    if os.name == "nt":
        return _windows_pid_is_running(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _windows_pid_is_running(pid: int) -> bool:
    """Check a Windows PID without using ``os.kill``.

    Windows implements every ``os.kill`` signal other than the console
    control events with ``TerminateProcess``. In particular, ``os.kill(pid,
    0)`` is not the POSIX existence probe and can terminate a live runner.
    Opening a query handle and polling it avoids that destructive behavior.
    """
    import ctypes
    from ctypes import wintypes

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    SYNCHRONIZE = 0x00100000
    WAIT_TIMEOUT = 0x00000102
    ERROR_ACCESS_DENIED = 5

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    handle = kernel32.OpenProcess(
        PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE,
        False,
        pid,
    )
    if not handle:
        # A protected process may reject the query even while it exists. Treat
        # access denial conservatively so a live runner is not duplicated.
        error_code = int(ctypes.get_last_error())  # type: ignore[attr-defined]
        return error_code == ERROR_ACCESS_DENIED
    try:
        return bool(kernel32.WaitForSingleObject(handle, 0) == WAIT_TIMEOUT)
    finally:
        kernel32.CloseHandle(handle)


def _windows_process_identity(pid: int) -> str | None:
    """Return the Windows process creation timestamp for PID-reuse detection."""
    import ctypes
    from ctypes import wintypes

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.GetProcessTimes.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
    ]
    kernel32.GetProcessTimes.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None
    try:
        created = wintypes.FILETIME()
        exited = wintypes.FILETIME()
        kernel = wintypes.FILETIME()
        user = wintypes.FILETIME()
        if not kernel32.GetProcessTimes(
            handle,
            ctypes.byref(created),
            ctypes.byref(exited),
            ctypes.byref(kernel),
            ctypes.byref(user),
        ):
            return None
        value = (int(created.dwHighDateTime) << 32) | int(created.dwLowDateTime)
        return f"windows:{value}"
    finally:
        kernel32.CloseHandle(handle)


def _process_identity(pid: int | None) -> str | None:
    """Return a stable creation identity for a currently existing process.

    PIDs are recycled. Persisting the native creation identity prevents a new,
    unrelated process from keeping an orphaned scheduler run or heartbeat alive.
    Failure to query identity remains conservative and falls back to PID liveness.
    """
    if pid is None or pid <= 0:
        return None
    if os.name == "nt":
        return _windows_process_identity(pid)
    if platform.system() == "Linux":
        try:
            stat = Path(f"/proc/{pid}/stat").read_text()
            # Field 2 (comm) is parenthesized and may contain spaces. Fields
            # after its final ')' begin with state (field 3); starttime is 22.
            fields = stat[stat.rfind(")") + 2 :].split()
            return f"linux:{fields[19]}"
        except (IndexError, OSError, UnicodeError):
            return None
    try:
        result = subprocess.run(
            ["ps", "-o", "lstart=", "-p", str(pid)],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    created = " ".join(result.stdout.split())
    return f"ps:{created}" if result.returncode == 0 and created else None


def _pid_matches_identity(pid: int | None, identity: str | None) -> bool:
    """Return whether PID is live and, when available, is the same process."""
    if not _pid_is_running(pid):
        return False
    if identity is None:
        return True
    current = _process_identity(pid)
    # If the platform temporarily refuses an identity query, preserve the run
    # rather than risk overlapping a still-live command.
    return current is None or current == identity


class SchedulerRepository:
    """SQLite source of truth for portable schedules and run history."""

    def __init__(self, database_path: str | Path | None = None) -> None:
        configured_database = services_data_dir / "scheduler.sqlite3"
        self.database_path = Path(database_path or configured_database)
        parent_existed = self.database_path.parent.exists()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        if database_path is None or self.database_path.resolve() == configured_database.resolve():
            # The configured Taskflows data directory has an owner-only
            # contract, including when the native installer pins this exact
            # database path on the daemon command line.
            ensure_data_dir()
        elif os.name != "nt" and not parent_existed:
            # Secure directories we create, but never change permissions on an
            # existing directory owned or managed by the caller.
            os.chmod(self.database_path.parent, 0o700)
        if os.name != "nt":
            # Definitions may contain environment values. The parent is usually
            # owner-only, but an explicitly configured database can live in an
            # existing shared directory. Set the database mode before enabling
            # WAL so SQLite also derives owner-only permissions for sidecars.
            try:
                self.database_path.touch(mode=0o600, exist_ok=True)
                os.chmod(self.database_path, 0o600)
            except OSError as exc:
                logger.warning(f"Could not set secure permissions on {self.database_path}: {exc}")
        self._initialize()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=10000")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self.connect() as db:
            schema_version = int(db.execute("PRAGMA user_version").fetchone()[0])
            if schema_version > SCHEMA_VERSION:
                raise RuntimeError(
                    f"scheduler database schema {schema_version} is newer than "
                    f"this Taskflows version supports ({SCHEMA_VERSION})"
                )
            db.execute("PRAGMA journal_mode=WAL")
            if schema_version == SCHEMA_VERSION:
                # Repository objects are intentionally cheap: the runner and
                # API create them per operation. Once the version marker says
                # the schema is current, avoid repeating every CREATE/PRAGMA
                # inspection on each scheduled command.
                current_schema = True
            else:
                current_schema = False
                # The API, CLI, and daemon can all be the first process to open
                # a registry after an upgrade. Serialize the entire migration,
                # then re-read the marker in case another process completed it
                # while this connection waited for the write lock.
                db.execute("BEGIN IMMEDIATE")
                schema_version = int(db.execute("PRAGMA user_version").fetchone()[0])
                if schema_version > SCHEMA_VERSION:
                    raise RuntimeError(
                        f"scheduler database schema {schema_version} is newer than "
                        f"this Taskflows version supports ({SCHEMA_VERSION})"
                    )
                current_schema = schema_version == SCHEMA_VERSION

            if not current_schema:
                db.execute(
                    """CREATE TABLE IF NOT EXISTS scheduled_tasks (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    command_json TEXT NOT NULL,
                    schedule_json TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    timeout REAL,
                    cwd TEXT,
                    environment_json TEXT NOT NULL DEFAULT '{}',
                    misfire_grace_time INTEGER,
                    coalesce INTEGER NOT NULL DEFAULT 1,
                    max_instances INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    revision INTEGER NOT NULL DEFAULT 1,
                    next_run_at TEXT
                )"""
                )
                db.execute(
                    """CREATE TABLE IF NOT EXISTS task_runs (
                    id TEXT PRIMARY KEY,
                    task_id TEXT,
                    task_name TEXT NOT NULL,
                    scheduled_for TEXT,
                    started_at TEXT,
                    finished_at TEXT,
                    status TEXT NOT NULL,
                    exit_code INTEGER,
                    stdout_path TEXT,
                    stderr_path TEXT,
                    error TEXT,
                    runner_pid INTEGER,
                    runner_identity TEXT,
                    task_revision INTEGER,
                    occurrence_key TEXT,
                    FOREIGN KEY(task_id) REFERENCES scheduled_tasks(id) ON DELETE SET NULL
                )"""
                )
                db.execute(
                    """CREATE INDEX IF NOT EXISTS idx_task_runs_task_started
                    ON task_runs(task_id, started_at DESC)"""
                )
                db.execute("CREATE INDEX IF NOT EXISTS idx_task_runs_status ON task_runs(status)")
                db.execute(
                    """CREATE TABLE IF NOT EXISTS scheduler_state (
                    singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
                    pid INTEGER NOT NULL,
                    hostname TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    heartbeat_at TEXT NOT NULL,
                    process_identity TEXT
                )"""
                )
                run_columns = {row[1] for row in db.execute("PRAGMA table_info(task_runs)")}
                foreign_keys = list(db.execute("PRAGMA foreign_key_list(task_runs)"))
                cascades_on_delete = any(str(row[6]).upper() == "CASCADE" for row in foreign_keys)
                if "task_name" not in run_columns or cascades_on_delete:
                    # Version 1 deleted history together with a task
                    # definition. The rebuild is part of the same write
                    # transaction as the version marker, so readers never see
                    # a half-migrated history table.
                    db.execute("ALTER TABLE task_runs RENAME TO task_runs_v1")
                    db.execute(
                        """CREATE TABLE task_runs (
                        id TEXT PRIMARY KEY,
                        task_id TEXT,
                        task_name TEXT NOT NULL,
                        scheduled_for TEXT,
                        started_at TEXT,
                        finished_at TEXT,
                        status TEXT NOT NULL,
                        exit_code INTEGER,
                        stdout_path TEXT,
                        stderr_path TEXT,
                        error TEXT,
                        runner_pid INTEGER,
                        runner_identity TEXT,
                        task_revision INTEGER,
                        occurrence_key TEXT,
                        FOREIGN KEY(task_id) REFERENCES scheduled_tasks(id) ON DELETE SET NULL
                    )"""
                    )
                    old_columns = {row[1] for row in db.execute("PRAGMA table_info(task_runs_v1)")}
                    name_expression = (
                        "COALESCE(r.task_name, t.name, '<deleted>')"
                        if "task_name" in old_columns
                        else "COALESCE(t.name, '<deleted>')"
                    )
                    db.execute(
                        f"""INSERT INTO task_runs
                        (id, task_id, task_name, scheduled_for, started_at, finished_at,
                         status, exit_code, stdout_path, stderr_path, error, runner_pid,
                         runner_identity, task_revision, occurrence_key)
                        SELECT r.id, r.task_id, {name_expression}, r.scheduled_for,
                               r.started_at, r.finished_at, r.status, r.exit_code,
                               r.stdout_path, r.stderr_path, r.error, NULL, NULL, NULL, NULL
                        FROM task_runs_v1 r
                        LEFT JOIN scheduled_tasks t ON t.id=r.task_id"""
                    )
                    db.execute("DROP TABLE task_runs_v1")
                    db.execute(
                        """CREATE INDEX idx_task_runs_task_started
                        ON task_runs(task_id, started_at DESC)"""
                    )
                    db.execute("CREATE INDEX idx_task_runs_status ON task_runs(status)")
                run_columns = {row[1] for row in db.execute("PRAGMA table_info(task_runs)")}
                if "runner_pid" not in run_columns:
                    db.execute("ALTER TABLE task_runs ADD COLUMN runner_pid INTEGER")
                if "runner_identity" not in run_columns:
                    db.execute("ALTER TABLE task_runs ADD COLUMN runner_identity TEXT")
                if "task_revision" not in run_columns:
                    db.execute("ALTER TABLE task_runs ADD COLUMN task_revision INTEGER")
                if "occurrence_key" not in run_columns:
                    db.execute("ALTER TABLE task_runs ADD COLUMN occurrence_key TEXT")
                db.execute(
                    """CREATE UNIQUE INDEX IF NOT EXISTS idx_task_runs_occurrence
                   ON task_runs(occurrence_key) WHERE occurrence_key IS NOT NULL"""
                )
                state_columns = {row[1] for row in db.execute("PRAGMA table_info(scheduler_state)")}
                if "process_identity" not in state_columns:
                    db.execute("ALTER TABLE scheduler_state ADD COLUMN process_identity TEXT")
                db.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        if os.name != "nt":
            os.chmod(self.database_path, 0o600)

    @staticmethod
    def _task_from_row(row: sqlite3.Row) -> ScheduledTask:
        return ScheduledTask(
            id=row["id"],
            name=row["name"],
            command=tuple(json.loads(row["command_json"])),
            schedule=ScheduleSpec.from_json(row["schedule_json"]),
            enabled=bool(row["enabled"]),
            timeout=row["timeout"],
            cwd=row["cwd"],
            environment=json.loads(row["environment_json"]),
            misfire_grace_time=row["misfire_grace_time"],
            coalesce=bool(row["coalesce"]),
            max_instances=row["max_instances"],
            created_at=parse_datetime(row["created_at"]),
            updated_at=parse_datetime(row["updated_at"]),
            revision=row["revision"],
            next_run_at=_dt(row["next_run_at"]),
        )

    @staticmethod
    def _resolve_row(db: sqlite3.Connection, identifier: str) -> sqlite3.Row | None:
        """Resolve with the documented ID-before-name precedence in one transaction."""
        row = db.execute("SELECT * FROM scheduled_tasks WHERE id=?", (identifier,)).fetchone()
        if row is None:
            row = db.execute("SELECT * FROM scheduled_tasks WHERE name=?", (identifier,)).fetchone()
        return cast("sqlite3.Row | None", row)

    def add(
        self,
        task: ScheduledTask,
        *,
        replace_existing: bool = False,
        expected_revision: int | None = None,
    ) -> ScheduledTask:
        if expected_revision is not None and not replace_existing:
            raise ValueError("expected_revision requires replace_existing=True")
        now = utc_now()
        values = (
            task.id,
            task.name,
            json.dumps(list(task.command)),
            task.schedule.to_json(),
            int(task.enabled),
            task.timeout,
            task.cwd,
            json.dumps(dict(task.environment), sort_keys=True),
            task.misfire_grace_time,
            int(task.coalesce),
            task.max_instances,
            _iso(task.created_at),
            _iso(now),
            max(task.revision, 1),
            None,
        )
        insert = """
                INSERT INTO scheduled_tasks (
                    id, name, command_json, schedule_json, enabled, timeout, cwd,
                    environment_json, misfire_grace_time, coalesce, max_instances,
                    created_at, updated_at, revision, next_run_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """
        if replace_existing:
            insert += """
                ON CONFLICT(name) DO UPDATE SET
                    command_json=excluded.command_json,
                    schedule_json=excluded.schedule_json,
                    enabled=excluded.enabled,
                    timeout=excluded.timeout,
                    cwd=excluded.cwd,
                    environment_json=excluded.environment_json,
                    misfire_grace_time=excluded.misfire_grace_time,
                    coalesce=excluded.coalesce,
                    max_instances=excluded.max_instances,
                    updated_at=excluded.updated_at,
                    revision=scheduled_tasks.revision+1,
                    next_run_at=NULL
                """
        try:
            with self.connect() as db:
                if expected_revision is not None:
                    # Lock before checking so no writer can change the row
                    # between the precondition and the atomic UPSERT.
                    db.execute("BEGIN IMMEDIATE")
                    current = db.execute(
                        "SELECT revision FROM scheduled_tasks WHERE name=?", (task.name,)
                    ).fetchone()
                    current_revision = current["revision"] if current is not None else "missing"
                    if current is None or current_revision != expected_revision:
                        raise RevisionConflict(
                            f"scheduled task {task.name!r} changed from revision "
                            f"{expected_revision} to {current_revision}"
                        )
                db.execute(insert, values)
                row = db.execute(
                    "SELECT * FROM scheduled_tasks WHERE name=?", (task.name,)
                ).fetchone()
                assert row is not None
                result = self._task_from_row(row)
        except sqlite3.IntegrityError as exc:
            if "scheduled_tasks.name" in str(exc):
                raise ValueError(f"a scheduled task named {task.name!r} already exists") from exc
            raise ValueError(f"a scheduled task with id {task.id!r} already exists") from exc
        return result

    def get(self, task_id: str) -> ScheduledTask | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM scheduled_tasks WHERE id=?", (task_id,)).fetchone()
        return self._task_from_row(row) if row else None

    def get_by_name(self, name: str) -> ScheduledTask | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM scheduled_tasks WHERE name=?", (name,)).fetchone()
        return self._task_from_row(row) if row else None

    def resolve(self, identifier: str) -> ScheduledTask:
        with self.connect() as db:
            row = self._resolve_row(db, identifier)
        if row is None:
            raise KeyError(f"scheduled task not found: {identifier}")
        return self._task_from_row(row)

    def list(self, *, enabled: bool | None = None, match: str | None = None) -> list[ScheduledTask]:
        query = "SELECT * FROM scheduled_tasks"
        params: tuple[Any, ...] = ()
        if enabled is not None:
            query += " WHERE enabled=?"
            params = (int(enabled),)
        query += " ORDER BY name"
        with self.connect() as db:
            rows = db.execute(query, params).fetchall()
        tasks = [self._task_from_row(row) for row in rows]
        # Keep portable registry matching consistent with SQLite's case-sensitive
        # task names. ``fnmatch`` silently becomes case-insensitive on Windows.
        return [task for task in tasks if not match or fnmatchcase(task.name, match)]

    def set_enabled(
        self, identifier: str, enabled: bool, *, expected_revision: int | None = None
    ) -> ScheduledTask:
        with self.connect() as db:
            # The read, idempotence decision, conditional write, and returned
            # representation belong to one write transaction. Otherwise an
            # expected-revision no-op can return success after another client
            # changes the row between resolve() and update().
            db.execute("BEGIN IMMEDIATE")
            row = self._resolve_row(db, identifier)
            if row is None:
                raise KeyError(f"scheduled task not found: {identifier}")
            task = self._task_from_row(row)
            if expected_revision is not None and task.revision != expected_revision:
                raise RevisionConflict(
                    f"scheduled task {task.name!r} changed from revision "
                    f"{expected_revision} to {task.revision}"
                )
            if task.enabled == enabled:
                return task
            db.execute(
                """UPDATE scheduled_tasks
                   SET enabled=?, updated_at=?, revision=revision+1, next_run_at=NULL
                   WHERE id=?""",
                (int(enabled), _iso(utc_now()), task.id),
            )
            updated = db.execute("SELECT * FROM scheduled_tasks WHERE id=?", (task.id,)).fetchone()
            assert updated is not None
            return self._task_from_row(updated)

    def delete(self, identifier: str, *, expected_revision: int | None = None) -> bool:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._resolve_row(db, identifier)
            if row is None:
                raise KeyError(f"scheduled task not found: {identifier}")
            task = self._task_from_row(row)
            if expected_revision is not None and task.revision != expected_revision:
                raise RevisionConflict(
                    f"scheduled task {task.name!r} changed from revision "
                    f"{expected_revision} to {task.revision}"
                )
            cursor = db.execute("DELETE FROM scheduled_tasks WHERE id=?", (task.id,))
            return cursor.rowcount > 0

    def set_next_runs(self, next_runs: dict[str, datetime | None]) -> None:
        """Update cached next-run values in one transaction for fast bulk status."""
        values = [
            (_iso(next_run), task_id, _iso(next_run)) for task_id, next_run in next_runs.items()
        ]
        if not values:
            return
        with self.connect() as db:
            db.executemany(
                """UPDATE scheduled_tasks SET next_run_at=?
                   WHERE id=? AND COALESCE(next_run_at, '') <> COALESCE(?, '')""",
                values,
            )

    def begin_run(
        self,
        task: ScheduledTask,
        scheduled_for: datetime | None,
        *,
        allow_disabled: bool = True,
    ) -> str | None:
        """Atomically reserve a current-definition run slot."""
        run_id = str(uuid4())
        now = utc_now()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            current = db.execute(
                "SELECT name, enabled, revision, max_instances FROM scheduled_tasks WHERE id=?",
                (task.id,),
            ).fetchone()
            if (
                current is None
                or current["revision"] != task.revision
                or (not allow_disabled and not bool(current["enabled"]))
            ):
                return None
            running = db.execute(
                """SELECT COUNT(*) FROM task_runs
                   WHERE task_id=? AND status IN ('starting', 'running')""",
                (task.id,),
            ).fetchone()[0]
            if running >= current["max_instances"]:
                db.execute(
                    """INSERT INTO task_runs
                       (id, task_id, task_name, scheduled_for, started_at, finished_at, status, error)
                       VALUES (?, ?, ?, ?, ?, ?, 'skipped', 'maximum concurrent instances reached')""",
                    (run_id, task.id, current["name"], _iso(scheduled_for), _iso(now), _iso(now)),
                )
                return None
            db.execute(
                """INSERT INTO task_runs
                   (id, task_id, task_name, scheduled_for, started_at, status,
                    runner_pid, runner_identity, task_revision)
                   VALUES (?, ?, ?, ?, ?, 'running', ?, ?, ?)""",
                (
                    run_id,
                    task.id,
                    current["name"],
                    _iso(scheduled_for),
                    _iso(now),
                    os.getpid(),
                    _process_identity(os.getpid()),
                    task.revision,
                ),
            )
        return run_id

    @staticmethod
    def _occurrence_key(task: ScheduledTask, scheduled_for: datetime) -> str:
        return f"{task.id}:{task.revision}:{_iso(scheduled_for)}"

    def reserve_occurrences(
        self,
        task: ScheduledTask,
        scheduled_times: builtins.list[datetime],
    ) -> builtins.list[QueuedOccurrence]:
        """Persist due occurrences before APScheduler advances their trigger."""
        if not scheduled_times:
            return []
        owner_pid = os.getpid()
        owner_identity = _process_identity(owner_pid)
        reserved: list[QueuedOccurrence] = []
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            current = db.execute(
                "SELECT name, enabled, revision FROM scheduled_tasks WHERE id=?",
                (task.id,),
            ).fetchone()
            if (
                current is None
                or not bool(current["enabled"])
                or current["revision"] != task.revision
            ):
                return []
            for scheduled_for in scheduled_times:
                run_id = str(uuid4())
                cursor = db.execute(
                    """INSERT OR IGNORE INTO task_runs
                       (id, task_id, task_name, task_revision, occurrence_key,
                        scheduled_for, status, runner_pid, runner_identity)
                       VALUES (?, ?, ?, ?, ?, ?, 'queued', ?, ?)""",
                    (
                        run_id,
                        task.id,
                        current["name"],
                        task.revision,
                        self._occurrence_key(task, scheduled_for),
                        _iso(scheduled_for),
                        owner_pid,
                        owner_identity,
                    ),
                )
                if cursor.rowcount:
                    reserved.append(QueuedOccurrence(run_id, task.id, task.revision, scheduled_for))
        return reserved

    def release_queued_owners(self, run_ids: builtins.list[str]) -> None:
        """Make occurrences recoverable when executor submission fails."""
        if not run_ids:
            return
        with self.connect() as db:
            db.executemany(
                """UPDATE task_runs SET runner_pid=NULL, runner_identity=NULL
                   WHERE id=? AND status='queued'""",
                [(run_id,) for run_id in run_ids],
            )

    def adopt_orphaned_occurrences(self) -> builtins.list[QueuedOccurrence]:
        """Claim queued work whose owning daemon no longer exists."""
        owner_pid = os.getpid()
        owner_identity = _process_identity(owner_pid)
        adopted: list[QueuedOccurrence] = []
        owner_liveness: dict[tuple[int | None, str | None], bool] = {}
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute(
                """SELECT id, task_id, task_revision, scheduled_for,
                          runner_pid, runner_identity
                   FROM task_runs WHERE status IN ('queued', 'starting')
                   ORDER BY scheduled_for, id"""
            ).fetchall()
            for row in rows:
                owner = (row["runner_pid"], row["runner_identity"])
                if owner not in owner_liveness:
                    owner_liveness[owner] = _pid_matches_identity(
                        row["runner_pid"], row["runner_identity"]
                    )
                is_live = owner_liveness[owner]
                if is_live:
                    continue
                if (
                    row["task_id"] is None
                    or row["task_revision"] is None
                    or row["scheduled_for"] is None
                ):
                    db.execute(
                        """UPDATE task_runs SET status='skipped', finished_at=?,
                           error='scheduled definition no longer exists'
                           WHERE id=? AND status IN ('queued', 'starting')""",
                        (_iso(utc_now()), row["id"]),
                    )
                    continue
                db.execute(
                    """UPDATE task_runs SET status='queued', runner_pid=?, runner_identity=?
                       WHERE id=? AND status IN ('queued', 'starting')""",
                    (owner_pid, owner_identity, row["id"]),
                )
                adopted.append(
                    QueuedOccurrence(
                        row["id"],
                        row["task_id"],
                        row["task_revision"],
                        parse_datetime(row["scheduled_for"]),
                    )
                )
        return adopted

    def claim_occurrence(self, run_id: str, task: ScheduledTask) -> bool:
        """Transition one queued occurrence to running under overlap limits."""
        now = _iso(utc_now())
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT status, task_id, task_revision FROM task_runs WHERE id=?",
                (run_id,),
            ).fetchone()
            if row is None or row["status"] != "queued":
                return False
            current = db.execute(
                "SELECT revision, max_instances FROM scheduled_tasks WHERE id=?",
                (task.id,),
            ).fetchone()
            if (
                row["task_id"] != task.id
                or row["task_revision"] != task.revision
                or current is None
                or current["revision"] != task.revision
            ):
                db.execute(
                    """UPDATE task_runs SET status='skipped', finished_at=?,
                       error='scheduled definition changed before dispatch'
                       WHERE id=? AND status='queued'""",
                    (now, run_id),
                )
                return False
            running = db.execute(
                """SELECT COUNT(*) FROM task_runs
                   WHERE task_id=? AND status IN ('starting', 'running')""",
                (task.id,),
            ).fetchone()[0]
            if running >= current["max_instances"]:
                db.execute(
                    """UPDATE task_runs SET status='skipped', started_at=?, finished_at=?,
                       error='maximum concurrent instances reached'
                       WHERE id=? AND status='queued'""",
                    (now, now, run_id),
                )
                return False
            cursor = db.execute(
                """UPDATE task_runs SET status='starting', started_at=?
                   WHERE id=? AND status='queued'""",
                (now, run_id),
            )
            return cursor.rowcount > 0

    def skip_queued_occurrence(self, run_id: str, reason: str) -> None:
        with self.connect() as db:
            db.execute(
                """UPDATE task_runs SET status='skipped', finished_at=?, error=?
                   WHERE id=? AND status='queued'""",
                (_iso(utc_now()), reason, run_id),
            )

    def set_runner_pid(
        self,
        run_id: str,
        pid: int,
        *,
        process_identity: str | None = None,
    ) -> None:
        """Record the command process and its creation identity after launch."""
        identity = process_identity if process_identity is not None else _process_identity(pid)
        with self.connect() as db:
            db.execute(
                """UPDATE task_runs
                   SET runner_pid=?, runner_identity=?, status='running'
                   WHERE id=? AND status IN ('starting', 'running')""",
                (pid, identity, run_id),
            )

    def finish_run(
        self,
        run_id: str,
        *,
        status: str,
        exit_code: int | None = None,
        stdout_path: str | None = None,
        stderr_path: str | None = None,
        error: str | None = None,
    ) -> None:
        with self.connect() as db:
            db.execute(
                """UPDATE task_runs SET finished_at=?, status=?, exit_code=?,
                   stdout_path=?, stderr_path=?, error=? WHERE id=?""",
                (
                    _iso(utc_now()),
                    status,
                    exit_code,
                    stdout_path,
                    stderr_path,
                    error,
                    run_id,
                ),
            )

    def record_missed(self, task: ScheduledTask, scheduled_for: datetime, reason: str) -> bool:
        now = utc_now()
        with self.connect() as db:
            current = db.execute(
                "SELECT revision FROM scheduled_tasks WHERE id=?", (task.id,)
            ).fetchone()
            if current is None or current["revision"] != task.revision:
                return False
            cursor = db.execute(
                """INSERT OR IGNORE INTO task_runs
                   (id, task_id, task_name, task_revision, occurrence_key, scheduled_for,
                    started_at, finished_at, status, error)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'missed', ?)""",
                (
                    str(uuid4()),
                    task.id,
                    task.name,
                    task.revision,
                    self._occurrence_key(task, scheduled_for),
                    _iso(scheduled_for),
                    _iso(now),
                    _iso(now),
                    reason,
                ),
            )
        return cursor.rowcount > 0

    def mark_interrupted_runs(self) -> int:
        now = _iso(utc_now())
        with self.connect() as db:
            running = db.execute(
                """SELECT id, runner_pid, runner_identity
                   FROM task_runs WHERE status='running'"""
            ).fetchall()
            stale_ids = [
                row["id"]
                for row in running
                if not _pid_matches_identity(row["runner_pid"], row["runner_identity"])
            ]
            if stale_ids:
                db.executemany(
                    """UPDATE task_runs SET status='interrupted', finished_at=?,
                       error=COALESCE(error, 'runner stopped before run completed')
                       WHERE id=? AND status='running'""",
                    [(now, run_id) for run_id in stale_ids],
                )
        return len(stale_ids)

    def active_run_counts(self) -> dict[str, int]:
        """Return stable active-state counts for status and diagnostics."""
        with self.connect() as db:
            rows = db.execute(
                """SELECT CASE WHEN status='starting' THEN 'queued' ELSE status END AS state,
                          COUNT(*) AS count
                   FROM task_runs WHERE status IN ('queued', 'starting', 'running')
                   GROUP BY state"""
            ).fetchall()
        counts = {"queued": 0, "running": 0}
        counts.update({row["state"]: row["count"] for row in rows})
        return counts

    def history(
        self, identifier: str | None = None, *, limit: int = 100
    ) -> builtins.list[dict[str, Any]]:
        params: list[Any] = []
        where = ""
        if identifier:
            task = self.get(identifier)
            if task is not None:
                where = "WHERE r.task_id=?"
                params.append(task.id)
            else:
                # Name queries span recreated tasks because history intentionally
                # outlives each individual task definition. IDs remain precise.
                where = "WHERE r.task_name=?"
                params.append(identifier)
        params.append(limit)
        with self.connect() as db:
            rows = db.execute(
                f"""SELECT r.* FROM task_runs r
                    {where} ORDER BY COALESCE(r.started_at, r.scheduled_for) DESC LIMIT ?""",
                params,
            ).fetchall()
        return [dict(row) for row in rows]

    def prune_history(
        self,
        *,
        before: datetime,
        keep_latest: int = 0,
        dry_run: bool = False,
    ) -> HistoryPruneResult:
        """Remove old terminal attempts while retaining recent runs per definition.

        Active runs are never eligible. Log paths are deleted only when they
        resolve beneath this registry's run directory.
        """
        if keep_latest < 0:
            raise ValueError("keep_latest cannot be negative")
        cutoff = _iso(parse_datetime(before))
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute(
                """WITH ranked AS (
                       SELECT id, stdout_path, stderr_path, finished_at,
                              ROW_NUMBER() OVER (
                                  PARTITION BY COALESCE(task_id, 'deleted:' || task_name)
                                  ORDER BY COALESCE(started_at, scheduled_for, finished_at) DESC,
                                           id DESC
                              ) AS newest_rank
                       FROM task_runs
                       WHERE status <> 'running' AND finished_at IS NOT NULL
                   )
                   SELECT id, stdout_path, stderr_path
                   FROM ranked
                   WHERE finished_at < ? AND newest_rank > ?""",
                (cutoff, keep_latest),
            ).fetchall()
            if rows and not dry_run:
                db.executemany("DELETE FROM task_runs WHERE id=?", [(row["id"],) for row in rows])

        if dry_run:
            return HistoryPruneResult(runs_deleted=len(rows), log_files_deleted=0)

        run_root = (self.database_path.parent / "runs").resolve()
        deleted_logs = 0
        errors: list[str] = []
        for row in rows:
            for value in (row["stdout_path"], row["stderr_path"]):
                if not value:
                    continue
                path = Path(value).resolve()
                if not path.is_relative_to(run_root):
                    errors.append(f"refused log outside run directory: {path}")
                    continue
                try:
                    path.unlink()
                except FileNotFoundError:
                    continue
                except OSError as exc:
                    errors.append(f"could not delete {path}: {exc}")
                else:
                    deleted_logs += 1
                    with suppress(OSError):
                        path.parent.rmdir()
        return HistoryPruneResult(
            runs_deleted=len(rows),
            log_files_deleted=deleted_logs,
            log_errors=tuple(errors),
        )

    def heartbeat(
        self,
        *,
        pid: int,
        hostname: str,
        started_at: datetime,
        process_identity: str | None = None,
    ) -> None:
        now = _iso(utc_now())
        identity = process_identity if process_identity is not None else _process_identity(pid)
        with self.connect() as db:
            db.execute(
                """INSERT INTO scheduler_state
                   (singleton, pid, hostname, started_at, heartbeat_at, process_identity)
                   VALUES (1, ?, ?, ?, ?, ?)
                   ON CONFLICT(singleton) DO UPDATE SET pid=excluded.pid,
                   hostname=excluded.hostname, started_at=excluded.started_at,
                   heartbeat_at=excluded.heartbeat_at,
                   process_identity=excluded.process_identity""",
                (pid, hostname, _iso(started_at), now, identity),
            )

    def daemon_state(self) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM scheduler_state WHERE singleton=1").fetchone()
        return dict(row) if row else None

    def clear_daemon_state(self, *, pid: int, process_identity: str | None = None) -> None:
        """Remove this daemon's heartbeat without erasing a newer owner's state."""
        with self.connect() as db:
            if process_identity is None:
                db.execute("DELETE FROM scheduler_state WHERE singleton=1 AND pid=?", (pid,))
            else:
                db.execute(
                    """DELETE FROM scheduler_state
                       WHERE singleton=1 AND pid=? AND process_identity=?""",
                    (pid, process_identity),
                )
