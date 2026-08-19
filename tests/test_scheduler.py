import json
import os
import plistlib
import socket
import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
from apscheduler.events import (
    EVENT_JOB_ERROR,
    EVENT_JOB_EXECUTED,
    EVENT_JOB_MISSED,
    EVENT_JOB_SUBMITTED,
)
from click.testing import CliRunner
from fastapi import HTTPException

from taskflows.admin.api import (
    create_portable_schedule,
    delete_portable_schedule,
    get_portable_schedule,
    list_portable_schedules,
    list_servers_endpoint,
    portable_schedule_history,
    portable_scheduler_diagnostics,
    portable_scheduler_status,
    preview_portable_schedule,
    run_portable_schedule,
    set_portable_schedule_enabled,
)
from taskflows.admin.cli import cli
from taskflows.admin.models import PortableScheduleRequest
from taskflows.exceptions import RevisionConflict
from taskflows.schedule import Calendar
from taskflows.scheduler import installer, supervisor
from taskflows.scheduler import repository as repository_module
from taskflows.scheduler.daemon import DaemonAlreadyRunning, SchedulerDaemon, _SingletonLock
from taskflows.scheduler.models import ScheduledTask, ScheduleSpec, schedule_preview, utc_now
from taskflows.scheduler.repository import (
    SchedulerRepository,
    _pid_is_running,
    _pid_matches_identity,
    _process_identity,
)
from taskflows.scheduler.runner import execute_scheduled_task, run_now
from taskflows.scheduler.status import DiagnosticCheck, runtime_status, scheduler_status
from taskflows.scheduler.supervisor import SupervisorStatus


def make_repository(tmp_path: Path) -> SchedulerRepository:
    return SchedulerRepository(tmp_path / "scheduler.sqlite3")


def test_schedule_specs_are_portable_and_validated():
    once = ScheduleSpec.once("2026-08-19T10:00:00Z")
    interval = ScheduleSpec.interval(30, start_at="2026-08-19T10:00:00+00:00")
    cron = ScheduleSpec.cron("0 9 * * mon-fri", timezone="America/New_York")

    assert once.to_trigger().run_date.isoformat() == "2026-08-19T10:00:00+00:00"
    assert interval.to_trigger().interval.total_seconds() == 30
    assert (
        str(cron.to_trigger())
        == "cron[month='*', day='*', day_of_week='mon-fri', hour='9', minute='0']"
    )
    assert ScheduleSpec.from_json(cron.to_json()) == cron

    with pytest.raises(ValueError, match="UTC offset"):
        ScheduleSpec.once("2026-08-19T10:00:00")
    with pytest.raises(ValueError, match="five fields"):
        ScheduleSpec.cron("0 9 *")
    with pytest.raises(ValueError, match="greater than zero"):
        ScheduleSpec.interval(0)
    with pytest.raises(ValueError, match="unknown IANA time zone"):
        ScheduleSpec.cron("0 9 * * *", timezone="Not/AZone")
    for invalid in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValueError, match="greater than zero"):
            ScheduleSpec.interval(invalid)


def test_schedule_preview_reuses_real_trigger_and_reports_local_and_utc_times():
    task = ScheduledTask.create(
        "preview",
        ["echo", "ok"],
        ScheduleSpec.cron("0 9 * * mon-fri", timezone="America/New_York"),
    )

    result = schedule_preview(task, after="2026-08-19T10:00:00Z", count=2)

    assert result["timezone"] == "America/New_York"
    assert result["occurrences"] == [
        {
            "utc": "2026-08-19T13:00:00+00:00",
            "local": "2026-08-19T09:00:00-04:00",
        },
        {
            "utc": "2026-08-20T13:00:00+00:00",
            "local": "2026-08-20T09:00:00-04:00",
        },
    ]
    assert (
        ScheduleSpec.once("2026-08-19T09:00:00Z").next_fire_times(after="2026-08-19T10:00:00Z")
        == ()
    )
    with pytest.raises(ValueError, match="cannot exceed"):
        task.schedule.next_fire_times(count=1001)


def test_task_rejects_non_finite_timeout_and_invalid_environment():
    schedule = ScheduleSpec.interval(60)
    for invalid in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValueError, match="timeout"):
            ScheduledTask.create("invalid-timeout", ["echo", "ok"], schedule, timeout=invalid)
    for environment in ({"": "value"}, {"BAD=KEY": "value"}, {"KEY": "bad\x00value"}):
        with pytest.raises(ValueError, match="environment variables"):
            ScheduledTask.create(
                "invalid-environment", ["echo", "ok"], schedule, environment=environment
            )
    with pytest.raises(ValueError, match="unique ignoring case"):
        ScheduledTask.create(
            "ambiguous-windows-environment",
            ["echo", "ok"],
            schedule,
            environment={"PATH": "first", "Path": "second"},
        )


def test_task_rejects_string_commands_and_unsafe_names_and_freezes_environment():
    schedule = ScheduleSpec.interval(60)
    with pytest.raises(TypeError, match="sequence of arguments"):
        ScheduledTask.create("split-command", "echo", schedule)
    for name in (" leading", "trailing ", "line\nbreak", "escape\x1bname"):
        with pytest.raises(ValueError, match="task name|control characters"):
            ScheduledTask.create(name, ["echo", "ok"], schedule)

    environment = {"MODE": "before"}
    task = ScheduledTask.create("immutable", ["echo", "ok"], schedule, environment=environment)
    environment["MODE"] = "after"
    assert task.environment == {"MODE": "before"}
    with pytest.raises(TypeError):
        task.environment["MODE"] = "mutated"


def test_legacy_calendar_datetime_preserves_fractional_seconds():
    schedule = Calendar.from_datetime(datetime.fromisoformat("2026-08-19T10:00:00.500000+00:00"))
    assert schedule.schedule == "Wed 2026-08-19 10:00:00.500000 UTC"


def test_repository_crud_revision_and_history_survives_delete(tmp_path):
    repository = make_repository(tmp_path)
    task = ScheduledTask.create(
        "backup",
        ["python", "-c", "print('ok')"],
        ScheduleSpec.interval(60),
        environment={"MODE": "test"},
    )
    saved = repository.add(task)
    assert repository.resolve("backup") == saved
    assert saved.schedule.start_at is not None

    disabled = repository.set_enabled(saved.id, False)
    assert disabled.enabled is False
    assert disabled.revision == saved.revision + 1

    run_id = repository.begin_run(disabled, utc_now())
    assert run_id is not None
    repository.finish_run(run_id, status="succeeded", exit_code=0)
    assert repository.delete(disabled.id)
    assert repository.list() == []
    history = repository.history()
    assert history[0]["task_name"] == "backup"
    assert history[0]["task_id"] is None
    assert repository.history("backup")[0]["task_name"] == "backup"


