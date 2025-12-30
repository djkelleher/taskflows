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
    status,
    stop,
    task_history,
    upsert_server,
)
from taskflows.admin.utils import with_hostname
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
    # 3. Static files
    # 4. Health check
    public_paths = ["/health", "/login", "/auth/login", "/auth/refresh"]
    if (
        request.url.path.startswith("/api/")
        or request.url.path in public_paths
        or request.url.path.startswith("/static/")
    ):
        logger.debug(f"JWT skipped for {request.url.path}")
        return await call_next(request)

    # Check for JWT token in Authorization header
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        logger.warning(f"Missing JWT token for {request.url.path}")
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"detail": "Not authenticated"},
        )

    # Import here to avoid circular dependency
    from taskflows.admin.auth import load_ui_config, verify_token

    try:
        token = auth_header.split(" ")[1]
        ui_config = load_ui_config()

        if not ui_config.jwt_secret:
            logger.error("JWT secret not configured")
            return JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content={"detail": "JWT secret not configured"},
            )

        username = verify_token(token, ui_config.jwt_secret, "access")
        if not username:
            logger.warning(f"Invalid JWT token for {request.url.path}")
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"detail": "Invalid or expired token"},
            )

        # Attach user to request state
        request.state.user = username
        logger.debug(f"JWT validated for user {username} on {request.url.path}")
        return await call_next(request)

    except Exception as e:
        logger.error(f"JWT validation error: {e}")
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"detail": "Authentication failed"},
        )


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
    return await status(match=match, running=running, all=all, as_json=True)


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

    @app.post("/auth/login", response_model=JWTToken)
    async def login(credentials: LoginRequest):
        """Login with username and password."""
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

        update_user_last_login(credentials.username)

        logger.info(f"User {credentials.username} logged in successfully")
        return JWTToken(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=60 * 60,
        )

    @app.post("/auth/refresh")
    async def refresh(refresh_token: str = Body(..., embed=True)):
        """Get new access token using refresh token."""
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
        logger.info(f"Refreshed access token for user {username}")
        return {"access_token": new_access_token, "token_type": "bearer"}

    @app.post("/auth/logout")
    async def logout(request: Request):
        """Logout (client-side token deletion primarily)."""
        username = getattr(request.state, "user", None)
        if username:
            logger.info(f"User {username} logged out")
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

    # Static file serving and HTML routes
    from pathlib import Path
    from fastapi.staticfiles import StaticFiles
    from fastapi.responses import HTMLResponse, FileResponse

    ui_static_dir = Path(__file__).parent.parent / "ui" / "static"

    # Mount static files
    app.mount("/static", StaticFiles(directory=ui_static_dir), name="static")

    # HTML routes
    @app.get("/login", response_class=HTMLResponse)
    async def serve_login():
        """Serve login page."""
        html_file = ui_static_dir / "login.html"
        if not html_file.exists():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Login page not found. Run 'python -m taskflows.ui.build' to build the UI.",
            )
        return FileResponse(html_file)

    @app.get("/", response_class=HTMLResponse)
    async def serve_dashboard():
        """Serve dashboard page."""
        html_file = ui_static_dir / "index.html"
        if not html_file.exists():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Dashboard page not found. Run 'python -m taskflows.ui.build' to build the UI.",
            )
        return FileResponse(html_file)

    @app.get("/logs/{service_name}", response_class=HTMLResponse)
    async def serve_logs(service_name: str):
        """Serve logs page for a specific service."""
        # Generate logs page dynamically
        from taskflows.ui.pages.logs import create_logs_page

        page = create_logs_page(service_name)
        return HTMLResponse(content=page.html.render())

    @app.get("/environments", response_class=HTMLResponse)
    async def serve_environments_list():
        """Serve environments list page."""
        html_file = ui_static_dir / "environments.html"
        if not html_file.exists():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Environments page not found. Run 'python -m taskflows.ui.build' to build the UI.",
            )
        return FileResponse(html_file)

    @app.get("/environments/create", response_class=HTMLResponse)
    async def serve_environments_create():
        """Serve environment creation page."""
        html_file = ui_static_dir / "environments_create.html"
        if not html_file.exists():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Environment creation page not found. Run 'python -m taskflows.ui.build' to build the UI.",
            )
        return FileResponse(html_file)

    @app.get("/environments/edit", response_class=HTMLResponse)
    async def serve_environments_edit(name: str = Query(...)):
        """Serve environment edit page."""
        # Generate edit page dynamically with the environment name
        from taskflows.ui.pages.environments import create_environments_page

        page = create_environments_page(mode="edit", env_name=name)
        return HTMLResponse(content=page.html.render())


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
