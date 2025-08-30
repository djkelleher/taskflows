import asyncio
import threading
from datetime import datetime, timezone
from logging import Logger
from typing import Any, Callable, List, Literal, Optional, Sequence

import anyio
from anyio.from_thread import BlockingPortal
import sqlalchemy as sa
from alert_msgs import ContentType, Emoji, FontSize, MsgDst, Text, send_alert
from pydantic import BaseModel

from .common import logger as default_logger
from .db import engine, get_tasks_db

TaskEvent = Literal["start", "error", "finish"]


class _RuntimeManager:
    """Singleton manager for the async runtime and blocking portal."""

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
            self._initialized = True

    def get_portal(self) -> BlockingPortal:
        """Get or create the blocking portal for running async code from sync context."""
        if self._portal is None or not self._thread.is_alive():
            with self._lock:
                if self._portal is None or not self._thread.is_alive():
                    self._start_runtime()
        return self._portal

    def _start_runtime(self):
        """Start the async runtime in a background thread."""
        portal_holder = {}
        ready_event = threading.Event()

        def run_async_runtime():
            async def main():
                async with anyio.from_thread.BlockingPortal() as portal:
                    portal_holder["portal"] = portal
                    ready_event.set()
                    await portal.sleep_until_stopped()

            anyio.run(main, backend="asyncio")

        self._thread = threading.Thread(target=run_async_runtime, daemon=True)
        self._thread.start()
        ready_event.wait(timeout=5)
        self._portal = portal_holder.get("portal")
        if not self._portal:
            raise RuntimeError("Failed to initialize async runtime")


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