def test_repository_add_is_atomic_and_replacements_increment_current_revision(tmp_path):
    database_path = tmp_path / "scheduler.sqlite3"
    SchedulerRepository(database_path)

    def add(replace_existing=False):
        repository = SchedulerRepository(database_path)
        task = ScheduledTask.create("racing", ["echo", "ok"], ScheduleSpec.interval(60))
        return repository.add(task, replace_existing=replace_existing)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: _capture_add(add), range(2)))
    assert sum(isinstance(result, ScheduledTask) for result in results) == 1
    assert sum(isinstance(result, ValueError) for result in results) == 1

    with ThreadPoolExecutor(max_workers=2) as executor:
        replacements = list(executor.map(lambda _: add(True), range(2)))
    saved = SchedulerRepository(database_path).resolve("racing")
    assert saved.revision == 3
    assert {task.id for task in replacements} == {saved.id}


def test_repository_replacement_can_require_the_current_revision(tmp_path):
    repository = make_repository(tmp_path)
    original = repository.add(
        ScheduledTask.create("replace-cas", ["echo", "old"], ScheduleSpec.interval(60))
    )
    current = repository.set_enabled(original.id, False, expected_revision=original.revision)
    replacement = ScheduledTask.create("replace-cas", ["echo", "new"], ScheduleSpec.interval(120))

    with pytest.raises(RevisionConflict, match="changed from revision"):
        repository.add(
            replacement,
            replace_existing=True,
            expected_revision=original.revision,
        )

    saved = repository.add(
        replacement,
        replace_existing=True,
        expected_revision=current.revision,
    )
    assert saved.command == ("echo", "new")
    assert saved.revision == current.revision + 1


def test_custom_database_does_not_chmod_existing_parent(tmp_path, monkeypatch):
    chmod_calls = []
    monkeypatch.setattr(
        repository_module.os,
        "chmod",
        lambda path, mode: chmod_calls.append((Path(path), mode)),
    )

    SchedulerRepository(tmp_path / "scheduler.sqlite3")

    assert all(path != tmp_path for path, _mode in chmod_calls)


def test_custom_database_secures_parent_it_creates(tmp_path, monkeypatch):
    database_path = tmp_path / "new" / "scheduler.sqlite3"
    chmod_calls = []
    monkeypatch.setattr(
        repository_module.os,
        "chmod",
        lambda path, mode: chmod_calls.append((Path(path), mode)),
    )

    SchedulerRepository(database_path)

    assert (database_path.parent, 0o700) in chmod_calls


def _capture_add(add):
    try:
        return add()
    except ValueError as exc:
        return exc


def test_set_enabled_is_idempotent(tmp_path):
    repository = make_repository(tmp_path)
    task = repository.add(
        ScheduledTask.create("enabled", ["echo", "ok"], ScheduleSpec.interval(60))
    )

    unchanged = repository.set_enabled(task.id, True)

    assert unchanged.revision == task.revision


def test_set_enabled_reports_stale_revision(tmp_path):
    repository = make_repository(tmp_path)
    task = repository.add(
        ScheduledTask.create("revisioned", ["echo", "ok"], ScheduleSpec.interval(60))
    )
    disabled = repository.set_enabled(task.id, False, expected_revision=task.revision)

    with pytest.raises(RevisionConflict, match="changed from revision"):
        repository.set_enabled(task.id, True, expected_revision=task.revision)
    assert repository.resolve(task.id) == disabled


def test_delete_reports_stale_revision(tmp_path):
    repository = make_repository(tmp_path)
    task = repository.add(
        ScheduledTask.create("delete-revision", ["echo", "ok"], ScheduleSpec.interval(60))
    )
    current = repository.set_enabled(task.id, False, expected_revision=task.revision)

    with pytest.raises(RevisionConflict, match="changed from revision"):
        repository.delete(task.id, expected_revision=task.revision)

    assert repository.resolve(task.id) == current


def test_repository_name_matching_is_case_sensitive(tmp_path):
    repository = make_repository(tmp_path)
    repository.add(ScheduledTask.create("Backup", ["echo", "ok"], ScheduleSpec.interval(60)))

    assert [task.name for task in repository.list(match="B*")] == ["Backup"]
    assert repository.list(match="b*") == []


def test_repository_prevents_overlapping_manual_runs(tmp_path):
    repository = make_repository(tmp_path)
    task = repository.add(ScheduledTask.create("single", ["echo", "ok"], ScheduleSpec.interval(60)))
    first = repository.begin_run(task, utc_now())
    second = repository.begin_run(task, utc_now())
    assert first is not None
    assert second is None
    assert [run["status"] for run in repository.history("single")] == ["skipped", "running"]


def test_reconcile_recovers_finished_orphan_reservations_without_restart(tmp_path, monkeypatch):
    daemon = SchedulerDaemon(make_repository(tmp_path).database_path)
    calls = []
    monkeypatch.setattr(daemon.repository, "mark_interrupted_runs", lambda: calls.append(True) or 0)

    daemon.reconcile()

    assert calls == [True]


def test_overlapping_scheduled_one_shot_is_consumed(tmp_path):
    repository = make_repository(tmp_path)
    task = repository.add(
        ScheduledTask.create(
            "single-date",
            ["echo", "ok"],
            ScheduleSpec.once(utc_now() + timedelta(minutes=1)),
        )
    )
    manual_run = repository.begin_run(task, utc_now())
    assert manual_run is not None

    assert (
        execute_scheduled_task(
            str(repository.database_path),
            task.id,
            task.revision,
            scheduled_for=utc_now().isoformat(),
        )
        is None
    )

    assert repository.resolve(task.id).enabled is False
    assert [run["status"] for run in repository.history(task.id)] == ["skipped", "running"]


def test_repository_rejects_run_reservation_for_stale_revision(tmp_path):
    repository = make_repository(tmp_path)
    stale = repository.add(
        ScheduledTask.create("changing", ["echo", "old"], ScheduleSpec.interval(60))
    )
    repository.add(
        ScheduledTask.create("changing", ["echo", "new"], ScheduleSpec.interval(60)),
        replace_existing=True,
    )

    assert repository.begin_run(stale, utc_now()) is None
    assert repository.history("changing") == []


