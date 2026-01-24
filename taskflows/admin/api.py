import logging
import os
import traceback
from contextlib import asynccontextmanager
from typing import List, Optional

import click
import uvicorn

# from trading.databases.timescale import pgconn
from fastapi import Body, FastAPI, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
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
    status as service_status,
    stop,
    task_history,
    upsert_server,
)
from taskflows.admin.utils import with_hostname
from taskflows.admin.security import (
    security_config,
    validate_hmac_request,
    create_csrf_token_data,
    store_csrf_token,
    get_csrf_token_data,
    remove_csrf_token,
    validate_csrf_token,
)
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


app = FastAPI(
    title="Taskflows Services API",
    description="Service management, task scheduling, and monitoring",
    version="0.1.0",
    docs_url="/docs",  # Enable Swagger UI
    redoc_url="/redoc",  # Enable ReDoc
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

# Add CORS middleware if UI is enabled
if os.getenv("TASKFLOWS_ENABLE_UI"):
    logger.info("UI enabled, adding CORS middleware")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=security_config.allowed_origins,
        allow_credentials=True,
        allow_methods=security_config.allowed_methods,
        allow_headers=security_config.allowed_headers,
    )

# Add Prometheus middleware for metrics collection
from taskflows.middleware.prometheus_middleware import PrometheusMiddleware

app.add_middleware(PrometheusMiddleware)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    logger.error(
        "Unhandled exception %s %s: %s%s",
        request.method,
        request.url.path,
        exc,
        f"\n{tb}" if tb else "",
    )
    payload = {
        "detail": str(exc),
        "error_type": type(exc).__name__,
        "path": request.url.path,
    }
    # Only include traceback in development mode (DEBUG=true)
    # This prevents information disclosure in production
    if tb and os.getenv("DEBUG", "").lower() in ("true", "1", "yes"):
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
    """Validate HMAC headers for API endpoints only."""
    # Skip HMAC for:
    # 1. When HMAC is disabled
    # 2. Health check
    # 3. UI routes (all non-API routes) - only API endpoints need HMAC
    # 4. Auth endpoints (they have their own authentication)
    # 5. Assets
    if (
        not security_config.enable_hmac
        or request.url.path == "/health"
        or not request.url.path.startswith("/api/")
        or request.url.path.startswith("/auth/")
        or request.url.path.startswith("/assets/")
    ):
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


# JWT validation middleware (for UI routes)
@app.middleware("http")
async def jwt_validation(request: Request, call_next):
    """Validate JWT for UI routes (when UI is enabled)."""
    # Skip if UI is not enabled
    if not os.getenv("TASKFLOWS_ENABLE_UI"):
        return await call_next(request)

    # Skip JWT for:
    # 1. API endpoints (use HMAC)
    # 2. Auth endpoints (login, refresh)
    # 3. Static files and UI routes (React handles auth client-side)
    # 4. Health check
    #
    # For React SPA: All non-API routes serve index.html, React handles authentication
    if (
        request.url.path.startswith("/api/")
        or request.url.path.startswith("/auth/")
        or request.url.path.startswith("/assets/")
        or request.url.path == "/health"
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
    if not os.getenv("TASKFLOWS_ENABLE_UI") or not security_config.enable_csrf:
        return await call_next(request)

    # Skip CSRF for:
    # 1. Safe methods (GET, HEAD, OPTIONS)
    # 2. Auth endpoints (login, refresh - they're establishing the token)
    # 3. API endpoints using HMAC
    # 4. Static files
    # 5. Health check
    if (
        request.method in ["GET", "HEAD", "OPTIONS"]
        or request.url.path in ["/health", "/auth/login", "/auth/refresh"]
        or request.url.path.startswith("/api/")  # HMAC-protected
        or request.url.path.startswith("/assets/")
    ):
        logger.debug(f"CSRF skipped for {request.method} {request.url.path}")
        return await call_next(request)

    # Get username from request state (set by JWT middleware)
    username = getattr(request.state, "user", None)
    if not username:
        logger.warning(f"CSRF check: No user in request state for {request.url.path}")
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"detail": "Authentication required"},
        )

    # Check for CSRF token in header
    csrf_token = request.headers.get(security_config.csrf_header)
    if not csrf_token:
        logger.warning(f"CSRF check failed: Missing token for user {username} on {request.url.path}")
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={"detail": "CSRF token required"},
        )

    # Get stored CSRF token data
    from taskflows.admin.auth import load_ui_config

    token_data = get_csrf_token_data(username)
    if not token_data:
        logger.warning(f"CSRF check failed: No stored token for user {username}")
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={"detail": "CSRF token expired or invalid"},
        )

    # Validate the token
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
    all: bool = Query(False),
):
    return await service_status(match=match, running=running, all=all, as_json=True)


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
    return await create(
        search_in=search_in, include=include, exclude=exclude, as_json=True
    )


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


