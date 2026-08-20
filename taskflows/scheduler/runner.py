from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from importlib import import_module
from pathlib import Path
from typing import Any, BinaryIO

from taskflows.common import logger
from taskflows.exceptions import RevisionConflict

from .models import MAX_RUN_LOG_BYTES, RunHandle, merge_environment, parse_datetime, utc_now
from .repository import SchedulerRepository, _pid_matches_identity

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


def _terminate_process_tree(
    process: subprocess.Popen[Any], *, include_exited_group: bool = False
) -> None:
    root_exited = process.poll() is not None
    if root_exited and not include_exited_group:
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
    if not root_exited:
        with suppress(subprocess.TimeoutExpired):
            process.wait(timeout=5)
    # The leader can exit promptly while a descendant ignores SIGTERM.  In
    # that case waiting on the leader alone would leave the process group and
    # inherited output pipes alive.  A group whose leader has exited is still
    # addressable by its original PGID.
    with suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGKILL)


def _assign_windows_job(process: subprocess.Popen[Any]) -> Any | None:
    """Put a suspended child in a kill-on-close Job Object, then resume it."""

    job: Any | None = None
    win32api: Any | None = None
    try:
        win32api = import_module("win32api")
        win32job: Any = import_module("win32job")

        job = win32job.CreateJobObject(None, "")
        information = win32job.QueryInformationJobObject(
            job, win32job.JobObjectExtendedLimitInformation
        )
        information["BasicLimitInformation"]["LimitFlags"] |= (
            win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        )
        win32job.SetInformationJobObject(
            job,
            win32job.JobObjectExtendedLimitInformation,
            information,
        )
        native_process: Any = process
        win32job.AssignProcessToJobObject(job, native_process._handle)
    except Exception as exc:
        if job is not None and win32api is not None:
            with suppress(Exception):
                win32api.CloseHandle(job)
            job = None
        logger.warning(f"Could not assign scheduled process {process.pid} to a Job Object: {exc}")
    try:
        native_process = process
        win32process = import_module("win32process")
        win32process.ResumeThread(native_process._thread)
    except Exception as exc:
        if job is not None and win32api is not None:
            with suppress(Exception):
                win32api.CloseHandle(job)
        with suppress(Exception):
            process.kill()
        raise RuntimeError(f"could not resume scheduled process {process.pid}: {exc}") from exc
    return job


def _finish_process_tree(process: subprocess.Popen[Any], windows_job: Any | None) -> None:
    """Remove descendants after the command leader exits and release job state."""

    if windows_job is not None:
        win32api: Any = import_module("win32api")

        # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE terminates descendants even when
        # the root process has already exited and TaskKill can no longer walk it.
        win32api.CloseHandle(windows_job)
        return
    _terminate_process_tree(process, include_exited_group=True)


def _join_capture_threads(
    capture_threads: list[threading.Thread], errors: list[str], timeout: float = 10.0
) -> None:
    """Wait a bounded total time for both output drains."""

    deadline = time.monotonic() + timeout
    for capture_thread in capture_threads:
        capture_thread.join(max(deadline - time.monotonic(), 0))
    stuck = [capture_thread.name for capture_thread in capture_threads if capture_thread.is_alive()]
    if stuck:
        errors.append(f"output capture did not stop: {', '.join(stuck)}")


def terminate_active_runs() -> None:
    """Stop every process launched by this scheduler daemon."""
    with _active_lock:
        processes = list(_active_processes.values())
    for process in processes:
        try:
            _terminate_process_tree(process)
        except Exception as exc:  # best effort during daemon shutdown
            logger.warning(f"Could not terminate scheduled process {process.pid}: {exc}")


