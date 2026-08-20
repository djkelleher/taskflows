import asyncio
import os
import threading
import time
import traceback
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path
from typing import Any, Literal

import click

try:
    import uvicorn
except ImportError as e:
    raise ImportError(
        "The taskflows API server requires the 'server' extra: pip install 'taskflows[server]'"
    ) from e
from fastapi import (
    Body,
    FastAPI,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from taskflows.admin.core import (
    call_api,
    create,
    disable,
    enable,
    list_servers,
    list_services,
    logs,
    next_runs,
    remove,
    restart,
    show,
    start,
    stop,
    upsert_server,
)
from taskflows.admin.core import (
    status as service_status,
)
from taskflows.admin.grafana_proxy import router as grafana_router
from taskflows.admin.models import PortableSchedulePatch, PortableScheduleRequest
from taskflows.admin.security import (
    create_csrf_token_data,
    get_csrf_token_data,
    remove_csrf_token,
    security_config,
    store_csrf_token,
    validate_csrf_token,
    validate_hmac_request,
)
from taskflows.admin.utils import with_hostname
from taskflows.common import Config, logger
from taskflows.exceptions import RevisionConflict
from taskflows.middleware.prometheus_middleware import PrometheusMiddleware
from taskflows.scheduler.models import (
    RunHandle,
    ScheduledTask,
    ScheduleSpec,
    merge_environment,
    resolve_working_directory,
    schedule_preview,
)
from taskflows.scheduler.repository import SchedulerRepository
from taskflows.scheduler.runner import cancel_run, submit_now
from taskflows.scheduler.status import diagnose_scheduler, operate_scheduler, scheduler_status
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


app = FastAPI(
    title="Taskflows Services API",
    description="Service management, task scheduling, and monitoring",
    version="0.1.0",
    docs_url="/docs",  # Enable Swagger UI
    redoc_url="/redoc",  # Enable ReDoc
    openapi_url="/openapi.json",
    lifespan=lifespan,
)


# Check if UI is enabled via env var OR config file
def _is_ui_enabled() -> bool:
    """Check if UI is enabled via environment variable or config file."""
    if os.getenv("TASKFLOWS_ENABLE_UI"):
        return True
    try:
        from taskflows.admin.auth import load_ui_config

        ui_config = load_ui_config()
        return bool(ui_config.enabled and ui_config.jwt_secret)
    except Exception:
        return False


UI_ENABLED = _is_ui_enabled()
MAX_CREATE_YAML_BYTES = int(os.getenv("TASKFLOWS_MAX_CREATE_YAML_BYTES", str(2 * 1024 * 1024)))
MAX_CREATE_MULTIPART_OVERHEAD_BYTES = int(
    os.getenv("TASKFLOWS_MAX_CREATE_MULTIPART_OVERHEAD_BYTES", str(64 * 1024))
)
CREATE_REQUEST_PATHS = {"/create", "/api/create"}
LOGIN_RATE_LIMIT_ATTEMPTS = int(os.getenv("TASKFLOWS_LOGIN_RATE_LIMIT_ATTEMPTS", "5"))
LOGIN_RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("TASKFLOWS_LOGIN_RATE_LIMIT_WINDOW_SECONDS", "300"))
LOGIN_RATE_LIMIT_LOCKOUT_SECONDS = int(
    os.getenv("TASKFLOWS_LOGIN_RATE_LIMIT_LOCKOUT_SECONDS", "300")
)
_login_attempts: dict[str, list[float]] = {}
_login_attempts_lock = threading.Lock()

PUBLIC_PATHS = {"/health", "/docs", "/redoc", "/openapi.json"}
PUBLIC_PREFIXES = ("/assets/",)
AUTH_PREFIXES = ("/auth/",)
PUBLIC_AUTH_PATHS = {"/auth/login", "/auth/refresh"}
TOP_LEVEL_API_PATHS = {
    "/list-servers",
    "/next",
    "/list",
    "/status",
    "/create",
    "/start",
    "/stop",
    "/restart",
    "/enable",
    "/disable",
    "/remove",
}


def _is_public_path(path: str) -> bool:
    return path in PUBLIC_PATHS or any(path.startswith(prefix) for prefix in PUBLIC_PREFIXES)


def _is_ui_route(path: str) -> bool:
    """Return True for React SPA routes that are not service-management APIs."""
    if path.startswith(("/api/", "/grafana/")):
        return False
    if path == "/metrics":
        return False
    if path.startswith(AUTH_PREFIXES):
        return path in PUBLIC_AUTH_PATHS
    if _is_public_path(path):
        return True
    return UI_ENABLED and not (path in TOP_LEVEL_API_PATHS or path.startswith(("/logs/", "/show/")))


def _requires_api_auth(path: str) -> bool:
    if path in PUBLIC_AUTH_PATHS or _is_public_path(path):
        return False
    return not _is_ui_route(path)


def _validate_yaml_size(yaml_content: str) -> None:
    size = len(yaml_content.encode("utf-8"))
    if size > MAX_CREATE_YAML_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=(f"Service definition is too large. Limit is {MAX_CREATE_YAML_BYTES} bytes."),
        )


def _create_request_limit(path: str) -> int:
    if path == "/api/create":
        return MAX_CREATE_YAML_BYTES + MAX_CREATE_MULTIPART_OVERHEAD_BYTES
    return MAX_CREATE_YAML_BYTES


