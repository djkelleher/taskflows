
import asyncio
import logging
import os
import socket
import traceback
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import datetime
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Dict, Literal, Optional, Sequence
from zoneinfo import ZoneInfo

import click
import sqlalchemy as sa
import uvicorn
from alert_msgs.components import CodeBlock, Map, MsgComp, StatusIndicator, Table, Text

# from dl.databases.timescale import pgconn
from dynamic_imports import class_inst
from fastapi import Body, FastAPI, Query, Request, status
from fastapi.responses import JSONResponse

from taskflows.admin.common import call_api, list_servers
from taskflows.admin.security import security_config, validate_hmac_request
from taskflows.common import Config, load_service_files, logger, sort_service_names
from taskflows.dashboard import Dashboard
from taskflows.db import engine, get_tasks_db
from taskflows.service import (
    RestartPolicy,
    Service,
    ServiceRegistry,
    Venv,
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
    reload_unit_files,
    service_logs,
    systemd_manager,
)


def get_unit_files(unit_type: Optional[Literal["service", "timer"]] = None,
    match: Optional[str] = None,
    states: Optional[str | Sequence[str]] = None
):
    # don't alter internal services
    protected_units = {"taskflows-srv-api", "stop-taskflows-srv-api"}
    files = _get_unit_files(unit_type=unit_type, match=match, states=states)
    kept = []
    for f in files:
        stem = Path(f).stem
        if stem not in protected_units:
            kept.append(f)
    return kept


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Services API FastAPI app startup")

    # Register this server in the database
    from taskflows.admin.common import upsert_server

    try:
        await upsert_server()
        logger.info("Server registered in database successfully")
    except Exception as e:
        logger.error(f"Failed to register server in database: {e}")

    yield
    # Shutdown (if needed)


app = FastAPI(title="Services Daemon API", lifespan=lifespan)
config = Config()


# Global exception handler to automatically include traceback for any unhandled errors

INCLUDE_TRACEBACKS = os.getenv("DL_API_INCLUDE_TRACEBACKS", "1") not in {"0", "false", "False"}

@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    tb = "" if not INCLUDE_TRACEBACKS else "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    logger.error(
        "Unhandled exception %s %s: %s%s", request.method, request.url.path, exc, f"\n{tb}" if tb else ""
    )
    payload = {
        "detail": str(exc),
        "error_type": type(exc).__name__,
        "path": request.url.path,
    }
    if tb:
        payload["traceback"] = tb
    # Reuse hostname wrapper for consistency
    return JSONResponse(status_code=500, content=with_hostname(payload))


# Add security headers middleware
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    if security_config.enable_security_headers:
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains"
        )
        response.headers["Content-Security-Policy"] = "default-src 'self'"
        logger.debug(f"Security headers added to response for {request.url.path}")
    return response


# Utility to get hostname
HOSTNAME = socket.gethostname()


def with_hostname(data: dict) -> dict:
    logger.debug(f"with_hostname called: {data}")
    return {**data, "hostname": HOSTNAME}


# HMAC validation middleware
@app.middleware("http")
async def hmac_validation(request: Request, call_next):
    """Validate HMAC headers unless disabled or health endpoint."""
    if not security_config.enable_hmac or request.url.path == "/health":
        logger.debug(f"HMAC skipped for {request.url.path}")
        return await call_next(request)

    secret = security_config.hmac_secret
    if not secret:
        logger.error("HMAC secret not configured")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "HMAC secret not configured"},
        )

    signature = request.headers.get(security_config.hmac_header)
    timestamp = request.headers.get(security_config.hmac_timestamp_header)
    if not signature or not timestamp:
        logger.warning(
            f"Missing HMAC headers for {request.url.path} from {request.client.host}"
        )
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"detail": "HMAC signature and timestamp required"},
        )

    body_str = ""
    if request.method in {"POST", "PUT", "DELETE"}:
        body_bytes = await request.body()
        body_str = body_bytes.decode("utf-8") if body_bytes else ""

        async def receive():
            return {"type": "http.request", "body": body_bytes}

        request._receive = receive  # allow downstream to re-read body

    is_valid, error_msg = validate_hmac_request(
        signature,
        timestamp,
        secret,
        body_str,
        security_config.hmac_window_seconds,
    )
    if not is_valid:
        logger.warning(
            f"Invalid HMAC from {request.client.host} on {request.url.path}: {error_msg}"
        )
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"detail": error_msg},
        )

    logger.debug(f"HMAC validated for {request.url.path} from {request.client.host}")
    return await call_next(request)



