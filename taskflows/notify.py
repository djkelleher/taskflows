"""sd_notify integration: readiness, status, and watchdog pings over NOTIFY_SOCKET.

Pure-stdlib implementation of the systemd notification protocol
(https://www.freedesktop.org/software/systemd/man/sd_notify.html). Every
function is a safe no-op when not running under systemd (no NOTIFY_SOCKET),
so application code can call these unconditionally.

Used together with ``Service(watchdog=Watchdog(...))``, which emits
``Type=notify`` + ``WatchdogSec=`` so systemd restarts the service if pings
stop arriving — kernel-supervised hang detection, not just crash detection.
"""

import asyncio
import contextlib
import os
import socket

from .common import logger


def sd_notify(state: str) -> bool:
    """Send a raw sd_notify state string (e.g. "READY=1").

    Returns True if the message was sent, False when not running under
    systemd or on any socket error (never raises).
    """
    addr = os.getenv("NOTIFY_SOCKET")
    if not addr:
        return False
    if addr.startswith("@"):
        # Linux abstract namespace socket
        addr = "\0" + addr[1:]
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
            sock.connect(addr)
            sock.sendall(state.encode())
        return True
    except OSError as err:
        logger.debug(f"sd_notify({state!r}) failed: {err}")
        return False


def ready() -> bool:
    """Tell systemd the service has finished starting up (Type=notify)."""
    return sd_notify("READY=1")


def stopping() -> bool:
    """Tell systemd the service has begun shutting down."""
    return sd_notify("STOPPING=1")


def status(message: str) -> bool:
    """Set the free-form status string shown by systemctl status."""
    return sd_notify(f"STATUS={message}")


def watchdog_ping() -> bool:
    """Send a keep-alive ping (WatchdogSec liveness)."""
    return sd_notify("WATCHDOG=1")


def watchdog_interval() -> float | None:
    """The watchdog interval in seconds, if systemd armed one for this process."""
    usec = os.getenv("WATCHDOG_USEC")
    if not usec:
        return None
    pid = os.getenv("WATCHDOG_PID")
    if pid and pid != str(os.getpid()):
        return None
    try:
        return int(usec) / 1_000_000
    except ValueError:
        return None


def start_watchdog_pinger() -> asyncio.Task | None:
    """Start a background task pinging the watchdog at half the armed interval.

    Call from a running event loop (e.g. inside an async_entrypoint function).
    Returns the pinger task, or None when no watchdog is armed. Cancel the
    task to stop pinging (systemd will then restart the unit after
    WatchdogSec when RestartPolicy(condition="on-watchdog") is set).
    """
    interval = watchdog_interval()
    if interval is None:
        return None

    async def _ping_forever():
        delay = interval / 2
        while True:
            watchdog_ping()
            await asyncio.sleep(delay)

    task = asyncio.get_running_loop().create_task(_ping_forever(), name="taskflows-watchdog-pinger")
    logger.info(f"systemd watchdog armed ({interval}s); pinging every {interval / 2}s")
    return task


@contextlib.contextmanager
def notify_stopping_on_exit():
    """Context manager sending STOPPING=1 when the block exits."""
    try:
        yield
    finally:
        stopping()
