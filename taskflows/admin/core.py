import asyncio
import inspect
import json
import socket
from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Literal
from urllib.parse import urlencode, urlsplit
from zoneinfo import ZoneInfo

import requests
from dynamic_imports import find_instances

from taskflows.alerts.components import Component, Map, Table, Text
from taskflows.alerts.utils import as_code_block
from taskflows.common import (
    config,
    load_service_files,
    logger,
    redact_sensitive,
    sort_service_names,
)
from taskflows.dashboard import Dashboard
from taskflows.db import get_servers
from taskflows.db import upsert_server as db_upsert_server
from taskflows.service import (
    Service,
    ServiceRegistry,
    _disable_service,
    _enable_service,
    _remove_service,
    _restart_service,
    _start_service,
    _stop_service,
    extract_service_name,
    get_schedule_info,
    get_unit_file_states,
    get_units,
    is_start_service,
    reload_unit_files,
    service_logs,
)
from taskflows.service import get_unit_files as _get_unit_files

from .security import create_hmac_headers, load_security_config, security_config
from .utils import get_public_ipv4, with_hostname

_API_RESPONSE_MAX_CHARS = 8000
_API_TRACEBACK_MAX_LINES = 40


def _deduplicate_services(services: Sequence[Service]) -> list[Service]:
    """Return one service per name, preserving last definition semantics."""
    services_by_name: dict[str | None, Service] = {}
    ordered_names: list[str | None] = []

    for service in services:
        if service.name not in services_by_name:
            ordered_names.append(service.name)
        services_by_name[service.name] = service

    duplicate_count = len(services) - len(ordered_names)
    if duplicate_count:
        logger.info(f"Skipped {duplicate_count} duplicate service definitions during create")

    return [services_by_name[name] for name in ordered_names]


async def get_unit_files(
    unit_type: Literal["service", "timer"] | None = None,
    match: str | None = None,
    states: str | Sequence[str] | None = None,
) -> list:
    """Get unit files excluding protected services.

    Args:
        unit_type: Filter by service or timer
        match: Glob pattern to match
        states: Unit states to filter by

    Returns:
        List of unit file paths
    """
    # don't alter internal services
    protected_units = {"taskflows-srv-api", "stop-taskflows-srv-api"}
    files = await _get_unit_files(unit_type=unit_type, match=match, states=states)
    kept = []
    for f in files:
        stem = Path(f).stem
        if stem not in protected_units:
            kept.append(f)
    return kept


def health_check(host: str | None = None) -> Text:
    """Call the /health endpoint and return a StatusIndicator component.

    Args:
        host (str): Host address of the admin API server. If None, calls local function.

    Returns:
        Text: Component showing health status
    """
    # Call via API
    data = call_api(host, "/health", method="GET", timeout=10)

    if "error" in data:
        return Text(f"🔴 Service Error: {data['error']}")
    elif data.get("status") == "ok":
        return Text("🟢 Service Healthy")
    else:
        return Text("🔴 Service Unhealthy")


async def list_servers() -> Table:
    """list servers.

    Args:
        host (str): Host address of the admin API server. If None, calls local function.

    Returns:
        Table: Table showing registered servers
    """
    # Call local free function - now uses JSON file
    servers = get_servers()
    # Convert to expected format with 'address' field
    return [{"address": f"{s['public_ipv4']}:7777", "hostname": s["hostname"]} for s in servers]


async def list_services(
    host: str | None = None, match: str | None = None, as_json: bool = False
) -> Table:
    """Call the /list endpoint and return a Table component.

    Args:
        host (str): Host address of the admin API server. If None, calls local function.
        match (str): Optional pattern to filter services
        as_json (bool): Return raw JSON data instead of Table component

    Returns:
        Table: Table showing available services
    """
    if host is None:
        # Call local free function
        logger.info(f"list_services called with match={match}")
        files = await get_unit_files(match=match, unit_type="service")
        srv_names = list({extract_service_name(f) for f in files})
        srv_names = sort_service_names(srv_names)
        logger.debug(f"list_services found {len(srv_names)} services")
        data = with_hostname({"services": srv_names})
    else:
        # Call via API
        params = {}
        if match:
            params["match"] = match
        data = await asyncio.to_thread(
            call_api, host, "/list", method="GET", params=params, timeout=10
        )

    if as_json:
        return data

    if "error" in data:
        return Table([{"Error": data["error"]}], title="Service List - Error")

    services = data.get("services", [])
    title = "Available Services"
    if match:
        title += f" - Matching '{match}'"

    if not services:
        return Table([], title=f"{title} (None)")

    # Convert list of service names to table rows
    service_rows = [{"Service": service} for service in services]
    return Table(service_rows, title=f"{title} ({len(services)})")