def _validate_declared_create_request_size(request: Request) -> JSONResponse | None:
    """Reject create requests before any middleware reads the body into memory."""
    if request.url.path not in CREATE_REQUEST_PATHS:
        return None

    content_length = request.headers.get("content-length")
    if not content_length:
        return JSONResponse(
            status_code=status.HTTP_411_LENGTH_REQUIRED,
            content={"detail": "Content-Length header is required for service-definition uploads"},
        )

    try:
        size = int(content_length)
    except ValueError:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"detail": "Invalid Content-Length header"},
        )

    if size < 0:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"detail": "Invalid Content-Length header"},
        )

    if size > _create_request_limit(request.url.path):
        return JSONResponse(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            content={
                "detail": (
                    f"Service definition is too large. Limit is {MAX_CREATE_YAML_BYTES} bytes."
                )
            },
        )
    return None


# Add CORS middleware if UI is enabled
if UI_ENABLED:
    logger.info("UI enabled, adding CORS middleware")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=security_config.allowed_origins,
        allow_credentials=True,
        allow_methods=security_config.allowed_methods,
        allow_headers=security_config.allowed_headers,
    )

app.add_middleware(PrometheusMiddleware)

# Register Grafana reverse proxy
app.include_router(grafana_router)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    logger.opt(exception=exc).error(f"Unhandled exception {request.method} {request.url.path}")

    debug_enabled = os.getenv("DEBUG", "").lower() in ("true", "1", "yes")
    payload = {"detail": "Internal server error", "path": request.url.path}
    if debug_enabled:
        payload.update(
            {
                "detail": str(exc),
                "error_type": type(exc).__name__,
            }
        )
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
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        if request.url.path.startswith("/grafana/"):
            # Allow embedding Grafana in iframes from same origin
            response.headers["Content-Security-Policy"] = "frame-ancestors 'self'"
        else:
            response.headers["X-Frame-Options"] = "DENY"
            response.headers["Content-Security-Policy"] = "default-src 'self'"
        logger.debug(f"Security headers added to response for {request.url.path}")
    return response


# HMAC validation middleware
@app.middleware("http")
async def hmac_validation(request: Request, call_next):
    """Validate HMAC/JWT headers for service-management endpoints."""
    if not security_config.enable_hmac or not _requires_api_auth(request.url.path):
        logger.debug(f"HMAC skipped for {request.url.path}")
        return await call_next(request)

    # When UI is enabled, accept JWT as alternative to HMAC for /api/ routes
    if UI_ENABLED:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            ui_config = load_ui_config()
            if ui_config.jwt_secret:
                username = verify_token(token, ui_config.jwt_secret, "access")
                if username:
                    logger.debug(f"JWT auth accepted for {request.url.path} (user: {username})")
                    request.state.user = username
                    return await call_next(request)
            # Invalid JWT
            logger.warning(f"Invalid JWT for {request.url.path}")
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"detail": "Invalid or expired token"},
            )
        if request.url.path.startswith(AUTH_PREFIXES):
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"detail": "JWT authentication required"},
            )
        # No Bearer token - if HMAC is not configured, require JWT
        if not security_config.hmac_secret:
            logger.warning(f"No auth provided for {request.url.path}")
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"detail": "Authentication required"},
            )

    secret = security_config.hmac_secret
    if not secret:
        logger.error("HMAC secret not configured")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "HMAC secret not configured"},
        )

    signature = request.headers.get(security_config.hmac_header)
    timestamp = request.headers.get(security_config.hmac_timestamp_header)
    nonce = request.headers.get(security_config.hmac_nonce_header)
    if not signature or not timestamp or not nonce:
        logger.warning(f"Missing HMAC headers for {request.url.path} from {request.client.host}")
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"detail": "HMAC signature, timestamp, and nonce required"},
        )

    body_str = ""
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        size_response = _validate_declared_create_request_size(request)
        if size_response is not None:
            return size_response

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
        method=request.method,
        path=request.url.path,
        query_string=str(request.url.query),
        nonce=nonce,
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


@app.middleware("http")
async def request_size_validation(request: Request, call_next):
    """Reject oversized service-definition uploads before reading bodies."""
    size_response = _validate_declared_create_request_size(request)
    if size_response is not None:
        return size_response
    return await call_next(request)


# JWT validation middleware (for UI routes)
@app.middleware("http")
async def jwt_validation(request: Request, call_next):
    """Validate JWT for UI routes (when UI is enabled)."""
    # Skip if UI is not enabled
    if not UI_ENABLED:
        return await call_next(request)

    # Skip JWT for:
    # 1. API endpoints (use HMAC)
    # 2. Auth endpoints (login, refresh)
    # 3. Static files and UI routes (React handles auth client-side)
    # 4. Health check
    #
    # For React SPA: All non-API routes serve index.html, React handles authentication
    if (
        request.url.path in PUBLIC_AUTH_PATHS
        or request.url.path.startswith("/assets/")
        or request.url.path == "/health"
        or _requires_api_auth(request.url.path)
    ):
        logger.debug(f"JWT skipped for {request.url.path}")
        return await call_next(request)

    # All other routes are UI routes - allow access, React will handle auth
    logger.debug(f"JWT skipped for UI route {request.url.path}")
    return await call_next(request)


