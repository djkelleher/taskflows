"""Portable scheduler status and diagnostics.

Native supervisors answer whether the daemon process is registered and running.
The Taskflows heartbeat answers whether that process is actually reconciling the
selected registry.  Keeping both views in one model prevents each CLI/API client
from inventing subtly different health semantics.
"""

from __future__ import annotations

import os
import shutil
import socket
import sqlite3
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from .models import ScheduledTask, merge_environment, parse_datetime
from .repository import SchedulerRepository, _pid_matches_identity
from .supervisor import SchedulerSupervisor, SupervisorStatus, get_supervisor

DEFAULT_HEARTBEAT_TIMEOUT_SECONDS = 5.0
OverallSchedulerState = Literal[
    "running", "starting", "stopped", "failed", "unresponsive", "not-installed", "unknown"
]
CheckLevel = Literal["ok", "warning", "error"]
WaitTarget = Literal["running", "stopped"]
SchedulerOperation = Literal["install", "uninstall", "start", "stop", "restart"]


@dataclass(frozen=True)
class SchedulerRuntimeStatus:
    """Normalized heartbeat state for one Taskflows scheduler registry."""

    healthy: bool
    pid: int | None = None
    pid_running: bool | None = None
    process_identity: str | None = None
    hostname: str | None = None
    started_at: str | None = None
    heartbeat_at: str | None = None
    heartbeat_age_seconds: float | None = None


@dataclass(frozen=True)
class SchedulerStatus:
    """Combined native-supervisor and Taskflows-runtime status."""

    state: OverallSchedulerState
    supervisor: SupervisorStatus
    runtime: SchedulerRuntimeStatus
    database_path: str
    task_count: int
    enabled_task_count: int
    queued_occurrence_count: int
    running_run_count: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DiagnosticCheck:
    """One actionable result returned by :func:`diagnose_scheduler`."""

    name: str
    level: CheckLevel
    message: str
    remedy: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def runtime_status(
    repository: SchedulerRepository,
    *,
    heartbeat_timeout: float = DEFAULT_HEARTBEAT_TIMEOUT_SECONDS,
    now: datetime | None = None,
) -> SchedulerRuntimeStatus:
    """Read a stable runtime status shape, including absent/corrupt heartbeats."""

    state = repository.daemon_state()
    if state is None:
        return SchedulerRuntimeStatus(healthy=False)

    heartbeat_value = state.get("heartbeat_at")
    age: float | None = None
    if heartbeat_value:
        try:
            heartbeat = parse_datetime(heartbeat_value).astimezone(UTC)
            age = ((now or datetime.now(UTC)).astimezone(UTC) - heartbeat).total_seconds()
        except (TypeError, ValueError):
            pass

    pid_value = state.get("pid")
    pid = pid_value if isinstance(pid_value, int) and not isinstance(pid_value, bool) else None
    hostname = state.get("hostname")
    local_owner = isinstance(hostname, str) and hostname == socket.gethostname()
    process_identity = state.get("process_identity")
    pid_running = (
        _pid_matches_identity(pid, process_identity) if pid is not None and local_owner else False
    )
    healthy = age is not None and 0 <= age < heartbeat_timeout and pid_running is True
    return SchedulerRuntimeStatus(
        healthy=healthy,
        pid=pid,
        pid_running=pid_running,
        process_identity=process_identity,
        hostname=hostname,
        started_at=state.get("started_at"),
        heartbeat_at=heartbeat_value,
        heartbeat_age_seconds=age,
    )


def scheduler_status(
    repository: SchedulerRepository | None = None,
    supervisor: SchedulerSupervisor | None = None,
    *,
    heartbeat_timeout: float = DEFAULT_HEARTBEAT_TIMEOUT_SECONDS,
) -> SchedulerStatus:
    """Return the common scheduler status used by all platform-facing clients."""

    repository = repository or SchedulerRepository()
    native = (supervisor or get_supervisor()).status()
    runtime = runtime_status(repository, heartbeat_timeout=heartbeat_timeout)
    tasks = repository.list()
    active_runs = repository.active_run_counts()
    if runtime.healthy:
        state: OverallSchedulerState = "running"
    elif native.state in {"not-installed", "starting", "failed", "unknown"}:
        state = native.state
    elif native.state == "running":
        state = "unresponsive"
    else:
        state = "stopped"
    return SchedulerStatus(
        state=state,
        supervisor=native,
        runtime=runtime,
        database_path=str(repository.database_path.resolve()),
        task_count=len(tasks),
        enabled_task_count=sum(task.enabled for task in tasks),
        queued_occurrence_count=active_runs["queued"],
        running_run_count=active_runs["running"],
    )


