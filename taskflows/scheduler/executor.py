"""APScheduler executor with a durable registry handoff.

APScheduler normally submits a callable and then advances its persistent
trigger. A daemon crash between those operations can lose an occurrence. This
executor writes each due occurrence to Taskflows' registry before submitting
the worker, and replacement daemons can adopt queued rows left behind.
"""

from __future__ import annotations

import logging
import sys
import threading
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

from .models import MAX_CATCH_UP_OCCURRENCES
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
            allow_disabled=occurrence.allow_disabled,
        )


class DurableThreadPoolExecutor(ThreadPoolExecutor):
    """Thread pool that persists scheduled occurrences before dispatch."""

    def __init__(
        self,
        database_path: str,
        max_workers: int = 10,
        *,
        max_pending_jobs: int | None = None,
    ) -> None:
        if max_pending_jobs is not None and max_pending_jobs < 1:
            raise ValueError("max_pending_jobs must be at least one")
        super().__init__(max_workers=max_workers)
        self.database_path = database_path
        self.max_pending_jobs = (
            max_pending_jobs if max_pending_jobs is not None else max_workers * 2
        )
        self._pending: set[Any] = set()
        self._reserved_slots = 0
        self._pending_lock = threading.RLock()
        self._stopping = False

    @property
    def pending_count(self) -> int:
        with self._pending_lock:
            return self._reserved_slots

    def _reserve_capacity(self) -> bool:
        with self._pending_lock:
            if self._stopping or self._reserved_slots >= self.max_pending_jobs:
                return False
            self._reserved_slots += 1
            return True

    def _release_capacity(self) -> None:
        with self._pending_lock:
            if self._reserved_slots:
                self._reserved_slots -= 1

    def _track(self, future: Any) -> None:
        with self._pending_lock:
            self._pending.add(future)

        def forget(completed: Any) -> None:
            with self._pending_lock:
                self._pending.discard(completed)
                self._reserved_slots -= 1

        future.add_done_callback(forget)

    def begin_shutdown(self) -> None:
        """Reject new work and cancel futures that have not launched yet."""

        with self._pending_lock:
            self._stopping = True
        # APScheduler will call shutdown again; concurrent.futures explicitly
        # permits repeated shutdown calls. Cancellation callbacks release the
        # durable rows so the next daemon can recover them.
        self._pool.shutdown(wait=False, cancel_futures=True)

    def _do_submit_job(self, job: Any, run_times: list[datetime]) -> None:
        repository = SchedulerRepository(self.database_path)
        task_id = str(job.kwargs["task_id"])
        revision = int(job.kwargs["revision"])
        task = repository.get(task_id)
        if len(run_times) > MAX_CATCH_UP_OCCURRENCES:
            dropped = run_times[:-MAX_CATCH_UP_OCCURRENCES]
            run_times = run_times[-MAX_CATCH_UP_OCCURRENCES:]
            if task is not None and task.revision == revision:
                # Persist one summary instead of turning a long outage on a
                # one-second interval into millions of SQLite writes and run
                # history rows. The retained execution batch remains bounded.
                repository.record_missed(
                    task,
                    dropped[-1],
                    f"catch-up backlog dropped {len(dropped)} occurrences; "
                    f"only the newest {MAX_CATCH_UP_OCCURRENCES} were retained",
                )
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

        if executable_times and not self._reserve_capacity():
            if task is not None and task.revision == revision:
                for run_time in executable_times:
                    repository.record_missed(task, run_time, "scheduler worker queue is full")
            self._run_job_success(job.id, missed_events)
            return

        slot_reserved = bool(executable_times)

        occurrences = (
            repository.reserve_occurrences(task, executable_times)
            if task is not None and task.revision == revision
            else []
        )
        if not occurrences:
            if slot_reserved:
                self._release_capacity()
            self._run_job_success(job.id, missed_events)
            return
        reserved_times = {occurrence.scheduled_for for occurrence in occurrences}
        if task is not None and task.revision == revision:
            for run_time in executable_times:
                if run_time not in reserved_times:
                    repository.record_missed(task, run_time, "scheduler occurrence queue is full")
                    missed_events.append(
                        JobExecutionEvent(
                            EVENT_JOB_MISSED,
                            job.id,
                            job._jobstore_alias,
                            run_time,
                        )
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
            self._release_capacity()
            raise
        self._track(future)
        future.add_done_callback(callback)

    def submit_recovered(self, occurrences: list[QueuedOccurrence]) -> None:
        """Submit adopted occurrences without creating new APScheduler jobs."""
        grouped: dict[str, list[QueuedOccurrence]] = defaultdict(list)
        for occurrence in occurrences:
            grouped[occurrence.task_id].append(occurrence)
        for task_occurrences in grouped.values():
            run_ids = [occurrence.run_id for occurrence in task_occurrences]
            if not self._reserve_capacity():
                SchedulerRepository(self.database_path).release_queued_owners(run_ids)
                continue
            try:
                future = self._pool.submit(
                    _run_recovered,
                    self.database_path,
                    task_occurrences,
                )
            except RuntimeError:
                self._release_capacity()
                SchedulerRepository(self.database_path).release_queued_owners(run_ids)
                continue
            self._track(future)

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
