from __future__ import annotations

import argparse
import os
import platform
import signal
import socket
import threading
import time
from contextlib import AbstractContextManager, suppress
from datetime import UTC, timedelta
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
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import URL

from taskflows.common import logger
from taskflows.exceptions import RevisionConflict

from .executor import DurableThreadPoolExecutor
from .models import ScheduledTask, parse_datetime, utc_now
from .repository import SchedulerRepository, _process_identity
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
        try:
            self.file.seek(0)
            self.file.truncate()
            self.file.write(str(os.getpid()))
            self.file.flush()
        except Exception:
            # __exit__ is not called when __enter__ fails. Closing the handle
            # releases either native lock and prevents a permanent in-process
            # lock leak on a filesystem error.
            self.file.close()
            self.file = None
            raise
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if self.file is not None:
            try:
                if platform.system() == "Windows":
                    from importlib import import_module

                    windows_lock: Any = import_module("msvcrt")
                    self.file.seek(0)
                    windows_lock.locking(self.file.fileno(), windows_lock.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(self.file.fileno(), fcntl.LOCK_UN)
            finally:
                # Never leak the file descriptor if an OS unlock call fails.
                self.file.close()
                self.file = None
        return False


class SchedulerDaemon:
    """Reconciles Taskflows' registry into a persistent APScheduler."""

    def __init__(
        self,
        database_path: str | Path | None = None,
        *,
        max_workers: int = 20,
        reconcile_interval: float = 1.0,
        history_retention_days: int = 30,
        history_keep_latest: int = 100,
    ) -> None:
        self.repository = SchedulerRepository(database_path)
        self.database_path = self.repository.database_path.resolve()
        self.reconcile_interval = reconcile_interval
        self.history_retention_days = history_retention_days
        self.history_keep_latest = history_keep_latest
        self._last_retention_at = 0.0
        self.started_at = utc_now()
        self.process_identity = _process_identity(os.getpid())
        self.stop_event = threading.Event()
        self._submitted_date_jobs: dict[str, int] = {}
        self._submitted_lock = threading.RLock()
        self._known_date_revisions: dict[str, int] = {}
        self._known_revisions: dict[str, int] = {}
        self._log_sink_id: int | None = None
        database_url = URL.create("sqlite", database=str(self.database_path))
        self.executor = DurableThreadPoolExecutor(str(self.database_path), max_workers=max_workers)
        self.scheduler = BackgroundScheduler(
            jobstores={
                "default": SQLAlchemyJobStore(
                    url=database_url,
                    engine_options={"connect_args": {"timeout": 10}},
                )
            },
            executors={"default": self.executor},
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

    def _configure_daemon_log(self) -> None:
        if self._log_sink_id is not None:
            return
        log_dir = self.database_path.parent / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        if os.name != "nt":
            os.chmod(log_dir, 0o700)
        self._log_sink_id = logger.add(
            str(log_dir / "scheduler-daemon.log"),
            rotation="20 MB",
            retention=3,
            level="INFO",
            enqueue=True,
        )

    @staticmethod
    def _job_id(task_id: str) -> str:
        return f"{JOB_PREFIX}{task_id}"

    def _disable_if_current(self, task: ScheduledTask) -> None:
        """Consume a one-shot without disturbing a concurrent replacement."""
        try:
            self.repository.set_enabled(task.id, False, expected_revision=task.revision)
        except (KeyError, RevisionConflict):
            # A replacement or deletion won the race. Reconciliation will use
            # that newer definition; an expected scheduler event must not crash
            # and restart the daemon merely because a client edited the task.
            return

    def _on_scheduler_event(self, event: JobExecutionEvent) -> None:
        if not event.job_id.startswith(JOB_PREFIX):
            return
        with self._submitted_lock:
            known_revision = self._known_revisions.get(event.job_id)
            is_known_date = event.job_id in self._known_date_revisions
        task = self.repository.get(event.job_id.removeprefix(JOB_PREFIX))
        if task is None:
            if event.code in (EVENT_JOB_EXECUTED, EVENT_JOB_ERROR):
                with self._submitted_lock:
                    self._submitted_date_jobs.pop(event.job_id, None)
                    self._known_date_revisions.pop(event.job_id, None)
                    self._known_revisions.pop(event.job_id, None)
            return
        # Events can arrive after the registry definition was replaced but
        # before reconciliation updates APScheduler. Never attribute an old
        # job's event to (or disable) the new definition.
        if known_revision is not None and task.revision != known_revision:
            if event.code in (EVENT_JOB_EXECUTED, EVENT_JOB_ERROR):
                with self._submitted_lock:
                    if self._submitted_date_jobs.get(event.job_id) == known_revision:
                        self._submitted_date_jobs.pop(event.job_id, None)
                    if is_known_date:
                        self._known_date_revisions.pop(event.job_id, None)
                        self._known_revisions.pop(event.job_id, None)
            return
        if event.code == EVENT_JOB_SUBMITTED:
            if is_known_date and known_revision is not None:
                with self._submitted_lock:
                    self._submitted_date_jobs[event.job_id] = known_revision
            return
        if event.code in (EVENT_JOB_EXECUTED, EVENT_JOB_ERROR):
            with self._submitted_lock:
                if self._submitted_date_jobs.get(event.job_id) == known_revision:
                    self._submitted_date_jobs.pop(event.job_id, None)
            # A DateTrigger is consumed when APScheduler dispatches it, even
            # if the callable fails before the stable runner can claim the
            # task. Disable the definition here as a final safety net so a
            # one-shot cannot remain enabled with no persisted job to run it.
            if task.schedule.kind == "date" and task.enabled:
                self._disable_if_current(task)
            if task.schedule.kind == "date":
                with self._submitted_lock:
                    self._known_date_revisions.pop(event.job_id, None)
                    self._known_revisions.pop(event.job_id, None)
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
            self._disable_if_current(task)

    def start(self) -> None:
        if self._started:
            return
        self._configure_daemon_log()
        self.repository.mark_interrupted_runs()
        # Pausing is important: persisted jobs must not fire before stale or
        # deleted Taskflows definitions have been reconciled.
        self.scheduler.start(paused=True)
        self._started = True
        try:
            self.reconcile()
            self.scheduler.resume()
        except Exception:
            # Do not leave APScheduler's worker/background threads alive when
            # initial reconciliation fails (for example, on corrupt state).
            self.scheduler.shutdown(wait=False)
            self._started = False
            if self._log_sink_id is not None:
                logger.remove(self._log_sink_id)
                self._log_sink_id = None
            raise

    def _add_or_update(self, task: ScheduledTask, existing: Any = None) -> Any:
        job_id = self._job_id(task.id)
        with self._submitted_lock:
            if self._submitted_date_jobs.get(job_id) == task.revision:
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
            with self._submitted_lock:
                self._known_revisions[job_id] = task.revision
                if task.schedule.kind == "date":
                    self._known_date_revisions[job_id] = task.revision
                else:
                    self._known_date_revisions.pop(job_id, None)
            return existing

        if task.schedule.kind == "date":
            run_at = parse_datetime(str(task.schedule.value))
            grace = task.misfire_grace_time
            if run_at < utc_now() and grace is not None:
                late_by = (utc_now() - run_at.astimezone(UTC)).total_seconds()
                if late_by > grace:
                    self.repository.record_missed(task, run_at, "misfire grace time exceeded")
                    self._disable_if_current(task)
                    if existing:
                        self.scheduler.remove_job(job_id)
                    return None

        # Record the revision before registering the job. A date job can be
        # submitted immediately during a runtime reconcile, before add_job()
        # returns; the event listener must already be able to identify it.
        with self._submitted_lock:
            self._known_revisions[job_id] = task.revision
            if task.schedule.kind == "date":
                self._known_date_revisions[job_id] = task.revision
            else:
                self._known_date_revisions.pop(job_id, None)
        try:
            return self.scheduler.add_job(
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
        except Exception:
            # Do not leave a failed registration looking like an in-flight
            # date job. Preserve newer state if another reconcile won a race.
            with self._submitted_lock:
                if self._known_revisions.get(job_id) == task.revision:
                    self._known_revisions.pop(job_id, None)
                if self._known_date_revisions.get(job_id) == task.revision:
                    self._known_date_revisions.pop(job_id, None)
            raise

    def reconcile(self) -> None:
        # A daemon killed with SIGKILL can leave a child command running. The
        # replacement daemon deliberately preserves that reservation while the
        # child exists; once it exits, release the stale slot without requiring
        # yet another daemon restart.
        self.repository.mark_interrupted_runs()
        self.executor.submit_recovered(self.repository.adopt_orphaned_occurrences())
        tasks = self.repository.list()
        desired_ids = {self._job_id(task.id) for task in tasks if task.enabled}
        jobs = {job.id: job for job in self.scheduler.get_jobs() if job.id.startswith(JOB_PREFIX)}
        for job in list(jobs.values()):
            if job.id.startswith(JOB_PREFIX) and job.id not in desired_ids:
                self.scheduler.remove_job(job.id)
                jobs.pop(job.id, None)
                with self._submitted_lock:
                    self._known_revisions.pop(job.id, None)
                    self._known_date_revisions.pop(job.id, None)
                    self._submitted_date_jobs.pop(job.id, None)
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
        now = time.monotonic()
        if self.history_retention_days > 0 and now - self._last_retention_at >= 24 * 60 * 60:
            result = self.repository.prune_history(
                before=utc_now() - timedelta(days=self.history_retention_days),
                keep_latest=self.history_keep_latest,
            )
            self._last_retention_at = now
            for error in result.log_errors:
                logger.warning(error)

    def heartbeat(self) -> None:
        self.repository.heartbeat(
            pid=os.getpid(),
            hostname=socket.gethostname(),
            started_at=self.started_at,
            process_identity=self.process_identity,
        )

    def request_stop(self, signum: int | None = None, frame: FrameType | None = None) -> None:
        self.stop_event.set()

    def run_forever(self) -> None:
        lock_path = self.database_path.with_suffix(".lock")
        with _SingletonLock(lock_path):
            self.start()
            try:
                self.heartbeat()
                while not self.stop_event.wait(self.reconcile_interval):
                    self.reconcile()
                    self.heartbeat()
            finally:
                self.shutdown()

    def shutdown(self) -> None:
        if not self._started:
            return
        try:
            # Stop dispatch first. Pending futures are cancelled and their
            # durable queue ownership is released before live process trees are
            # terminated, so shutdown cannot launch new commands behind us.
            with suppress(Exception):
                self.scheduler.pause()
            self.executor.begin_shutdown()
            terminate_active_runs()
            self.scheduler.shutdown(wait=True)
        finally:
            # Cleanup must happen even if APScheduler reports an executor or
            # job-store error while stopping. Otherwise status would retain a
            # stale heartbeat and a later daemon could appear unhealthy.
            try:
                self.repository.mark_interrupted_runs()
            finally:
                self.repository.clear_daemon_state(
                    pid=os.getpid(), process_identity=self.process_identity
                )
                self._started = False
                if self._log_sink_id is not None:
                    logger.remove(self._log_sink_id)
                    self._log_sink_id = None


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the Taskflows portable scheduler daemon")
    parser.add_argument("--database", help="Path to the scheduler SQLite registry")
    arguments = parser.parse_args(argv)
    daemon = SchedulerDaemon(arguments.database)
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
