from __future__ import annotations

import os
import signal
import subprocess
import threading
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from datetime import datetime
from pathlib import Path
from typing import Any, BinaryIO

from taskflows.common import logger
from taskflows.exceptions import RevisionConflict

from .models import merge_environment, parse_datetime, utc_now
from .repository import SchedulerRepository

_active_processes: dict[str, subprocess.Popen[Any]] = {}
_active_lock = threading.RLock()


@contextmanager
def _open_run_log(path: Path) -> Iterator[BinaryIO]:
    """Create a run log with owner-only permissions on POSIX systems."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_BINARY", 0)
    if os.name != "nt":
        # Run IDs are generated internally, but refusing symlinks prevents a
        # compromised writable data directory from redirecting captured output.
        flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o600)
    stream: BinaryIO | None = None
    try:
        if os.name != "nt":
            os.fchmod(descriptor, 0o600)
        stream = os.fdopen(descriptor, "wb")
        descriptor = -1
        yield stream
    finally:
        if stream is not None:
            stream.close()
        elif descriptor >= 0:
            os.close(descriptor)


def _terminate_process_tree(process: subprocess.Popen[Any]) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        # CREATE_NEW_PROCESS_GROUP does not include grandchildren when killed
        # directly. taskkill /T is the native process-tree operation.
        try:
            result = subprocess.run(
                ["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True,
                check=False,
                timeout=10,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            result = None
        if (result is None or result.returncode != 0) and process.poll() is None:
            process.kill()
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        with suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
    else:
        # The leader can exit promptly while a descendant ignores SIGTERM.
        # In that case waiting on the leader alone would leave the rest of
        # the process group orphaned.  A group whose leader has exited is
        # still safe to address by its original PGID; if it no longer exists,
        # killpg raises ProcessLookupError and there is nothing left to do.
        with suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)


def terminate_active_runs() -> None:
    """Stop every process launched by this scheduler daemon."""
    with _active_lock:
        processes = list(_active_processes.values())
    for process in processes:
        try:
            _terminate_process_tree(process)
        except Exception as exc:  # best effort during daemon shutdown
            logger.warning(f"Could not terminate scheduled process {process.pid}: {exc}")


def execute_scheduled_task(
    database_path: str,
    task_id: str,
    revision: int,
    *,
    run_id: str | None = None,
    scheduled_for: str | None = None,
    allow_disabled: bool = False,
) -> int | None:
    """Stable APScheduler entry point: load a task ID and execute its command.

    Only primitive identifiers are serialized into APScheduler's job store.
    Commands, working directories and environment values remain in the
    Taskflows-owned registry.
    """
    repository = SchedulerRepository(database_path)
    task = repository.get(task_id)
    if task is None:
        if run_id is not None:
            repository.skip_queued_occurrence(run_id, "scheduled definition no longer exists")
        logger.warning(f"Scheduled task {task_id} no longer exists")
        return None
    if not task.enabled and not allow_disabled:
        if run_id is not None:
            repository.skip_queued_occurrence(run_id, "scheduled definition is disabled")
        logger.info(f"Scheduled task {task.name} is disabled; skipping")
        return None
    if task.revision != revision and not allow_disabled:
        if run_id is not None:
            repository.skip_queued_occurrence(
                run_id, "scheduled definition changed before dispatch"
            )
        logger.info(f"Ignoring stale revision of scheduled task {task.name}")
        return None

    planned_at = parse_datetime(scheduled_for) if scheduled_for else utc_now()
    if run_id is not None:
        claimed = repository.claim_occurrence(run_id, task)
    else:
        run_id = repository.begin_run(task, planned_at, allow_disabled=allow_disabled)
        claimed = run_id is not None
    if not claimed or run_id is None:
        # APScheduler has consumed a DateTrigger once it dispatches, even when
        # a concurrent manual run occupies the registry-level overlap slot.
        # Consume the definition too so a restart cannot retry it unexpectedly.
        if task.schedule.kind == "date" and not allow_disabled:
            with suppress(KeyError, RevisionConflict):
                repository.set_enabled(task.id, False, expected_revision=task.revision)
        logger.warning(f"Scheduled task {task.name} was not claimed for execution")
        return None

    log_dir = repository.database_path.parent / "runs" / task.id
    stdout_path = log_dir / f"{run_id}.stdout.log"
    stderr_path = log_dir / f"{run_id}.stderr.log"
    process: subprocess.Popen[Any] | None = None

    try:
        # Claim one-time schedules before starting so the reconcile loop cannot
        # recreate a DateTrigger after APScheduler removes it. A manual
        # `schedule run` must not consume a future one-time schedule.
        if task.schedule.kind == "date" and task.enabled and not allow_disabled:
            with suppress(KeyError, RevisionConflict):
                repository.set_enabled(task.id, False, expected_revision=task.revision)

        # Setup belongs inside the guarded section: permission or filesystem
        # failures must finish the durable run record rather than strand it in
        # the running state until the next daemon restart.
        log_dir.mkdir(parents=True, exist_ok=True)
        if os.name != "nt":
            os.chmod(log_dir, 0o700)

        environment = merge_environment(os.environ, task.environment)
        # Schema versions before Taskflows persisted a creation-time cwd may
        # still contain NULL. Use one documented fallback rather than inheriting
        # the platform supervisor's process directory (/, $HOME, or another
        # backend-specific value).
        working_directory = task.cwd or str(Path.home())
        popen_kwargs: dict[str, Any] = {
            "cwd": working_directory,
            "env": environment,
        }
        if os.name == "nt":
            popen_kwargs["creationflags"] = getattr(
                subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200
            )
        else:
            popen_kwargs["start_new_session"] = True

        with _open_run_log(stdout_path) as stdout, _open_run_log(stderr_path) as stderr:
            process = subprocess.Popen(
                list(task.command), stdout=stdout, stderr=stderr, **popen_kwargs
            )
            repository.set_runner_pid(run_id, process.pid)
            with _active_lock:
                _active_processes[run_id] = process
            try:
                exit_code = process.wait(timeout=task.timeout)
            except subprocess.TimeoutExpired:
                _terminate_process_tree(process)
                try:
                    exit_code = process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    # Last-resort direct termination if a platform tree-kill
                    # command did not reap the root process.
                    process.kill()
                    exit_code = process.wait(timeout=10)
                repository.finish_run(
                    run_id,
                    status="timed_out",
                    exit_code=exit_code,
                    stdout_path=str(stdout_path),
                    stderr_path=str(stderr_path),
                    error=f"execution exceeded {task.timeout:g} seconds",
                )
                return exit_code

        status = "succeeded" if exit_code == 0 else "failed"
        repository.finish_run(
            run_id,
            status=status,
            exit_code=exit_code,
            stdout_path=str(stdout_path),
            stderr_path=str(stderr_path),
            error=None if exit_code == 0 else f"command exited with status {exit_code}",
        )
        return exit_code
    except Exception as exc:
        if process is not None and process.poll() is None:
            try:
                _terminate_process_tree(process)
            except Exception as termination_error:
                logger.warning(
                    f"Could not terminate failed scheduled process {process.pid}: "
                    f"{termination_error}"
                )
        repository.finish_run(
            run_id,
            status="failed",
            exit_code=process.poll() if process else None,
            stdout_path=str(stdout_path),
            stderr_path=str(stderr_path),
            error=str(exc),
        )
        logger.exception(f"Scheduled task {task.name} failed to launch: {exc}")
        return 127 if isinstance(exc, FileNotFoundError) else 1
    finally:
        with _active_lock:
            _active_processes.pop(run_id, None)


def run_now(database_path: str | Path, identifier: str) -> int | None:
    repository = SchedulerRepository(database_path)
    task = repository.resolve(identifier)
    return execute_scheduled_task(
        str(repository.database_path),
        task.id,
        task.revision,
        scheduled_for=datetime.now().astimezone().isoformat(),
        allow_disabled=True,
    )
