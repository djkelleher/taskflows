from __future__ import annotations

import builtins
import json
import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from fnmatch import fnmatch
from pathlib import Path
from typing import Any
from uuid import uuid4

from taskflows.common import ensure_data_dir, services_data_dir

from .models import ScheduledTask, ScheduleSpec, parse_datetime, utc_now

SCHEMA_VERSION = 2


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(UTC).isoformat() if value else None


def _dt(value: str | None) -> datetime | None:
    return parse_datetime(value) if value else None


class SchedulerRepository:
    """SQLite source of truth for portable schedules and run history."""

    def __init__(self, database_path: str | Path | None = None) -> None:
        self.database_path = Path(database_path or (services_data_dir / "scheduler.sqlite3"))
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        if database_path is None:
            ensure_data_dir()
        if os.name != "nt":
            os.chmod(self.database_path.parent, 0o700)
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
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS scheduled_tasks (
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
                );
                CREATE TABLE IF NOT EXISTS task_runs (
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
                    FOREIGN KEY(task_id) REFERENCES scheduled_tasks(id) ON DELETE SET NULL
                );
                CREATE INDEX IF NOT EXISTS idx_task_runs_task_started
                    ON task_runs(task_id, started_at DESC);
                CREATE INDEX IF NOT EXISTS idx_task_runs_status ON task_runs(status);
                CREATE TABLE IF NOT EXISTS scheduler_state (
                    singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
                    pid INTEGER NOT NULL,
                    hostname TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    heartbeat_at TEXT NOT NULL
                );
                """
            )
            run_columns = {row[1] for row in db.execute("PRAGMA table_info(task_runs)")}
            foreign_keys = list(db.execute("PRAGMA foreign_key_list(task_runs)"))
            cascades_on_delete = any(str(row[6]).upper() == "CASCADE" for row in foreign_keys)
            if "task_name" not in run_columns or cascades_on_delete:
                # Version 1 deleted history together with a task definition.
                # Preserve existing rows while rebuilding the foreign key.
                db.execute("PRAGMA foreign_keys=OFF")
                db.execute("ALTER TABLE task_runs RENAME TO task_runs_v1")
                db.executescript(
                    """
                    CREATE TABLE task_runs (
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
                        FOREIGN KEY(task_id) REFERENCES scheduled_tasks(id) ON DELETE SET NULL
                    );
                    """
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
                         status, exit_code, stdout_path, stderr_path, error)
                        SELECT r.id, r.task_id, {name_expression}, r.scheduled_for,
                               r.started_at, r.finished_at, r.status, r.exit_code,
                               r.stdout_path, r.stderr_path, r.error
                        FROM task_runs_v1 r
                        LEFT JOIN scheduled_tasks t ON t.id=r.task_id"""
                )
                db.execute("DROP TABLE task_runs_v1")
                db.execute(
                    "CREATE INDEX idx_task_runs_task_started ON task_runs(task_id, started_at DESC)"
                )
                db.execute("CREATE INDEX idx_task_runs_status ON task_runs(status)")
                db.execute("PRAGMA foreign_keys=ON")
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

    def add(self, task: ScheduledTask, *, replace_existing: bool = False) -> ScheduledTask:
        existing = self.get_by_name(task.name)
        if existing and not replace_existing:
            raise ValueError(f"a scheduled task named {task.name!r} already exists")
        now = utc_now()
        task_id = existing.id if existing else task.id
        revision = (existing.revision + 1) if existing else max(task.revision, 1)
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO scheduled_tasks (
                    id, name, command_json, schedule_json, enabled, timeout, cwd,
                    environment_json, misfire_grace_time, coalesce, max_instances,
                    created_at, updated_at, revision, next_run_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    revision=excluded.revision,
                    next_run_at=NULL
                """,
                (
                    task_id,
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
                    _iso(existing.created_at if existing else task.created_at),
                    _iso(now),
                    revision,
                    None,
                ),
            )
        result = self.get(task_id)
        assert result is not None
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
        task = self.get(identifier) or self.get_by_name(identifier)
        if task is None:
            raise KeyError(f"scheduled task not found: {identifier}")
        return task

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
        return [task for task in tasks if not match or fnmatch(task.name, match)]

    def set_enabled(self, identifier: str, enabled: bool) -> ScheduledTask:
        task = self.resolve(identifier)
        with self.connect() as db:
            db.execute(
                """UPDATE scheduled_tasks
                   SET enabled=?, updated_at=?, revision=revision+1, next_run_at=NULL
                   WHERE id=?""",
                (int(enabled), _iso(utc_now()), task.id),
            )
        result = self.get(task.id)
        assert result is not None
        return result

    def delete(self, identifier: str) -> bool:
        task = self.resolve(identifier)
        with self.connect() as db:
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

    def begin_run(self, task: ScheduledTask, scheduled_for: datetime | None) -> str | None:
        """Atomically reserve a run slot, respecting per-task overlap limits."""
        run_id = str(uuid4())
        now = utc_now()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            running = db.execute(
                "SELECT COUNT(*) FROM task_runs WHERE task_id=? AND status='running'",
                (task.id,),
            ).fetchone()[0]
            if running >= task.max_instances:
                db.execute(
                    """INSERT INTO task_runs
                       (id, task_id, task_name, scheduled_for, started_at, finished_at, status, error)
                       VALUES (?, ?, ?, ?, ?, ?, 'skipped', 'maximum concurrent instances reached')""",
                    (run_id, task.id, task.name, _iso(scheduled_for), _iso(now), _iso(now)),
                )
                return None
            db.execute(
                """INSERT INTO task_runs
                   (id, task_id, task_name, scheduled_for, started_at, status)
                   VALUES (?, ?, ?, ?, ?, 'running')""",
                (run_id, task.id, task.name, _iso(scheduled_for), _iso(now)),
            )
        return run_id

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

    def record_missed(self, task: ScheduledTask, scheduled_for: datetime, reason: str) -> None:
        now = utc_now()
        with self.connect() as db:
            db.execute(
                """INSERT INTO task_runs
                   (id, task_id, task_name, scheduled_for, started_at, finished_at, status, error)
                   VALUES (?, ?, ?, ?, ?, ?, 'missed', ?)""",
                (
                    str(uuid4()),
                    task.id,
                    task.name,
                    _iso(scheduled_for),
                    _iso(now),
                    _iso(now),
                    reason,
                ),
            )

    def mark_interrupted_runs(self) -> int:
        now = _iso(utc_now())
        with self.connect() as db:
            cursor = db.execute(
                """UPDATE task_runs SET status='interrupted', finished_at=?,
                   error=COALESCE(error, 'scheduler stopped before run completed')
                   WHERE status='running'""",
                (now,),
            )
        return cursor.rowcount

    def history(
        self, identifier: str | None = None, *, limit: int = 100
    ) -> builtins.list[dict[str, Any]]:
        params: list[Any] = []
        where = ""
        if identifier:
            task = self.resolve(identifier)
            where = "WHERE r.task_id=?"
            params.append(task.id)
        params.append(limit)
        with self.connect() as db:
            rows = db.execute(
                f"""SELECT r.* FROM task_runs r
                    {where} ORDER BY COALESCE(r.started_at, r.scheduled_for) DESC LIMIT ?""",
                params,
            ).fetchall()
        return [dict(row) for row in rows]

    def heartbeat(self, *, pid: int, hostname: str, started_at: datetime) -> None:
        now = _iso(utc_now())
        with self.connect() as db:
            db.execute(
                """INSERT INTO scheduler_state
                   (singleton, pid, hostname, started_at, heartbeat_at)
                   VALUES (1, ?, ?, ?, ?)
                   ON CONFLICT(singleton) DO UPDATE SET pid=excluded.pid,
                   hostname=excluded.hostname, started_at=excluded.started_at,
                   heartbeat_at=excluded.heartbeat_at""",
                (pid, hostname, _iso(started_at), now),
            )

    def daemon_state(self) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM scheduler_state WHERE singleton=1").fetchone()
        return dict(row) if row else None

    def clear_daemon_state(self, *, pid: int) -> None:
        """Remove this daemon's heartbeat without erasing a newer owner's state."""
        with self.connect() as db:
            db.execute("DELETE FROM scheduler_state WHERE singleton=1 AND pid=?", (pid,))
