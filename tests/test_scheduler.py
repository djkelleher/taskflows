import os
import plistlib
import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED, EVENT_JOB_MISSED
from click.testing import CliRunner

from taskflows.admin.api import (
    create_portable_schedule,
    list_portable_schedules,
    portable_schedule_history,
    run_portable_schedule,
)
from taskflows.admin.cli import cli
from taskflows.admin.models import PortableScheduleRequest
from taskflows.schedule import Calendar
from taskflows.scheduler import installer
from taskflows.scheduler import repository as repository_module
from taskflows.scheduler.daemon import DaemonAlreadyRunning, SchedulerDaemon, _SingletonLock
from taskflows.scheduler.models import ScheduledTask, ScheduleSpec, utc_now
from taskflows.scheduler.repository import SchedulerRepository, _pid_is_running
from taskflows.scheduler.runner import execute_scheduled_task, run_now


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


def test_windows_runner_liveness_does_not_use_destructive_os_kill(monkeypatch):
    monkeypatch.setattr(repository_module.os, "name", "nt")
    monkeypatch.setattr(repository_module, "_windows_pid_is_running", lambda pid: True)
    monkeypatch.setattr(
        repository_module.os,
        "kill",
        lambda *_args: pytest.fail("os.kill must not be used for Windows liveness checks"),
    )

    assert _pid_is_running(1234) is True


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
    migrated.delete(task.id)
    assert migrated.history()[0]["task_name"] == "legacy"


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
    assert Path(run["stdout_path"]).read_text() == "stdout\n"
    assert Path(run["stderr_path"]).read_text() == "stderr\n"


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
    daemon._submitted_date_jobs.add(job_id)
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
    assert repository.resolve("cli-job")
    result = runner.invoke(cli, ["schedule", "list", "--json"])
    assert result.exit_code == 0
    assert '"name": "cli-job"' in result.output
    result = runner.invoke(cli, ["schedule", "run", "cli-job"])
    assert result.exit_code == 0, result.output
    assert marker.exists()
    assert repository.resolve("cli-job").enabled is True


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

    assert result.exit_code == 0
    assert result.output.strip() == "stopped or unresponsive"


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
    assert calls[-1] == ["systemctl", "--user", "enable", "--now", installer.LINUX_UNIT_NAME]


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