# CSRF validation middleware (for UI routes)
@app.middleware("http")
async def csrf_validation(request: Request, call_next):
    """Validate CSRF token for state-changing operations (POST/PUT/DELETE/PATCH).

    Defense-in-depth measure against CSRF attacks. While JWT-in-header is already
    CSRF-resistant, this provides an additional security layer.
    """
    # Skip if UI is not enabled or CSRF is disabled
    if not UI_ENABLED or not security_config.enable_csrf:
        return await call_next(request)

    if (
        request.headers.get(security_config.hmac_header)
        and request.headers.get(security_config.hmac_timestamp_header)
        and request.headers.get(security_config.hmac_nonce_header)
    ):
        logger.debug(f"CSRF skipped for HMAC-authenticated request {request.url.path}")
        return await call_next(request)

    auth_header = request.headers.get("Authorization", "")
    if _requires_api_auth(request.url.path) and not auth_header.startswith("Bearer "):
        logger.debug(f"CSRF deferred to HMAC auth for {request.url.path}")
        return await call_next(request)

    # Skip CSRF for:
    # 1. Safe methods (GET, HEAD, OPTIONS)
    # 2. Auth endpoints (login, refresh - they're establishing the token)
    # 3. API endpoints using HMAC
    # 4. Static files
    # 5. Health check
    if (
        request.method in ["GET", "HEAD", "OPTIONS"]
        or request.url.path in ["/health", *PUBLIC_AUTH_PATHS]
        or request.url.path.startswith("/assets/")
        or _is_ui_route(request.url.path)
    ):
        logger.debug(f"CSRF skipped for {request.method} {request.url.path}")
        return await call_next(request)

    # Get username from request state, or validate Bearer token directly because
    # middleware order can run CSRF before the auth middleware.
    username = getattr(request.state, "user", None)
    if not username and auth_header.startswith("Bearer "):
        ui_config = load_ui_config()
        if ui_config.jwt_secret:
            username = verify_token(auth_header[7:], ui_config.jwt_secret, "access")
            if username:
                request.state.user = username
    if not username:
        logger.warning(f"CSRF check: No user in request state for {request.url.path}")
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"detail": "Authentication required"},
        )

    # Check for CSRF token in header
    csrf_token = request.headers.get(security_config.csrf_header)
    if not csrf_token:
        logger.warning(
            f"CSRF check failed: Missing token for user {username} on {request.url.path}"
        )
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={"detail": "CSRF token required"},
        )

    token_data = get_csrf_token_data(username, csrf_token)
    if not token_data:
        logger.warning(f"CSRF check failed: No stored token for user {username}")
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={"detail": "CSRF token expired or invalid"},
        )

    ui_config = load_ui_config()
    is_valid, error_msg = validate_csrf_token(
        csrf_token,
        username,
        token_data["expiry"],
        token_data["signature"],
        ui_config.jwt_secret,
    )

    if not is_valid:
        logger.warning(f"CSRF check failed for user {username} on {request.url.path}: {error_msg}")
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={"detail": error_msg or "Invalid CSRF token"},
        )

    logger.debug(f"CSRF validated for user {username} on {request.url.path}")
    return await call_next(request)


@app.get("/health", tags=["monitoring"])
async def health_check_endpoint():
    """Health check logic as a free function."""
    logger.info("health check called")
    return with_hostname({"status": "ok"})


@app.get("/metrics", include_in_schema=False)
async def metrics_endpoint():
    """Expose Prometheus metrics."""
    from fastapi.responses import Response
    from prometheus_client import generate_latest

    return Response(
        content=generate_latest(), media_type="text/plain; version=0.0.4; charset=utf-8"
    )


@app.get("/list-servers")
async def list_servers_endpoint():
    return await list_servers()


@app.get("/next")
async def next_runs_endpoint(
    match: str | None = Query(None),
    iterations: int = Query(5, ge=1, le=50),
):
    return await next_runs(match=match, iterations=iterations, as_json=True)


@app.get("/list")
async def list_services_endpoint(
    match: str | None = Query(None),
):
    return await list_services(match=match, as_json=True)


@app.get("/status")
async def status_endpoint(
    match: str | None = Query(None),
    running: bool = Query(False),
    all: bool = Query(False),
    details: bool = Query(False),
):
    return await service_status(
        match=match, running=running, all=all, details=details, as_json=True
    )


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
    search_in: str | None = Body(None, embed=True),
    yaml_content: str | None = Body(None, embed=True),
    include: str | None = Body(None, embed=True),
    exclude: str | None = Body(None, embed=True),
):
    import tempfile

    if search_in:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=("Remote Python service discovery is disabled. Submit yaml_content instead."),
        )
    if yaml_content:
        _validate_yaml_size(yaml_content)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            temp_path = f.name
        try:
            return await create(yaml_file=temp_path, include=include, exclude=exclude, as_json=True)
        finally:
            os.unlink(temp_path)
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


def _portable_task_data(task: ScheduledTask) -> dict[str, Any]:
    """Public schedule representation; deliberately excludes environment values."""
    return task.to_public_dict()


@app.get("/api/schedules")
async def list_portable_schedules(
    match: str | None = Query(None),
) -> dict[str, list[dict[str, Any]]]:
    tasks = await asyncio.to_thread(SchedulerRepository().list, match=match)
    return {"schedules": [_portable_task_data(task) for task in tasks]}


@app.get("/api/schedules/{identifier}")
async def get_portable_schedule(identifier: str) -> dict[str, Any]:
    try:
        task = await asyncio.to_thread(SchedulerRepository().resolve, identifier)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return _portable_task_data(task)


@app.get("/api/schedules/{identifier}/preview")
async def preview_portable_schedule(
    identifier: str,
    count: int = Query(5, ge=1, le=1000),
    from_time: str | None = Query(None, alias="from"),
) -> dict[str, Any]:
    """Preview occurrences with the same trigger implementation as the daemon."""
    try:
        task = await asyncio.to_thread(SchedulerRepository().resolve, identifier)
        return schedule_preview(task, after=from_time, count=count)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@app.post("/api/schedules", status_code=status.HTTP_201_CREATED)
