import asyncio
import contextvars
import threading
from datetime import datetime, timedelta, timezone
from logging import Logger
from typing import Any, Callable, List, Literal, Optional, Sequence
from urllib.parse import quote

import anyio
from anyio.from_thread import BlockingPortal
from pydantic import BaseModel

from .alerts import ContentType, Emoji, FontSize, MsgDst, Text, send_alert
from .common import config
from .common import logger as default_logger
from .loggers import (
    clear_request_context,
    generate_request_id,
    get_struct_logger,
    set_request_context,
)

TaskEvent = Literal["start", "error", "finish"]

# Context variable for current task_id
_current_task_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "current_task_id", default=None
)


def get_current_task_id() -> str | None:
    """Get the current task ID within task execution context.

    Returns the task_id if called from within a @task decorated function,
    or None if called outside of task context.

    Example:
        @task(name="my_task")
        async def my_task():
            task_id = get_current_task_id()
            # Use task_id for API calls, DB records, etc.
            await api_call(correlation_id=task_id)
    """
    return _current_task_id.get()


def build_loki_query_url(
    task_name: str,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    error_only: bool = False,
) -> str:
    """
    Build a Grafana Explore URL with a Loki query for the given task.

    Args:
        task_name: Name of the task to query logs for
        start_time: Start time for the query (defaults to 1 hour ago)
        end_time: End time for the query (defaults to now)
        error_only: If True, filter for ERROR level logs only

    Returns:
        URL string for Grafana Explore with the Loki query
    """
    if end_time is None:
        end_time = datetime.now(timezone.utc)
    if start_time is None:
        start_time = end_time - timedelta(hours=1)  # Default to 1 hour lookback

    # Build LogQL query
    if error_only:
        query = f'{{service_name=~".*{task_name}.*"}} |= "ERROR"'
    else:
        query = f'{{service_name=~".*{task_name}.*"}}'

    # Convert times to Unix timestamps in milliseconds
    from_ts = int(start_time.timestamp() * 1000)
    to_ts = int(end_time.timestamp() * 1000)

    # Build Grafana Explore URL
    grafana_base = config.grafana.rstrip("/")
    if not grafana_base.startswith("http"):
        grafana_base = f"http://{grafana_base}"

    encoded_query = quote(query, safe="")
    url = f"{grafana_base}/explore?orgId=1&left=%7B%22datasource%22:%22loki%22,%22queries%22:%5B%7B%22expr%22:%22{encoded_query}%22%7D%5D,%22range%22:%7B%22from%22:%22{from_ts}%22,%22to%22:%22{to_ts}%22%7D%7D"

    return url