def wait_for_scheduler(
    target: WaitTarget,
    repository: SchedulerRepository | None = None,
    supervisor: SchedulerSupervisor | None = None,
    *,
    timeout: float = 15.0,
    poll_interval: float = 0.2,
) -> SchedulerStatus:
    """Wait for the combined native/runtime contract to reach a lifecycle target."""
    if timeout <= 0:
        raise ValueError("timeout must be greater than zero")
    repository = repository or SchedulerRepository()
    supervisor = supervisor or get_supervisor()
    deadline = time.monotonic() + timeout
    current = scheduler_status(repository, supervisor)
    while True:
        reached = (
            current.runtime.healthy and current.supervisor.state == "running"
            if target == "running"
            else (
                current.supervisor.state not in {"running", "starting"}
                and not current.runtime.healthy
            )
        )
        if reached:
            return current
        if time.monotonic() >= deadline:
            raise TimeoutError(
                f"scheduler did not become {target} within {timeout:g}s "
                f"(current state: {current.state})"
            )
        time.sleep(min(poll_interval, max(deadline - time.monotonic(), 0)))
        current = scheduler_status(repository, supervisor)


def operate_scheduler(
    operation: SchedulerOperation,
    repository: SchedulerRepository | None = None,
    supervisor: SchedulerSupervisor | None = None,
    *,
    wait: bool = True,
    timeout: float = 15.0,
) -> SchedulerStatus:
    """Apply one normalized native lifecycle operation.

    Keeping lifecycle dispatch and readiness waiting here gives Python, CLI,
    and REST clients identical install/start/stop semantics on every supported
    operating system.
    """
    repository = repository or SchedulerRepository()
    supervisor = supervisor or get_supervisor()
    operations = {
        "install": supervisor.install,
        "uninstall": supervisor.uninstall,
        "start": supervisor.start,
        "stop": supervisor.stop,
        "restart": supervisor.restart,
    }
    try:
        action = operations[operation]
    except KeyError as exc:
        raise ValueError(f"unsupported scheduler operation: {operation}") from exc
    action()
    if not wait:
        return scheduler_status(repository, supervisor)
    target: WaitTarget = "stopped" if operation in {"stop", "uninstall"} else "running"
    return wait_for_scheduler(target, repository, supervisor, timeout=timeout)