async def create_portable_schedule(request: PortableScheduleRequest) -> dict[str, Any]:
    selected = sum(
        value is not None for value in (request.run_at, request.interval_seconds, request.cron)
    )
    if selected != 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="provide exactly one of run_at, interval_seconds, or cron",
        )
    if request.start_at is not None and request.interval_seconds is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="start_at can only be used with interval_seconds",
        )
    if request.expected_revision is not None and not request.replace_existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="expected_revision requires replace_existing=true",
        )
    if request.no_timeout and "timeout" in request.model_fields_set:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="no_timeout cannot be combined with timeout",
        )
    if request.timeout is None and not request.no_timeout:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="use no_timeout=true to create an unbounded command",
        )
    try:
        if request.run_at is not None:
            schedule = ScheduleSpec.once(request.run_at, timezone=request.timezone)
        elif request.interval_seconds is not None:
            schedule = ScheduleSpec.interval(
                request.interval_seconds,
                start_at=request.start_at,
                timezone=request.timezone,
            )
        else:
            schedule = ScheduleSpec.cron(request.cron or "", timezone=request.timezone)
        task = ScheduledTask.create(
            request.name,
            request.command,
            schedule,
            enabled=request.enabled,
            timeout=None if request.no_timeout else request.timeout,
            cwd=request.cwd,
            environment=request.environment,
            misfire_grace_time=request.misfire_grace_time,
            coalesce=request.coalesce,
            max_instances=request.max_instances,
        )
        saved = await asyncio.to_thread(
            SchedulerRepository().add,
            task,
            replace_existing=request.replace_existing,
            expected_revision=request.expected_revision,
        )
    except RevisionConflict as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except (TypeError, ValueError) as exc:
        code = (
            status.HTTP_409_CONFLICT
            if "already exists" in str(exc)
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(status_code=code, detail=str(exc)) from exc
    return _portable_task_data(saved)


@app.patch("/api/schedules/{identifier}")
async def patch_portable_schedule(
    identifier: str, request: PortableSchedulePatch
) -> dict[str, Any]:
    """Update selected fields without requiring secret environment values again."""

    repository = SchedulerRepository()
    try:
        current = await asyncio.to_thread(repository.resolve, identifier)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    fields = request.model_fields_set
    trigger_fields = fields & {"run_at", "interval_seconds", "cron"}
    try:
        if trigger_fields:
            selected = [
                ("date", request.run_at),
                ("interval", request.interval_seconds),
                ("cron", request.cron),
            ]
            chosen = [(kind, value) for kind, value in selected if value is not None]
            if len(chosen) != 1:
                raise ValueError("provide exactly one of run_at, interval_seconds, or cron")
            kind, value = chosen[0]
            timezone = (
                request.timezone if request.timezone is not None else current.schedule.timezone
            )
            if request.start_at is not None and kind != "interval":
                raise ValueError("start_at can only be used with an interval schedule")
            if kind == "date":
                schedule = ScheduleSpec.once(str(value), timezone=timezone)
            elif kind == "interval":
                schedule = ScheduleSpec.interval(
                    float(value), start_at=request.start_at, timezone=timezone
                ).with_stable_anchor()
            else:
                schedule = ScheduleSpec.cron(str(value), timezone=timezone)
        elif fields & {"timezone", "start_at"}:
            timezone = (
                request.timezone if request.timezone is not None else current.schedule.timezone
            )
            if current.schedule.kind == "date":
                if "start_at" in fields:
                    raise ValueError("start_at can only be used with an interval schedule")
                schedule = ScheduleSpec.once(str(current.schedule.value), timezone=timezone)
            elif current.schedule.kind == "interval":
                schedule = ScheduleSpec.interval(
                    float(current.schedule.value),
                    start_at=request.start_at
                    if "start_at" in fields
                    else current.schedule.start_at,
                    timezone=timezone,
                )
            else:
                if "start_at" in fields:
                    raise ValueError("start_at can only be used with an interval schedule")
                schedule = ScheduleSpec.cron(str(current.schedule.value), timezone=timezone)
        else:
            schedule = current.schedule

        environment = dict(current.environment)
        for name in request.remove_environment:
            for existing in tuple(environment):
                if existing.casefold() == name.casefold():
                    environment.pop(existing)
        if request.environment is not None:
            environment = merge_environment(environment, request.environment)

        timeout = current.timeout
        if request.no_timeout:
            if "timeout" in fields:
                raise ValueError("no_timeout cannot be combined with timeout")
            timeout = None
        elif "timeout" in fields:
            if request.timeout is None:
                raise ValueError("use no_timeout=true to create an unbounded command")
            timeout = request.timeout

        candidate = replace(
            current,
            name=request.name if request.name is not None else current.name,
            command=tuple(request.command) if request.command is not None else current.command,
            schedule=schedule,
            enabled=request.enabled if request.enabled is not None else current.enabled,
            timeout=timeout,
            cwd=resolve_working_directory(request.cwd) if "cwd" in fields else current.cwd,
            environment=environment,
            misfire_grace_time=request.misfire_grace_time
            if "misfire_grace_time" in fields
            else current.misfire_grace_time,
            coalesce=request.coalesce if request.coalesce is not None else current.coalesce,
            max_instances=request.max_instances
            if request.max_instances is not None
            else current.max_instances,
        )
        saved = await asyncio.to_thread(
            repository.update,
            current.id,
            candidate,
            expected_revision=request.expected_revision,
        )
    except RevisionConflict as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except (TypeError, ValueError) as exc:
        code = (
            status.HTTP_409_CONFLICT
            if "already exists" in str(exc)
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(status_code=code, detail=str(exc)) from exc
    return _portable_task_data(saved)


@app.patch("/api/schedules/{identifier}/enabled")
async def set_portable_schedule_enabled(
    identifier: str,
    enabled: bool = Body(..., embed=True),
    expected_revision: int | None = Body(None, embed=True, ge=1),
) -> dict[str, Any]:
    try:
        task = await asyncio.to_thread(
            SchedulerRepository().set_enabled,
            identifier,
            enabled,
            expected_revision=expected_revision,
        )
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except RevisionConflict as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _portable_task_data(task)


@app.delete("/api/schedules/{identifier}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_portable_schedule(
    identifier: str,
    expected_revision: int | None = Query(None, ge=1),
) -> None:
    try:
        await asyncio.to_thread(
            SchedulerRepository().delete,
            identifier,
            expected_revision=expected_revision,
        )
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except RevisionConflict as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@app.post("/api/schedules/{identifier}/run", status_code=status.HTTP_202_ACCEPTED)
async def run_portable_schedule(
    identifier: str,
    response: Response = None,  # type: ignore[assignment]
    wait: bool = Query(False),
    timeout: float = Query(60.0, gt=0, le=3600),
) -> dict[str, Any]:
    repository = SchedulerRepository()
    legacy_direct_call = response is None
    if legacy_direct_call:
        # Preserve the pre-handle Python-call contract. HTTP clients always
        # receive the durable RunHandle representation.
        wait = True
        timeout = 60.0
    else:
        response.status_code = status.HTTP_202_ACCEPTED
    try:
        handle = await asyncio.to_thread(submit_now, repository.database_path, identifier)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc)) from exc
    if wait:
        deadline = time.monotonic() + timeout
        while not handle.terminal and time.monotonic() < deadline:
            await asyncio.sleep(0.05)
            handle = await asyncio.to_thread(repository.get_run, handle.id)
        if not handle.terminal:
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail="run is still active"
            )
        if response is not None:
            response.status_code = status.HTTP_200_OK
    if legacy_direct_call:
        return {"exit_code": handle.exit_code}
    return handle.to_dict()