async def next_runs(
    host: str | None = None,
    match: str | None = None,
    iterations: int = 5,
    as_json: bool = False,
) -> Table:
    """Show the upcoming activation times for scheduled (timer) services.

    Calendar schedules are expanded with systemd-analyze; periodic
    (boot/interval) timers report the next elapse systemd has computed.
    Times are rendered in the configured display timezone.

    Args:
        host: Host address of the admin API server. If None, runs locally.
        match: Optional pattern to filter services.
        iterations: How many upcoming runs to show per calendar schedule.
        as_json: Return raw JSON data instead of a Table component.
    """
    if host is None:
        from taskflows.schedule import analyze_calendar_spec

        tz = ZoneInfo(config.display_timezone)
        files = await get_unit_files(match=match, unit_type="timer")
        services: dict[str, list[str]] = {}
        for f in files:
            srv_name = extract_service_name(f)
            try:
                content = Path(f).read_text()
            except OSError as err:
                services[srv_name] = [f"error reading timer: {err}"]
                continue
            specs = [
                line.split("=", 1)[1].strip()
                for line in content.splitlines()
                if line.startswith("OnCalendar=")
            ]
            runs: list[str] = []
            for spec in specs:
                try:
                    runs.extend(
                        analyze_calendar_spec(
                            spec, iterations=iterations, timezone=config.display_timezone
                        )
                    )
                except ValueError as err:
                    runs.append(str(err))
            if not specs:
                # Periodic (OnBootSec/OnUnitActiveSec) timer: use systemd's own next elapse
                info = await get_schedule_info(Path(f).name)
                raw = info.get("Next Start")
                if isinstance(raw, datetime):
                    next_dt = raw.astimezone(tz)
                    runs.append(next_dt.strftime("%a %Y-%m-%d %H:%M:%S %Z"))
                else:
                    runs.append("no scheduled elapse (periodic timer not active)")
            services[srv_name] = runs
        data = with_hostname({"next_runs": services})
    else:
        params = {"iterations": iterations}
        if match:
            params["match"] = match
        data = await asyncio.to_thread(
            call_api, host, "/next", method="GET", params=params, timeout=30
        )

    if as_json:
        return data

    if "error" in data:
        return Table([{"Error": data["error"]}], title="Next Runs - Error")

    rows = [
        {"Service": srv, "Next Runs": "\n".join(runs) if runs else "-"}
        for srv, runs in sorted(data.get("next_runs", {}).items())
    ]
    title = "Upcoming Runs"
    if match:
        title += f" - Matching '{match}'"
    if not rows:
        return Table([], title=f"{title} (None)")
    return Table(rows, title=f"{title} ({len(rows)})")


