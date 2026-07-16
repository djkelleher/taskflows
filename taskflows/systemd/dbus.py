"""systemd D-Bus session-bus connection management with automatic reconnection."""

import asyncio
from contextlib import suppress

from dbus_next import BusType
from dbus_next.aio import MessageBus
from dbus_next.errors import DBusError

from ..common import logger

# DBus connection management with automatic reconnection (async dbus-next)
# Uses asyncio for non-blocking D-Bus operations
# Use a dict to store locks per event loop to avoid "bound to different event loop" errors
_dbus_connection_locks: dict = {}
_dbus_session_bus: MessageBus | None = None
_dbus_manager = None
_dbus_manager_introspection = None
_dbus_last_error_time = 0
_dbus_error_cooldown = 5  # Seconds between reconnection attempts


def _get_dbus_lock() -> asyncio.Lock:
    """Get the asyncio lock for the current event loop.

    This handles the case where tests run with different event loops.
    Each event loop gets its own lock.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    loop_id = id(loop) if loop else 0
    if loop_id not in _dbus_connection_locks:
        _dbus_connection_locks[loop_id] = asyncio.Lock()
    return _dbus_connection_locks[loop_id]


async def _reset_dbus_connections():
    """Reset DBus connections (called when connection becomes stale)."""
    global _dbus_session_bus, _dbus_manager, _dbus_manager_introspection
    if _dbus_session_bus is not None:
        with suppress(Exception):
            _dbus_session_bus.disconnect()
    _dbus_session_bus = None
    _dbus_manager = None
    _dbus_manager_introspection = None
    logger.info("DBus connections reset for reconnection")


async def _session_dbus_unlocked() -> MessageBus:
    """Internal: Get or create the D-Bus session bus connection without acquiring lock.

    MUST be called with _get_dbus_lock() already held.
    """
    global _dbus_session_bus, _dbus_last_error_time
    import time

    # Try to use existing connection
    if _dbus_session_bus is not None and _dbus_session_bus.connected:
        return _dbus_session_bus

    if _dbus_session_bus is not None:
        logger.warning("DBus session bus disconnected, reconnecting...")
        _dbus_session_bus = None

    # Apply cooldown to avoid tight reconnection loops
    current_time = time.time()
    if current_time - _dbus_last_error_time < _dbus_error_cooldown:
        await asyncio.sleep(0.5)  # Brief delay

    # Create new connection
    try:
        logger.info("Creating new DBus session bus connection")
        _dbus_session_bus = await MessageBus(bus_type=BusType.SESSION).connect()
        logger.info("DBus session bus connection established successfully")
        return _dbus_session_bus
    except Exception as e:
        _dbus_last_error_time = current_time
        logger.error(f"Failed to create DBus session bus: {e}", exc_info=True)
        raise


async def session_dbus() -> MessageBus:
    """Get or create the D-Bus session bus connection.

    Implements automatic reconnection on connection failure.
    Handles systemd restarts gracefully.

    Returns:
        MessageBus instance

    Raises:
        DBusError: If connection cannot be established
    """
    async with _get_dbus_lock():
        return await _session_dbus_unlocked()


async def systemd_manager():
    """Get or create the systemd D-Bus manager interface.

    Implements automatic reconnection on connection failure.
    Handles systemd restarts gracefully.

    Returns:
        Proxy interface to systemd manager

    Raises:
        DBusError: If manager cannot be accessed
    """
    global _dbus_manager, _dbus_manager_introspection

    async with _get_dbus_lock():
        # Get bus (will reconnect if needed) - use unlocked version since we already hold the lock
        bus = await _session_dbus_unlocked()

        # Try to use existing manager if bus is still the same
        if _dbus_manager is not None:
            try:
                # Health check: try a simple property access
                version = await _dbus_manager.get_version()
                return _dbus_manager
            except (DBusError, Exception) as e:
                logger.warning(f"DBus manager health check failed: {e}")
                await _reset_dbus_connections()
                bus = await _session_dbus_unlocked()

        # Create new manager interface
        try:
            logger.info("Creating new systemd D-Bus manager interface")
            _dbus_manager_introspection = await bus.introspect(
                "org.freedesktop.systemd1", "/org/freedesktop/systemd1"
            )
            proxy = bus.get_proxy_object(
                "org.freedesktop.systemd1",
                "/org/freedesktop/systemd1",
                _dbus_manager_introspection,
            )
            _dbus_manager = proxy.get_interface("org.freedesktop.systemd1.Manager")
            # Verify manager works
            version = await _dbus_manager.get_version()
            logger.info(f"Systemd D-Bus manager connected (version: {version})")
            return _dbus_manager
        except Exception as e:
            logger.error(f"Failed to create systemd manager: {e}", exc_info=True)
            await _reset_dbus_connections()
            raise


async def _dbus_operation_with_retry(operation, operation_name, max_retries=2):
    """Execute a D-Bus operation with automatic retry on connection failure.

    Args:
        operation: Async callable that performs the D-Bus operation
        operation_name: Human-readable name for logging
        max_retries: Maximum number of retry attempts

    Returns:
        Result of the operation

    Raises:
        DBusError: If all retries fail
    """
    for attempt in range(max_retries + 1):
        try:
            return await operation()
        except DBusError as e:
            error_str = str(e).lower()

            # Check if this is a connection-related error
            is_connection_error = any(
                keyword in error_str
                for keyword in [
                    "connection",
                    "disconnected",
                    "not available",
                    "no reply",
                ]
            )

            if is_connection_error and attempt < max_retries:
                logger.warning(
                    f"DBus operation '{operation_name}' failed with connection error "
                    f"(attempt {attempt + 1}/{max_retries + 1}): {e}"
                )
                # Reset connections and retry
                await _reset_dbus_connections()
                await asyncio.sleep(0.5 * (attempt + 1))  # Exponential backoff
                continue
            # Non-connection error or final attempt - propagate
            if attempt == max_retries:
                logger.error(
                    f"DBus operation '{operation_name}' failed after {max_retries + 1} attempts: {e}"
                )
            raise
        except Exception as e:
            # Unexpected error - always propagate
            logger.error(
                f"Unexpected error in DBus operation '{operation_name}': {e}",
                exc_info=True,
            )
            raise
    raise RuntimeError(f"DBus operation '{operation_name}' exhausted retries")


async def reload_unit_files():
    """Reload systemd unit files with automatic retry on connection failure."""

    async def _reload():
        mgr = await systemd_manager()
        await mgr.call_reload()

    await _dbus_operation_with_retry(_reload, "reload_unit_files")


async def escape_path(path) -> str:
    """Escape a path so that it can be used in a systemd file."""
    mgr = await systemd_manager()
    return await mgr.call_escape_path(path)


async def _get_unit_proxy(bus: MessageBus, unit_path: str):
    """Get a proxy object for a unit at the given path."""
    introspection = await bus.introspect("org.freedesktop.systemd1", unit_path)
    return bus.get_proxy_object("org.freedesktop.systemd1", unit_path, introspection)
