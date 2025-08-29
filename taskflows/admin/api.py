
import logging
import traceback
from contextlib import asynccontextmanager
from typing import Optional

import click
import uvicorn

# from dl.databases.timescale import pgconn
from fastapi import Body, FastAPI, Query, Request, status
from fastapi.responses import JSONResponse

from taskflows.admin.core import (
    create,
    disable,
    enable,
    list_servers,
    list_services,
    logs,
    remove,
    restart,
    show,
    start,
    status,
    stop,
    task_history,
    upsert_server,
    with_hostname,
)
from taskflows.admin.security import security_config, validate_hmac_request
from taskflows.common import Config, logger
from taskflows.service import RestartPolicy, Service, Venv

config = Config()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Services API FastAPI app startup")

    try:
        await upsert_server()
        logger.info("Server registered in database successfully")
    except Exception as e:
        logger.error(f"Failed to register server in database: {e}")

    yield
    # Shutdown (if needed)

app = FastAPI(title="Services Daemon API", lifespan=lifespan)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
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
async def health_check_endpoint():
    """Health check logic as a free function."""
    logger.info("health check called")
    return with_hostname({"status": "ok"})


@app.get("/list-servers")
async def list_servers_endpoint():
    return await list_servers(as_json=True)


@app.get("/history")
async def task_history_endpoint(
    limit: int = Query(3),
    match: Optional[str] = Query(None),
):
    return await task_history(limit=limit, match=match, as_json=True)


@app.get("/list")
async def list_services_endpoint(
    match: Optional[str] = Query(None),
):
    return await list_services(match=match, as_json=True)



@app.get("/status")
async def status_endpoint(
    match: Optional[str] = Query(None),
    running: bool = Query(False),
):
    return await status(match=match, running=running, as_json=True)



@app.get("/logs/{service_name}")
async def logs_endpoint(
    service_name: str,
    n_lines: int = Query(1000, description="Number of log lines to return"),
):
    return await logs(service_name=service_name, n_lines=n_lines, as_json=True)



@app.get("/show/{match}")
async def show_endpoint(
    match: str,
):
    return await show(match=match, as_json=True)



@app.post("/create")
async def create_endpoint(
    search_in: str = Body(..., embed=True),
    include: Optional[str] = Body(None, embed=True),
    exclude: Optional[str] = Body(None, embed=True),
):
    return await create(search_in=search_in, include=include, exclude=exclude, as_json=True)

@app.post("/start")
async def start_endpoint(
    match: str = Body(..., embed=True),
    timers: bool = Body(False, embed=True),
    services: bool = Body(False, embed=True),
):
    return await start(match=match, timers=timers, services=services, as_json=True)

@app.post("/stop")
async def stop_endpoint(
    match: str = Body(..., embed=True),
    timers: bool = Body(False, embed=True),
    services: bool = Body(False, embed=True),
):
    return await stop(match=match, timers=timers, services=services, as_json=True)


@app.post("/restart")
async def restart_endpoint(
    match: str = Body(..., embed=True),
):
    return await restart(match=match, as_json=True)


@app.post("/enable")
async def enable_endpoint(
    match: str = Body(..., embed=True),
    timers: bool = Body(False, embed=True),
    services: bool = Body(False, embed=True),
):
    return await enable(match=match, timers=timers, services=services, as_json=True)

@app.post("/disable")
async def disable_endpoint(
    match: str = Body(..., embed=True),
    timers: bool = Body(False, embed=True),
    services: bool = Body(False, embed=True),
):
    return await disable(match=match, timers=timers, services=services, as_json=True)

@app.post("/remove")
async def remove_endpoint(match: str = Body(..., embed=True)):
    return await remove(match=match, as_json=True)



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