def health_check(host: Optional[str] = None) -> StatusIndicator:
    """Call the /health endpoint and return a StatusIndicator component.

    Args:
        host (str): Host address of the admin API server. If None, calls local function.

    Returns:
        StatusIndicator: Component showing health status
    """
    # Call via API
    data = call_api(host, "/health", method="GET", timeout=10)

    if "error" in data:
        return StatusIndicator(f"Service Error: {data['error']}", color="red")
    elif data.get("status") == "ok":
        return StatusIndicator("Service Healthy", color="green")
    else:
        return StatusIndicator("Service Unhealthy", color="red")

@app.get("/health")
async def health_check_endpoint():
    """Health check logic as a free function."""
    logger.info("health check called")
    return with_hostname({"status": "ok"})

async def list_servers(host: Optional[str] = None, as_json: bool = False) -> Table:
    """Call the /list-servers endpoint and return a Table component.

    Args:
        host (str): Host address of the admin API server. If None, calls local function.

    Returns:
        Table: Table showing registered servers
    """
    if host is None:
        # Call local free function
        data = await list_servers()
        data = with_hostname({"servers": data, "count": len(servers)})
    else:
        # Call via API
        data = call_api(host, "/list-servers", method="GET", timeout=10)

    if as_json:
        return data
    
    if "error" in data:
        return Table([{"Error": data["error"]}], title="Server List - Error")

    servers = data.get("servers", [])
    if not servers:
        return Table([], title="Registered Servers (None)")

    return Table(
        servers, title=f"Registered Servers ({data.get('count', len(servers))})"
    )


@app.get("/list-servers")
async def list_servers_endpoint():
    return await list_servers(as_json=True)


async def task_history(
    host: Optional[str] = None, limit: int = 3, match: Optional[str] = None, as_json: bool = False
) -> Table:
    """Call the /history endpoint and return a Table component.

    Args:
        host (str): Host address of the admin API server. If None, calls local function.
        limit (int): Number of recent task runs to show
        match (str): Optional pattern to filter task names

    Returns:
        Table: Table showing task run history
    """
    if host is None:
        db = await get_tasks_db()
        table = db.task_runs_table

        task_names_query = sa.select(table.c.task_name).distinct()

        if match:
            task_names_query = task_names_query.where(table.c.task_name.like(f"%{match}%"))

        query = (
            sa.select(table)
            .where(table.c.task_name.in_(task_names_query))
            .order_by(table.c.started.desc(), table.c.task_name)
        )

        if limit:
            query = query.limit(limit)

        # Execute query synchronously
        with engine.connect() as conn:
            result = conn.execute(query)
            rows = result.fetchall()
        columns = [c.name.replace("_", " ").title() for c in table.columns]

        rows = [dict(zip(columns, row)) for row in rows]
        if rows and all(row.get("Retries", 0) == 0 for row in rows):
            columns.remove("Retries")
            for row in rows:
                row.pop("Retries", None)
        logger.debug(f"history returned {len(rows)} rows")
        data = with_hostname({"history": rows})
    else:
        # Call via API
        params = {"limit": limit}
        if match:
            params["match"] = match
        data = call_api(host, "/history", method="GET", params=params, timeout=10)

    if as_json:
        return data
    
    if "error" in data:
        return Table([{"Error": data["error"]}], title="Task History - Error")

    history = data.get("history", [])
    title = f"Task History (Last {limit})"
    if match:
        title += f" - Matching '{match}'"

    if not history:
        return Table([], title=f"{title} (None)")

    return Table(history, title=title)


