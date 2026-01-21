import json
import socket
from collections import defaultdict
from datetime import datetime, timezone
from fnmatch import fnmatchcase
from functools import cache
from pathlib import Path
from typing import Dict, Literal, Optional, Sequence
from zoneinfo import ZoneInfo

import requests
from taskflows.alerts.components import Component, Map, Table, Text
from taskflows.alerts.utils import as_code_block

# from trading.databases.timescale import pgconn
from taskflows.dynamic_imports import find_instances
from fastapi import status

from taskflows.admin.security import security_config
from taskflows.common import config, load_service_files, logger, sort_service_names
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
)
from taskflows.service import get_unit_files as _get_unit_files
from taskflows.service import (
    get_units,
    is_start_service,
    reload_unit_files,
    service_logs,
    systemd_manager,
)

from .security import create_hmac_headers  # new import reuse
from .security import load_security_config, security_config

HOSTNAME = socket.gethostname()


def with_hostname(data: dict) -> dict:
    #logger.debug(f"with_hostname called: {data}")
    return {**data, "hostname": HOSTNAME}


async def get_unit_files(
    unit_type: Optional[Literal["service", "timer"]] = None,
    match: Optional[str] = None,
    states: Optional[str | Sequence[str]] = None,
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


def health_check(host: Optional[str] = None) -> Text:
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
    return [
        {"address": f"{s['public_ipv4']}:7777", "hostname": s["hostname"]}
        for s in servers
    ]


async def task_history(
    host: Optional[str] = None,
    limit: int = 3,
    match: Optional[str] = None,
    as_json: bool = False,
) -> Table:
    """DEPRECATED: Task history is now available via Loki log queries.

    This function previously queried the database for task run history.
    Use Grafana/Loki to query task logs instead:
    - Query: {service_name=~".*task_name.*"}
    - Filter by time range to see historical runs

    Args:
        host (str): Host address of the admin API server. If None, calls local function.
        limit (int): Number of recent task runs to show
        match (str): Optional pattern to filter task names

    Returns:
        Table: Table with deprecation message
    """
    grafana_url = config.grafana.rstrip("/")
    if not grafana_url.startswith("http"):
        grafana_url = f"http://{grafana_url}"

    message = (
        f"Task history is now available via Loki log queries. "
        f"Visit {grafana_url}/explore to query task logs using LogQL. "
        f"Example query: {{service_name=~\".*{match or 'your_task'}.*\"}}"
    )

    if as_json:
        return with_hostname({
            "history": [],
            "message": message,
            "grafana_url": f"{grafana_url}/explore",
        })

    return Table(
        [{"Info": message}],
        title="Task History - Use Loki"
    )


async def list_services(
    host: Optional[str] = None, match: Optional[str] = None, as_json: bool = False
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
        srv_names = [extract_service_name(f) for f in files]
        srv_names = sort_service_names(srv_names)
        logger.debug(f"list_services found {len(srv_names)} services")
        data = with_hostname({"services": srv_names})
    else:
        # Call via API
        params = {}
        if match:
            params["match"] = match
        data = call_api(host, "/list", method="GET", params=params, timeout=10)

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


async def status(
    host: Optional[str] = None,
    match: Optional[str] = None,
    running: bool = False,
    all: bool = False,
    as_json: bool = False,
) -> Table:
    """Call the /status endpoint and return a Table component.

    Args:
        host (str): Host address of the admin API server. If None, calls local function.
        match (str): Optional pattern to filter services
        running (bool): Only show running services
        all (bool): Show all services including stop-* and restart-* services

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
            "Last Start",
            "Uptime",
            "Last Finish",
            "Next Start",
            "Timers",
        ]

        # Gather service states
        srv_states = await get_unit_file_states(unit_type="service", match=match)
        if not srv_states:
            data = with_hostname({"status": []})
        else:
            # Build units metadata
            manager = await systemd_manager()
            units_meta = defaultdict(dict)

            # Process services and timers
            for file_path, enabled_status in srv_states.items():
                stem = Path(file_path).stem
                units_meta[stem]["Service\nEnabled"] = enabled_status
                await manager.call_load_unit(Path(file_path).name)

            for file_path, enabled_status in (await get_unit_file_states(
                unit_type="timer", match=match
            )).items():
                units_meta[Path(file_path).stem]["Timer\nEnabled"] = enabled_status

            # Add unit runtime data
            for unit in await get_units(unit_type="service", match=match, states=None):
                units_meta[Path(unit["unit_name"]).stem].update(unit)

            # Enrich with schedule info and service names
            for unit_name, unit_data in units_meta.items():
                unit_data.update(await get_schedule_info(unit_name))
                unit_data["Service"] = extract_service_name(unit_name)

            # Filter out not-found units
            units_meta = {
                k: v for k, v in units_meta.items() if v.get("load_state") != "not-found"
            }

            # Process rows
            srv_data = {row["Service"]: row for row in units_meta.values()}
            result = []

            for srv_name in sort_service_names(srv_data.keys()):
                row = srv_data[srv_name]

                # Apply running filter
                if running and row.get("active_state") != "active":
                    continue

                # Filter out stop-* and restart-* services unless all flag is set
                if not all and (srv_name.startswith("stop-") or srv_name.startswith("restart-")):
                    continue

                # Format timers
                timers = [
                    f"{t['base']}({t['spec']})" for t in row.get("Timers Calendar", [])
                ] + [f"{t['base']}({t['offset']})" for t in row.get("Timers Monotonic", [])]
                row["Timers"] = "\n".join(timers) or "-"

                # Calculate uptime
                if row.get("active_state") == "active" and (
                    last_start := row.get("Last Start")
                ):
                    row["Uptime"] = str(datetime.now() - last_start).split(".")[0]

                # Format datetime columns
                tz = ZoneInfo(config.display_timezone)
                for dt_col in ("Last Start", "Last Finish", "Next Start"):
                    if isinstance(row.get(dt_col), datetime):
                        row[dt_col] = (
                            row[dt_col].astimezone(tz).strftime("%Y-%m-%d %I:%M:%S %p")
                        )

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
        params = {"running": running, "all": all}
        if match:
            params["match"] = match
        data = call_api(host, "/status", method="GET", params=params, timeout=10)
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
    host: Optional[str] = None,
    service_name: Optional[str] = None,
    n_lines: Optional[int] = None,
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
        data = with_hostname({"logs": service_logs(service_name, n_lines or 1000)})
    else:
        # Call via API
        params = {"n_lines": n_lines} if n_lines else {}
        data = call_api(
            host, f"/logs/{service_name}", method="GET", timeout=30, params=params
        )

    if as_json:
        return data

    if "error" in data:
        return Text(as_code_block(f"Error fetching logs: {data['error']}"))

    logs_content = data.get("logs", "No logs available")
    return Text(as_code_block(logs_content))


async def show(
    host: Optional[str] = None, match: Optional[str] = None, as_json: bool = False
) -> Table:
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
        return Table(
            [{"Error": "match parameter is required"}], title="Service Files - Error"
        )

    if host is None:
        # Call local free function
        logger.info(f"show called with match={match}")
        files = await get_unit_files(match=match)
        logger.debug(f"show returned files for {match}")
        data = with_hostname({"files": load_service_files(files)})
    else:
        # Call via API
        data = call_api(host, f"/show/{match}", method="GET", timeout=30)

    if as_json:
        return data

    if "error" in data:
        return Table(
            [{"Error": data["error"]}], title=f"Service Files for '{match}' - Error"
        )

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
    host: Optional[str] = None,
    match: Optional[str] = None,
    search_in: Optional[str] = None,
    include: Optional[str] = None,
    exclude: Optional[str] = None,
    as_json: bool = False,
) -> Table:
    """Call the /create endpoint and return a Table component.

    Args:
        host (str): Host address of the admin API server. If None, calls local function.
        match (str): Alternative name for search_in (from command)
        search_in (str): Directory to search for services
        include (str): Pattern to include services
        exclude (str): Pattern to exclude services

    Returns:
        Table: Component showing created services and dashboards
    """
    # Handle match as search_in for compatibility
    if match and not search_in:
        search_in = match

    if not search_in:
        return Table(
            [{"Error": "search_in parameter is required"}], title="Create - Error"
        )

    if host is None:
        # Call local free function
        logger.info(
            f"create called with search_in={search_in}, include={include}, exclude={exclude}"
        )
        # Now that deploy.py uses services, let's use the original approach
        services = find_instances(class_type=Service, search_in=search_in)
        print(f"Found {len(services)} services")

        for sr in find_instances(class_type=ServiceRegistry, search_in=search_in):
            print(f"ServiceRegistry found with {len(sr.services)} services")
            services.extend(sr.services)

        dashboards = find_instances(class_type=Dashboard, search_in=search_in)
        print(f"Found {len(dashboards)} dashboards")

        print(f"Total services: {len(services)}")
        if include:
            services = [s for s in services if fnmatchcase(name=s.name, pat=include)]
            dashboards = [
                d for d in dashboards if fnmatchcase(name=d.title, pat=include)
            ]

        if exclude:
            services = [
                s for s in services if not fnmatchcase(name=s.name, pat=exclude)
            ]
            dashboards = [
                d for d in dashboards if not fnmatchcase(name=d.title, pat=exclude)
            ]

        for srv in services:
            await srv.create(defer_reload=True)
        for dashboard in dashboards:
            dashboard.create()
        await reload_unit_files()

        logger.info(
            f"create created {len(services)} services, {len(dashboards)} dashboards"
        )
        result = with_hostname(
            {
                "services": [s.name for s in services],
                "dashboards": [d.title for d in dashboards],
            }
        )
    else:
        # Call via API
        data = {"search_in": search_in}
        if include:
            data["include"] = include
        if exclude:
            data["exclude"] = exclude
        result = call_api(host, "/create", method="POST", json_data=data, timeout=30)

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
    host: Optional[str] = None,
    match: Optional[str] = None,
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
        logger.info(
            f"start called with match={match}, timers={timers}, services={services}"
        )
        if (services and timers) or (not services and not timers):
            unit_type = None
        elif services:
            unit_type = "service"
        elif timers:
            unit_type = "timer"
        files = await get_unit_files(match=match, unit_type=unit_type)
        await _start_service(files)
        logger.info(f"start started {len(files)} units")
        result = with_hostname({"started": files})
    else:
        # Call via API
        data = {"match": match, "timers": timers, "services": services}
        result = call_api(host, "/start", method="POST", json_data=data, timeout=30)

    if as_json:
        return result

    if "error" in result:
        return Table([{"Error": result["error"]}], title="Start - Error")

    started = result.get("started", [])
    rows = [{"Started": item} for item in started]
    return Table(rows, title=f"Started Items ({len(rows)})")


async def stop(
    host: Optional[str] = None,
    match: Optional[str] = None,
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
        logger.info(
            f"stop called with match={match}, timers={timers}, services={services}"
        )
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
        result = call_api(host, "/stop", method="POST", json_data=data, timeout=30)

    if as_json:
        return result

    if "error" in result:
        return Table([{"Error": result["error"]}], title="Stop - Error")

    stopped = result.get("stopped", [])
    rows = [{"Stopped": item} for item in stopped]
    return Table(rows, title=f"Stopped Items ({len(rows)})")


async def restart(
    host: Optional[str] = None, match: Optional[str] = None, as_json: bool = False
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
        return Table(
            [{"Error": "match parameter is required"}], title="Restart - Error"
        )

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
        result = call_api(host, "/restart", method="POST", json_data=data, timeout=30)

    if as_json:
        return result

    if "error" in result:
        return Table([{"Error": result["error"]}], title="Restart - Error")

    restarted = result.get("restarted", [])
    rows = [{"Restarted": item} for item in restarted]
    return Table(rows, title=f"Restarted Items ({len(rows)})")


async def remove(
    host: Optional[str] = None, match: Optional[str] = None, as_json: bool = False
) -> Table:
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
        result = call_api(host, "/remove", method="POST", json_data=data, timeout=30)

    if as_json:
        return result

    if "error" in result:
        return Table([{"Error": result["error"]}], title="Remove - Error")

    removed = result.get("removed", [])
    rows = [{"Removed": item} for item in removed]
    return Table(rows, title=f"Removed Items ({len(rows)})")


async def disable(
    host: Optional[str] = None,
    match: Optional[str] = None,
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
        return Table(
            [{"Error": "match parameter is required"}], title="Disable - Error"
        )

    if host is None:
        # Call local free function
        logger.info(
            f"disable called with match={match}, timers={timers}, services={services}"
        )
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
        result = call_api(host, "/disable", method="POST", json_data=data, timeout=30)

    if as_json:
        return result

    if "error" in result:
        return Table([{"Error": result["error"]}], title="Disable - Error")

    disabled = result.get("disabled", [])
    rows = [{"Disabled": item} for item in disabled]
    return Table(rows, title=f"Disabled Items ({len(rows)})")


async def enable(
    host: Optional[str] = None,
    match: Optional[str] = None,
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
        logger.info(
            f"enable called with match={match}, timers={timers}, services={services}"
        )
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
        result = call_api(host, "/enable", method="POST", json_data=data, timeout=30)

    if as_json:
        return result

    if "error" in result:
        return Table([{"Error": result["error"]}], title="Enable - Error")

    enabled = result.get("enabled", [])
    rows = [{"Enabled": item} for item in enabled]
    return Table(rows, title=f"Enabled Items ({len(rows)})")


@cache
def get_public_ipv4() -> Optional[str]:
    """Detect and cache the machine's public IPv4 address.

    Tries multiple external services and returns the first validated public IPv4.
    Cached for process lifetime; call get_public_ipv4.cache_clear() if refresh needed.
    """
    services = (
        "https://api.ipify.org",
        "https://ipv4.icanhazip.com",
        "https://checkip.amazonaws.com",
    )
    for url in services:
        try:
            resp = requests.get(url, timeout=5)
            if resp.status_code != 200:
                logger.debug(f"get_public_ipv4: Non-200 from {url}: {resp.status_code}")
                continue
            # Some services may return with newline; split to be safe
            candidate = resp.text.strip().split()[0]
            logger.debug(f"get_public_ipv4: Selected public IP {candidate} from {url}")
            return candidate
        except requests.RequestException as e:
            logger.debug(f"get_public_ipv4: Request error from {url}: {e}")
        except Exception as e:
            logger.debug(f"get_public_ipv4: Unexpected error from {url}: {e}")
    logger.warning("get_public_ipv4: Failed to determine public IPv4 address")
    return None


async def upsert_server(
    hostname: Optional[str] = None, public_ipv4: Optional[str] = None
) -> None:
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


async def execute_command_on_servers(
    command: str, servers=None, **kwargs
) -> Dict[str, Component]:
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
    elif isinstance(servers, list):
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
            "localhost": Text(
                "Server removal is not supported. " "Servers are managed automatically."
            )
        }

    # Map commands to client functions
    command_map = {
        "health": health_check,
        "history": task_history,
        "list": list_services,
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
    results = {}

    # Execute on specified servers
    for server in servers:
        hostname = server["address"] or "localhost"
        # pass hostname (normalized) directly as host parameter
        # If address is None, it will use local functions
        results[hostname] = await func(host=server["address"], **kwargs)

    # If all results are Tables, concatenate them with Host column
    if len(results) > 0 and all(isinstance(r, Table) for r in results.values()):
        combined_rows = []
        combined_title = None

        for hostname, table in results.items():
            # Extract title from first table
            if combined_title is None and table.title:
                combined_title = table.title.value if hasattr(table.title, 'value') else str(table.title)

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
    logger.info(f"{method.upper()} {url} params={params} json_data={json_data}")

    def build_headers(cfg) -> Dict[str, str]:
        headers: Dict[str, str] = {}
        body = ""
        if json_data is not None:
            body = json.dumps(json_data, separators=(",", ":"))
        if endpoint != "/health" and cfg.enable_hmac and cfg.hmac_secret:
            try:
                headers.update(create_hmac_headers(cfg.hmac_secret, body))
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
                json=json_data,
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
            # Cap total size in logs
            MAX_TOTAL = 8000
            MAX_TB_LINES = 40
            try:
                data = resp.json()
                if (
                    isinstance(data, dict)
                    and "traceback" in data
                    and isinstance(data["traceback"], str)
                ):
                    lines = data["traceback"].splitlines()
                    if len(lines) > MAX_TB_LINES:
                        data["traceback"] = (
                            "\n".join(lines[:MAX_TB_LINES])
                            + f"\n... truncated {len(lines) - MAX_TB_LINES} lines ..."
                        )
                text = json.dumps(data, indent=2, ensure_ascii=False)
                if len(text) > MAX_TOTAL:
                    text = (
                        text[:MAX_TOTAL]
                        + f"\n... truncated {len(text) - MAX_TOTAL} chars ..."
                    )
            except Exception:
                text = resp.text or ""
                if len(text) > MAX_TOTAL:
                    return (
                        text[:MAX_TOTAL]
                        + f"\n... truncated {len(text) - MAX_TOTAL} chars ..."
                    )
            logger.error(
                "HTTPError status=%s url=%s error=%s\nResponse body:\n%s",
                getattr(resp, "status_code", None),
                url,
                he,
                text,
            )
            status_code = (
                getattr(resp, "status_code", None) if "resp" in locals() else None
            )
            return {
                "error": str(he),
                "status_code": status_code,
                "endpoint": endpoint,
            }
        except Exception as e:
            logger.exception(f"{type(e)} Exception for {url}: {e}")
            return {"error": str(e), "endpoint": endpoint}
    return {"error": "Unknown error", "endpoint": endpoint}