@app.get("/api/schedule-runs")
async def portable_schedule_history(
    identifier: str | None = Query(None), limit: int = Query(100, ge=1, le=10000)
) -> dict[str, list[dict[str, Any]]]:
    try:
        runs = await asyncio.to_thread(SchedulerRepository().history, identifier, limit=limit)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return {"runs": [RunHandle.from_row(run).to_dict() for run in runs]}


@app.get("/api/schedule-runs/{run_id}")
async def portable_schedule_run(run_id: str) -> dict[str, Any]:
    try:
        run = await asyncio.to_thread(SchedulerRepository().get_run, run_id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return run.to_dict()


@app.post("/api/schedule-runs/{run_id}/cancel")
async def cancel_portable_schedule_run(run_id: str) -> dict[str, Any]:
    repository = SchedulerRepository()
    try:
        run = await asyncio.to_thread(cancel_run, repository.database_path, run_id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return run.to_dict()


def _safe_run_log(repository: SchedulerRepository, value: str) -> Path:
    root = (repository.database_path.parent / "runs").resolve()
    path = Path(value).resolve()
    if not path.is_relative_to(root):
        raise ValueError("run log is outside the Taskflows run directory")
    return path


def _tail_file(path: Path, lines: int, *, max_bytes: int = 1024 * 1024) -> str:
    with path.open("rb") as stream:
        stream.seek(0, os.SEEK_END)
        size = stream.tell()
        stream.seek(max(size - max_bytes, 0))
        content = stream.read(max_bytes)
    return b"\n".join(content.splitlines()[-lines:]).decode(errors="replace")


@app.get("/api/schedule-runs/{run_id}/logs")
async def portable_schedule_run_logs(
    run_id: str,
    stream: Literal["stdout", "stderr", "both"] = Query("both"),
    lines: int = Query(200, ge=1, le=10000),
) -> dict[str, str]:
    repository = SchedulerRepository()
    try:
        run = await asyncio.to_thread(repository.get_run, run_id)
        selected = ("stdout", "stderr") if stream == "both" else (stream,)
        result: dict[str, str] = {}
        for name in selected:
            value = run.stdout_path if name == "stdout" else run.stderr_path
            if value:
                path = _safe_run_log(repository, value)
                result[name] = await asyncio.to_thread(_tail_file, path, lines)
        return result
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@app.get("/api/scheduler/status")
async def portable_scheduler_status() -> dict[str, Any]:
    """Return the same cross-platform status contract as the scheduler CLI."""
    try:
        result = await asyncio.to_thread(scheduler_status)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"could not inspect scheduler status: {exc}",
        ) from exc
    return result.to_dict()


@app.get("/api/scheduler/diagnostics")
async def portable_scheduler_diagnostics() -> dict[str, Any]:
    """Return actionable supervisor, registry, heartbeat, and dispatch checks."""
    try:
        current, checks = await asyncio.to_thread(diagnose_scheduler)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"could not diagnose scheduler: {exc}",
        ) from exc
    return {
        "status": current.to_dict(),
        "checks": [check.to_dict() for check in checks],
    }


@app.post("/api/scheduler/{operation}")
async def operate_portable_scheduler(
    operation: Literal["ensure", "install", "uninstall", "start", "stop", "restart"],
    wait: bool = Query(True),
    timeout: float = Query(15.0, gt=0, le=120),
) -> dict[str, Any]:
    """Apply the same normalized native lifecycle used by the scheduler CLI."""

    def operate() -> dict[str, Any]:
        return operate_scheduler(operation, wait=wait, timeout=timeout).to_dict()

    try:
        return await asyncio.to_thread(operate)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"could not {operation} scheduler: {exc}",
        ) from exc