async def status(
    host: str | None = None,
    match: str | None = None,
    running: bool = False,
    all: bool = False,
    details: bool = False,
    as_json: bool = False,
) -> Table:
    """Call the /status endpoint and return a Table component.

    Args:
        host (str): Host address of the admin API server. If None, calls local function.
        match (str): Optional pattern to filter services
        running (bool): Only show running services
        all (bool): Show all services including stop-* and restart-* services
        details (bool): Include per-unit timing and timer properties

    Returns:
        Table: Table showing service status
    """
    if host is None:
        logger.info(f"status called with match={match}, running={running}")
        COLOR_EMOJI = {"green": "🟢", "yellow": "🟡", "red": "🔴", "orange1": "🟠"}

        COLUMN_COLORS = {
            "Service\nEnabled": {
                "enabled": "green",
                "enabled-runtime": "yellow",
                "disabled": "red",
            },
            "Timer\nEnabled": {
                "enabled": "green",
                "enabled-runtime": "yellow",
                "disabled": "red",
            },
            "load_state": {
                "loaded": "green",
                "merged": "yellow",
                "stub": "yellow",
                "error": "red",
                "not-found": "red",
                "bad-setting": "red",
                "masked": "red",
            },
            "active_state": {
                "active": "green",
                "activating": "yellow",
                "deactivating": "yellow",
                "inactive": "yellow",
                "failed": "red",
                "reloading": "yellow",
            },
            "sub_state": {
                "running": "green",
                "exited": "green",
                "waiting": "yellow",
                "start-pre": "green",
                "start": "green",
                "start-post": "green",
                "reloading": "yellow",
                "stop": "yellow",
                "stop-sigterm": "yellow",
                "stop-sigkill": "yellow",
                "stop-post": "yellow",
                "failed": "red",
                "auto-restart": "orange1",
                "dead": "yellow",
            },
        }

        COLUMNS = [
            "Service",
            "description",
            "Service\nEnabled",
            "Timer\nEnabled",
            "load_state",
            "active_state",
            "sub_state",
        ]
        if details:
            COLUMNS.extend(["Last Start", "Uptime", "Last Finish", "Next Start", "Timers"])

        # Gather service states
        # One systemd file-state scan supplies both service and timer states.
        # ListUnitFilesByPatterns is comparatively expensive on large user
        # configurations, so avoid running it twice.
        all_unit_states = await get_unit_file_states(match=match)
        srv_states = {
            path: state for path, state in all_unit_states.items() if path.endswith(".service")
        }
        if not srv_states:
            data = with_hostname({"status": []})
        else:
            # Build unit metadata from the two bulk unit-file queries.
            units_meta = defaultdict(dict)

            for file_path, enabled_status in srv_states.items():
                stem = Path(file_path).stem
                units_meta[stem]["Service\nEnabled"] = enabled_status

            for file_path, enabled_status in all_unit_states.items():
                if not file_path.endswith(".timer"):
                    continue
                units_meta[Path(file_path).stem]["Timer\nEnabled"] = enabled_status

            if details:
                # Load and inspect units concurrently. get_schedule_info loads
                # both the service and timer, so the old preliminary LoadUnit
                # loop was duplicate work. Keep concurrency bounded.
                semaphore = asyncio.Semaphore(32)

                async def schedule_info(unit_name: str):
                    async with semaphore:
                        return unit_name, await get_schedule_info(unit_name)

                detail_rows = await asyncio.gather(
                    *(schedule_info(unit_name) for unit_name in units_meta)
                )
                for unit_name, detail in detail_rows:
                    units_meta[unit_name].update(detail)

            # The default summary is a single bulk runtime-state operation.
            # In detail mode all installed units were loaded above first.
            for unit in await get_units(unit_type="service", match=match, states=None):
                units_meta[Path(unit["unit_name"]).stem].update(unit)

            # Add public service names.
            for unit_name, unit_data in units_meta.items():
                unit_data["Service"] = extract_service_name(unit_name)
                unit_data.setdefault("load_state", "not-loaded")
                unit_data.setdefault("active_state", "inactive")
                unit_data.setdefault("sub_state", "dead")

            # Filter out not-found units
            units_meta = {k: v for k, v in units_meta.items() if v.get("load_state") != "not-found"}

            # Process rows
            srv_data = {row["Service"]: row for row in units_meta.values()}
            result = []

            for srv_name in sort_service_names(srv_data.keys()):
                row = srv_data[srv_name]

                # Apply running filter
                if running and row.get("active_state") != "active":
                    continue

                # Filter out stop-* and restart-* services unless all flag is set
                if not all and srv_name.startswith(("stop-", "restart-")):
                    continue

                if details:
                    timers = [
                        f"{t['base']}({t['spec']})" for t in row.get("Timers Calendar", [])
                    ] + [f"{t['base']}({t['offset']})" for t in row.get("Timers Monotonic", [])]
                    row["Timers"] = "\n".join(timers) or "-"

                # Calculate uptime
                if row.get("active_state") == "active" and (last_start := row.get("Last Start")):
                    row["Uptime"] = str(datetime.now(last_start.tzinfo) - last_start).split(".")[0]

                # Format datetime columns
                tz = ZoneInfo(config.display_timezone)
                for dt_col in ("Last Start", "Last Finish", "Next Start"):
                    if isinstance(row.get(dt_col), datetime):
                        row[dt_col] = row[dt_col].astimezone(tz).strftime("%Y-%m-%d %I:%M:%S %p")

                # Build output row with emoji prefixes
                output_row = {}
                for col in COLUMNS:
                    val = str(row.get(col, "-"))

                    # Add color emoji if mapping exists
                    if col in COLUMN_COLORS:
                        color = COLUMN_COLORS[col].get(val)
                        if color and color in COLOR_EMOJI:
                            val = f"{COLOR_EMOJI[color]} {val}"

                    output_row[col] = val

                result.append(output_row)
            logger.debug(f"status returning {len(result)} rows")
            data = with_hostname({"status": result})

    else:
        # Call via API
        params = {"running": running, "all": all, "details": details}
        if match:
            params["match"] = match
        data = await asyncio.to_thread(
            call_api, host, "/status", method="GET", params=params, timeout=10
        )
    if as_json:
        return data
    if "error" in data:
        return Table([{"Error": data["error"]}], title="Service Status - Error")

    if isinstance(data, dict) and data.get("status_code") == 401:
        return Table([], title="Service Status - Unauthorized (check HMAC config)")
    status_data = data.get("status", [])
    title = "Service Status"
    if match:
        title += f" - Matching '{match}'"
    if running:
        title += " (Running Only)"
    if not status_data:
        return Table([], title=f"{title} (None)")

    return Table(status_data, title=title)


