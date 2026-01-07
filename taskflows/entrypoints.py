import asyncio
import inspect
import re
import signal
import sys
import traceback
from functools import cache, wraps
from pprint import pformat
from typing import Any, Callable, Dict, Sequence

import click
from click import Group
from .dynamic_imports import import_module_attr

from .common import logger


def parse_str_kwargs(kwargs: Sequence[str]) -> Dict[str, float | str]:
    """Parses string in the form 'key=value'"""
    kwargs_dict = {}
    for pair in kwargs:
        if "=" not in pair:
            raise click.BadParameter(f"Invalid key=value pair: {pair}")
        key, value = pair.split("=", 1)
        if re.match(r"(\d+(\.\d+)?)$", value):
            value = float(value)
        kwargs_dict[key] = value
    return kwargs_dict


class ShutdownHandler:
    def __init__(self, shutdown_on_exception: bool = False):
        """
        Initialize the ShutdownHandler.

        Sets up the event loop and signal handlers for managing graceful
        shutdowns in response to specific signals or exceptions.

        Args:
            shutdown_on_exception (bool): If True, initiate shutdown on
                uncaught exceptions. Defaults to False.
        """
        self.shutdown_on_exception = shutdown_on_exception
        self.loop = asyncio.get_event_loop_policy().get_event_loop()
        self.callbacks = []
        self._shutdown_task = None
        self._exit_code = None
        self.loop.set_exception_handler(self._loop_exception_handle)
        for s in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
            self.loop.add_signal_handler(
                s,
                lambda s=s: self.loop.create_task(self._on_signal_interrupt(s)),
            )

    def add_callback(self, cb: Callable[[], None]):
        """
        Registers a coroutine function to be called on shutdown.

        The function takes no arguments and returns nothing. It is called in
        the event loop thread.

        Raises:
            ValueError: if the callback is not a coroutine function
        """
        if not inspect.iscoroutinefunction(cb):
            raise ValueError("Callback must be coroutine function")
        self.callbacks.append(cb)

    async def shutdown(self, exit_code: int):
        """
        Initiate shutdown of the event loop.

        Starts the shutdown process by scheduling the :meth:`_shutdown` task
        with the given `exit_code`. If the shutdown task is already running,
        this method simply returns the existing task.

        Args:
            exit_code (int): The code to exit with when shutting down.

        Returns:
            The shutdown task.
        """
        if self._shutdown_task is None:
            self._create_shutdown_task(exit_code)
        return await self._shutdown_task

    def _loop_exception_handle(self, loop: Any, context: Dict[str, Any]):
        """
        Exception handler for the event loop.

        This function is called when an uncaught exception is raised in a
        coroutine. It logs the exception and its traceback, and if
        `shutdown_on_exception` is True, it initiates shutdown by calling
        `self._create_shutdown_task(1)`.

        :param loop: The event loop.
        :param context: A dictionary containing information about the
            exception.
        """
        logger.error(f"Uncaught coroutine exception: {pformat(context)}")
        # Extract the exception object from the context
        exception = context.get("exception")
        if exception:
            # Log the exception traceback
            tb = "".join(
                traceback.format_exception(
                    type(exception), exception, exception.__traceback__
                )
            )
            logger.error(f"Exception traceback:\n{tb}")
        else:
            # Log the message if no exception is provided
            message = context.get("message", "No exception object found in context")
            logger.error(f"Error message: {message}")

        if self.shutdown_on_exception and (self._shutdown_task is None):
            self._create_shutdown_task(1)

    async def _on_signal_interrupt(self, signum: int):
        """
        Handle a signal interrupt.

        This function is called when a signal interrupt is received. It logs a
        message indicating the signal that was received and shuts down the event
        loop.

        Args:
            signum (int): The signal number that was received.
        """
        signame = signal.Signals(signum).name if signum is not None else "Unknown"
        logger.warning(f"Caught signal {signum} ({signame}). Shutting down.")
        await self.shutdown(0)

    def _create_shutdown_task(self, exit_code: int):
        """
        Create and schedule the shutdown task.

        This function creates and schedules a shutdown task by calling
        `self._shutdown(exit_code)` with the given `exit_code` argument. The
        task is scheduled to run in the event loop.

        Args:
            exit_code (int): The exit code to use when shutting down.

        Returns:
            None
        """
        self._shutdown_task = self.loop.create_task(self._shutdown(exit_code))

    async def _shutdown(self, exit_code: int):
        """
        Perform the shutdown procedure.

        This method executes the shutdown process in the following steps:

        1. Execute all registered shutdown callbacks.
        2. Store the exit code for later use.
        3. Schedule loop stop to occur after this task completes.

        Args:
            exit_code (int): The exit code to use when terminating the program.
        """
        logger.info(f"Shutting down. Exit code: {exit_code}")
        # Execute all registered shutdown callbacks
        for cb in self.callbacks:
            logger.info(f"Calling shutdown callback: {cb}")
            try:
                # Wait up to 5 seconds for each callback to complete
                await asyncio.wait_for(cb(), timeout=5)
            except Exception as err:
                # Log any exceptions that occur in the callbacks
                logger.exception(
                    f"{type(err)} error in shutdown callback {cb}: {err}"
                )
        # Store the exit code for retrieval after event loop completes
        self._exit_code = exit_code
        # Schedule loop stop to happen after this coroutine completes
        # This allows the current task to finish before the loop stops
        logger.info(f"Scheduling event loop stop. Exit code: {exit_code}")
        self.loop.call_soon(self.loop.stop)


