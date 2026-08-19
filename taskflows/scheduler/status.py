"""Portable scheduler status and diagnostics.

Native supervisors answer whether the daemon process is registered and running.
The Taskflows heartbeat answers whether that process is actually reconciling the
selected registry.  Keeping both views in one model prevents each CLI/API client
from inventing subtly different health semantics.
"""

from __future__ import annotations

import os
import socket
import sqlite3
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from .models import parse_datetime
from .repository import SchedulerRepository, _pid_matches_identity
from .supervisor import SchedulerSupervisor, SupervisorStatus, get_supervisor

DEFAULT_HEARTBEAT_TIMEOUT_SECONDS = 5.0
OverallSchedulerState = Literal[
    "running", "starting", "stopped", "failed", "unresponsive", "not-installed", "unknown"
]
CheckLevel = Literal["ok", "warning", "error"]


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
    )


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
        checks.append(
            DiagnosticCheck(
                "native-process",
                "error",
                f"native supervisor reports {status.supervisor.state}{detail}",
                "run 'tf scheduler start', then inspect the native supervisor logs",
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
    return status, checks