async def logs(
    host: str | None = None,
    service_name: str | None = None,
    n_lines: int | None = None,
    as_json: bool = False,
) -> Text:
    """Call the /logs/{service_name} endpoint and return a CodeBlock component.

    Args:
        host (str): Host address of the admin API server. If None, calls local function.
        service_name (str): Name of the service to get logs for
        n_lines (int): Number of log lines to return.
        as_json (bool): Return raw JSON data instead of CodeBlock component

    Returns:
        Text: Component showing service logs
    """
    if not service_name:
        if as_json:
            return {"error": "service_name is required"}
        return Text(as_code_block("Error: service_name is required"))

    if host is None:
        # Call local free function
        logger.info(f"logs called for service_name={service_name}, n_lines={n_lines}")
        data = with_hostname(
            {"logs": await asyncio.to_thread(service_logs, service_name, n_lines or 1000)}
        )
    else:
        # Call via API
        params = {"n_lines": n_lines} if n_lines else {}
        data = await asyncio.to_thread(
            call_api,
            host,
            f"/logs/{service_name}",
            method="GET",
            timeout=30,
            params=params,
        )

    if as_json:
        return data

    if "error" in data:
        return Text(as_code_block(f"Error fetching logs: {data['error']}"))

    logs_content = data.get("logs", "No logs available")
    return Text(as_code_block(logs_content))


async def show(host: str | None = None, match: str | None = None, as_json: bool = False) -> Table:
    """Call the /show/{match} endpoint and return a Table component.

    Args:
        host (str): Host address of the admin API server. If None, calls local function.
        match (str): Name or pattern of services to show
        as_json (bool): Return raw JSON data instead of Table component

    Returns:
        Table: Table showing service file contents
    """
    if not match:
        if as_json:
            return {"error": "match parameter is required"}
        return Table([{"Error": "match parameter is required"}], title="Service Files - Error")

    if host is None:
        # Call local free function
        logger.info(f"show called with match={match}")
        files = await get_unit_files(match=match)
        logger.debug(f"show returned files for {match}")
        data = with_hostname({"files": load_service_files(files)})
    else:
        # Call via API
        data = await asyncio.to_thread(call_api, host, f"/show/{match}", method="GET", timeout=30)

    if as_json:
        return data

    if "error" in data:
        return Table([{"Error": data["error"]}], title=f"Service Files for '{match}' - Error")

    files_data = data.get("files", {})
    if not files_data:
        return Table([], title=f"Service Files for '{match}' (None)")

    # Flatten the file data for table display
    rows = []
    for service_name, files in files_data.items():
        for file_info in files:
            rows.append(
                {
                    "Service": service_name,
                    "File": file_info.get("name", ""),
                    "Path": file_info.get("path", ""),
                    "Content": file_info.get("content", ""),
                }
            )

    return Table(rows, title=f"Service Files for '{match}' ({len(rows)} files)")