def _copy_bounded(
    source: BinaryIO,
    destination: BinaryIO,
    limit: int,
    errors: list[str],
) -> None:
    """Drain a child pipe completely while retaining only a bounded prefix."""

    written = 0
    truncated = False
    writable = True
    try:
        while chunk := source.read(64 * 1024):
            remaining = max(limit - written, 0)
            if remaining and writable:
                try:
                    destination.write(chunk[:remaining])
                except OSError as exc:
                    errors.append(str(exc))
                    writable = False
                else:
                    written += min(len(chunk), remaining)
            if len(chunk) > remaining:
                truncated = True
    except OSError as exc:
        errors.append(str(exc))
    if writable:
        try:
            if truncated:
                destination.write(f"\n[taskflows: output truncated after {limit} bytes]\n".encode())
            destination.flush()
        except OSError as exc:
            errors.append(str(exc))


def _terminate_pid_tree(pid: int) -> None:
    """Best-effort cross-process counterpart to :func:`_terminate_process_tree`."""

    if os.name == "nt":
        subprocess.run(
            ["taskkill.exe", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            check=False,
            timeout=10,
        )
        return
    with suppress(ProcessLookupError):
        os.killpg(pid, signal.SIGTERM)
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            os.killpg(pid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.05)
    with suppress(ProcessLookupError):
        os.killpg(pid, signal.SIGKILL)


def cancel_run(database_path: str | Path, run_id: str) -> RunHandle:
    """Request cancellation and terminate the recorded process tree when live."""

    repository = SchedulerRepository(database_path)
    handle = repository.request_cancellation(run_id)
    if handle.status in {"starting", "running"}:
        deadline = time.monotonic() + 2
        pid, identity = repository.run_process(run_id)
        while pid is None and time.monotonic() < deadline:
            current = repository.get_run(run_id)
            if current.terminal:
                return current
            time.sleep(0.02)
            pid, identity = repository.run_process(run_id)
        if pid is not None and _pid_matches_identity(pid, identity):
            try:
                _terminate_pid_tree(pid)
            except (OSError, subprocess.SubprocessError) as exc:
                logger.warning(f"Could not terminate scheduled run {run_id}: {exc}")
    return repository.get_run(run_id)


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
    if task.revision != revision:
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
    windows_job: Any | None = None

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

        if repository.cancellation_requested(run_id):
            repository.finish_run(run_id, status="cancelled", error="cancelled by user")
            return None

        environment = merge_environment(os.environ, task.environment)
        # Schema versions before Taskflows persisted a creation-time cwd may
        # still contain NULL. Use one documented fallback rather than inheriting
        # the platform supervisor's process directory (/, $HOME, or another
        # backend-specific value).
        popen_kwargs: dict[str, Any] = {
            "cwd": str(task.working_directory),
            "env": environment,
        }
        if os.name == "nt":
            popen_kwargs["creationflags"] = getattr(
                subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200
            ) | getattr(subprocess, "CREATE_SUSPENDED", 0x00000004)
        else:
            popen_kwargs["start_new_session"] = True

        with _open_run_log(stdout_path) as stdout, _open_run_log(stderr_path) as stderr:
            process = subprocess.Popen(
                list(task.command), stdout=subprocess.PIPE, stderr=subprocess.PIPE, **popen_kwargs
            )
            if os.name == "nt":
                windows_job = _assign_windows_job(process)
            assert process.stdout is not None and process.stderr is not None
            capture_errors: list[str] = []
            capture_threads = [
                threading.Thread(
                    target=_copy_bounded,
                    args=(process.stdout, stdout, MAX_RUN_LOG_BYTES, capture_errors),
                    name=f"taskflows-stdout-{run_id}",
                    daemon=True,
                ),
                threading.Thread(
                    target=_copy_bounded,
                    args=(process.stderr, stderr, MAX_RUN_LOG_BYTES, capture_errors),
                    name=f"taskflows-stderr-{run_id}",
                    daemon=True,
                ),
            ]
            for capture_thread in capture_threads:
                capture_thread.start()
            registered = repository.set_runner_pid(run_id, process.pid)
            with _active_lock:
                _active_processes[run_id] = process
            if not registered and repository.cancellation_requested(run_id):
                _terminate_process_tree(process)
                exit_code = process.wait(timeout=10)
                _finish_process_tree(process, windows_job)
                windows_job = None
                _join_capture_threads(capture_threads, capture_errors)
                repository.finish_run(
                    run_id,
                    status="cancelled",
                    exit_code=exit_code,
                    stdout_path=str(stdout_path),
                    stderr_path=str(stderr_path),
                    error="cancelled by user"
                    + (
                        f"; output capture failed: {'; '.join(capture_errors)}"
                        if capture_errors
                        else ""
                    ),
                )
                return exit_code
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
                _finish_process_tree(process, windows_job)
                windows_job = None
                _join_capture_threads(capture_threads, capture_errors)
                repository.finish_run(
                    run_id,
                    status="timed_out",
                    exit_code=exit_code,
                    stdout_path=str(stdout_path),
                    stderr_path=str(stderr_path),
                    error=f"execution exceeded {task.timeout:g} seconds"
                    + (
                        f"; output capture failed: {'; '.join(capture_errors)}"
                        if capture_errors
                        else ""
                    ),
                )
                return exit_code

            # A scheduled command owns its complete process tree. If its root
            # exits after spawning a background descendant, terminate that
            # descendant before waiting for inherited output pipes to close.
            _finish_process_tree(process, windows_job)
            windows_job = None
            _join_capture_threads(capture_threads, capture_errors)

        status = "succeeded" if exit_code == 0 else "failed"
        capture_error = (
            f"output capture failed: {'; '.join(capture_errors)}" if capture_errors else None
        )
        repository.finish_run(
            run_id,
            status=status,
            exit_code=exit_code,
            stdout_path=str(stdout_path),
            stderr_path=str(stderr_path),
            error=capture_error
            if exit_code == 0
            else f"command exited with status {exit_code}"
            + (f"; {capture_error}" if capture_error else ""),
        )
        return exit_code
    except Exception as exc:
        failure_exit_code = (
            process.poll()
            if process is not None and process.poll() is not None
            else 127
            if isinstance(exc, FileNotFoundError)
            else 1
        )
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
            exit_code=failure_exit_code,
            stdout_path=str(stdout_path),
            stderr_path=str(stderr_path),
            error=str(exc),
        )
        logger.exception(f"Scheduled task {task.name} failed to launch: {exc}")
        return failure_exit_code
    finally:
        if windows_job is not None and process is not None:
            with suppress(Exception):
                _finish_process_tree(process, windows_job)
        with _active_lock:
            _active_processes.pop(run_id, None)