class TaskLogger:
    """Utility class for handling async database logging, sending alerts, etc."""

    @classmethod
    async def create(
        cls,
        name: str,
        required: bool,
        db_record: bool = False,
        alerts: Optional[Sequence[Alerts]] = None,
        error_msg_max_length: int = 5000,
    ):
        """
        Create and initialize an TaskLogger instance.

        Args:
            name (str): Name of the task.
            required (bool): Whether the task is required.
            db_record (bool, optional): Whether to record the task in the database. Defaults to False.
            alerts (Optional[Sequence[Alerts]], optional): Alert configurations / destinations. Defaults to None.
        """
        self = cls()
        self.name = name
        self.required = required
        self.db_record = db_record
        self.alerts = alerts or []
        self.error_msg_max_length = error_msg_max_length
        self.errors = []
        self.db = None

        if self.db_record:
            self.db = await get_tasks_db()

        return self

    async def on_task_start(self):
        """
        Handles actions to be performed when a task starts.

        Records the start time of the task, logs it to the database if `db_record`
        is enabled, and sends start alerts if configured.
        """
        # record the start time of the task
        self.start_time = datetime.now(timezone.utc)

        # if db_record is enabled, log the start of the task to the database
        if self.db_record and self.db:
            async with engine.begin() as conn:
                statement = sa.insert(self.db.task_runs_table).values(
                    task_name=self.name,
                    started=self.start_time,
                )
                await conn.execute(statement)

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

        # 2. if db_record is enabled, record the error in the database
        if self.db_record and self.db:
            async with engine.begin() as conn:
                statement = sa.insert(self.db.task_errors_table).values(
                    task_name=self.name,
                    type=str(type(error)),
                    message=str(error),
                )
                await conn.execute(statement)

        # 3. if there are any error alerts configured, send them
        if send_to := self._event_alerts("error"):
            subject = f"{type(error)} Error executing task {self.name}"
            error_message = f"{Emoji.red_circle} {subject}: {error}"
            components = [
                Text(
                    error_message,
                    font_size=FontSize.LARGE,
                    level=ContentType.ERROR,
                    max_length=self.error_msg_max_length,
                )
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
        # record the finish time
        finish_time = datetime.now(timezone.utc)
        status = "success" if success else "failed"

        # if db_record is enabled, record the task run in the database
        if self.db_record and self.db:
            async with engine.begin() as conn:
                statement = (
                    sa.update(self.db.task_runs_table)
                    .where(
                        self.db.task_runs_table.c.task_name == self.name,
                        self.db.task_runs_table.c.started == self.start_time,
                    )
                    .values(
                        finished=finish_time,
                        retries=retries,
                        status=status,
                    )
                )
                await conn.execute(statement)

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

            if self.errors:
                components.append(
                    Text(
                        f"ERRORS{Emoji.red_exclamation}",
                        font_size=FontSize.LARGE,
                        level=ContentType.ERROR,
                    )
                )
                for e in self.errors:
                    error_text = f"{type(e)}: {e}"
                    components.append(
                        Text(
                            error_text,
                            font_size=FontSize.MEDIUM,
                            level=ContentType.INFO,
                            max_length=self.error_msg_max_length,
                        )
                    )

            await send_alert(content=components, send_to=send_to)

        # if there were any errors and the task is required, raise an error
        if self.errors and self.required:
            if len(self.errors) > 1:
                error_types = {type(e) for e in self.errors}
                if len(error_types) == 1:
                    errors_str = "\n\n".join([str(e) for e in self.errors])
                    raise error_types.pop()(
                        f"{len(self.errors)} errors executing task {self.name}:\n{errors_str}"
                    )
                raise RuntimeError(
                    f"{len(self.errors)} errors executing task {self.name}: {self.errors}"
                )
            raise type(self.errors[0])(str(self.errors[0]))

    def _event_alerts(self, event: Literal["start", "error", "finish"]) -> List[MsgDst]:
        """
        Get the list of destinations to send alerts for the given event.

        Args:
            event: The event (start, error, or finish) for which to get the
                alert destinations.

        Returns:
            A list of destinations to send the alert to.
        """
        send_to = []
        for alert in self.alerts:
            if event in alert.send_on:
                send_to += alert.send_to
        return send_to


async def _async_task_wrapper(
    func: Callable,
    retries: int,
    timeout: Optional[float],
    task_logger: TaskLogger,
    logger: Logger,
    *args,
    **kwargs,
):
    """
    Async wrapper for a task function.

    Wraps a task function with retry and timeout logic, and logs the result
    of the task using the provided logger.
    """
    await task_logger.on_task_start()
    for i in range(retries + 1):
        try:
            # Check if function is async
            if asyncio.iscoroutinefunction(func):
                if timeout:
                    result = await asyncio.wait_for(
                        func(*args, **kwargs), timeout=timeout
                    )
                else:
                    result = await func(*args, **kwargs)
            else:
                # For sync functions, run them in a thread pool
                if timeout:
                    result = await asyncio.wait_for(
                        asyncio.to_thread(func, *args, **kwargs), timeout=timeout
                    )
                else:
                    result = await asyncio.to_thread(func, *args, **kwargs)
            await task_logger.on_task_finish(
                success=True, retries=i, return_value=result
            )
            return result
        except Exception as exp:
            msg = f"Error executing task {task_logger.name}. Retries remaining: {retries-i}.\n({type(exp)}) -- {exp}"
            logger.exception(msg)
            await task_logger.on_task_error(exp)
    await task_logger.on_task_finish(success=False, retries=retries)


async def run_task(
    func: Callable,
    name: Optional[str] = None,
    required: bool = False,
    retries: int = 0,
    timeout: Optional[float] = None,
    db_record: bool = False,
    alerts: Optional[Sequence[Alerts | MsgDst]] = None,
    logger: Optional[Logger] = None,
    *args,
    **kwargs,
):
    """Run an async function as a task with retry, timeout, and logging capabilities.

    Args:
        func (Callable): The async function to run as a task.
        *args: Positional arguments to pass to the function.
        name (str): Name which should be used to identify the task.
        required (bool, optional): Required tasks will raise exceptions. Defaults to False.
        retries (int, optional): How many times to retry the task on failure. Defaults to 0.
        timeout (Optional[float], optional): Timeout (seconds) for function execution. Defaults to None.
        db_record (bool, optional): Whether to record the task in the database. Defaults to False.
        alerts (Optional[Sequence[Alerts]], optional): Alert configurations / destinations.
        logger (Optional[Logger], optional): Logger to use for error logging.
        **kwargs: Keyword arguments to pass to the function.

    Returns:
        The result of the function execution.
    """
    logger = logger or default_logger
    if alerts:
        if not isinstance(alerts, (list, tuple)):
            alerts = [alerts]
        alerts = [a if isinstance(a, Alerts) else Alerts(send_to=a) for a in alerts]

    task_logger = await TaskLogger.create(
        name=name or func.__name__,
        required=required,
        db_record=db_record,
        alerts=alerts,
    )
    return await _async_task_wrapper(
        func=func,
        retries=retries,
        timeout=timeout,
        task_logger=task_logger,
        logger=logger,
        *args,
        **kwargs,
    )


def task(
    name: Optional[str] = None,
    required: bool = False,
    retries: int = 0,
    timeout: Optional[float] = None,
    db_record: bool = False,
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
    logger = logger or default_logger
    if alerts:
        if not isinstance(alerts, (list, tuple)):
            alerts = [alerts]
        alerts = [a if isinstance(a, Alerts) else Alerts(send_to=a) for a in alerts]

    def task_decorator(func):
        # Check if the function is async
        is_async = asyncio.iscoroutinefunction(func)

        async def async_wrapper(*args, **kwargs):
            task_logger = await TaskLogger.create(
                name=name or func.__name__,
                required=required,
                db_record=db_record,
                alerts=alerts,
            )
            return await _async_task_wrapper(
                func=func,
                retries=retries,
                timeout=timeout,
                task_logger=task_logger,
                logger=logger,
                *args,
                **kwargs,
            )

        def sync_wrapper(*args, **kwargs):
            # Smart wrapper that works with uvloop and existing event loops
            try:
                # Check if we're already in an async context
                loop = asyncio.get_running_loop()
                # Return a coroutine/task that can be awaited
                return asyncio.create_task(async_wrapper(*args, **kwargs))
            except RuntimeError:
                # No running loop, use the portal
                portal = _runtime_manager.get_portal()
                return portal.call(async_wrapper, *args, **kwargs)

        # Return the appropriate wrapper based on whether the function is async
        return async_wrapper if is_async else sync_wrapper

    return task_decorator