class _RuntimeManager:
    """Singleton manager for the async runtime and blocking portal.

    FIXED: Added portal health checks, automatic recovery, and retry logic
    to prevent race conditions where portal becomes invalid between check and use.
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if not self._initialized:
            self._portal: Optional[BlockingPortal] = None
            self._thread: Optional[threading.Thread] = None
            self._portal_healthy: bool = False
            self._last_health_check: float = 0
            self._health_check_interval: float = 1.0  # Check health every 1 second
            self._initialized = True

    def _is_portal_healthy(self) -> bool:
        """Check if the portal is healthy and usable.

        Returns:
            True if portal exists and thread is alive
        """
        if self._portal is None or self._thread is None:
            return False

        if not self._thread.is_alive():
            default_logger.warning("Portal thread is not alive, needs restart")
            return False

        return True

    def get_portal(self) -> BlockingPortal:
        """Get or create the blocking portal for running async code from sync context.

        FIXED: Implements health checking and automatic recovery to prevent
        race conditions where portal becomes invalid between check and use.

        Returns:
            BlockingPortal instance

        Raises:
            RuntimeError: If portal cannot be initialized after retries
        """
        import time

        # Fast path: recent health check passed
        current_time = time.time()
        if (
            self._portal_healthy
            and current_time - self._last_health_check < self._health_check_interval
        ):
            return self._portal

        # Check if portal needs initialization or recovery
        max_retries = 3
        retry_delay = 0.5

        for attempt in range(max_retries):
            needs_restart = False

            # Check portal health
            if not self._is_portal_healthy():
                needs_restart = True
                default_logger.info(f"Portal unhealthy, attempting restart (attempt {attempt + 1}/{max_retries})")
            else:
                # Portal looks healthy, update health status
                self._portal_healthy = True
                self._last_health_check = current_time
                default_logger.debug("Portal health check passed")
                return self._portal

            # Restart portal if needed
            if needs_restart:
                with self._lock:
                    # Double-check inside lock
                    if not self._is_portal_healthy():
                        try:
                            # Clean up old portal if it exists
                            if self._portal is not None:
                                default_logger.debug("Stopping old portal before restart")
                                try:
                                    self._portal.call(self._portal.stop)
                                except Exception as e:
                                    default_logger.debug(f"Error stopping old portal: {e}")

                            # Start new runtime
                            self._start_runtime()

                            # Verify the new portal is healthy
                            if self._is_portal_healthy():
                                self._portal_healthy = True
                                self._last_health_check = time.time()
                                default_logger.info("Portal successfully restarted and verified")
                                return self._portal
                            else:
                                default_logger.error("Portal restart succeeded but health check failed")

                        except Exception as e:
                            default_logger.error(f"Portal restart failed: {e}", exc_info=True)
                            self._portal_healthy = False

            # Wait before retry (except on last attempt)
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
                retry_delay *= 2  # Exponential backoff

        # All retries exhausted
        raise RuntimeError(
            f"Failed to initialize or recover async portal after {max_retries} attempts. "
            "The async runtime may be in an unrecoverable state."
        )

    def _start_runtime(self):
        """Start the async runtime in a background thread.

        FIXED: Added better error handling and verification.
        """
        portal_holder = {}
        ready_event = threading.Event()
        error_holder = {}

        def run_async_runtime():
            try:
                async def main():
                    async with anyio.from_thread.BlockingPortal() as portal:
                        portal_holder["portal"] = portal
                        ready_event.set()
                        default_logger.debug("Async runtime started, portal ready")
                        await portal.sleep_until_stopped()
                        default_logger.debug("Async runtime stopped")

                anyio.run(main, backend="asyncio")
            except Exception as e:
                error_holder["error"] = e
                default_logger.error(f"Async runtime error: {e}", exc_info=True)
                ready_event.set()  # Unblock waiting thread

        self._thread = threading.Thread(target=run_async_runtime, daemon=True, name="TaskflowsAsyncRuntime")
        self._thread.start()

        # Wait for portal to be ready
        if not ready_event.wait(timeout=5):
            raise RuntimeError("Timeout waiting for async runtime to start")

        # Check if there was an error during startup
        if "error" in error_holder:
            raise RuntimeError(f"Async runtime failed to start: {error_holder['error']}")

        self._portal = portal_holder.get("portal")
        if not self._portal:
            raise RuntimeError("Failed to initialize async runtime: portal not created")

        default_logger.debug("Async runtime initialization completed successfully")


# Global singleton for runtime management
_runtime_manager = _RuntimeManager()


class Alerts(BaseModel):
    # where to send the alerts (e.g. email, slack, etc.)
    send_to: Sequence[MsgDst] | MsgDst
    # when to send the alerts (start, error, finish)
    send_on: Sequence[TaskEvent] | TaskEvent = ["start", "error", "finish"]

    def model_post_init(self, __context=None) -> None:
        if not isinstance(self.send_to, (list, tuple)):
            self.send_to = [self.send_to]
        if isinstance(self.send_on, str):
            self.send_on = [self.send_on]


def _normalize_alerts(
    alerts: Optional[Sequence["Alerts | MsgDst"]],
) -> Optional[List[Alerts]]:
    """Normalize alert configuration to a list of Alerts objects."""
    if not alerts:
        return None
    if not isinstance(alerts, (list, tuple)):
        alerts = [alerts]
    return [a if isinstance(a, Alerts) else Alerts(send_to=a) for a in alerts]


class TaskLogger:
    """Utility class for handling task logging and sending alerts with Loki URLs."""

    def __init__(
        self,
        name: str,
        required: bool,
        alerts: Optional[Sequence[Alerts]] = None,
        error_msg_max_length: int = 5000,
        task_id: Optional[str] = None,
    ):
        """
        Initialize a TaskLogger instance.

        Args:
            name (str): Name of the task.
            required (bool): Whether the task is required.
            alerts (Optional[Sequence[Alerts]], optional): Alert configurations / destinations. Defaults to None.
            task_id (Optional[str], optional): Unique task ID. Generated if not provided.
        """
        self.name = name
        self.required = required
        self.alerts = alerts or []
        self.error_msg_max_length = error_msg_max_length
        self.errors = []
        self.task_id = task_id or generate_request_id()

    async def on_task_start(self):
        """
        Handles actions to be performed when a task starts.

        Records the start time of the task, binds task context for logging,
        and sends start alerts if configured.
        """
        # Set task_id in context variable for access via get_current_task_id()
        _current_task_id.set(self.task_id)

        # Bind task_id to structlog context for all subsequent logs
        set_request_context(task_id=self.task_id, task_name=self.name)

        # record the start time of the task
        self.start_time = datetime.now(timezone.utc)

        # if there are any start alerts configured, send them
        if send_to := self._event_alerts("start"):
            components = [
                Text(
                    f"{Emoji.blue_circle} Starting: {self.name}",
                    font_size=FontSize.LARGE,
                    level=ContentType.IMPORTANT,
                )
            ]
            await send_alert(content=components, send_to=send_to)

    async def on_task_error(self, error: Exception):
        """
        Handles actions to be performed when a task encounters an error.

        Args:
            error (Exception): The exception that was raised.
        """
        # 1. add the error to the list of errors encountered by the task
        self.errors.append(error)

        # 2. if there are any error alerts configured, send them with Loki URL
        if send_to := self._event_alerts("error"):
            subject = f"{type(error).__name__} Error executing task {self.name}"
            error_message = f"{Emoji.red_circle} {subject}: {error}"

            # Build Loki URL for error logs
            loki_url = build_loki_query_url(
                task_name=self.name,
                start_time=self.start_time,
                end_time=datetime.now(timezone.utc),
                error_only=True,
            )

            components = [
                Text(
                    error_message,
                    font_size=FontSize.LARGE,
                    level=ContentType.ERROR,
                    max_length=self.error_msg_max_length,
                ),
                Text(
                    f"View error logs in Loki: {loki_url}",
                    font_size=FontSize.MEDIUM,
                    level=ContentType.INFO,
                ),
            ]
            await send_alert(content=components, send_to=send_to, subject=subject)

    async def on_task_finish(
        self,
        success: bool,
        return_value: Any = None,
        retries: int = 0,
    ):
        """
        Handles actions to be performed when a task finishes execution.

        Args:
            success (bool): Whether the task executed successfully.
            return_value (Any): The value returned by the task, if any.
            retries (int): The number of retries performed by the task, if any.
        """
        try:
            # record the finish time
            finish_time = datetime.now(timezone.utc)

            # if there are any finish alerts configured, send them
            if send_to := self._event_alerts("finish"):
                components = [
                    Text(
                        f"{Emoji.green_circle if success else Emoji.red_circle} Finished: {self.name} | {self.start_time} - {finish_time} ({finish_time-self.start_time})",
                        font_size=FontSize.LARGE,
                        level=(ContentType.IMPORTANT if success else ContentType.ERROR),
                    )
                ]

                if return_value is not None:
                    components.append(
                        Text(
                            f"Result: {return_value}",
                            font_size=FontSize.MEDIUM,
                            level=ContentType.IMPORTANT,
                        )
                    )

                # Build Loki URL for all logs during task execution
                loki_url = build_loki_query_url(
                    task_name=self.name,
                    start_time=self.start_time,
                    end_time=finish_time,
                    error_only=False,
                )

                if self.errors:
                    components.append(
                        Text(
                            f"ERRORS{Emoji.red_exclamation}",
                            font_size=FontSize.LARGE,
                            level=ContentType.ERROR,
                        )
                    )
                    for e in self.errors:
                        error_text = f"{type(e).__name__}: {e}"
                        components.append(
                            Text(
                                error_text,
                                font_size=FontSize.MEDIUM,
                                level=ContentType.INFO,
                                max_length=self.error_msg_max_length,
                            )
                        )

                # Add Loki URL for viewing logs
                components.append(
                    Text(
                        f"View logs in Loki: {loki_url}",
                        font_size=FontSize.MEDIUM,
                        level=ContentType.INFO,
                    )
                )

                await send_alert(content=components, send_to=send_to)

            # if there were any errors and the task is required, raise an error
            if self.errors and self.required:
                if len(self.errors) == 1:
                    raise self.errors[0]
                error_types = {type(e) for e in self.errors}
                if len(error_types) == 1:
                    # All errors are the same type — try to re-raise as that type
                    error_type = error_types.pop()
                    errors_str = "\n\n".join([str(e) for e in self.errors])
                    try:
                        raise error_type(
                            f"{len(self.errors)} errors executing task {self.name}:\n{errors_str}"
                        )
                    except TypeError:
                        # Some exception types (e.g. pydantic ValidationError) can't be
                        # constructed with just a string message
                        raise RuntimeError(
                            f"{len(self.errors)} errors executing task {self.name}:\n{errors_str}"
                        )
                raise RuntimeError(
                    f"{len(self.errors)} errors executing task {self.name}: {self.errors}"
                )
        finally:
            # Clear task context after task completes (success or failure)
            _current_task_id.set(None)
            clear_request_context()

    def _event_alerts(self, event: Literal["start", "error", "finish"]) -> List[MsgDst]:
        """Get the list of destinations to send alerts for the given event."""
        return [dst for alert in self.alerts if event in alert.send_on for dst in alert.send_to]


async def _async_task_wrapper(
    func: Callable,
    retries: int,
    timeout: Optional[float],
    task_logger: TaskLogger,
    logger: Logger,
    is_async: Optional[bool] = None,
    *args,
    **kwargs,
):
    """
    Async wrapper for a task function.

    Wraps a task function with retry and timeout logic, and logs the result
    of the task using the provided logger.
    """
    import time

    from taskflows.metrics import task_count, task_duration, task_errors, task_retries

    await task_logger.on_task_start()
    start_time = time.time()
    status = "failure"  # Default status

    # Determine if function is async (use cached value if provided)
    func_is_async = is_async if is_async is not None else asyncio.iscoroutinefunction(func)

    # Retry loop: range(retries + 1) gives us (retries + 1) total attempts
    for i in range(retries + 1):
        try:
            if func_is_async:
                if timeout:
                    result = await asyncio.wait_for(
                        func(*args, **kwargs), timeout=timeout
                    )
                else:
                    result = await func(*args, **kwargs)
            else:
                # For sync functions, run them in a thread pool with context propagation
                ctx = contextvars.copy_context()

                def run_in_context():
                    return ctx.run(func, *args, **kwargs)

                if timeout:
                    result = await asyncio.wait_for(
                        asyncio.to_thread(run_in_context), timeout=timeout
                    )
                else:
                    result = await asyncio.to_thread(run_in_context)
            await task_logger.on_task_finish(
                success=True, retries=i, return_value=result
            )
            # Track success metrics
            status = "success"
            task_count.labels(task_name=task_logger.name, status="success").inc()
            duration = time.time() - start_time
            task_duration.labels(task_name=task_logger.name, status="success").observe(duration)
            return result
        except TimeoutError as exp:
            msg = f"Task {task_logger.name} timed out. Retries remaining: {retries-i}.\n({type(exp)}) -- {exp}"
            logger.exception(msg)
            await task_logger.on_task_error(exp)
            if i < retries:
                task_retries.labels(task_name=task_logger.name).inc()
            else:
                # Final timeout failure
                status = "timeout"
                task_errors.labels(task_name=task_logger.name, error_type="timeout").inc()
                task_count.labels(task_name=task_logger.name, status="timeout").inc()
        except Exception as exp:
            msg = f"Error executing task {task_logger.name}. Retries remaining: {retries-i}.\n({type(exp)}) -- {exp}"
            logger.exception(msg)
            await task_logger.on_task_error(exp)
            if i < retries:
                task_retries.labels(task_name=task_logger.name).inc()
            else:
                # Final failure
                error_type = type(exp).__name__
                task_errors.labels(task_name=task_logger.name, error_type=error_type).inc()
                task_count.labels(task_name=task_logger.name, status="failure").inc()

    # Track final duration for failures
    if status != "success":
        duration = time.time() - start_time
        task_duration.labels(task_name=task_logger.name, status=status).observe(duration)

    await task_logger.on_task_finish(success=False, retries=retries)


async def run_task(
    func: Callable,
    name: Optional[str] = None,
    required: bool = False,
    retries: int = 0,
    timeout: Optional[float] = None,
    alerts: Optional[Sequence[Alerts | MsgDst]] = None,
    logger: Optional[Logger] = None,
    *args,
    **kwargs,
):
    """Run a function as a task with retry, timeout, and logging capabilities.

    Args:
        func (Callable): The function to run as a task.
        *args: Positional arguments to pass to the function.
        name (str): Name which should be used to identify the task.
        required (bool, optional): Required tasks will raise exceptions. Defaults to False.
        retries (int, optional): How many times to retry the task on failure. Defaults to 0.
        timeout (Optional[float], optional): Timeout (seconds) for function execution. Defaults to None.
        alerts (Optional[Sequence[Alerts]], optional): Alert configurations / destinations.
        logger (Optional[Logger], optional): Logger to use for error logging.
        **kwargs: Keyword arguments to pass to the function.

    Returns:
        The result of the function execution.
    """
    task_logger = TaskLogger(
        name=name or func.__name__,
        required=required,
        alerts=_normalize_alerts(alerts),
    )
    return await _async_task_wrapper(
        func=func,
        retries=retries,
        timeout=timeout,
        task_logger=task_logger,
        logger=logger or default_logger,
        *args,
        **kwargs,
    )


def task(
    name: Optional[str] = None,
    required: bool = False,
    retries: int = 0,
    timeout: Optional[float] = None,
    alerts: Optional[Sequence[Alerts | MsgDst]] = None,
    logger: Optional[Logger] = None,
):
    """Decorator for both sync and async task functions.

    Args:
        name (str): Name which should be used to identify the task.
        required (bool, optional): Required tasks will raise exceptions. Defaults to False.
        retries (int, optional): How many times to retry the task on failure. Defaults to 0.
        timeout (Optional[float], optional): Timeout (seconds) for function execution. Defaults to None.
        alerts (Optional[Sequence[Alerts]], optional): Alert configurations / destinations.
        logger (Optional[Logger], optional): Logger to use for error logging.
    """
    normalized_alerts = _normalize_alerts(alerts)
    task_logger_inst = logger or default_logger

    def task_decorator(func):
        # Check if the function is async at decoration time (once)
        func_is_async = asyncio.iscoroutinefunction(func)
        task_name = name or func.__name__

        async def async_wrapper(*args, **kwargs):
            task_logger = TaskLogger(
                name=task_name,
                required=required,
                alerts=normalized_alerts,
            )
            return await _async_task_wrapper(
                func=func,
                retries=retries,
                timeout=timeout,
                task_logger=task_logger,
                logger=task_logger_inst,
                is_async=func_is_async,
                *args,
                **kwargs,
            )

        def sync_wrapper(*args, **kwargs):
            # Smart wrapper that works with uvloop and existing event loops
            try:
                # Check if we're already in an async context
                asyncio.get_running_loop()
                # Return a coroutine/task that can be awaited
                return asyncio.create_task(async_wrapper(*args, **kwargs))
            except RuntimeError:
                # No running loop, use the portal
                portal = _runtime_manager.get_portal()
                return portal.call(async_wrapper, *args, **kwargs)

        # Return the appropriate wrapper based on whether the function is async
        return async_wrapper if func_is_async else sync_wrapper

    return task_decorator
