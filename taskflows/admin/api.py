import logging
import os
import socket
import traceback
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import datetime
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Literal, Optional, Sequence
from zoneinfo import ZoneInfo

import click
import sqlalchemy as sa
import uvicorn
# from dl.databases.timescale import pgconn
from dynamic_imports import class_inst
from fastapi import Body, FastAPI, Query, Request, status
from fastapi.responses import JSONResponse
from taskflows.admin.security import security_config, validate_hmac_request
from taskflows.common import (Config, load_service_files, logger,
                              sort_service_names)
from taskflows.dashboard import Dashboard
from taskflows.db import engine, get_tasks_db
from taskflows.service import (RestartPolicy, Service, ServiceRegistry, Venv,
                               _disable_service, _enable_service,
                               _remove_service, _restart_service,
                               _start_service, _stop_service,
                               extract_service_name, get_schedule_info,
                               get_unit_file_states)
from taskflows.service import get_unit_files as _get_unit_files
from taskflows.service import (get_units, reload_unit_files, service_logs,
                               systemd_manager)


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


@app.get("/health")
async def health_check():
    logger.info("/health endpoint called")
    return with_hostname({"status": "ok"})


@app.get("/list-servers")
async def api_list_servers():
    """List all registered services servers."""
    from taskflows.admin.common import list_servers

    servers = await list_servers()
    return with_hostname({"servers": servers, "count": len(servers)})


@app.get("/history")
async def api_history(
    limit: int = Query(3),
    match: Optional[str] = Query(None),
):
    """Get task run history data as JSON.

    This function retrieves the most recent task runs from the database
    and returns them as a list of dictionaries.

    Args:
        limit (int): Number of most recent task runs to show.
        match (str, optional): Only show history for task names matching this pattern.
                              Uses SQL LIKE pattern matching (% wildcards).

    Returns:
        List[dict]: List of task run records with formatted column names.
    """

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
    logger.debug(f"/history returned {len(rows)} rows")
    return with_hostname({"history": rows})


@app.get("/list")
async def api_list_services(
    match: Optional[str] = Query(None),
):
    logger.info(f"/list called with match={match}")
    files = get_unit_files(match=match, unit_type="service")
    srv_names = [extract_service_name(f) for f in files]
    srv_names = sort_service_names(srv_names)
    logger.debug(f"/list found {len(srv_names)} services")
    return with_hostname({"services": srv_names})


@app.get("/status")
async def api_status(
    match: Optional[str] = Query(None),
    running: bool = Query(False),
):
    logger.info(f"/status called with match={match}, running={running}")
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
    logger.debug(f"/status returning {len(result)} rows")
    return with_hostname({"status": result})


@app.get("/logs/{service_name}")
async def api_logs(
    service_name: str,
    n_lines: int = Query(1000, description="Number of log lines to return"),
):
    logger.info(f"/logs called for service_name={service_name}, n_lines={n_lines}")
    return with_hostname({"logs": service_logs(service_name, n_lines)})


@app.post("/create")
async def api_create(
    search_in: str = Body(..., embed=True),
    include: Optional[str] = Body(None, embed=True),
    exclude: Optional[str] = Body(None, embed=True),
):
    logger.info(
        f"/create called with search_in={search_in}, include={include}, exclude={exclude}"
    )
    # Now that deploy.py uses services, let's use the original approach
    services = class_inst(class_type=Service, search_in=search_in)
    print(f"Found {len(services)} services")

    for sr in class_inst(class_type=ServiceRegistry, search_in=search_in):
        print(f"ServiceRegistry found with {len(sr.services)} services")
        services.extend(sr.services)

    dashboards = class_inst(class_type=Dashboard, search_in=search_in)
    print(f"Found {len(dashboards)} dashboards")

    print(f"Total services: {len(services)}")
    if include:
        services = [s for s in services if fnmatchcase(name=s.name, pat=include)]
        dashboards = [d for d in dashboards if fnmatchcase(name=d.title, pat=include)]

    if exclude:
        services = [s for s in services if not fnmatchcase(name=s.name, pat=exclude)]
        dashboards = [
            d for d in dashboards if not fnmatchcase(name=d.title, pat=exclude)
        ]

    for srv in services:
        srv.create(defer_reload=True)
    for dashboard in dashboards:
        dashboard.create()
    reload_unit_files()

    logger.info(
        f"/create created {len(services)} services, {len(dashboards)} dashboards"
    )
    return with_hostname(
        {
            "services": [s.name for s in services],
            "dashboards": [d.title for d in dashboards],
        }
    )


