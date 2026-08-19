from __future__ import annotations

import os
import signal
import subprocess
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from taskflows.common import logger

from .models import parse_datetime, utc_now
from .repository import SchedulerRepository

_active_processes: dict[str, subprocess.Popen[Any]] = {}
_active_lock = threading.RLock()


def _terminate_process_tree(process: subprocess.Popen[Any]) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        # CREATE_NEW_PROCESS_GROUP does not include grandchildren when killed
        # directly. taskkill /T is the native process-tree operation.
        result = subprocess.run(
            ["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
            capture_output=True,
            check=False,
            timeout=10,
        )
        if result.returncode != 0 and process.poll() is None:
            process.kill()
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=5)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        if process.poll() is None:
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
        logger.warning(f"Scheduled task {task_id} no longer exists")
        return None
    if not task.enabled and not allow_disabled:
        logger.info(f"Scheduled task {task.name} is disabled; skipping")
        return None
    if task.revision != revision and not allow_disabled:
        logger.info(f"Ignoring stale revision of scheduled task {task.name}")
        return None

    planned_at = parse_datetime(scheduled_for) if scheduled_for else utc_now()
    run_id = repository.begin_run(task, planned_at)
    if run_id is None:
        logger.warning(f"Scheduled task {task.name} reached max_instances={task.max_instances}")
        return None

    # Claim one-time schedules before starting so the reconcile loop cannot
    # recreate a DateTrigger after APScheduler removes it.
    # A manual `schedule run` must not consume a future one-time schedule.
    if task.schedule.kind == "date" and task.enabled and not allow_disabled:
        repository.set_enabled(task.id, False)

    log_dir = repository.database_path.parent / "runs" / task.id
    log_dir.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        os.chmod(log_dir, 0o700)
    stdout_path = log_dir / f"{run_id}.stdout.log"
    stderr_path = log_dir / f"{run_id}.stderr.log"
    process: subprocess.Popen[Any] | None = None

    try:
        environment = os.environ.copy()
        environment.update(task.environment)
        popen_kwargs: dict[str, Any] = {
            "cwd": task.cwd,
            "env": environment,
        }
        if os.name == "nt":
            popen_kwargs["creationflags"] = getattr(
                subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200
            )
        else:
            popen_kwargs["start_new_session"] = True

        with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
            process = subprocess.Popen(
                list(task.command), stdout=stdout, stderr=stderr, **popen_kwargs
            )
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
