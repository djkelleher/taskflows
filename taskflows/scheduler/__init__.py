"""Portable scheduling for short-lived Taskflows jobs.

The operating system supervises one Taskflows scheduler daemon. Individual
jobs are persisted in Taskflows' SQLite registry and dispatched by
APScheduler, so their schedule semantics are the same on Linux, macOS and
Windows.
"""

from .models import RunHandle, ScheduledTask, ScheduleSpec, schedule_preview
from .repository import HistoryPruneResult, SchedulerRepository
from .runner import cancel_run, enqueue_now, submit_now
from .status import (
    DiagnosticCheck,
    SchedulerOperation,
    SchedulerRuntimeStatus,
    SchedulerStatus,
    diagnose_scheduler,
    operate_scheduler,
    scheduler_status,
    wait_for_scheduler,
)
from .supervisor import SchedulerSupervisor, SupervisorStatus, get_supervisor

__all__ = [
    "DiagnosticCheck",
    "HistoryPruneResult",
    "RunHandle",
    "ScheduleSpec",
    "ScheduledTask",
    "SchedulerRepository",
    "SchedulerOperation",
    "SchedulerRuntimeStatus",
    "SchedulerStatus",
    "SchedulerSupervisor",
    "SupervisorStatus",
    "diagnose_scheduler",
    "cancel_run",
    "enqueue_now",
    "get_supervisor",
    "operate_scheduler",
    "schedule_preview",
    "scheduler_status",
    "submit_now",
    "wait_for_scheduler",
]