def test_interrupted_run_cleanup_preserves_live_manual_runner(tmp_path):
    repository = make_repository(tmp_path)
    task = repository.add(ScheduledTask.create("live", ["echo", "ok"], ScheduleSpec.interval(60)))
    run_id = repository.begin_run(task, utc_now())
    assert run_id is not None

    assert repository.mark_interrupted_runs() == 0
    assert repository.history(task.id)[0]["status"] == "running"

    with repository.connect() as db:
        db.execute("UPDATE task_runs SET runner_pid=NULL WHERE id=?", (run_id,))
    assert repository.mark_interrupted_runs() == 1
    assert repository.history(task.id)[0]["status"] == "interrupted"


def test_interrupted_cleanup_rejects_recycled_pid_identity(tmp_path, monkeypatch):
    repository = make_repository(tmp_path)
    task = repository.add(
        ScheduledTask.create("recycled", ["echo", "ok"], ScheduleSpec.interval(60))
    )
    run_id = repository.begin_run(task, utc_now())
    assert run_id is not None
    with repository.connect() as db:
        db.execute(
            "UPDATE task_runs SET runner_pid=123, runner_identity='linux:old' WHERE id=?",
            (run_id,),
        )
    monkeypatch.setattr(repository_module, "_pid_is_running", lambda pid: True)
    monkeypatch.setattr(repository_module, "_process_identity", lambda pid: "linux:new")

    assert repository.mark_interrupted_runs() == 1
    assert repository.history(task.id)[0]["status"] == "interrupted"


def test_windows_runner_liveness_does_not_use_destructive_os_kill(monkeypatch):
    monkeypatch.setattr(repository_module.os, "name", "nt")
    monkeypatch.setattr(repository_module, "_windows_pid_is_running", lambda pid: True)
    monkeypatch.setattr(
        repository_module.os,
        "kill",
        lambda *_args: pytest.fail("os.kill must not be used for Windows liveness checks"),
    )

    assert _pid_is_running(1234) is True


def test_current_process_has_a_reusable_native_identity():
    identity = _process_identity(os.getpid())

    assert identity is not None
    assert _pid_matches_identity(os.getpid(), identity) is True
    assert _pid_matches_identity(os.getpid(), f"{identity}:different") is False


def test_repository_migrates_v1_run_history_without_losing_rows(tmp_path):
    repository = make_repository(tmp_path)
    task = repository.add(ScheduledTask.create("legacy", ["echo", "ok"], ScheduleSpec.interval(60)))
    with sqlite3.connect(repository.database_path) as db:
        db.executescript(
            """
            DROP TABLE task_runs;
            CREATE TABLE task_runs (
                id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                scheduled_for TEXT,
                started_at TEXT,
                finished_at TEXT,
                status TEXT NOT NULL,
                exit_code INTEGER,
                stdout_path TEXT,
                stderr_path TEXT,
                error TEXT,
                FOREIGN KEY(task_id) REFERENCES scheduled_tasks(id) ON DELETE CASCADE
            );
            PRAGMA user_version=1;
            """
        )
        db.execute(
            "INSERT INTO task_runs (id, task_id, status) VALUES ('old-run', ?, 'succeeded')",
            (task.id,),
        )

    migrated = SchedulerRepository(repository.database_path)
    assert migrated.history()[0]["task_name"] == "legacy"
    assert "runner_identity" in migrated.history()[0]
    with migrated.connect() as db:
        assert "process_identity" in {
            row[1] for row in db.execute("PRAGMA table_info(scheduler_state)")
        }
    migrated.delete(task.id)
    assert migrated.history()[0]["task_name"] == "legacy"


def test_repository_rejects_newer_database_schema(tmp_path):
    database_path = tmp_path / "scheduler.sqlite3"
    with sqlite3.connect(database_path) as db:
        db.execute("PRAGMA user_version=999")

    with pytest.raises(RuntimeError, match="newer than this Taskflows version"):
        SchedulerRepository(database_path)


def test_runner_captures_output_environment_and_working_directory(tmp_path):
    repository = make_repository(tmp_path)
    output_file = tmp_path / "result.txt"
    script = (
        "import os, pathlib; "
        f"pathlib.Path({str(output_file)!r}).write_text(os.environ['VALUE'] + ':' + pathlib.Path.cwd().name); "
        "print('stdout'); print('stderr', file=__import__('sys').stderr)"
    )
    task = repository.add(
        ScheduledTask.create(
            "runner",
            [sys.executable, "-c", script],
            ScheduleSpec.interval(60),
            cwd=str(tmp_path),
            environment={"VALUE": "present"},
        )
    )

    assert run_now(repository.database_path, task.id) == 0
    assert output_file.read_text() == f"present:{tmp_path.name}"
    run = repository.history(task.id)[0]
    assert run["status"] == "succeeded"
    assert run["runner_pid"] != os.getpid()
    assert Path(run["stdout_path"]).read_text() == "stdout\n"
    assert Path(run["stderr_path"]).read_text() == "stderr\n"
    if os.name != "nt":
        assert Path(run["stdout_path"]).stat().st_mode & 0o777 == 0o600
        assert Path(run["stderr_path"]).stat().st_mode & 0o777 == 0o600


def test_runner_enforces_timeout(tmp_path):
    repository = make_repository(tmp_path)
    task = repository.add(
        ScheduledTask.create(
            "slow",
            [sys.executable, "-c", "import time; time.sleep(10)"],
            ScheduleSpec.interval(60),
            timeout=0.1,
        )
    )
    started = time.monotonic()
    run_now(repository.database_path, task.id)
    assert time.monotonic() - started < 3
    assert repository.history(task.id)[0]["status"] == "timed_out"


def test_runner_timeout_terminates_child_process_tree(tmp_path):
    repository = make_repository(tmp_path)
    marker = tmp_path / "orphaned-child.txt"
    child = (
        "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
        f"from pathlib import Path; time.sleep(1); Path({str(marker)!r}).touch()"
    )
    parent = (
        "import subprocess, sys, time; "
        f"subprocess.Popen([sys.executable, '-c', {child!r}]); "
        "time.sleep(10)"
    )
    task = repository.add(
        ScheduledTask.create(
            "process-tree",
            [sys.executable, "-c", parent],
            ScheduleSpec.interval(60),
            timeout=0.1,
        )
    )

    run_now(repository.database_path, task.id)
    time.sleep(1.25)

    assert not marker.exists()
    assert repository.history(task.id)[0]["status"] == "timed_out"