async def create(
    host: str | None = None,
    match: str | None = None,
    search_in: str | None = None,
    yaml_file: str | None = None,
    include: str | None = None,
    exclude: str | None = None,
    as_json: bool = False,
) -> Table:
    """Call the /create endpoint and return a Table component.

    Args:
        host (str): Host address of the admin API server. If None, calls local function.
        match (str): Alternative name for search_in (from command)
        search_in (str): Directory to search for services
        yaml_file (str): Path to a YAML file containing service definitions
        include (str): Pattern to include services
        exclude (str): Pattern to exclude services

    Returns:
        Table: Component showing created services and dashboards
    """
    # Handle match as search_in for compatibility
    if match and not search_in:
        search_in = match

    if not search_in and not yaml_file:
        return Table(
            [{"Error": "Either search_in or yaml_file parameter is required"}],
            title="Create - Error",
        )

    if host is None:
        # Call local free function
        logger.info(
            f"create called with search_in={search_in}, yaml_file={yaml_file}, include={include}, exclude={exclude}"
        )

        services = []
        dashboards = []

        if yaml_file:
            # Load services and dashboards from YAML file
            from taskflows.serialization import (
                load_dashboards_from_yaml,
                load_services_from_yaml,
            )

            try:
                services = load_services_from_yaml(yaml_file)
            except ValueError as exc:
                if "'services' key" not in str(exc):
                    raise
                services = []
            try:
                dashboards = load_dashboards_from_yaml(yaml_file)
            except ValueError as exc:
                if "'dashboards' key" not in str(exc):
                    raise
                dashboards = []
            logger.info(
                f"Loaded {len(services)} services and {len(dashboards)} dashboards from {yaml_file}"
            )
        else:
            # Search Python files for Service instances
            services = find_instances(class_type=Service, search_in=search_in)
            logger.info(f"Found {len(services)} services")

            for sr in find_instances(class_type=ServiceRegistry, search_in=search_in):
                logger.info(f"ServiceRegistry found with {len(sr.services)} services")
                services.extend(sr.services)

            dashboards = find_instances(class_type=Dashboard, search_in=search_in)
            logger.info(f"Found {len(dashboards)} dashboards")

        logger.info(f"Total services: {len(services)}")
        if include:
            services = [s for s in services if fnmatchcase(name=s.name, pat=include)]
            dashboards = [d for d in dashboards if fnmatchcase(name=d.title, pat=include)]

        if exclude:
            services = [s for s in services if not fnmatchcase(name=s.name, pat=exclude)]
            dashboards = [d for d in dashboards if not fnmatchcase(name=d.title, pat=exclude)]

        services = _deduplicate_services(services)

        for srv in services:
            await srv.create(defer_reload=True)
        for dashboard in dashboards:
            dashboard.create()
        await reload_unit_files()

        logger.info(f"create created {len(services)} services, {len(dashboards)} dashboards")
        result = with_hostname(
            {
                "services": [s.name for s in services],
                "dashboards": [d.title for d in dashboards],
            }
        )
    else:
        # Call via API
        data = {}
        if search_in:
            data["search_in"] = search_in
        if yaml_file:
            data["yaml_content"] = Path(yaml_file).read_text()
        if include:
            data["include"] = include
        if exclude:
            data["exclude"] = exclude
        result = await asyncio.to_thread(
            call_api, host, "/create", method="POST", json_data=data, timeout=30
        )

    if as_json:
        return result

    if "error" in result:
        return Table([{"Error": result["error"]}], title="Create - Error")

    services = result.get("services", [])
    dashboards = result.get("dashboards", [])
    rows = []
    for service in services:
        rows.append({"Type": "Service", "Name": service})
    for dashboard in dashboards:
        rows.append({"Type": "Dashboard", "Name": dashboard})

    return Table(rows, title=f"Created Items ({len(rows)})")


async def start(
    host: str | None = None,
    match: str | None = None,
    timers: bool = False,
    services: bool = False,
    as_json: bool = False,
) -> Table:
    """Call the /start endpoint and return a Table component.

    Args:
        host (str): Host address of the admin API server. If None, calls local function.
        match (str): Pattern to match services/timers
        timers (bool): Whether to start timers
        services (bool): Whether to start services

    Returns:
        Table: Component showing started items
    """
    if not match:
        if as_json:
            return {"error": "match parameter is required"}
        return Table([{"Error": "match parameter is required"}], title="Start - Error")

    if host is None:
        # Call local free function
        logger.info(f"start called with match={match}, timers={timers}, services={services}")
        if (services and timers) or (not services and not timers):
            unit_type = None
        elif services:
            unit_type = "service"
        elif timers:
            unit_type = "timer"
        files = await get_unit_files(match=match, unit_type=unit_type)
        # Filter out stop-* and restart-* auxiliary units
        files = [f for f in files if is_start_service(f)]
        await _start_service(files)
        logger.info(f"start started {len(files)} units")
        result = with_hostname({"started": files})
    else:
        # Call via API
        data = {"match": match, "timers": timers, "services": services}
        result = await asyncio.to_thread(
            call_api, host, "/start", method="POST", json_data=data, timeout=30
        )

    if as_json:
        return result

    if "error" in result:
        return Table([{"Error": result["error"]}], title="Start - Error")

    started = result.get("started", [])
    rows = [{"Started": item} for item in started]
    return Table(rows, title=f"Started Items ({len(rows)})")


async def stop(
    host: str | None = None,
    match: str | None = None,
    timers: bool = False,
    services: bool = False,
    as_json: bool = False,
) -> Table:
    """Call the /stop endpoint and return a Table component.

    Args:
        host (str): Host address of the admin API server. If None, calls local function.
        match (str): Pattern to match services/timers
        timers (bool): Whether to stop timers
        services (bool): Whether to stop services

    Returns:
        Table: Component showing stopped items
    """
    if not match:
        if as_json:
            return {"error": "match parameter is required"}
        return Table([{"Error": "match parameter is required"}], title="Stop - Error")

    if host is None:
        # Call local free function
        logger.info(f"stop called with match={match}, timers={timers}, services={services}")
        if (services and timers) or (not services and not timers):
            unit_type = None
        elif services:
            unit_type = "service"
        elif timers:
            unit_type = "timer"
        files = await get_unit_files(match=match, unit_type=unit_type)
        await _stop_service(files)
        logger.info(f"stop stopped {len(files)} units")
        result = with_hostname({"stopped": files})
    else:
        # Call via API
        data = {"match": match, "timers": timers, "services": services}
        result = await asyncio.to_thread(
            call_api, host, "/stop", method="POST", json_data=data, timeout=30
        )

    if as_json:
        return result

    if "error" in result:
        return Table([{"Error": result["error"]}], title="Stop - Error")

    stopped = result.get("stopped", [])
    rows = [{"Stopped": item} for item in stopped]
    return Table(rows, title=f"Stopped Items ({len(rows)})")


