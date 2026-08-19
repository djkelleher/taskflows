"""APScheduler executor with a durable registry handoff.

APScheduler normally submits a callable and then advances its persistent
trigger. A daemon crash between those operations can lose an occurrence. This
executor writes each due occurrence to Taskflows' registry before submitting
the worker, and replacement daemons can adopt queued rows left behind.
"""

from __future__ import annotations

import logging
import sys
import traceback
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from apscheduler.events import (
    EVENT_JOB_ERROR,
    EVENT_JOB_EXECUTED,
    EVENT_JOB_MISSED,
    JobExecutionEvent,
)
from apscheduler.executors.pool import ThreadPoolExecutor

from .repository import QueuedOccurrence, SchedulerRepository
from .runner import execute_scheduled_task


def _run_reserved_job(
    job: Any,
    jobstore_alias: str,
    occurrences: list[QueuedOccurrence],
    logger_name: str,
) -> list[JobExecutionEvent]:
    """Execute already-persisted occurrences with APScheduler-compatible events."""
    events: list[JobExecutionEvent] = []
    logger = logging.getLogger(logger_name)
    for occurrence in occurrences:
        logger.info('Running job "%s" (scheduled at %s)', job, occurrence.scheduled_for)
        kwargs = dict(job.kwargs)
        kwargs.update(
            run_id=occurrence.run_id,
            scheduled_for=occurrence.scheduled_for.isoformat(),
        )
        try:
            retval = job.func(*job.args, **kwargs)
        except BaseException as exc:
            _, _, tb = sys.exc_info()
            formatted_tb = "".join(traceback.format_tb(tb)) if tb is not None else ""
            events.append(
                JobExecutionEvent(
                    EVENT_JOB_ERROR,
                    job.id,
                    jobstore_alias,
                    occurrence.scheduled_for,
                    exception=exc,
                    traceback=formatted_tb,
                )
            )
            logger.exception('Job "%s" raised an exception', job)
            if tb is not None:
                traceback.clear_frames(tb)
        else:
            events.append(
                JobExecutionEvent(
                    EVENT_JOB_EXECUTED,
                    job.id,
                    jobstore_alias,
                    occurrence.scheduled_for,
                    retval=retval,
                )
            )
            logger.info('Job "%s" executed successfully', job)
    return events


def _run_recovered(database_path: str, occurrences: list[QueuedOccurrence]) -> None:
    """Execute orphaned queued work, serially per task to preserve catch-up order."""
    for occurrence in occurrences:
        execute_scheduled_task(
            database_path,
            occurrence.task_id,
            occurrence.revision,
            run_id=occurrence.run_id,
            scheduled_for=occurrence.scheduled_for.isoformat(),
        )


class DurableThreadPoolExecutor(ThreadPoolExecutor):
    """Thread pool that persists scheduled occurrences before dispatch."""

    def __init__(self, database_path: str, max_workers: int = 10) -> None:
        super().__init__(max_workers=max_workers)
        self.database_path = database_path

    def _do_submit_job(self, job: Any, run_times: list[datetime]) -> None:
        repository = SchedulerRepository(self.database_path)
        task_id = str(job.kwargs["task_id"])
        revision = int(job.kwargs["revision"])
        task = repository.get(task_id)
        executable_times: list[datetime] = []
        missed_events: list[JobExecutionEvent] = []
        now = datetime.now(UTC)
        for run_time in run_times:
            if job.misfire_grace_time is not None and now - run_time > timedelta(
                seconds=job.misfire_grace_time
            ):
                if task is not None and task.revision == revision:
                    repository.record_missed(task, run_time, "misfire grace time exceeded")
                missed_events.append(
                    JobExecutionEvent(
                        EVENT_JOB_MISSED,
                        job.id,
                        job._jobstore_alias,
                        run_time,
                    )
                )
            else:
                executable_times.append(run_time)

        occurrences = (
            repository.reserve_occurrences(task, executable_times)
            if task is not None and task.revision == revision
            else []
        )

        def callback(future: Any) -> None:
            try:
                exception = future.exception()
            except BaseException as exc:
                repository.release_queued_owners([occurrence.run_id for occurrence in occurrences])
                self._run_job_error(job.id, exc, exc.__traceback__)
                return
            if exception:
                # A failure outside execute_scheduled_task() means one or more
                # durable rows may still be queued. Drop this daemon's claim so
                # reconciliation can retry them without requiring a restart.
                repository.release_queued_owners([occurrence.run_id for occurrence in occurrences])
                self._run_job_error(job.id, exception, exception.__traceback__)
                return
            self._run_job_success(job.id, [*missed_events, *future.result()])

        try:
            future = self._pool.submit(
                _run_reserved_job,
                job,
                job._jobstore_alias,
                occurrences,
                self._logger.name,
            )
        except BaseException:
            repository.release_queued_owners([occurrence.run_id for occurrence in occurrences])
            raise
        future.add_done_callback(callback)

    def submit_recovered(self, occurrences: list[QueuedOccurrence]) -> None:
        """Submit adopted occurrences without creating new APScheduler jobs."""
        grouped: dict[str, list[QueuedOccurrence]] = defaultdict(list)
        for occurrence in occurrences:
            grouped[occurrence.task_id].append(occurrence)
        for task_occurrences in grouped.values():
            run_ids = [occurrence.run_id for occurrence in task_occurrences]
            future = self._pool.submit(
                _run_recovered,
                self.database_path,
                task_occurrences,
            )

            def log_failure(completed: Any, occurrence_ids: list[str] = run_ids) -> None:
                try:
                    exception = completed.exception()
                except BaseException as exc:
                    exception = exc
                if exception:
                    SchedulerRepository(self.database_path).release_queued_owners(occurrence_ids)
                    self._logger.error(
                        "Recovered scheduler occurrence failed",
                        exc_info=(type(exception), exception, exception.__traceback__),
                    )

            future.add_done_callback(log_failure)
