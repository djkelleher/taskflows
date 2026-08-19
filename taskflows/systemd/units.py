"""Query and drive systemd user units."""

import asyncio
import os
import re
import subprocess
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from pprint import pformat
from typing import Literal

import docker.errors
from dbus_next.errors import DBusError

from ..common import (
    _SYSTEMD_FILE_PREFIX,
    extract_service_name,
    logger,
    services_data_dir,
)
from ..docker import delete_docker_container, get_docker_client
from .dbus import (
    _get_unit_proxy,
    reload_unit_files,
    session_dbus,
    systemd_manager,
)


def service_logs(service_name: str, n_lines: int = 1000):
    """Get logs for a service.

    For Docker containers: reads from docker logs
    For systemd services: reads from journalctl

    Args:
        service_name (str): The name of the service to show logs for.
        n_lines (int): Number of log lines to retrieve.

    Returns:
        str: The log output.
    """
    from taskflows.security_validation import validate_service_name

    service_name = validate_service_name(service_name)
    n_lines = max(1, min(int(n_lines), 100_000))
    container_name = f"{_SYSTEMD_FILE_PREFIX}{service_name}"

    # Check if this is a Docker container
    try:
        client = get_docker_client()
        container = client.containers.get(container_name)
        # Docker container exists - use docker logs
        logs = container.logs(tail=n_lines, timestamps=True).decode("utf-8")
        return logs.strip()
    except docker.errors.NotFound:
        pass  # Not a Docker container, fall through to journalctl
    except Exception as e:
        logger.debug(f"Docker check failed for {container_name}: {e}")

    # Fall back to journalctl for systemd services
    cmd = [
        "journalctl",
        "--user",
        "-u",
        f"{_SYSTEMD_FILE_PREFIX}{service_name}",
        "-n",
        str(n_lines),
    ]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=True,
        timeout=int(os.getenv("TASKFLOWS_JOURNALCTL_TIMEOUT_SECONDS", "15")),
    )
    txt = []
    if result.stderr:
        txt.append(result.stderr)
    if result.stdout:
        txt.append(result.stdout)
    return "\n\n".join(txt).strip()


async def get_schedule_info(unit: str):
    """Get the schedule information for a unit."""
    unit_stem = Path(unit).stem
    accepted_prefixes = (
        _SYSTEMD_FILE_PREFIX,
        f"stop-{_SYSTEMD_FILE_PREFIX}",
        f"restart-{_SYSTEMD_FILE_PREFIX}",
    )
    if not unit_stem.startswith(accepted_prefixes):
        unit_stem = f"{_SYSTEMD_FILE_PREFIX}{unit_stem}"
    manager = await systemd_manager()
    bus = await session_dbus()

    async def properties(suffix: str, interface: str, *, required: bool):
        try:
            path = await manager.call_load_unit(f"{unit_stem}.{suffix}")
            proxy = await _get_unit_proxy(bus, path)
            return await proxy.get_interface("org.freedesktop.DBus.Properties").call_get_all(
                interface
            )
        except DBusError as exc:
            if not required and exc.type.endswith(".NoSuchUnit"):
                return {}
            raise

    # Fetch each interface in one operation. A timer is optional: long-running
    # services without one must still be inspectable with `tf status --details`.
    service_values, timer_values = await asyncio.gather(
        properties("service", "org.freedesktop.systemd1.Unit", required=True),
        properties("timer", "org.freedesktop.systemd1.Timer", required=False),
    )
    schedule = {
        "Last Start": service_values.get("ActiveEnterTimestamp", 0),
        "Last Finish": service_values.get("ActiveExitTimestamp", 0),
    }
    schedule["Next Start"] = timer_values.get("NextElapseUSecRealtime", 0)

    def timestamp_to_dt(timestamp):
        try:
            # Handle Variant type from dbus-next
            if hasattr(timestamp, "value"):
                timestamp = timestamp.value
            if not timestamp:
                return None
            return datetime.fromtimestamp(timestamp / 1_000_000, tz=UTC)
        except (OverflowError, ValueError, TypeError):
            # "year 586524 is out of range" or type error
            return None

    schedule = {field: timestamp_to_dt(val) for field, val in schedule.items()}

    # TimersCalendar
    timers_cal = []
    timers_calendar_raw = timer_values.get("TimersCalendar", [])
    # Handle Variant type
    if hasattr(timers_calendar_raw, "value"):
        timers_calendar_raw = timers_calendar_raw.value
    for timer in timers_calendar_raw:
        base, spec, next_start = timer
        timers_cal.append(
            {
                "base": base,
                "spec": spec,
                "next_start": timestamp_to_dt(next_start),
            }
        )
    schedule["Timers Calendar"] = timers_cal
    if (not schedule["Next Start"]) and (
        next_start := [t["next_start"] for t in timers_cal if t["next_start"]]
    ):
        schedule["Next Start"] = min(next_start)

    # TimersMonotonic
    timers_mono = []
    timers_monotonic_raw = timer_values.get("TimersMonotonic", [])
    # Handle Variant type
    if hasattr(timers_monotonic_raw, "value"):
        timers_monotonic_raw = timers_monotonic_raw.value
    for timer in timers_monotonic_raw:
        base, offset, next_start = timer
        timers_mono.append(
            {
                "base": base,
                "offset": offset,
                "next_start": timestamp_to_dt(next_start),
            }
        )
    schedule["Timers Monotonic"] = timers_mono
    return schedule