async def restart(
    host: str | None = None, match: str | None = None, as_json: bool = False
) -> Table:
    """Call the /restart endpoint and return a Table component.

    Args:
        host (str): Host address of the admin API server. If None, calls local function.
        match (str): Pattern to match services

    Returns:
        Table: Component showing restarted items
    """
    if not match:
        if as_json:
            return {"error": "match parameter is required"}
        return Table([{"Error": "match parameter is required"}], title="Restart - Error")

    if host is None:
        # Call local free function
        files = await get_unit_files(match=match, unit_type="service")
        # Filter out stop-* and restart-* auxiliary services
        files = [f for f in files if is_start_service(f)]
        await _restart_service(files)
        result = with_hostname({"restarted": files})
    else:
        # Call via API
        data = {"match": match}
        result = await asyncio.to_thread(
            call_api, host, "/restart", method="POST", json_data=data, timeout=30
        )

    if as_json:
        return result

    if "error" in result:
        return Table([{"Error": result["error"]}], title="Restart - Error")

    restarted = result.get("restarted", [])
    rows = [{"Restarted": item} for item in restarted]
    return Table(rows, title=f"Restarted Items ({len(rows)})")


async def remove(host: str | None = None, match: str | None = None, as_json: bool = False) -> Table:
    """Call the /remove endpoint and return a Table component.

    Args:
        host (str): Host address of the admin API server. If None, calls local function.
        match (str): Pattern to match services

    Returns:
        Table: Component showing removed items
    """
    if not match:
        if as_json:
            return {"error": "match parameter is required"}
        return Table([{"Error": "match parameter is required"}], title="Remove - Error")

    if host is None:
        # Call local free function
        logger.info(f"remove called with match={match}")
        service_files = await get_unit_files(match=match, unit_type="service")
        timer_files = await get_unit_files(match=match, unit_type="timer")
        await _remove_service(
            service_files=service_files,
            timer_files=timer_files,
        )
        removed_names = [Path(f).name for f in service_files + timer_files]
        logger.info(f"remove removed {len(removed_names)} units")
        result = with_hostname({"removed": removed_names})
    else:
        # Call via API
        data = {"match": match}
        result = await asyncio.to_thread(
            call_api, host, "/remove", method="POST", json_data=data, timeout=30
        )

    if as_json:
        return result

    if "error" in result:
        return Table([{"Error": result["error"]}], title="Remove - Error")

    removed = result.get("removed", [])
    rows = [{"Removed": item} for item in removed]
    return Table(rows, title=f"Removed Items ({len(rows)})")


async def disable(
    host: str | None = None,
    match: str | None = None,
    timers: bool = False,
    services: bool = False,
    as_json: bool = False,
) -> Table:
    """Call the /disable endpoint and return a Table component.

    Args:
        host (str): Host address of the admin API server. If None, calls local function.
        match (str): Pattern to match services/timers
        timers (bool): Whether to disable timers
        services (bool): Whether to disable services

    Returns:
        Table: Component showing disabled items
    """
    if not match:
        if as_json:
            return {"error": "match parameter is required"}
        return Table([{"Error": "match parameter is required"}], title="Disable - Error")

    if host is None:
        # Call local free function
        logger.info(f"disable called with match={match}, timers={timers}, services={services}")
        if (services and timers) or (not services and not timers):
            unit_type = None
        elif services:
            unit_type = "service"
        elif timers:
            unit_type = "timer"
        files = await get_unit_files(match=match, unit_type=unit_type)
        await _disable_service(files)
        logger.info(f"disable disabled {len(files)} units")
        result = with_hostname({"disabled": files})
    else:
        # Call via API
        data = {"match": match, "timers": timers, "services": services}
        result = await asyncio.to_thread(
            call_api, host, "/disable", method="POST", json_data=data, timeout=30
        )

    if as_json:
        return result

    if "error" in result:
        return Table([{"Error": result["error"]}], title="Disable - Error")

    disabled = result.get("disabled", [])
    rows = [{"Disabled": item} for item in disabled]
    return Table(rows, title=f"Disabled Items ({len(rows)})")