# Batch operations endpoint
if os.getenv("TASKFLOWS_ENABLE_UI"):
    from pydantic import BaseModel as PydanticBaseModel

    class BatchOperation(PydanticBaseModel):
        """Batch operation request model."""

        service_names: List[str]
        operation: str

    @app.post("/api/batch")
    async def batch_operation(batch: BatchOperation):
        """Execute operation on multiple services."""
        results = {}

        for service_name in batch.service_names:
            try:
                if batch.operation == "start":
                    result = await start(match=service_name, as_json=True)
                elif batch.operation == "stop":
                    result = await stop(match=service_name, as_json=True)
                elif batch.operation == "restart":
                    result = await restart(match=service_name, as_json=True)
                elif batch.operation == "enable":
                    result = await enable(match=service_name, as_json=True)
                elif batch.operation == "disable":
                    result = await disable(match=service_name, as_json=True)
                else:
                    results[service_name] = {
                        "status": "error",
                        "error": f"Unknown operation: {batch.operation}",
                    }
                    continue

                results[service_name] = {"status": "success", "result": result}
            except Exception as e:
                logger.error(f"Batch operation {batch.operation} failed for {service_name}: {e}")
                results[service_name] = {"status": "error", "error": str(e)}

        return with_hostname({"batch_results": results})


# Authentication endpoints (only when UI is enabled)
if os.getenv("TASKFLOWS_ENABLE_UI"):
    from fastapi import HTTPException
    from taskflows.admin.auth import (
        authenticate_user,
        create_access_token,
        create_refresh_token,
        load_ui_config,
        update_user_last_login,
        verify_token,
        JWTToken,
        LoginRequest,
    )

    @app.post("/auth/login")
    async def login(credentials: LoginRequest):
        """Login with username and password.

        Returns JWT access/refresh tokens and CSRF token for defense-in-depth.
        """
        user = authenticate_user(credentials.username, credentials.password)
        if not user:
            logger.warning(f"Failed login attempt for user {credentials.username}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials",
            )

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

        update_user_last_login(credentials.username)

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
    async def logout(request: Request):
        """Logout and remove CSRF token."""
        username = getattr(request.state, "user", None)
        if username:
            # Remove CSRF token from server
            remove_csrf_token(username)
            logger.info(f"User {username} logged out, CSRF token removed")
        return {"message": "Logged out successfully"}

    # Environments API endpoints
    from taskflows.admin.environments import (
        create_environment,
        delete_environment,
        find_services_using_environment,
        get_environment,
        list_environments,
        update_environment,
        NamedEnvironment,
    )

    @app.get("/api/environments", response_model=List[NamedEnvironment])
    async def list_environments_endpoint():
        """List all named environments."""
        return list_environments()

    @app.post("/api/environments", response_model=NamedEnvironment)
    async def create_environment_endpoint(env: NamedEnvironment):
        """Create a new named environment."""
        try:
            return create_environment(env)
        except ValueError as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

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
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

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
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))

    # Static file serving for React SPA
    from pathlib import Path
    from fastapi.staticfiles import StaticFiles
    from fastapi.responses import HTMLResponse, FileResponse, JSONResponse, PlainTextResponse

    frontend_dist_dir = Path(__file__).parent.parent.parent / "frontend" / "dist"

    # Mount React assets (JS/CSS bundles with hashes)
    app.mount("/assets", StaticFiles(directory=frontend_dist_dir / "assets"), name="assets")

    # Serve index.html for all UI routes (React Router handles client-side routing)
    @app.exception_handler(404)
    async def spa_404_handler(request, exc):
        """Serve index.html for UI routes, return JSON 404 for API routes."""
        # API routes should return JSON 404
        if request.url.path.startswith("/api/") or request.url.path.startswith("/auth/"):
            return JSONResponse(
                status_code=404,
                content={"detail": "Not found"}
            )

        # For all other routes, serve React SPA index.html
        index_file = frontend_dist_dir / "index.html"
        if not index_file.exists():
            return PlainTextResponse(
                "Frontend not built. Run 'cd frontend && npm run build'",
                status_code=503
            )
        return FileResponse(index_file)


@click.command("start")
@click.option("--host", default="localhost", help="Host to bind the server to")
@click.option("--port", default=7777, help="Port to bind the server to")
@click.option(
    "--reload/--no-reload", default=True, help="Enable auto-reload on code changes"
)
@click.option(
    "--enable-ui/--no-enable-ui", default=False, help="Enable web UI with authentication"
)
def _start_api_cmd(host: str, port: int, reload: bool, enable_ui: bool):
    """Start the Services API server. This installs as _start_srv_api command."""
    click.echo(
        click.style(f"Starting Services API api on {host}:{port}...", fg="green")
    )
    if reload:
        click.echo(click.style("Auto-reload enabled", fg="yellow"))
    if enable_ui:
        click.echo(click.style("Web UI enabled", fg="cyan"))
        import os
        os.environ["TASKFLOWS_ENABLE_UI"] = "1"
    # Also log to file so we can see something even if import path is wrong
    logger.info(f"Launching uvicorn on {host}:{port} reload={reload} enable_ui={enable_ui}")
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
        logger.info("Creating and starting srv-api service")
        srv_api.create()
    srv_api.start()