def run_now(database_path: str | Path, identifier: str) -> int | None:
    """Compatibility helper that submits a typed run and waits for completion."""

    handle = submit_now(database_path, identifier)
    repository = SchedulerRepository(database_path)
    while not handle.terminal:
        time.sleep(0.05)
        handle = repository.get_run(handle.id)
    return handle.exit_code


def enqueue_now(database_path: str | Path, identifier: str) -> RunHandle:
    """Durably queue a manual run for adoption by the scheduler daemon."""

    repository = SchedulerRepository(database_path)
    task = repository.resolve(identifier)
    return repository.reserve_manual_run(task)


def submit_now(database_path: str | Path, identifier: str) -> RunHandle:
    """Accept a manual run and execute it in this long-lived process.

    CLI/API callers that return before completion should use :func:`enqueue_now`
    so command ownership belongs to the scheduler daemon rather than a daemon
    thread that disappears with the submitting process.
    """

    repository = SchedulerRepository(database_path)
    handle = enqueue_now(repository.database_path, identifier)
    if handle.task_id is None or handle.task_revision is None:
        raise RuntimeError(f"manual run {handle.id} has no scheduled definition")
    worker = threading.Thread(
        target=execute_scheduled_task,
        kwargs={
            "database_path": str(repository.database_path),
            "task_id": handle.task_id,
            "revision": handle.task_revision,
            "run_id": handle.id,
            "scheduled_for": handle.scheduled_for,
            "allow_disabled": True,
        },
        name=f"taskflows-manual-{handle.id}",
        daemon=True,
    )
    worker.start()
    return handle