# Batch operations endpoint
if UI_ENABLED:
    from pydantic import BaseModel as PydanticBaseModel

    class BatchOperation(PydanticBaseModel):
        """Batch operation request model."""

        service_names: list[str]
        operation: str

    @app.post("/api/batch")
    async def batch_operation(batch: BatchOperation):
        """Execute operation on multiple services."""
        from taskflows.security_validation import validate_service_name

        max_batch_size = 50
        if len(batch.service_names) > max_batch_size:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Batch operations are limited to {max_batch_size} services",
            )
        valid_operations = {"start", "stop", "restart", "enable", "disable", "remove"}
        if batch.operation not in valid_operations:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown operation: {batch.operation}",
            )

        try:
            service_names = [validate_service_name(name) for name in batch.service_names]
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc

        operation_funcs = {
            "start": start,
            "stop": stop,
            "restart": restart,
            "enable": enable,
            "disable": disable,
            "remove": remove,
        }
        op_func = operation_funcs[batch.operation]

        async def _run_one(service_name: str):
            try:
                result = await op_func(match=service_name, as_json=True)
                return service_name, {"status": "success", "result": result}
            except Exception as e:
                logger.error(f"Batch operation {batch.operation} failed for {service_name}: {e}")
                return service_name, {"status": "error", "error": str(e)}

        all_results = await asyncio.gather(*[_run_one(n) for n in service_names])
        return with_hostname({"batch_results": dict(all_results)})

    # UI-specific API endpoints with /api/ prefix
    import re as _re

    _EMOJI_PREFIX_RE = _re.compile(r"^[\U0001f300-\U0001faff\u2600-\u27bf]\s*")

    def _strip_emoji(value: str) -> str:
        """Strip leading emoji prefix from status values."""
        if not value or value == "-":
            return "-"
        return _EMOJI_PREFIX_RE.sub("", value) or "-"

    def _parse_status(sub_state: str) -> str:
        """Convert sub_state emoji format to frontend status."""
        if "running" in sub_state:
            return "running"
        elif "dead" in sub_state or "stopped" in sub_state:
            return "stopped"
        elif "failed" in sub_state:
            return "failed"
        elif "inactive" in sub_state:
            return "inactive"
        elif "active" in sub_state:
            return "active"
        return "inactive"

    @app.get("/api/services")
    async def get_services_api(
        match: str | None = Query(None),
        running: bool = Query(False),
        all: bool = Query(False),
    ):
        """Get services for UI dashboard."""
        result = await service_status(
            match=match, running=running, all=all, details=True, as_json=True
        )
        # Transform to frontend expected format
        services = []
        for svc in result.get("status", []):
            services.append(
                {
                    # Original fields (backward compatible)
                    "name": svc.get("Service", ""),
                    "status": _parse_status(svc.get("sub_state", "")),
                    "schedule": svc.get("Timers", "-")
                    if svc.get("Timers") and svc.get("Timers") != "-"
                    else "-",
                    "last_run": svc.get("Last Start", "-")
                    if svc.get("Last Start") and svc.get("Last Start") != "-"
                    else "-",
                    # Extended fields
                    "description": _strip_emoji(svc.get("description", "-")),
                    "service_enabled": _strip_emoji(svc.get("Service\nEnabled", "-")),
                    "timer_enabled": _strip_emoji(svc.get("Timer\nEnabled", "-")),
                    "load_state": _strip_emoji(svc.get("load_state", "-")),
                    "active_state": _strip_emoji(svc.get("active_state", "-")),
                    "sub_state": _strip_emoji(svc.get("sub_state", "-")),
                    "uptime": svc.get("Uptime", "-")
                    if svc.get("Uptime") and svc.get("Uptime") != "-"
                    else "-",
                    "last_finish": svc.get("Last Finish", "-")
                    if svc.get("Last Finish") and svc.get("Last Finish") != "-"
                    else "-",
                    "next_start": svc.get("Next Start", "-")
                    if svc.get("Next Start") and svc.get("Next Start") != "-"
                    else "-",
                }
            )
        return {"services": services}

    @app.get("/api/logs")
    async def get_logs_api(
        service_name: str = Query(...),
        n_lines: int = Query(1000),
    ):
        """Get logs for UI log viewer."""
        return await logs(service_name=service_name, n_lines=n_lines, as_json=True)

    @app.post("/api/start")
    async def start_api(match: str = Query(...)):
        """Start a service from UI."""
        return await start(match=match, as_json=True)

    @app.post("/api/stop")
    async def stop_api(match: str = Query(...)):
        """Stop a service from UI."""
        return await stop(match=match, as_json=True)

    @app.post("/api/restart")
    async def restart_api(match: str = Query(...)):
        """Restart a service from UI."""
        return await restart(match=match, as_json=True)

    @app.post("/api/enable")
    async def enable_api(match: str = Query(...)):
        """Enable a service from UI."""
        return await enable(match=match, as_json=True)

    @app.post("/api/disable")
    async def disable_api(match: str = Query(...)):
        """Disable a service from UI."""
        return await disable(match=match, as_json=True)

    @app.post("/api/remove")
    async def remove_api(match: str = Query(...)):
        """Remove a service from UI."""
        return await remove(match=match, as_json=True)

    @app.get("/api/show")
    async def show_api(match: str = Query(...)):
        """Show service files from UI."""
        return await show(match=match, as_json=True)

    @app.get("/api/servers")
    async def servers_api():
        """List servers from UI."""
        return await list_servers()

    @app.post("/api/create")
    async def create_api(
        file: UploadFile = File(...),
        host: str | None = Form(None),
        include: str | None = Form(None),
        exclude: str | None = Form(None),
    ):
        """Create services from uploaded YAML file."""
        import tempfile

        content = await file.read(MAX_CREATE_YAML_BYTES + 1)
        if len(content) > MAX_CREATE_YAML_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail=(
                    f"Service definition is too large. Limit is {MAX_CREATE_YAML_BYTES} bytes."
                ),
            )
        yaml_content = content.decode("utf-8")

        if host:
            # Forward to remote host via HMAC-authenticated API
            json_data = {"yaml_content": yaml_content}
            if include:
                json_data["include"] = include
            if exclude:
                json_data["exclude"] = exclude
            return await asyncio.to_thread(
                call_api,
                host,
                "/create",
                method="POST",
                json_data=json_data,
                timeout=30,
            )

        # Local creation: save to temp file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            temp_path = f.name
        try:
            return await create(yaml_file=temp_path, include=include, exclude=exclude, as_json=True)
        finally:
            os.unlink(temp_path)


