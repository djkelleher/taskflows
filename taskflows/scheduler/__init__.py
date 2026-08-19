"""Portable scheduling for short-lived Taskflows jobs.

The operating system supervises one Taskflows scheduler daemon. Individual
jobs are persisted in Taskflows' SQLite registry and dispatched by
APScheduler, so their schedule semantics are the same on Linux, macOS and
Windows.
"""

from .models import ScheduledTask, ScheduleSpec
from .repository import HistoryPruneResult, SchedulerRepository
from .status import (
    DiagnosticCheck,
    SchedulerRuntimeStatus,
    SchedulerStatus,
    diagnose_scheduler,
    scheduler_status,
)
from .supervisor import SchedulerSupervisor, SupervisorStatus, get_supervisor

__all__ = [
    "DiagnosticCheck",
    "HistoryPruneResult",
    "ScheduleSpec",
    "ScheduledTask",
    "SchedulerRepository",
    "SchedulerRuntimeStatus",
    "SchedulerStatus",
    "SchedulerSupervisor",
    "SupervisorStatus",
    "diagnose_scheduler",
    "get_supervisor",
    "scheduler_status",
]
