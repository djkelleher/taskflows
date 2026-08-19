from __future__ import annotations

import os
import platform
import signal
import socket
import threading
from contextlib import AbstractContextManager
from datetime import UTC
from pathlib import Path
from types import FrameType
from typing import Any, TextIO

from apscheduler.events import (
    EVENT_JOB_ERROR,
    EVENT_JOB_EXECUTED,
    EVENT_JOB_MAX_INSTANCES,
    EVENT_JOB_MISSED,
    EVENT_JOB_SUBMITTED,
    JobExecutionEvent,
)
from apscheduler.executors.pool import ThreadPoolExecutor
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.background import BackgroundScheduler

from taskflows.common import logger

from .models import ScheduledTask, parse_datetime, utc_now
from .repository import SchedulerRepository
from .runner import execute_scheduled_task, terminate_active_runs

JOB_PREFIX = "taskflows:"


class DaemonAlreadyRunning(RuntimeError):
    pass


class _SingletonLock(AbstractContextManager):
    """Small cross-platform advisory lock preventing two local schedulers."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.file: TextIO | None = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.file = self.path.open("a+")
        try:
            if platform.system() == "Windows":
                from importlib import import_module

                windows_lock: Any = import_module("msvcrt")
                file = self.file
                file.seek(0)
                if file.read(1) == "":
                    file.write(" ")
                    file.flush()
                file.seek(0)
                windows_lock.locking(file.fileno(), windows_lock.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.file.close()
            self.file = None
            raise DaemonAlreadyRunning("another Taskflows scheduler daemon is running") from exc
        self.file.seek(0)
        self.file.truncate()
        self.file.write(str(os.getpid()))
        self.file.flush()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if self.file is not None:
            if platform.system() == "Windows":
                from importlib import import_module

                windows_lock: Any = import_module("msvcrt")
                self.file.seek(0)
                windows_lock.locking(self.file.fileno(), windows_lock.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.file.fileno(), fcntl.LOCK_UN)
            self.file.close()
        return False


class SchedulerDaemon:
    """Reconciles Taskflows' registry into a persistent APScheduler."""

    def __init__(
        self,
        database_path: str | Path | None = None,
        *,
        max_workers: int = 20,
        reconcile_interval: float = 1.0,
    ) -> None:
        self.repository = SchedulerRepository(database_path)
        self.database_path = self.repository.database_path.resolve()
        self.reconcile_interval = reconcile_interval
        self.started_at = utc_now()
        self.stop_event = threading.Event()
        self._submitted_date_jobs: set[str] = set()
        self._submitted_lock = threading.RLock()
        self._known_date_revisions: dict[str, int] = {}
        database_url = f"sqlite:///{self.database_path.as_posix()}"
        self.scheduler = BackgroundScheduler(
            jobstores={
                "default": SQLAlchemyJobStore(
                    url=database_url,
                    engine_options={"connect_args": {"timeout": 10}},
                )
            },
            executors={"default": ThreadPoolExecutor(max_workers=max_workers)},
            timezone=UTC,
        )
        self.scheduler.add_listener(
            self._on_scheduler_event,
            EVENT_JOB_MISSED
            | EVENT_JOB_MAX_INSTANCES
            | EVENT_JOB_SUBMITTED
            | EVENT_JOB_EXECUTED
            | EVENT_JOB_ERROR,
        )
        self._started = False

    @staticmethod
    def _job_id(task_id: str) -> str:
        return f"{JOB_PREFIX}{task_id}"

    def _on_scheduler_event(self, event: JobExecutionEvent) -> None:
        if not event.job_id.startswith(JOB_PREFIX):
            return
        task = self.repository.get(event.job_id.removeprefix(JOB_PREFIX))
        if task is None:
            return
        if event.code == EVENT_JOB_SUBMITTED:
            if task.schedule.kind == "date":
                with self._submitted_lock:
                    self._submitted_date_jobs.add(event.job_id)
            return
        if event.code in (EVENT_JOB_EXECUTED, EVENT_JOB_ERROR):
            with self._submitted_lock:
                self._submitted_date_jobs.discard(event.job_id)
            return
        scheduled_times = getattr(event, "scheduled_run_times", None) or [
            getattr(event, "scheduled_run_time", utc_now())
        ]
        reason = (
            "maximum concurrent instances reached"
            if event.code == EVENT_JOB_MAX_INSTANCES
            else "misfire grace time exceeded"
        )
        for scheduled_time in scheduled_times:
            self.repository.record_missed(task, scheduled_time, reason)
        if task.schedule.kind == "date":
            self.repository.set_enabled(task.id, False)

    def start(self) -> None:
        if self._started:
            return
        self.repository.mark_interrupted_runs()
        # Pausing is important: persisted jobs must not fire before stale or
        # deleted Taskflows definitions have been reconciled.
        self.scheduler.start(paused=True)
        self.reconcile()
        self.scheduler.resume()
        self._started = True

    def _add_or_update(self, task: ScheduledTask, existing: Any = None) -> Any:
        job_id = self._job_id(task.id)
        with self._submitted_lock:
            if job_id in self._submitted_date_jobs:
                return existing
            # Date jobs disappear from APScheduler's job store immediately
            # before their executor thread starts. Remember the revision so a
            # fast reconcile cannot recreate the same one-shot in that gap.
            if (
                task.schedule.kind == "date"
                and self._known_date_revisions.get(job_id) == task.revision
            ):
                return existing
        existing_revision = existing.kwargs.get("revision") if existing else None
        if existing is not None and existing_revision == task.revision:
            if task.schedule.kind == "date":
                with self._submitted_lock:
                    self._known_date_revisions[job_id] = task.revision
            return existing

        if task.schedule.kind == "date":
            run_at = parse_datetime(str(task.schedule.value))
            grace = task.misfire_grace_time
            if run_at < utc_now() and grace is not None:
                late_by = (utc_now() - run_at.astimezone(UTC)).total_seconds()
                if late_by > grace:
                    self.repository.record_missed(task, run_at, "misfire grace time exceeded")
                    self.repository.set_enabled(task.id, False)
                    if existing:
                        self.scheduler.remove_job(job_id)
                    return None

        job = self.scheduler.add_job(
            execute_scheduled_task,
            trigger=task.schedule.to_trigger(),
            id=job_id,
            name=task.name,
            kwargs={
                "database_path": str(self.database_path),
                "task_id": task.id,
                "revision": task.revision,
            },
            replace_existing=True,
            coalesce=task.coalesce,
            misfire_grace_time=task.misfire_grace_time,
            max_instances=task.max_instances,
        )
        if task.schedule.kind == "date":
            with self._submitted_lock:
                self._known_date_revisions[job_id] = task.revision
        return job

    def reconcile(self) -> None:
        tasks = self.repository.list()
        desired_ids = {self._job_id(task.id) for task in tasks if task.enabled}
        jobs = {job.id: job for job in self.scheduler.get_jobs() if job.id.startswith(JOB_PREFIX)}
        for job in list(jobs.values()):
            if job.id.startswith(JOB_PREFIX) and job.id not in desired_ids:
                self.scheduler.remove_job(job.id)
                jobs.pop(job.id, None)
        for task in tasks:
            if task.enabled:
                job_id = self._job_id(task.id)
                jobs[job_id] = self._add_or_update(task, jobs.get(job_id))
        self.repository.set_next_runs(
            {
                task.id: getattr(jobs.get(self._job_id(task.id)), "next_run_time", None)
                for task in tasks
            }
        )

    def heartbeat(self) -> None:
        self.repository.heartbeat(
            pid=os.getpid(), hostname=socket.gethostname(), started_at=self.started_at
        )

    def request_stop(self, signum: int | None = None, frame: FrameType | None = None) -> None:
        self.stop_event.set()

    def run_forever(self) -> None:
        lock_path = self.database_path.with_suffix(".lock")
        with _SingletonLock(lock_path):
            self.start()
            self.heartbeat()
            try:
                while not self.stop_event.wait(self.reconcile_interval):
                    self.reconcile()
                    self.heartbeat()
            finally:
                self.shutdown()

    def shutdown(self) -> None:
        if not self._started:
            return
        terminate_active_runs()
        self.scheduler.shutdown(wait=True)
        self.repository.mark_interrupted_runs()
        self.repository.clear_daemon_state(pid=os.getpid())
        self._started = False


def main() -> None:
    daemon = SchedulerDaemon()
    if threading.current_thread() is threading.main_thread():
        for signum in (signal.SIGINT, signal.SIGTERM):
            signal.signal(signum, daemon.request_stop)
    try:
        daemon.run_forever()
    except DaemonAlreadyRunning as exc:
        logger.error(str(exc))
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