async def get_unit_files(
    unit_type: Literal["service", "timer"] | None = None,
    match: str | None = None,
    states: str | Sequence[str] | None = None,
) -> list[str]:
    """Get a list of paths of taskflows unit files."""
    file_states = await get_unit_file_states(unit_type=unit_type, match=match, states=states)
    return list(file_states.keys())


async def get_unit_file_states(
    unit_type: Literal["service", "timer"] | None = None,
    match: str | None = None,
    states: str | Sequence[str] | None = None,
) -> dict[str, str]:
    """Map taskflows unit file path to unit state."""
    states = states or []
    pattern = _make_unit_match_pattern(unit_type=unit_type, match=match)
    mgr = await systemd_manager()
    files = await mgr.call_list_unit_files_by_patterns(states, [pattern])
    logger.debug(f"Found {len(files)} units matching: {pattern}")
    if not files:
        logger.error(f"No taskflows unit files found matching: {pattern}")
    return {str(file): str(state) for file, state in files}


async def get_units(
    unit_type: Literal["service", "timer"] | None = None,
    match: str | None = None,
    states: str | Sequence[str] | None = None,
) -> list[dict[str, str]]:
    """Get metadata for taskflows units."""
    states = states or []
    pattern = _make_unit_match_pattern(unit_type=unit_type, match=match)
    mgr = await systemd_manager()
    files = await mgr.call_list_units_by_patterns(states, [pattern])
    fields = [
        "unit_name",
        "description",
        "load_state",
        "active_state",
        "sub_state",
        "followed",
        "unit_path",
        "job_id",
        "job_type",
        "job_path",
    ]
    units = [{k: str(v) for k, v in zip(fields, f, strict=False)} for f in files]
    logger.debug(f"Found {len(units)} units matching: {pattern}")
    return units


def _make_unit_match_pattern(
    unit_type: Literal["service", "timer"] | None = None, match: str | None = None
) -> str:
    pattern = match or "*"
    if unit_type:
        suffix = f".{unit_type}"
        if not pattern.endswith(suffix):
            pattern += suffix
    elif not pattern.endswith((".service", ".timer", ".*")):
        pattern += ".*"
    if _SYSTEMD_FILE_PREFIX not in pattern:
        pattern = f"*{_SYSTEMD_FILE_PREFIX}{pattern}"
    return re.sub(r"\*{2,}", "*", pattern)


def is_start_service(unit_file: str) -> bool:
    """Check if a unit file is a main start service (not an auxiliary stop/restart service).

    Args:
        unit_file: Unit file path or filename

    Returns:
        True if the unit is the main service (doesn't start with "stop-" or "restart-")
    """
    filename = os.path.basename(unit_file) if os.path.sep in unit_file else unit_file
    return not filename.startswith(("stop-", "restart-"))


async def start_units(files: Sequence[str]):
    from taskflows.metrics import get_metrics

    service_state = get_metrics().service_state
    mgr = await systemd_manager()
    for sf in files:
        sf = os.path.basename(sf)
        if is_start_service(sf):
            service_name = extract_service_name(sf)
            logger.info(f"Running: {sf}")
            await mgr.call_start_unit(sf, "replace")
            # Track service state change
            service_state.labels(service_name=service_name, state="active").set(1)
            service_state.labels(service_name=service_name, state="inactive").set(0)