@cache
def get_shutdown_handler():
    """
    Return an instance of ShutdownHandler.

    This function is memoized.

    :return: An instance of ShutdownHandler.
    """
    return ShutdownHandler()


def async_entrypoint(blocking: bool = False, shutdown_on_exception: bool = True):
    def decorator(f):
        loop = asyncio.get_event_loop_policy().get_event_loop()
        sdh = get_shutdown_handler()
        sdh.shutdown_on_exception = shutdown_on_exception

        async def async_entrypoint_async(*args, **kwargs):
            logger.info(f"Running main task: {f}")
            try:
                await f(*args, **kwargs)
                if blocking:
                    await sdh.shutdown(0)
            except Exception as err:
                logger.exception("Error running main task: %s", err)
                await sdh.shutdown(1)

        @wraps(f)
        def wrapper(*args, **kwargs):
            task = loop.create_task(async_entrypoint_async(*args, **kwargs))
            try:
                if blocking:
                    loop.run_until_complete(task)
                else:
                    loop.run_forever()
            finally:
                # After loop stops, just close it
                # The loop shutdown already handled task cancellation via _shutdown()
                try:
                    if not loop.is_closed():
                        loop.close()
                except Exception as e:
                    # Log but don't fail on cleanup errors
                    logger.debug(f"Error closing event loop: {e}")

                # Exit with the stored exit code if shutdown was requested
                if sdh._exit_code is not None:
                    sys.exit(sdh._exit_code)

        return wrapper

    return decorator


class CLIGroup:
    """Combine and optionally lazy load multiple click CLIs."""

    def __init__(self):
        self.cli = Group()
        self.commands = {}

    def add_sub_cli(self, cli: Group):
        self.cli.add_command(cli)

    def add_lazy_sub_cli(self, name: str, cli_module: str, cli_variable: str):
        self.commands[name] = lambda: import_module_attr(cli_module, cli_variable)

    def run(self):
        if len(sys.argv) > 1 and (cmd_name := sys.argv[1]) in self.commands:
            # construct sub-command only as needed.
            self.cli.add_command(self.commands[cmd_name](), name=cmd_name)
        else:
            # For user can list all sub-commands.
            for cmd_name, cmd_importer in self.commands.items():
                self.cli.add_command(cmd_importer(), name=cmd_name)
        self.cli()