def diagnose_scheduler(
    repository: SchedulerRepository | None = None,
    supervisor: SchedulerSupervisor | None = None,
) -> tuple[SchedulerStatus, list[DiagnosticCheck]]:
    """Inspect native registration, registry integrity, and runtime health."""

    repository = repository or SchedulerRepository()
    status = scheduler_status(repository, supervisor)
    checks: list[DiagnosticCheck] = []

    if status.supervisor.installed:
        checks.append(
            DiagnosticCheck(
                "supervisor-registration",
                "ok",
                f"registered with {status.supervisor.backend}",
            )
        )
    else:
        checks.append(
            DiagnosticCheck(
                "supervisor-registration",
                "error",
                f"not registered with {status.supervisor.backend}",
                "run 'tf scheduler install'",
            )
        )

    if status.supervisor.automatic is False:
        checks.append(
            DiagnosticCheck(
                "automatic-start",
                "warning",
                "native registration is disabled for future login/boot starts",
                "run 'tf scheduler install' to re-enable and refresh the registration",
            )
        )
    elif status.supervisor.automatic is True:
        checks.append(
            DiagnosticCheck(
                "automatic-start",
                "ok",
                "native registration is enabled for future login/boot starts",
            )
        )

    if status.supervisor.state == "running":
        checks.append(DiagnosticCheck("native-process", "ok", "native supervisor reports running"))
    elif status.supervisor.state == "starting":
        checks.append(
            DiagnosticCheck("native-process", "warning", "native supervisor reports starting")
        )
    else:
        detail = f": {status.supervisor.detail}" if status.supervisor.detail else ""
        if status.supervisor.last_exit_code not in (None, 0):
            detail += f" (last exit code {status.supervisor.last_exit_code})"
        log_remedy = (
            f"inspect {status.supervisor.log_hint}"
            if status.supervisor.log_hint
            else "inspect the native supervisor logs"
        )
        checks.append(
            DiagnosticCheck(
                "native-process",
                "error",
                f"native supervisor reports {status.supervisor.state}{detail}",
                f"run 'tf scheduler start', then {log_remedy}",
            )
        )

    database = Path(status.database_path)
    try:
        with sqlite3.connect(database, timeout=10) as connection:
            integrity = connection.execute("PRAGMA quick_check").fetchone()[0]
        if integrity != "ok":
            raise sqlite3.DatabaseError(str(integrity))
    except (OSError, sqlite3.Error) as exc:
        checks.append(
            DiagnosticCheck(
                "registry",
                "error",
                f"registry check failed: {exc}",
                f"check permissions and free space for {database}",
            )
        )
    else:
        writable = os.access(database, os.R_OK | os.W_OK) and os.access(database.parent, os.W_OK)
        checks.append(
            DiagnosticCheck(
                "registry",
                "ok" if writable else "error",
                f"SQLite registry is healthy at {database}"
                if writable
                else f"SQLite registry or its directory is not writable: {database}",
                None if writable else "restore owner read/write permissions",
            )
        )

    if status.runtime.healthy:
        age = status.runtime.heartbeat_age_seconds or 0.0
        checks.append(DiagnosticCheck("heartbeat", "ok", f"daemon heartbeat is {age:.1f}s old"))
    elif status.runtime.heartbeat_at is None:
        checks.append(
            DiagnosticCheck(
                "heartbeat",
                "error",
                "no daemon heartbeat is recorded",
                "start the scheduler and inspect its native logs if this persists",
            )
        )
    else:
        heartbeat_age = status.runtime.heartbeat_age_seconds
        description = "invalid" if heartbeat_age is None else f"{heartbeat_age:.1f}s old"
        checks.append(
            DiagnosticCheck(
                "heartbeat",
                "error",
                f"daemon heartbeat is stale or invalid ({description})",
                "restart the scheduler and inspect its native logs",
            )
        )

    enabled_tasks = repository.list(enabled=True)
    definition_errors = _task_definition_errors(enabled_tasks)
    if definition_errors:
        shown = "; ".join(definition_errors[:5])
        omitted = len(definition_errors) - 5
        if omitted:
            shown += f"; and {omitted} more"
        checks.append(
            DiagnosticCheck(
                "task-definitions",
                "error",
                shown,
                "replace invalid definitions with an existing working directory and "
                "an absolute executable path",
            )
        )
    else:
        checks.append(
            DiagnosticCheck(
                "task-definitions",
                "ok",
                f"{len(enabled_tasks)} enabled schedule definitions are locally executable",
            )
        )

    if status.enabled_task_count and status.state != "running":
        checks.append(
            DiagnosticCheck(
                "dispatch-readiness",
                "warning",
                f"{status.enabled_task_count} enabled task(s) cannot be confirmed dispatch-ready",
                "resolve the scheduler errors above before relying on future occurrences",
            )
        )
    else:
        checks.append(
            DiagnosticCheck(
                "dispatch-readiness",
                "ok",
                f"{status.enabled_task_count} of {status.task_count} task(s) enabled",
            )
        )

    if status.queued_occurrence_count:
        checks.append(
            DiagnosticCheck(
                "queued-occurrences",
                "ok" if status.state == "running" else "warning",
                f"{status.queued_occurrence_count} durable occurrence(s) awaiting a worker",
                None
                if status.state == "running"
                else "start the scheduler; queued occurrences will be recovered automatically",
            )
        )
    return status, checks


def _task_definition_errors(tasks: list[ScheduledTask]) -> list[str]:
    """Return portable preflight failures without executing user commands."""
    errors: list[str] = []
    for task in tasks:
        working_directory = Path(task.cwd) if task.cwd else None
        if working_directory is not None and not working_directory.is_dir():
            errors.append(f"{task.name}: working directory does not exist ({working_directory})")
            # A relative executable cannot be evaluated against an invalid cwd.
            continue

        executable = task.command[0]
        has_separator = any(
            separator and separator in executable for separator in (os.sep, os.altsep)
        )
        if has_separator or Path(executable).is_absolute():
            executable_path = Path(executable)
            if not executable_path.is_absolute():
                executable_path = (working_directory or Path.cwd()) / executable_path
            if not executable_path.is_file():
                errors.append(f"{task.name}: executable does not exist ({executable_path})")
            elif os.name != "nt" and not os.access(executable_path, os.X_OK):
                errors.append(f"{task.name}: executable is not runnable ({executable_path})")
            continue

        environment = merge_environment(os.environ, task.environment)
        path_value = next(
            (value for name, value in environment.items() if name.casefold() == "path"),
            None,
        )
        if shutil.which(executable, path=path_value) is None:
            errors.append(f"{task.name}: executable is not on PATH ({executable})")
    return errors