async def stop_units(files: Sequence[str]):
    from taskflows.metrics import get_metrics

    service_state = get_metrics().service_state
    mgr = await systemd_manager()
    for sf in files:
        sf = os.path.basename(sf)
        service_name = extract_service_name(sf)
        logger.info(f"Stopping: {sf}")
        try:
            await mgr.call_stop_unit(sf, "replace")
            # Track service state change
            service_state.labels(service_name=service_name, state="inactive").set(1)
            service_state.labels(service_name=service_name, state="active").set(0)
        except DBusError as err:
            logger.warning(f"Could not stop {sf}: ({type(err)}) {err}")

        # remove any failed status caused by stopping service.
        # await mgr.call_reset_failed_unit(sf)


async def restart_units(files: Sequence[str]):
    from taskflows.metrics import get_metrics

    service_restarts = get_metrics().service_restarts

    units = [os.path.basename(f) for f in files]
    # only restart main service units
    units = [u for u in units if is_start_service(u)]
    mgr = await systemd_manager()
    for sf in units:
        service_name = extract_service_name(sf)
        logger.info(f"Restarting: {sf}")
        try:
            await mgr.call_restart_unit(sf, "replace")
            # Track restart
            service_restarts.labels(service_name=service_name, reason="manual").inc()
        except DBusError as err:
            logger.warning(f"Could not restart {sf}: ({type(err)}) {err}")


async def enable_units(files: Sequence[str]):
    mgr = await systemd_manager()
    logger.info(f"Enabling: {pformat(files)}")

    async def enable_files(files, is_retry=False):
        try:
            # the first bool controls whether the unit shall be enabled for runtime only (true, /run), or persistently (false, /etc).
            # The second one controls whether symlinks pointing to other units shall be replaced if necessary.
            await mgr.call_enable_unit_files(files, False, True)
        except DBusError as err:
            logger.warning(f"Could not enable {files}: ({type(err)}) {err}")
            if not is_retry and len(files) > 1:
                for file in files:
                    await enable_files([file], is_retry=True)

    await enable_files(files)


async def disable_units(files: Sequence[str]):
    mgr = await systemd_manager()
    files = [os.path.basename(f) for f in files]
    logger.info(f"Disabling: {pformat(files)}")

    async def disable_files(files, is_retry=False):
        try:
            # the first bool controls whether the unit shall be enabled for runtime only (true, /run), or persistently (false, /etc).
            # The second one controls whether symlinks pointing to other units shall be replaced if necessary.
            result = await mgr.call_disable_unit_files(files, False)
            for meta in result:
                # meta has: the type of the change (one of symlink or unlink), the file name of the symlink and the destination of the symlink.
                logger.info(f"{meta[0]} {meta[1]} {meta[2]}")
        except DBusError as err:
            logger.warning(f"Could not disable {files}: ({type(err)}) {err}")
            if not is_retry and len(files) > 1:
                for file in files:
                    await disable_files([file], is_retry=True)

    await disable_files(files)


async def remove_units(
    service_files: Sequence[str],
    timer_files: Sequence[str],
    preserve_container: bool = False,
):
    def valid_file_paths(files):
        files = [Path(f) for f in files]
        return [f for f in files if f.is_file()]

    service_files = valid_file_paths(service_files)
    timer_files = valid_file_paths(timer_files)
    logger.info(f"Removing {len(service_files)} services and {len(timer_files)} timers")
    files = service_files + timer_files
    await stop_units(files)
    await disable_units(files)
    container_names = set()
    mgr = await systemd_manager()
    for srv_file in service_files:
        logger.info(f"Cleaning cache and runtime directories: {srv_file}.")
        try:
            # the possible values are "configuration", "state", "logs", "cache", "runtime", "fdstore", and "all".
            await mgr.call_clean_unit(srv_file.name, ["all"])
        except DBusError as err:
            logger.warning(f"Could not clean {srv_file}: ({type(err)}) {err}")
        container_name = re.search(r"docker (?:start|stop) ([\w-]+)", srv_file.read_text())
        if container_name:
            container_names.add(container_name.group(1))
    if not preserve_container:
        for cname in container_names:
            delete_docker_container(cname)
    else:
        logger.info(f"Preserving Docker containers: {container_names}")
    for srv in service_files:
        files.extend(services_data_dir.glob(f"{extract_service_name(srv)}#*.pickle"))
        files.extend(services_data_dir.glob(f"{extract_service_name(srv)}#monitor.json"))
    for file in files:
        logger.info(f"Deleting {file}")
        file.unlink(missing_ok=True)
    logger.info(f"Finished removing {len(service_files)} services and {len(timer_files)} timers")
    await reload_unit_files()