async def enable(
    host: str | None = None,
    match: str | None = None,
    timers: bool = False,
    services: bool = False,
    as_json: bool = False,
) -> Table:
    """Call the /enable endpoint and return a Table component.

    Args:
        host (str): Host address of the admin API server. If None, calls local function.
        match (str): Pattern to match services/timers
        timers (bool): Whether to enable timers
        services (bool): Whether to enable services

    Returns:
        Table: Component showing enabled items
    """
    if not match:
        if as_json:
            return {"error": "match parameter is required"}
        return Table([{"Error": "match parameter is required"}], title="Enable - Error")

    if host is None:
        # Call local free function
        logger.info(f"enable called with match={match}, timers={timers}, services={services}")
        if (services and timers) or (not services and not timers):
            unit_type = None
        elif services:
            unit_type = "service"
        elif timers:
            unit_type = "timer"
        files = await get_unit_files(match=match, unit_type=unit_type)
        await _enable_service(files)
        logger.info(f"enable enabled {len(files)} units")
        result = with_hostname({"enabled": files})
    else:
        # Call via API
        data = {"match": match, "timers": timers, "services": services}
        result = await asyncio.to_thread(
            call_api, host, "/enable", method="POST", json_data=data, timeout=30
        )

    if as_json:
        return result

    if "error" in result:
        return Table([{"Error": result["error"]}], title="Enable - Error")

    enabled = result.get("enabled", [])
    rows = [{"Enabled": item} for item in enabled]
    return Table(rows, title=f"Enabled Items ({len(rows)})")


async def upsert_server(hostname: str | None = None, public_ipv4: str | None = None) -> None:
    """Upsert server information to JSON file.

    Args:
        hostname: Server hostname, defaults to current machine hostname
        public_ipv4: Server public IP, defaults to detected IP
    """
    if hostname is None:
        hostname = socket.gethostname()
    if public_ipv4 is None:
        public_ipv4 = get_public_ipv4()

    # Use the JSON-based server registry
    db_upsert_server(hostname=hostname, public_ipv4=public_ipv4)


async def execute_command_on_servers(command: str, servers=None, **kwargs) -> dict[str, Component]:
    """
    Execute a command on specified servers and return JSON responses.

    Args:
        command: The command to execute
        servers: Either a single server (str or dict) or list of servers to execute on.
                 Each server can be a string (host address) or dict with 'address' and optional 'alias'.
                 If None/empty, calls local functions directly.
        **kwargs: JSON parameters to forward to the API

    Returns:
        Dictionary mapping hostname to Component response.
        If all results are Tables, they will be concatenated with a Host column.
    """
    # Normalize servers argument
    if not servers:
        # None means local execution
        servers = [{"address": None}]
    elif isinstance(servers, str):
        servers = [{"address": servers}]
    elif isinstance(servers, dict):
        servers = [servers]
    elif isinstance(servers, (list, tuple)):
        normalized = []
        for s in servers:
            if isinstance(s, str):
                normalized.append({"address": s})
            elif isinstance(s, dict):
                normalized.append(s)
            else:
                raise ValueError(f"Invalid server entry type: {type(s)}")
        servers = normalized or [{"address": None}]
    else:
        raise ValueError(f"Invalid servers argument type: {type(servers)}")

    # Handle server management commands locally
    if command == "register-server":
        return {
            "localhost": Text(
                "Server registration is now automatic. "
                "Servers register themselves when the API starts."
            )
        }

    elif command == "list-servers":
        servers_list = await list_servers()
        if not servers_list:
            return {"localhost": Map({"servers": []})}
        return {"localhost": Map({"servers": servers_list})}

    elif command == "remove-server":
        return {
            "localhost": Text("Server removal is not supported. Servers are managed automatically.")
        }

    # Map commands to client functions
    command_map = {
        "health": health_check,
        "list": list_services,
        "next": next_runs,
        "status": status,
        "logs": logs,
        "show": show,
        "create": create,
        "start": start,
        "stop": stop,
        "restart": restart,
        "enable": enable,
        "disable": disable,
        "remove": remove,
    }
    if command not in command_map:
        return {"localhost": Text(f"Unknown command: {command}")}

    func = command_map[command]

    async def invoke(server):
        hostname = server["address"] or "localhost"
        if inspect.iscoroutinefunction(func):
            result = await func(host=server["address"], **kwargs)
        else:
            result = await asyncio.to_thread(func, host=server["address"], **kwargs)
        return hostname, result

    # Hosts are independent. Querying them serially made total latency grow
    # linearly with server count even when each backend was responsive.
    pairs = await asyncio.gather(*(invoke(server) for server in servers))
    results = dict(pairs)

    # If all results are Tables, concatenate them with Host column
    if len(results) > 0 and all(isinstance(r, Table) for r in results.values()):
        combined_rows = []
        combined_title = None

        for hostname, table in results.items():
            # Extract title from first table
            if combined_title is None and table.title:
                combined_title = (
                    table.title.value if hasattr(table.title, "value") else str(table.title)
                )

            # Add Host column to each row
            for row in table.rows:
                row_with_host = {"Host": hostname, **row}
                combined_rows.append(row_with_host)

        # Create combined table with Host as first column
        combined_table = Table(combined_rows, title=combined_title)
        # Return single result
        return {"_combined": combined_table}

    return results