def test_runner_finishes_reservation_when_log_setup_fails(tmp_path, monkeypatch):
    repository = make_repository(tmp_path)
    task = repository.add(
        ScheduledTask.create("log-failure", ["echo", "ok"], ScheduleSpec.interval(60))
    )
    log_dir = repository.database_path.parent / "runs" / task.id
    original_mkdir = Path.mkdir

    def fail_log_setup(path, *args, **kwargs):
        if path == log_dir:
            raise PermissionError("cannot create logs")
        return original_mkdir(path, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", fail_log_setup)

    assert run_now(repository.database_path, task.id) == 1

    run = repository.history(task.id)[0]
    assert run["status"] == "failed"
    assert run["finished_at"] is not None
    assert run["error"] == "cannot create logs"


def test_daemon_executes_and_disables_one_time_task(tmp_path):
    repository = make_repository(tmp_path)
    marker = tmp_path / "ran"
    task = repository.add(
        ScheduledTask.create(
            "once",
            [sys.executable, "-c", f"from pathlib import Path; Path({str(marker)!r}).touch()"],
            ScheduleSpec.once(utc_now() + timedelta(milliseconds=300)),
        )
    )
    daemon = SchedulerDaemon(repository.database_path, reconcile_interval=0.05)
    daemon.start()
    try:
        deadline = time.monotonic() + 5
        while not marker.exists() and time.monotonic() < deadline:
            daemon.reconcile()
            time.sleep(0.05)
    finally:
        daemon.shutdown()

    assert marker.exists()
    assert repository.resolve(task.id).enabled is False
    assert [run["status"] for run in repository.history(task.id)] == ["succeeded"]


def test_daemon_records_expired_one_time_misfire(tmp_path):
    repository = make_repository(tmp_path)
    task = repository.add(
        ScheduledTask.create(
            "expired",
            ["echo", "never"],
            ScheduleSpec.once(utc_now() - timedelta(minutes=5)),
            misfire_grace_time=1,
        )
    )
    daemon = SchedulerDaemon(repository.database_path)
    daemon.start()
    daemon.shutdown()

    assert repository.resolve(task.id).enabled is False
    assert repository.history(task.id)[0]["status"] == "missed"


def test_daemon_shutdown_clears_its_heartbeat(tmp_path):
    repository = make_repository(tmp_path)
    daemon = SchedulerDaemon(repository.database_path)
    daemon.start()
    daemon.heartbeat()
    assert repository.daemon_state() is not None

    daemon.shutdown()

    assert repository.daemon_state() is None


def test_daemon_shutdown_cleans_heartbeat_when_scheduler_stop_fails(tmp_path, monkeypatch):
    repository = make_repository(tmp_path)
    daemon = SchedulerDaemon(repository.database_path)
    daemon.heartbeat()
    daemon._started = True
    monkeypatch.setattr(
        daemon.scheduler,
        "shutdown",
        lambda wait: (_ for _ in ()).throw(RuntimeError("stop failed")),
    )

    with pytest.raises(RuntimeError, match="stop failed"):
        daemon.shutdown()

    assert repository.daemon_state() is None
    assert daemon._started is False


def test_daemon_start_cleans_up_when_initial_reconcile_fails(tmp_path, monkeypatch):
    daemon = SchedulerDaemon(make_repository(tmp_path).database_path)
    monkeypatch.setattr(daemon, "reconcile", lambda: (_ for _ in ()).throw(RuntimeError("bad")))

    with pytest.raises(RuntimeError, match="bad"):
        daemon.start()

    assert daemon._started is False
    assert daemon.scheduler.running is False


def test_scheduler_singleton_lock_uses_native_platform_lock(tmp_path):
    lock_path = tmp_path / "scheduler.lock"

    with (
        _SingletonLock(lock_path),
        pytest.raises(DaemonAlreadyRunning),
        _SingletonLock(lock_path),
    ):
        pass

    # The native lock must be released when the first context exits.
    with _SingletonLock(lock_path):
        pass
    assert lock_path.read_text() == str(os.getpid())


def test_stale_scheduler_event_does_not_disable_replacement(tmp_path):
    repository = make_repository(tmp_path)
    original = repository.add(
        ScheduledTask.create(
            "replace-me", ["echo", "old"], ScheduleSpec.once(utc_now() + timedelta(days=1))
        )
    )
    daemon = SchedulerDaemon(repository.database_path)
    job_id = daemon._job_id(original.id)
    daemon._known_revisions[job_id] = original.revision
    daemon._known_date_revisions[job_id] = original.revision
    daemon._submitted_date_jobs[job_id] = original.revision
    replacement = repository.add(
        ScheduledTask.create("replace-me", ["echo", "new"], ScheduleSpec.interval(60)),
        replace_existing=True,
    )

    daemon._on_scheduler_event(
        SimpleNamespace(
            job_id=job_id,
            code=EVENT_JOB_MISSED,
            scheduled_run_time=utc_now(),
        )
    )
    assert repository.resolve(replacement.id).enabled is True
    assert repository.history(replacement.id) == []

    daemon._on_scheduler_event(SimpleNamespace(job_id=job_id, code=EVENT_JOB_EXECUTED))
    assert job_id not in daemon._submitted_date_jobs


def test_late_submission_event_cannot_block_reenabled_one_shot(tmp_path):
    repository = make_repository(tmp_path)
    task = repository.add(
        ScheduledTask.create(
            "fast-once", ["echo", "ok"], ScheduleSpec.once(utc_now() + timedelta(days=1))
        )
    )
    daemon = SchedulerDaemon(repository.database_path)
    job_id = daemon._job_id(task.id)
    daemon._known_revisions[job_id] = task.revision
    daemon._known_date_revisions[job_id] = task.revision

    # A very fast executor can queue completion before APScheduler dispatches
    # its submission event to listeners.
    daemon._on_scheduler_event(SimpleNamespace(job_id=job_id, code=EVENT_JOB_EXECUTED))
    daemon._on_scheduler_event(SimpleNamespace(job_id=job_id, code=EVENT_JOB_SUBMITTED))

    assert job_id not in daemon._submitted_date_jobs
    disabled = repository.resolve(task.id)
    reenabled = repository.set_enabled(task.id, True, expected_revision=disabled.revision)
    assert daemon._add_or_update(reenabled) is not None
    daemon.scheduler.remove_all_jobs()


def test_one_time_scheduler_error_consumes_definition(tmp_path):
    repository = make_repository(tmp_path)
    task = repository.add(
        ScheduledTask.create(
            "error-once",
            ["echo", "never"],
            ScheduleSpec.once(utc_now() + timedelta(days=1)),
        )
    )
    daemon = SchedulerDaemon(repository.database_path)
    job_id = daemon._job_id(task.id)
    daemon._known_revisions[job_id] = task.revision
    daemon._known_date_revisions[job_id] = task.revision

    daemon._on_scheduler_event(SimpleNamespace(job_id=job_id, code=EVENT_JOB_ERROR))

    assert repository.resolve(task.id).enabled is False


def test_one_time_consumption_ignores_a_concurrent_revision_change(tmp_path, monkeypatch):
    repository = make_repository(tmp_path)
    task = repository.add(
        ScheduledTask.create(
            "concurrent-once",
            ["echo", "never"],
            ScheduleSpec.once(utc_now() + timedelta(days=1)),
        )
    )
    daemon = SchedulerDaemon(repository.database_path)

    def changed(*args, **kwargs):
        raise RevisionConflict("changed concurrently")

    monkeypatch.setattr(daemon.repository, "set_enabled", changed)

    # Expected edit races are handled as normal reconciliation, not as an
    # event-listener failure that tears down the scheduler process.
    daemon._disable_if_current(task)


def test_schedule_cli_add_list_and_run(tmp_path, monkeypatch):
    repository = make_repository(tmp_path)
    monkeypatch.setattr("taskflows.scheduler.cli._repository", lambda: repository)
    runner = CliRunner()
    marker = tmp_path / "cli-ran"
    at = (utc_now() + timedelta(days=1)).isoformat()
    result = runner.invoke(
        cli,
        [
            "schedule",
            "add",
            "cli-job",
            "--at",
            at,
            "--",
            sys.executable,
            "-c",
            f"from pathlib import Path; Path({str(marker)!r}).touch()",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "scheduler daemon is not responding" in result.output
    assert repository.resolve("cli-job")
    result = runner.invoke(cli, ["schedule", "list", "--json"])
    assert result.exit_code == 0
    assert '"name": "cli-job"' in result.output
    result = runner.invoke(cli, ["schedule", "run", "cli-job"])
    assert result.exit_code == 0, result.output
    assert marker.exists()
    assert repository.resolve("cli-job").enabled is True


def test_schedule_cli_accepts_human_durations_env_files_and_reads_logs(tmp_path, monkeypatch):
    repository = make_repository(tmp_path)
    monkeypatch.setattr("taskflows.scheduler.cli._repository", lambda: repository)
    env_file = tmp_path / "job.env"
    env_file.write_text("Value=from-file\nSECRET_NAME=hidden\n")
    start_at = (utc_now() + timedelta(days=1)).isoformat()
    runner = CliRunner()

    result = runner.invoke(
        cli,
        [
            "schedule",
            "add",
            "friendly-job",
            "--interval",
            "5m",
            "--start-at",
            start_at,
            "--timeout",
            "1.5h",
            "--env-file",
            str(env_file),
            "--env",
            "VALUE=explicit",
            "--",
            sys.executable,
            "-c",
            "import os; print(os.environ['VALUE'])",
        ],
    )

    assert result.exit_code == 0, result.output
    task = repository.resolve("friendly-job")
    assert task.schedule.value == 300.0
    assert task.schedule.start_at == start_at
    assert task.timeout == 5400.0
    assert task.environment["VALUE"] == "explicit"
    assert "Value" not in task.environment

    shown = runner.invoke(cli, ["schedule", "show", "friendly-job", "--json"])
    assert shown.exit_code == 0, shown.output
    assert "SECRET_NAME" in shown.output
    assert "hidden" not in shown.output

    assert runner.invoke(cli, ["schedule", "run", "friendly-job"]).exit_code == 0
    logs = runner.invoke(cli, ["schedule", "logs", "friendly-job", "--stream", "stdout"])
    assert logs.exit_code == 0, logs.output
    assert logs.output.strip() == "explicit"


def test_schedule_cli_previews_portable_occurrences(tmp_path, monkeypatch):
    repository = make_repository(tmp_path)
    repository.add(
        ScheduledTask.create(
            "daily",
            ["echo", "ok"],
            ScheduleSpec.cron("0 9 * * *", timezone="America/New_York"),
        )
    )
    monkeypatch.setattr("taskflows.scheduler.cli._repository", lambda: repository)

    result = CliRunner().invoke(
        cli,
        [
            "schedule",
            "preview",
            "daily",
            "--from",
            "2026-08-19T10:00:00Z",
            "--count",
            "1",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["occurrences"][0]["local"] == "2026-08-19T09:00:00-04:00"


def test_scheduler_status_rejects_future_heartbeat(tmp_path, monkeypatch):
    repository = make_repository(tmp_path)
    future = utc_now() + timedelta(days=1)
    repository.heartbeat(pid=123, hostname="host", started_at=future)
    with repository.connect() as db:
        db.execute(
            "UPDATE scheduler_state SET heartbeat_at=? WHERE singleton=1", (future.isoformat(),)
        )
    monkeypatch.setattr("taskflows.scheduler.cli._repository", lambda: repository)

    result = CliRunner().invoke(cli, ["scheduler", "status"])

    assert result.exit_code == 1
    assert "in the future" in result.output


def test_portable_status_combines_native_runtime_and_registry(tmp_path):
    repository = make_repository(tmp_path)
    repository.add(ScheduledTask.create("enabled", ["echo", "ok"], ScheduleSpec.interval(60)))
    repository.add(
        ScheduledTask.create("disabled", ["echo", "ok"], ScheduleSpec.interval(60), enabled=False)
    )
    repository.heartbeat(pid=os.getpid(), hostname=socket.gethostname(), started_at=utc_now())
    native = SupervisorStatus(backend="systemd", installed=True, state="running", automatic=True)
    fake_supervisor = SimpleNamespace(status=lambda: native)

    status = scheduler_status(repository, fake_supervisor)

    assert status.state == "running"
    assert status.runtime.healthy is True
    assert status.runtime.pid_running is True
    assert status.task_count == 2
    assert status.enabled_task_count == 1
    assert status.to_dict()["supervisor"]["automatic"] is True


def test_scheduler_doctor_has_stable_actionable_json(tmp_path, monkeypatch):
    repository = make_repository(tmp_path)
    repository.heartbeat(pid=os.getpid(), hostname=socket.gethostname(), started_at=utc_now())
    native = SupervisorStatus(backend="systemd", installed=True, state="running", automatic=True)
    fake_supervisor = SimpleNamespace(status=lambda: native)
    monkeypatch.setattr("taskflows.scheduler.cli._repository", lambda: repository)
    monkeypatch.setattr("taskflows.scheduler.cli.get_supervisor", lambda: fake_supervisor)

    result = CliRunner().invoke(cli, ["scheduler", "doctor", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["status"]["state"] == "running"
    assert {check["name"] for check in payload["checks"]} >= {
        "supervisor-registration",
        "automatic-start",
        "registry",
        "heartbeat",
        "dispatch-readiness",
    }


def test_runtime_status_has_stable_empty_shape(tmp_path):
    status = runtime_status(make_repository(tmp_path))

    assert status.healthy is False
    assert status.pid is None
    assert status.heartbeat_at is None


def test_runtime_status_rejects_a_fresh_heartbeat_owned_by_another_host(tmp_path):
    repository = make_repository(tmp_path)
    repository.heartbeat(pid=os.getpid(), hostname="another-host", started_at=utc_now())

    status = runtime_status(repository)

    assert status.healthy is False
    assert status.pid_running is False


def test_runtime_status_rejects_a_recycled_daemon_pid(tmp_path, monkeypatch):
    repository = make_repository(tmp_path)
    repository.heartbeat(
        pid=123,
        hostname=socket.gethostname(),
        started_at=utc_now(),
        process_identity="linux:old",
    )
    monkeypatch.setattr(repository_module, "_pid_is_running", lambda pid: True)
    monkeypatch.setattr(repository_module, "_process_identity", lambda pid: "linux:new")

    status = runtime_status(repository)

    assert status.healthy is False
    assert status.pid_running is False
    assert status.process_identity == "linux:old"


def test_history_retention_keeps_latest_and_removes_owned_logs(tmp_path, monkeypatch):
    repository = make_repository(tmp_path)
    task = repository.add(
        ScheduledTask.create("retained", ["echo", "ok"], ScheduleSpec.interval(60))
    )
    run_dir = repository.database_path.parent / "runs" / task.id
    run_dir.mkdir(parents=True)
    timestamps = [
        utc_now() - timedelta(days=90),
        utc_now() - timedelta(days=80),
        utc_now() - timedelta(days=70),
    ]
    paths = []
    for index, timestamp in enumerate(timestamps):
        run_id = repository.begin_run(task, timestamp)
        assert run_id is not None
        path = run_dir / f"{run_id}.stdout.log"
        path.write_text(str(index))
        paths.append(path)
        repository.finish_run(run_id, status="succeeded", exit_code=0, stdout_path=str(path))
        with repository.connect() as db:
            db.execute(
                "UPDATE task_runs SET started_at=?, finished_at=? WHERE id=?",
                (timestamp.isoformat(), timestamp.isoformat(), run_id),
            )

    preview = repository.prune_history(
        before=utc_now() - timedelta(days=30), keep_latest=1, dry_run=True
    )
    monkeypatch.setattr("taskflows.scheduler.cli._repository", lambda: repository)
    cli_preview = CliRunner().invoke(
        cli,
        ["schedule", "prune", "--older-than", "30d", "--keep-latest", "1", "--dry-run"],
    )
    result = repository.prune_history(before=utc_now() - timedelta(days=30), keep_latest=1)

    assert preview.runs_deleted == 2
    assert cli_preview.exit_code == 0, cli_preview.output
    assert "Would delete 2 terminal run(s)" in cli_preview.output
    assert result.runs_deleted == 2
    assert result.log_files_deleted == 2
    assert repository.history(task.id, limit=10)[0]["stdout_path"] == str(paths[-1])
    assert not paths[0].exists()
    assert not paths[1].exists()
    assert paths[2].exists()


@pytest.mark.asyncio
async def test_portable_schedule_api_uses_bulk_registry(tmp_path, monkeypatch):
    repository = make_repository(tmp_path)
    monkeypatch.setattr("taskflows.admin.api.SchedulerRepository", lambda: repository)
    marker = tmp_path / "api-ran"
    request = PortableScheduleRequest(
        name="api-job",
        command=[
            sys.executable,
            "-c",
            f"from pathlib import Path; Path({str(marker)!r}).touch()",
        ],
        interval_seconds=3600,
        start_at="2026-08-19T10:00:00Z",
    )
    created = await create_portable_schedule(request)
    listed = await list_portable_schedules(None)
    assert created["name"] == "api-job"
    assert listed["schedules"][0]["name"] == "api-job"
    assert "environment" not in listed["schedules"][0]

    assert await run_portable_schedule("api-job") == {"exit_code": 0}
    assert marker.exists()
    history = await portable_schedule_history("api-job", 10)
    assert history["runs"][0]["status"] == "succeeded"

    preview = await preview_portable_schedule("api-job", count=2, from_time="2026-08-19T10:00:00Z")
    assert len(preview["occurrences"]) == 2
    assert preview["occurrences"][0]["utc"] == "2026-08-19T10:00:00+00:00"


@pytest.mark.asyncio
async def test_portable_schedule_api_reports_revision_conflict(tmp_path, monkeypatch):
    repository = make_repository(tmp_path)
    task = repository.add(
        ScheduledTask.create("api-revision", ["echo", "ok"], ScheduleSpec.interval(60))
    )
    monkeypatch.setattr("taskflows.admin.api.SchedulerRepository", lambda: repository)
    disabled = repository.set_enabled(task.id, False, expected_revision=task.revision)

    with pytest.raises(HTTPException) as raised:
        await set_portable_schedule_enabled(task.id, True, task.revision)

    assert raised.value.status_code == 409
    assert repository.resolve(task.id) == disabled

    replacement = PortableScheduleRequest(
        name="api-revision",
        command=["echo", "new"],
        interval_seconds=120,
        replace_existing=True,
        expected_revision=task.revision,
    )
    with pytest.raises(HTTPException) as replaced:
        await create_portable_schedule(replacement)
    assert replaced.value.status_code == 409


@pytest.mark.asyncio
async def test_portable_schedule_api_get_and_delete_use_revisions(tmp_path, monkeypatch):
    repository = make_repository(tmp_path)
    task = repository.add(
        ScheduledTask.create("api-delete", ["echo", "ok"], ScheduleSpec.interval(60))
    )
    monkeypatch.setattr("taskflows.admin.api.SchedulerRepository", lambda: repository)

    fetched = await get_portable_schedule(task.id)
    assert fetched["name"] == "api-delete"
    assert "environment" not in fetched

    current = repository.set_enabled(task.id, False, expected_revision=task.revision)
    with pytest.raises(HTTPException) as raised:
        await delete_portable_schedule(task.id, task.revision)
    assert raised.value.status_code == 409

    assert await delete_portable_schedule(task.id, current.revision) is None
    assert repository.get(task.id) is None


@pytest.mark.asyncio
async def test_scheduler_api_reuses_portable_status_contract(tmp_path, monkeypatch):
    repository = make_repository(tmp_path)
    repository.heartbeat(pid=os.getpid(), hostname=socket.gethostname(), started_at=utc_now())
    native = SupervisorStatus(backend="systemd", installed=True, state="running", automatic=True)
    current = scheduler_status(repository, SimpleNamespace(status=lambda: native))
    checks = [DiagnosticCheck("heartbeat", "ok", "healthy")]
    monkeypatch.setattr("taskflows.admin.api.scheduler_status", lambda: current)
    monkeypatch.setattr("taskflows.admin.api.diagnose_scheduler", lambda: (current, checks))

    status_payload = await portable_scheduler_status()
    diagnostic_payload = await portable_scheduler_diagnostics()

    assert status_payload["state"] == "running"
    assert diagnostic_payload["status"] == status_payload
    assert diagnostic_payload["checks"] == [checks[0].to_dict()]


@pytest.mark.asyncio
async def test_list_servers_endpoint_uses_core_signature(monkeypatch):
    expected = {"servers": [], "hostname": "test"}

    async def fake_list_servers():
        return expected

    monkeypatch.setattr("taskflows.admin.api.list_servers", fake_list_servers)
    assert await list_servers_endpoint() == expected


def test_linux_installer_writes_one_user_service(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(installer, "_home_dir", lambda: tmp_path)
    monkeypatch.setattr(installer, "services_data_dir", tmp_path / "data%dir")
    monkeypatch.setattr(installer, "_run", lambda command, check=True: calls.append(command))

    unit_path = installer.install_linux()
    content = unit_path.read_text()
    assert "taskflows.scheduler.daemon" in content
    assert str(tmp_path / "data%%dir" / "scheduler.sqlite3") in content
    assert f"TASKFLOWS_DATA_DIR={tmp_path / 'data%%dir'}" in content
    assert unit_path.stat().st_mode & 0o777 == 0o600
    assert "Restart=on-failure" in content
    assert calls[-2:] == [
        ["systemctl", "--user", "enable", installer.LINUX_UNIT_NAME],
        ["systemctl", "--user", "restart", installer.LINUX_UNIT_NAME],
    ]


def test_supervisor_selection_exposes_one_common_lifecycle():
    assert isinstance(supervisor.get_supervisor("linux"), supervisor.SystemdSupervisor)
    assert isinstance(supervisor.get_supervisor("darwin"), supervisor.LaunchdSupervisor)
    assert isinstance(supervisor.get_supervisor("win32"), supervisor.WindowsTaskSupervisor)
    with pytest.raises(NotImplementedError, match="unsupported"):
        supervisor.get_supervisor("plan9")


def test_systemd_supervisor_reports_native_state(tmp_path, monkeypatch):
    unit = tmp_path / ".config" / "systemd" / "user" / installer.LINUX_UNIT_NAME
    unit.parent.mkdir(parents=True)
    unit.write_text("unit")
    monkeypatch.setattr(installer, "_home_dir", lambda: tmp_path)
    monkeypatch.setattr(
        installer,
        "_run",
        lambda command, check=True: __import__("subprocess").CompletedProcess(
            command, 0, "enabled\n" if "is-enabled" in command else "active\n", ""
        ),
    )

    status = supervisor.SystemdSupervisor().status()

    assert status.installed is True
    assert status.state == "running"
    assert status.backend == "systemd"
    assert status.automatic is True


def test_launchd_supervisor_distinguishes_loaded_but_stopped(tmp_path, monkeypatch):
    plist = tmp_path / "Library" / "LaunchAgents" / f"{installer.MACOS_LABEL}.plist"
    plist.parent.mkdir(parents=True)
    plist.write_text("plist")
    monkeypatch.setattr(installer, "_home_dir", lambda: tmp_path)
    monkeypatch.setattr(supervisor.os, "getuid", lambda: 501, raising=False)
    monkeypatch.setattr(
        installer,
        "_run",
        lambda command, check=True: __import__("subprocess").CompletedProcess(
            command, 0, "state = exited\n", ""
        ),
    )

    status = supervisor.LaunchdSupervisor().status()

    assert status.installed is True
    assert status.state == "stopped"


def test_launchd_stop_preserves_login_autostart_and_reports_last_failure(tmp_path, monkeypatch):
    plist = tmp_path / "Library" / "LaunchAgents" / f"{installer.MACOS_LABEL}.plist"
    plist.parent.mkdir(parents=True)
    plist.write_text("plist")
    calls = []
    monkeypatch.setattr(installer, "_home_dir", lambda: tmp_path)
    monkeypatch.setattr(supervisor.os, "getuid", lambda: 501, raising=False)

    def run(command, check=True):
        calls.append(command)
        output = (
            f'{{ "{installer.MACOS_LABEL}" => false }}'
            if command[:2] == ["launchctl", "print-disabled"]
            else "state = exited\nlast exit code = 7\n"
        )
        return __import__("subprocess").CompletedProcess(command, 0, output, "")

    monkeypatch.setattr(installer, "_run", run)
    adapter = supervisor.LaunchdSupervisor()

    adapter.stop()
    status = adapter.status()

    assert not any(command[:2] == ["launchctl", "disable"] for command in calls)
    assert status.automatic is True
    assert status.state == "failed"
    assert status.last_exit_code == 7


@pytest.mark.parametrize(
    ("native_state", "expected"),
    [
        (4, "running"),
        (3, "stopped"),
        (2, "starting"),
        (1, "stopped"),
        (0, "unknown"),
    ],
)
def test_windows_supervisor_normalizes_task_states(native_state, expected, monkeypatch):
    monkeypatch.setattr(
        supervisor, "_windows_registered_task", lambda: SimpleNamespace(State=native_state)
    )

    status = supervisor.WindowsTaskSupervisor().status()

    assert status.installed is True
    assert status.state == expected


def test_launchd_restart_bootstraps_an_unloaded_agent(tmp_path, monkeypatch):
    plist = tmp_path / "Library" / "LaunchAgents" / f"{installer.MACOS_LABEL}.plist"
    plist.parent.mkdir(parents=True)
    plist.write_text("plist")
    calls = []
    monkeypatch.setattr(installer, "_home_dir", lambda: tmp_path)
    monkeypatch.setattr(supervisor.os, "getuid", lambda: 501, raising=False)

    def run(command, check=True):
        calls.append(command)
        return __import__("subprocess").CompletedProcess(
            command,
            1 if command[:2] == ["launchctl", "print"] else 0,
            "",
            "not loaded" if command[:2] == ["launchctl", "print"] else "",
        )

    monkeypatch.setattr(installer, "_run", run)

    supervisor.LaunchdSupervisor().restart()

    assert any(command[:2] == ["launchctl", "bootstrap"] for command in calls)
    assert calls[-1][:3] == ["launchctl", "kickstart", "-k"]


def test_macos_installer_writes_launch_agent(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(installer, "_home_dir", lambda: tmp_path)
    monkeypatch.setattr(installer, "services_data_dir", tmp_path / "data")
    monkeypatch.setattr(installer.os, "getuid", lambda: 501, raising=False)
    monkeypatch.setattr(installer, "_run", lambda command, check=True: calls.append(command))

    plist_path = installer.install_macos()
    with plist_path.open("rb") as stream:
        definition = plistlib.load(stream)
    assert definition["Label"] == installer.MACOS_LABEL
    assert definition["KeepAlive"] == {"SuccessfulExit": False}
    assert definition["ProgramArguments"][1:3] == ["-m", "taskflows.scheduler.daemon"]
    assert definition["ProgramArguments"][-1] == str(tmp_path / "data" / "scheduler.sqlite3")
    assert plist_path.stat().st_mode & 0o777 == 0o600
    assert (tmp_path / "data").stat().st_mode & 0o777 == 0o700
    assert (tmp_path / "data" / "logs").stat().st_mode & 0o777 == 0o700
    enable_index = next(
        i for i, command in enumerate(calls) if command[:2] == ["launchctl", "enable"]
    )
    bootstrap_index = next(
        i for i, command in enumerate(calls) if command[:2] == ["launchctl", "bootstrap"]
    )
    assert enable_index < bootstrap_index


def test_windows_installer_registers_per_user_task(tmp_path, monkeypatch):
    settings = SimpleNamespace()
    trigger = SimpleNamespace()
    definition = SimpleNamespace(
        RegistrationInfo=SimpleNamespace(),
        Principal=SimpleNamespace(),
        Settings=settings,
        Triggers=SimpleNamespace(Create=lambda kind: trigger),
    )
    action = SimpleNamespace()
    definition.Actions = SimpleNamespace(Create=lambda kind: action)

    class FakeTask:
        ran = False
        stopped = False

        def Run(self, argument):
            self.ran = True

        def Stop(self, flags):
            self.stopped = True

    task = FakeTask()

    class FakeFolder:
        registered = None

        def RegisterTaskDefinition(self, *args):
            self.registered = args

        def GetTask(self, name):
            return task

    folder = FakeFolder()

    class FakeRoot:
        def GetFolder(self, name):
            raise RuntimeError("missing")

        def CreateFolder(self, name):
            assert name == installer.WINDOWS_TASK_FOLDER
            return folder

    scheduler = SimpleNamespace(
        Connect=lambda: None,
        GetFolder=lambda name: FakeRoot(),
        NewTask=lambda flags: definition,
    )
    client = ModuleType("win32com.client")
    client.Dispatch = lambda name: scheduler
    package = ModuleType("win32com")
    package.client = client
    win32api = ModuleType("win32api")
    win32api.NameSamCompatible = 2
    win32api.GetUserNameEx = lambda name_format: "EXAMPLE\\scheduler-user"
    monkeypatch.setitem(sys.modules, "win32api", win32api)
    monkeypatch.setitem(sys.modules, "win32com", package)
    monkeypatch.setitem(sys.modules, "win32com.client", client)
    monkeypatch.setattr(installer, "services_data_dir", tmp_path / "custom-data")

    installer.install_windows()

    assert folder.registered[0] == installer.WINDOWS_TASK_NAME
    assert folder.registered[3] == "EXAMPLE\\scheduler-user"
    assert folder.registered[5] == installer._TASK_LOGON_INTERACTIVE_TOKEN
    assert definition.Principal.UserId == "EXAMPLE\\scheduler-user"
    assert definition.Principal.LogonType == 3
    assert trigger.UserId == "EXAMPLE\\scheduler-user"
    assert trigger.Enabled is True
    assert definition.Settings.ExecutionTimeLimit == "PT0S"
    assert definition.Settings.DisallowStartIfOnBatteries is False
    assert definition.Settings.StopIfGoingOnBatteries is False
    assert definition.Settings.RunOnlyIfIdle is False
    assert definition.Settings.RunOnlyIfNetworkAvailable is False
    assert definition.Settings.AllowDemandStart is True
    assert action.Path == sys.executable
    assert "taskflows.scheduler.daemon" in action.Arguments
    assert str(tmp_path / "custom-data" / "scheduler.sqlite3") in action.Arguments
    assert task.stopped
    assert task.ran


def test_windows_uninstaller_deletes_task_even_when_stop_fails(monkeypatch):
    class FakeTask:
        def Stop(self, flags):
            raise RuntimeError("task is not running")

    class FakeFolder:
        deleted = False

        def GetTask(self, name):
            assert name == installer.WINDOWS_TASK_NAME
            return FakeTask()

        def DeleteTask(self, name, flags):
            assert name == installer.WINDOWS_TASK_NAME
            self.deleted = True

    folder = FakeFolder()
    scheduler = SimpleNamespace(
        Connect=lambda: None,
        GetFolder=lambda name: folder,
    )
    client = ModuleType("win32com.client")
    client.Dispatch = lambda name: scheduler
    package = ModuleType("win32com")
    package.client = client
    monkeypatch.setitem(sys.modules, "win32com", package)
    monkeypatch.setitem(sys.modules, "win32com.client", client)

    installer.uninstall_windows()

    assert folder.deleted
