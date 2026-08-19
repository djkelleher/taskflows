"""Portable scheduling for short-lived Taskflows jobs.

The operating system supervises one Taskflows scheduler daemon. Individual
jobs are persisted in Taskflows' SQLite registry and dispatched by
APScheduler, so their schedule semantics are the same on Linux, macOS and
Windows.
"""

from .models import ScheduledTask, ScheduleSpec, schedule_preview
from .repository import HistoryPruneResult, SchedulerRepository
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
    "ScheduleSpec",
    "ScheduledTask",
    "SchedulerRepository",
    "SchedulerOperation",
    "SchedulerRuntimeStatus",
    "SchedulerStatus",
    "SchedulerSupervisor",
    "SupervisorStatus",
    "diagnose_scheduler",
    "get_supervisor",
    "operate_scheduler",
    "schedule_preview",
    "scheduler_status",
    "wait_for_scheduler",
]