@app.post("/start")
async def api_start(
    match: str = Body(..., embed=True),
    timers: bool = Body(False, embed=True),
    services: bool = Body(False, embed=True),
):
    logger.info(
        f"/start called with match={match}, timers={timers}, services={services}"
    )
    if (services and timers) or (not services and not timers):
        unit_type = None
    elif services:
        unit_type = "service"
    elif timers:
        unit_type = "timer"
    files = get_unit_files(match=match, unit_type=unit_type)
    _start_service(files)
    logger.info(f"/start started {len(files)} units")
    return with_hostname({"started": files})


@app.post("/stop")
async def api_stop(
    match: str = Body(..., embed=True),
    timers: bool = Body(False, embed=True),
    services: bool = Body(False, embed=True),
):
    logger.info(
        f"/stop called with match={match}, timers={timers}, services={services}"
    )
    if (services and timers) or (not services and not timers):
        unit_type = None
    elif services:
        unit_type = "service"
    elif timers:
        unit_type = "timer"
    files = get_unit_files(match=match, unit_type=unit_type)
    _stop_service(files)
    logger.info(f"/stop stopped {len(files)} units")
    return with_hostname({"stopped": files})


@app.post("/restart")
async def api_restart(
    match: str = Body(..., embed=True),
):
    logger.info(f"/restart called with match={match}")
    files = get_unit_files(match=match, unit_type="service")
    _restart_service(files)
    logger.info(f"/restart restarted {len(files)} units")
    return with_hostname({"restarted": files})


@app.post("/enable")
async def api_enable(
    match: str = Body(..., embed=True),
    timers: bool = Body(False, embed=True),
    services: bool = Body(False, embed=True),
):
    logger.info(
        f"/enable called with match={match}, timers={timers}, services={services}"
    )
    if (services and timers) or (not services and not timers):
        unit_type = None
    elif services:
        unit_type = "service"
    elif timers:
        unit_type = "timer"
    files = get_unit_files(match=match, unit_type=unit_type)
    _enable_service(files)
    logger.info(f"/enable enabled {len(files)} units")
    return with_hostname({"enabled": files})


@app.post("/disable")
async def api_disable(
    match: str = Body(..., embed=True),
    timers: bool = Body(False, embed=True),
    services: bool = Body(False, embed=True),
):
    logger.info(
        f"/disable called with match={match}, timers={timers}, services={services}"
    )
    if (services and timers) or (not services and not timers):
        unit_type = None
    elif services:
        unit_type = "service"
    elif timers:
        unit_type = "timer"
    files = get_unit_files(match=match, unit_type=unit_type)
    _disable_service(files)
    logger.info(f"/disable disabled {len(files)} units")
    return with_hostname({"disabled": files})

@app.post("/remove")
async def api_remove(match: str = Body(..., embed=True)):
    logger.info(f"/remove called with match={match}")
    service_files = get_unit_files(match=match, unit_type="service")
    timer_files = get_unit_files(match=match, unit_type="timer")
    _remove_service(
        service_files=service_files,
        timer_files=timer_files,
    )
    removed_names = [Path(f).name for f in service_files + timer_files]
    logger.info(f"/remove removed {len(removed_names)} units")
    return with_hostname({"removed": removed_names})


@app.get("/show/{match}")
async def api_show(
    match: str,
):
    logger.info(f"/show called with match={match}")
    files = get_unit_files(match=match)
    logger.debug(f"/show returned files for {match}")
    return with_hostname({"files": load_service_files(files)})


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