@app.get("/history")
async def task_history_endpoint(
    limit: int = Query(3),
    match: Optional[str] = Query(None),
):
    return await task_history(limit=limit, match=match, as_json=True)

def list_services(
    host: Optional[str] = None, match: Optional[str] = None
) -> Table:
    """Call the /list endpoint and return a Table component.

    Args:
        host (str): Host address of the admin API server. If None, calls local function.
        match (str): Optional pattern to filter services

    Returns:
        Table: Table showing available services
    """
    if host is None:
        # Call local free function
        logger.info(f"list_services called with match={match}")
        files = get_unit_files(match=match, unit_type="service")
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

@app.get("/list")
async def list_services_endpoint(
    match: Optional[str] = Query(None),
):
    return list_services(match=match)


def api_status(
    host: Optional[str] = None, match: Optional[str] = None, running: bool = False, as_json: bool = False
) -> Table:
    """Call the /status endpoint and return a Table component.

    Args:
        host (str): Host address of the admin API server. If None, calls local function.
        match (str): Optional pattern to filter services
        running (bool): Only show running services

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
            "load_state",
            "active_state",
            "sub_state",
            "Last Start",
            "Uptime",
            "Last Finish",
            "Next Start",
            "Timers",
            "Timer\nEnabled",
        ]

        # Gather service states
        srv_states = get_unit_file_states(unit_type="service", match=match)
        if not srv_states:
            return with_hostname({"status": []})

        # Build units metadata
        manager = systemd_manager()
        units_meta = defaultdict(dict)

        # Process services and timers
        for file_path, enabled_status in srv_states.items():
            stem = Path(file_path).stem
            units_meta[stem]["Service\nEnabled"] = enabled_status
            manager.LoadUnit(Path(file_path).name)

        for file_path, enabled_status in get_unit_file_states(
            unit_type="timer", match=match
        ).items():
            units_meta[Path(file_path).stem]["Timer\nEnabled"] = enabled_status

        # Add unit runtime data
        for unit in get_units(unit_type="service", match=match, states=None):
            units_meta[Path(unit["unit_name"]).stem].update(unit)

        # Enrich with schedule info and service names
        for unit_name, data in units_meta.items():
            data.update(get_schedule_info(unit_name))
            data["Service"] = extract_service_name(unit_name)

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
        params = {"running": running}
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


def api_logs(
    host: Optional[str] = None, service_name: Optional[str] = None, n_lines: Optional[int] = None
) -> CodeBlock:
    """Call the /logs/{service_name} endpoint and return a CodeBlock component.

    Args:
        host (str): Host address of the admin API server. If None, calls local function.
        service_name (str): Name of the service to get logs for
        n_lines (int): Number of log lines to return.

    Returns:
        CodeBlock: Component showing service logs
    """
    if not service_name:
        return CodeBlock("Error: service_name is required", language="text")

    if host is None:
        # Call local free function
        from taskflows.admin.api import free_logs
        data = free_logs(service_name=service_name, n_lines=n_lines or 1000)
    else:
        # Call via API
        params = {"n_lines": n_lines} if n_lines else {}
        data = call_api(host, f"/logs/{service_name}", method="GET", timeout=30, params=params)
    
    if "error" in data:
        return CodeBlock(f"Error fetching logs: {data['error']}", language="text")

    logs = data.get("logs", "No logs available")
    return CodeBlock(logs, language="text", show_line_numbers=False)


def api_show(host: Optional[str] = None, match: Optional[str] = None) -> Table:
    """Call the /show/{match} endpoint and return a Table component.

    Args:
        host (str): Host address of the admin API server. If None, calls local function.
        match (str): Name or pattern of services to show

    Returns:
        Table: Table showing service file contents
    """
    if not match:
        return Table(
            [{"Error": "match parameter is required"}], title="Service Files - Error"
        )

    if host is None:
        # Call local free function
        from taskflows.admin.api import free_show
        data = free_show(match=match)
    else:
        # Call via API
        data = call_api(host, f"/show/{match}", method="GET", timeout=30)
    
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


def api_create(
    host: Optional[str] = None,
    match: Optional[str] = None,
    search_in: Optional[str] = None,
    include: Optional[str] = None,
    exclude: Optional[str] = None,
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
        from taskflows.admin.api import free_create
        result = free_create(search_in=search_in, include=include, exclude=exclude)
    else:
        # Call via API
        data = {"search_in": search_in}
        if include:
            data["include"] = include
        if exclude:
            data["exclude"] = exclude
        result = call_api(host, "/create", method="POST", json_data=data, timeout=30)
    
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


def api_start(
    host: Optional[str] = None,
    match: Optional[str] = None,
    timers: bool = False,
    services: bool = False,
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
        return Table([{"Error": "match parameter is required"}], title="Start - Error")

    if host is None:
        # Call local free function
        from taskflows.admin.api import free_start
        result = free_start(match=match, timers=timers, services=services)
    else:
        # Call via API
        data = {"match": match, "timers": timers, "services": services}
        result = call_api(host, "/start", method="POST", json_data=data, timeout=30)
    
    if "error" in result:
        return Table([{"Error": result["error"]}], title="Start - Error")

    started = result.get("started", [])
    rows = [{"Started": item} for item in started]
    return Table(rows, title=f"Started Items ({len(rows)})")


def api_stop(
    host: Optional[str] = None,
    match: Optional[str] = None,
    timers: bool = False,
    services: bool = False,
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
        return Table([{"Error": "match parameter is required"}], title="Stop - Error")

    if host is None:
        # Call local free function
        from taskflows.admin.api import free_stop
        result = free_stop(match=match, timers=timers, services=services)
    else:
        # Call via API
        data = {"match": match, "timers": timers, "services": services}
        result = call_api(host, "/stop", method="POST", json_data=data, timeout=30)
    
    if "error" in result:
        return Table([{"Error": result["error"]}], title="Stop - Error")

    stopped = result.get("stopped", [])
    rows = [{"Stopped": item} for item in stopped]
    return Table(rows, title=f"Stopped Items ({len(rows)})")


def api_restart(host: Optional[str] = None, match: Optional[str] = None) -> Table:
    """Call the /restart endpoint and return a Table component.

    Args:
        host (str): Host address of the admin API server. If None, calls local function.
        match (str): Pattern to match services

    Returns:
        Table: Component showing restarted items
    """
    if not match:
        return Table(
            [{"Error": "match parameter is required"}], title="Restart - Error"
        )

    if host is None:
        # Call local free function
        from taskflows.admin.api import free_restart
        result = free_restart(match=match)
    else:
        # Call via API
        data = {"match": match}
        result = call_api(host, "/restart", method="POST", json_data=data, timeout=30)
    
    if "error" in result:
        return Table([{"Error": result["error"]}], title="Restart - Error")

    restarted = result.get("restarted", [])
    rows = [{"Restarted": item} for item in restarted]
    return Table(rows, title=f"Restarted Items ({len(rows)})")


def api_enable(
    host: Optional[str] = None,
    match: Optional[str] = None,
    timers: bool = False,
    services: bool = False,
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
        return Table([{"Error": "match parameter is required"}], title="Enable - Error")

    if host is None:
        # Call local free function
        from taskflows.admin.api import free_enable
        result = free_enable(match=match, timers=timers, services=services)
    else:
        # Call via API
        data = {"match": match, "timers": timers, "services": services}
        result = call_api(host, "/enable", method="POST", json_data=data, timeout=30)
    
    if "error" in result:
        return Table([{"Error": result["error"]}], title="Enable - Error")

    enabled = result.get("enabled", [])
    rows = [{"Enabled": item} for item in enabled]
    return Table(rows, title=f"Enabled Items ({len(rows)})")


def api_disable(
    host: Optional[str] = None,
    match: Optional[str] = None,
    timers: bool = False,
    services: bool = False,
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
        return Table(
            [{"Error": "match parameter is required"}], title="Disable - Error"
        )

    if host is None:
        # Call local free function
        from taskflows.admin.api import free_disable
        result = free_disable(match=match, timers=timers, services=services)
    else:
        # Call via API
        data = {"match": match, "timers": timers, "services": services}
        result = call_api(host, "/disable", method="POST", json_data=data, timeout=30)
    
    if "error" in result:
        return Table([{"Error": result["error"]}], title="Disable - Error")

    disabled = result.get("disabled", [])
    rows = [{"Disabled": item} for item in disabled]
    return Table(rows, title=f"Disabled Items ({len(rows)})")


def api_remove(host: Optional[str] = None, match: Optional[str] = None) -> Table:
    """Call the /remove endpoint and return a Table component.

    Args:
        host (str): Host address of the admin API server. If None, calls local function.
        match (str): Pattern to match services

    Returns:
        Table: Component showing removed items
    """
    if not match:
        return Table([{"Error": "match parameter is required"}], title="Remove - Error")

    if host is None:
        # Call local free function
        from taskflows.admin.api import free_remove
        result = free_remove(match=match)
    else:
        # Call via API
        data = {"match": match}
        result = call_api(host, "/remove", method="POST", json_data=data, timeout=30)
    
    if "error" in result:
        return Table([{"Error": result["error"]}], title="Remove - Error")

    removed = result.get("removed", [])
    rows = [{"Removed": item} for item in removed]
    return Table(rows, title=f"Removed Items ({len(rows)})")


action_commands = {"start", "stop", "restart", "enable", "disable", "remove"}
read_commands = {"history", "list", "status", "logs", "show"}


async def execute_command_on_servers(
    command: str, servers=None, **kwargs
) -> Dict[str, MsgComp]:
    """
    Execute a command on specified servers and return JSON responses.

    Args:
        command: The command to execute
        servers: Either a single server (str or dict) or list of servers to execute on.
                 Each server can be a string (host address) or dict with 'address' and optional 'alias'.
                 If None/empty, calls local functions directly.
        **kwargs: JSON parameters to forward to the API

    Returns:
        Dictionary mapping hostname to MsgComp response
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
        "health": api_health,
        "history": api_history,
        "list": api_list_services,
        "status": api_status,
        "logs": api_logs,
        "show": api_show,
        "create": api_create,
        "start": api_start,
        "stop": api_stop,
        "restart": api_restart,
        "enable": api_enable,
        "disable": api_disable,
        "remove": api_remove,
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
        results[hostname] = func(host=server["address"], **kwargs)

    return results




@click.command("start")
@click.option("--host", default="localhost", help="Host to bind the server to")
@click.option("--port", default=7777, help="Port to bind the server to")
@click.option(
    "--reload/--no-reload", default=True, help="Enable auto-reload on code changes"
)
def _start_api_cmd(host: str, port: int, reload: bool):
    """Start the Services API server. This installs as _start_srv_api command."""
    click.echo(
        click.style(f"Starting Services API api on {host}:{port}...", fg="green")
    )
    if reload:
        click.echo(click.style("Auto-reload enabled", fg="yellow"))
    # Also log to file so we can see something even if import path is wrong
    logger.info(f"Launching uvicorn on {host}:{port} reload={reload}")
    uvicorn.run("taskflows.admin.api:app", host=host, port=port, reload=reload)


srv_api = Service(
    name="srv-api",
    start_command="_start_srv_api",
    environment=Venv("trading"),
    restart_policy=RestartPolicy(
        condition="always",
        delay=10,
    ),
    enabled=True,
)


def start_api_srv():
    if not srv_api.exists:
        logging.info("Creating and starting srv-api service")
        srv_api.create()
    srv_api.start()