# Authentication endpoints (only when UI is enabled)
if UI_ENABLED:
    from taskflows.admin.auth import (
        LoginRequest,
        authenticate_user,
        create_access_token,
        create_refresh_token,
        load_ui_config,
        revoke_refresh_token,
        verify_token,
    )

    def _login_rate_key(request: Request, username: str) -> str:
        client_host = request.client.host if request.client else "unknown"
        return f"{client_host}:{username.casefold()}"

    def _login_retry_after_seconds(key: str) -> int | None:
        now = time.time()
        with _login_attempts_lock:
            attempts = [
                ts
                for ts in _login_attempts.get(key, [])
                if now - ts <= LOGIN_RATE_LIMIT_WINDOW_SECONDS
            ]
            _login_attempts[key] = attempts
            if len(attempts) < LOGIN_RATE_LIMIT_ATTEMPTS:
                return None
            retry_after = LOGIN_RATE_LIMIT_LOCKOUT_SECONDS - int(now - attempts[-1])
            return max(1, retry_after) if retry_after > 0 else None

    def _record_login_failure(key: str) -> None:
        now = time.time()
        with _login_attempts_lock:
            attempts = [
                ts
                for ts in _login_attempts.get(key, [])
                if now - ts <= LOGIN_RATE_LIMIT_WINDOW_SECONDS
            ]
            attempts.append(now)
            _login_attempts[key] = attempts

    def _clear_login_failures(key: str) -> None:
        with _login_attempts_lock:
            _login_attempts.pop(key, None)

    @app.post("/auth/login")
    async def login(credentials: LoginRequest, request: Request):
        """Login with username and password.

        Returns JWT access/refresh tokens and CSRF token for defense-in-depth.
        """
        rate_key = _login_rate_key(request, credentials.username)
        retry_after = _login_retry_after_seconds(rate_key)
        if retry_after is not None:
            logger.warning(f"Rate-limited login attempt for user {credentials.username}")
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many failed login attempts. Try again later.",
                headers={"Retry-After": str(retry_after)},
            )

        user = authenticate_user(credentials.username, credentials.password)
        if not user:
            _record_login_failure(rate_key)
            logger.warning(f"Failed login attempt for user {credentials.username}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials",
            )
        _clear_login_failures(rate_key)

        ui_config = load_ui_config()
        if not ui_config.jwt_secret:
            logger.error("JWT secret not configured")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="JWT secret not configured",
            )

        access_token = create_access_token(credentials.username, ui_config.jwt_secret)
        refresh_token = create_refresh_token(credentials.username, ui_config.jwt_secret)

        # Create and store CSRF token for defense-in-depth
        csrf_data = create_csrf_token_data(credentials.username, ui_config.jwt_secret)
        store_csrf_token(credentials.username, csrf_data)

        logger.info(f"User {credentials.username} logged in successfully with CSRF protection")
        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_in": 60 * 60,
            "token_type": "bearer",
            "csrf_token": csrf_data["token"],
            "csrf_expires_in": security_config.csrf_token_expiry,
        }

    @app.post("/auth/refresh")
    async def refresh(refresh_token: str = Body(..., embed=True)):
        """Get new access token and CSRF token using refresh token."""
        ui_config = load_ui_config()
        if not ui_config.jwt_secret:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="JWT secret not configured",
            )

        username = verify_token(refresh_token, ui_config.jwt_secret, "refresh")
        if not username:
            logger.warning("Invalid refresh token")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid refresh token",
            )

        new_access_token = create_access_token(username, ui_config.jwt_secret)

        # Also refresh CSRF token
        csrf_data = create_csrf_token_data(username, ui_config.jwt_secret)
        store_csrf_token(username, csrf_data)

        logger.info(f"Refreshed access token and CSRF token for user {username}")
        return {
            "access_token": new_access_token,
            "token_type": "bearer",
            "csrf_token": csrf_data["token"],
            "csrf_expires_in": security_config.csrf_token_expiry,
        }

    @app.post("/auth/logout")
    async def logout(
        request: Request,
        refresh_token: str | None = Body(None, embed=True),
    ):
        """Logout, remove CSRF token, and revoke the current refresh token."""
        username = getattr(request.state, "user", None)
        if username:
            # Remove CSRF token from server
            csrf_token = request.headers.get(security_config.csrf_header)
            remove_csrf_token(username, csrf_token)
            if refresh_token:
                ui_config = load_ui_config()
                if ui_config.jwt_secret:
                    revoke_refresh_token(refresh_token, ui_config.jwt_secret)
            logger.info(f"User {username} logged out, CSRF token removed")
        return {"message": "Logged out successfully"}

    # Environments API endpoints
    from taskflows.admin.environments import (
        NamedEnvironment,
        create_environment,
        delete_environment,
        find_services_using_environment,
        get_environment,
        list_environments,
        update_environment,
    )

    @app.get("/api/environments", response_model=list[NamedEnvironment])
    async def list_environments_endpoint():
        """List all named environments."""
        return list_environments()

    @app.post("/api/environments", response_model=NamedEnvironment)
    async def create_environment_endpoint(env: NamedEnvironment):
        """Create a new named environment."""
        try:
            return create_environment(env)
        except ValueError as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e

    @app.get("/api/environments/{name}", response_model=NamedEnvironment)
    async def get_environment_endpoint(name: str):
        """Get an environment by name."""
        env = get_environment(name)
        if not env:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Environment '{name}' not found",
            )
        return env

    @app.put("/api/environments/{name}", response_model=NamedEnvironment)
    async def update_environment_endpoint(name: str, env: NamedEnvironment):
        """Update an existing environment."""
        try:
            return update_environment(name, env)
        except ValueError as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e

    @app.delete("/api/environments/{name}")
    async def delete_environment_endpoint(name: str):
        """Delete an environment."""
        # Check if any services use this environment
        services = find_services_using_environment(name)
        if services:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot delete: {len(services)} services use this environment: {', '.join(services)}",
            )

        try:
            delete_environment(name)
            return {"message": f"Environment '{name}' deleted successfully"}
        except ValueError as e:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e

    # Static file serving for React SPA
    from pathlib import Path

    from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
    from fastapi.staticfiles import StaticFiles

    def _resolve_frontend_dist_dir() -> Path:
        """Locate the built web UI.

        Priority: TASKFLOWS_FRONTEND_DIST env override (development), then the
        copy bundled inside the wheel (taskflows/admin/static), then the repo
        checkout's frontend/dist.
        """
        if override := os.getenv("TASKFLOWS_FRONTEND_DIST"):
            return Path(override)
        packaged = Path(__file__).parent / "static"
        if packaged.exists():
            return packaged
        return Path(__file__).parent.parent.parent / "frontend" / "dist"

    frontend_dist_dir = _resolve_frontend_dist_dir()

    # Mount React assets (JS/CSS bundles with hashes) when the frontend is built.
    assets_dir = frontend_dist_dir / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    # Serve index.html for all UI routes (React Router handles client-side routing)
    @app.exception_handler(404)
    async def spa_404_handler(request, exc):
        """Serve index.html for UI routes, return JSON 404 for API routes."""
        # API and Grafana routes should return JSON 404
        if (
            request.url.path.startswith("/api/")
            or request.url.path.startswith("/auth/")
            or request.url.path.startswith("/grafana/")
        ):
            return JSONResponse(status_code=404, content={"detail": "Not found"})

        # For all other routes, serve React SPA index.html
        index_file = frontend_dist_dir / "index.html"
        if not index_file.exists():
            return PlainTextResponse(
                "Web UI not found. Reinstall taskflows[server] from a release wheel, "
                "or build it from a repo checkout: cd frontend && npm ci && npm run build "
                "(set TASKFLOWS_FRONTEND_DIST to point at a custom build).",
                status_code=503,
            )
        return FileResponse(index_file)