def call_api(
    server,
    endpoint: str,
    method: str = "get",
    params=None,
    json_data=None,
    timeout: int = 10,
) -> dict:
    method = method.lower()
    if isinstance(server, dict):
        server = server["address"]
    if not server.startswith("http"):
        server = f"http://{server}"
    url = server.rstrip("/") + endpoint
    logger.info(
        f"{method.upper()} {url} params={redact_sensitive(params)} "
        f"json_data={redact_sensitive(json_data)}"
    )

    body = ""
    request_data = None
    if json_data is not None:
        body = json.dumps(json_data, separators=(",", ":"))
        request_data = body.encode("utf-8")

    parsed_endpoint = urlsplit(endpoint)
    endpoint_path = parsed_endpoint.path or "/"
    query_parts = [
        part for part in (parsed_endpoint.query, urlencode(params or {}, doseq=True)) if part
    ]
    query_string = "&".join(query_parts)

    def build_headers(cfg) -> dict[str, str]:
        headers: dict[str, str] = {}
        if endpoint != "/health" and cfg.enable_hmac and cfg.hmac_secret:
            try:
                headers.update(
                    create_hmac_headers(
                        cfg.hmac_secret,
                        body,
                        method=method.upper(),
                        path=endpoint_path,
                        query_string=query_string,
                    )
                )
                if json_data is not None:
                    headers["Content-Type"] = "application/json"
                logger.debug(f"HMAC headers added for {url}")
            except Exception as e:
                logger.error(f"Failed to create HMAC headers: {e}")
        return headers

    cfg = security_config  # initial reference
    headers = build_headers(cfg)

    for attempt in (1, 2):
        try:
            resp = requests.request(
                method.upper(),
                url,
                params=params,
                data=request_data,
                headers=headers,
                timeout=timeout,
            )
            logger.info(f"[{resp.status_code}] {url}")
            if resp.status_code == 401 and attempt == 1:
                # Reload security config and retry once (secret may have rotated)
                new_cfg = load_security_config()
                if new_cfg.hmac_secret != cfg.hmac_secret:
                    cfg = new_cfg
                    headers = build_headers(cfg)
                    logger.info(f"Retrying {url} after HMAC secret reload")
                    continue
            resp.raise_for_status()
            return resp.json()
        except requests.HTTPError as he:
            try:
                data = resp.json()
                if (
                    isinstance(data, dict)
                    and "traceback" in data
                    and isinstance(data["traceback"], str)
                ):
                    lines = data["traceback"].splitlines()
                    if len(lines) > _API_TRACEBACK_MAX_LINES:
                        data["traceback"] = (
                            "\n".join(lines[:_API_TRACEBACK_MAX_LINES])
                            + f"\n... truncated {len(lines) - _API_TRACEBACK_MAX_LINES} lines ..."
                        )
                text = json.dumps(data, indent=2, ensure_ascii=False)
                if len(text) > _API_RESPONSE_MAX_CHARS:
                    text = (
                        text[:_API_RESPONSE_MAX_CHARS]
                        + f"\n... truncated {len(text) - _API_RESPONSE_MAX_CHARS} chars ..."
                    )
            except Exception:
                text = resp.text or ""
                if len(text) > _API_RESPONSE_MAX_CHARS:
                    text = (
                        text[:_API_RESPONSE_MAX_CHARS]
                        + f"\n... truncated {len(text) - _API_RESPONSE_MAX_CHARS} chars ..."
                    )
            logger.error(
                "HTTPError status=%s url=%s error=%s\nResponse body:\n%s",
                getattr(resp, "status_code", None),
                url,
                he,
                text,
            )
            status_code = getattr(resp, "status_code", None) if "resp" in locals() else None
            return {
                "error": str(he),
                "status_code": status_code,
                "endpoint": endpoint,
                "response_body": text,
            }
        except Exception as e:
            logger.exception(f"{type(e)} Exception for {url}: {e}")
            return {"error": str(e), "endpoint": endpoint}
    return {"error": "Unknown error", "endpoint": endpoint}