@click.command("start")
@click.option("--host", default="localhost", help="Host to bind the server to")
@click.option("--port", default=7777, help="Port to bind the server to")
@click.option("--reload/--no-reload", default=True, help="Enable auto-reload on code changes")
@click.option(
    "--enable-ui/--no-enable-ui",
    default=False,
    help="Enable web UI with authentication",
)
def _start_api_cmd(host: str, port: int, reload: bool, enable_ui: bool):
    """Start the Services API server. This installs as _start_srv_api command."""
    click.echo(click.style(f"Starting Services API api on {host}:{port}...", fg="green"))
    if reload:
        click.echo(click.style("Auto-reload enabled", fg="yellow"))
    if enable_ui:
        click.echo(click.style("Web UI enabled", fg="cyan"))
        import os

        os.environ["TASKFLOWS_ENABLE_UI"] = "1"
        if not UI_ENABLED:
            import sys

            args = [
                sys.executable,
                "-m",
                "uvicorn",
                "taskflows.admin.api:app",
                "--host",
                host,
                "--port",
                str(port),
            ]
            if reload:
                args.append("--reload")
            os.execv(sys.executable, args)
    # Also log to file so we can see something even if import path is wrong
    logger.info(f"Launching uvicorn on {host}:{port} reload={reload} enable_ui={enable_ui}")
    uvicorn.run("taskflows.admin.api:app", host=host, port=port, reload=reload)


def build_api_service() -> Service:
    """Build the systemd service definition for the taskflows API server.

    By default the unit runs `_start_srv_api` from the environment taskflows
    is installed in (resolved to an absolute path so the unit does not depend
    on PATH). Set TASKFLOWS_API_ENV to a conda/mamba environment name to run
    it inside that environment instead.
    """
    import shutil

    if env_name := os.getenv("TASKFLOWS_API_ENV"):
        environment = Venv(env_name)
        start_command = "_start_srv_api"
    else:
        environment = None
        start_command = shutil.which("_start_srv_api") or "_start_srv_api"
    return Service(
        name="srv-api",
        start_command=start_command,
        environment=environment,
        restart_policy=RestartPolicy(
            condition="always",
            delay=10,
        ),
        enabled=True,
    )


def start_api_srv():
    srv_api = build_api_service()
    if not srv_api.exists:
        logger.info("Creating and starting srv-api service")
        asyncio.run(srv_api.create())
    asyncio.run(srv_api.start())
