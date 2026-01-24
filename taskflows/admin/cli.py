import os

# Configure CLI logging to only log to file (no terminal output)
# This MUST be set before any taskflows imports that use the logger
os.environ['TASKFLOWS_NO_TERMINAL'] = '1'
os.environ['TASKFLOWS_FILE_DIR'] = '/opt/taskflows/data/logs'

from functools import lru_cache
from itertools import cycle
from typing import Optional

import click
from taskflows.alerts.components import Table
from click import Group
from rich.console import Console

from taskflows.admin.core import execute_command_on_servers
from taskflows.entrypoints import async_entrypoint

from .api import srv_api, start_api_srv
from .security import (
    config_file,
    generate_hmac_secret,
    save_security_config,
    security_config,
)

cli = Group("admin")


def get_console_with_wrap() -> Console:
    """Create a Rich Console with soft wrapping enabled for better text display."""
    return Console(soft_wrap=True)


@cli.group
def api():
    """Manage API service."""
    pass


@api.command
def start():
    start_api_srv()


@api.command
def restart():
    srv_api.restart()


@api.command
def stop():
    srv_api.stop()


@api.group("security")
def security():
    """Manage API security settings."""
    pass


@security.command("setup")
@click.option("--regenerate-secret", "-r", is_flag=True)
def setup_security(regenerate_secret):
    """Setup HMAC security for the Services API."""
    security_config.enable_hmac = True
    if regenerate_secret or not security_config.hmac_secret:
        security_config.hmac_secret = generate_hmac_secret()
        click.echo(f"✅ HMAC authentication enabled")
        click.echo(f"🔐 Generated HMAC secret: {security_config.hmac_secret}")
        click.echo(
            f"   Use headers: {security_config.hmac_header} and {security_config.hmac_timestamp_header}"
        )
    else:
        click.echo(f"✅ HMAC authentication already enabled")
        click.echo(f"🔐 Current HMAC secret: {security_config.hmac_secret}")

    save_security_config(security_config)
    click.echo(f"💾 Security configuration saved to {config_file}")


@security.command("disable")
def disable_security():
    """Disable HMAC security (not recommended)."""
    security_config.enable_hmac = False
    save_security_config(security_config)
    click.echo("⚠️  HMAC authentication disabled (not recommended for production)")


@security.command("set-secret")
@click.argument("secret")
def set_secret(secret: str):
    """Set a specific HMAC secret (for distributing to multiple machines)."""
    security_config.hmac_secret = secret
    save_security_config(security_config)
    click.echo(f"🔐 HMAC secret set")


@security.command("status")
def security_status():
    """Show current security settings."""
    click.echo("🔒 Current Security Settings:")
    click.echo(
        f"  HMAC: {'✅ Enabled' if security_config.enable_hmac else '❌ Disabled'}"
    )
    if security_config.enable_hmac and security_config.hmac_secret:
        click.echo(f"    Secret configured: ✅")
        click.echo(
            f"    Secret: {security_config.hmac_secret[:8]}..."
            if security_config.hmac_secret
            else "    Secret: Not set"
        )
        click.echo(f"    Window: {security_config.hmac_window_seconds} seconds")
        click.echo(f"    Header: {security_config.hmac_header}")
        click.echo(f"    Timestamp Header: {security_config.hmac_timestamp_header}")
    click.echo(
        f"  CORS: {'✅ Enabled' if security_config.enable_cors else '❌ Disabled'}"
    )
    if security_config.enable_cors:
        click.echo(f"    Origins: {', '.join(security_config.allowed_origins)}")
    click.echo(
        f"  Security Headers: {'✅ Enabled' if security_config.enable_security_headers else '❌ Disabled'}"
    )
    click.echo(f"  Config file: {config_file}")


@api.command("setup-ui")
@click.option("--username", default="admin", help="Admin username")
@click.option("--password", prompt=True, hide_input=True, confirmation_prompt=True, help="Admin password")
def setup_ui(username: str, password: str):
    """Setup web UI with admin credentials.

    This creates file-based credentials. For Docker/automation, you can also
    use environment variables instead:
      TF_ADMIN_USER, TF_ADMIN_PASSWORD, TF_JWT_SECRET
    """
    from taskflows.admin.auth import (
        create_admin_user,
        generate_jwt_secret,
        load_ui_config,
        save_ui_config,
    )

    # Create JWT secret
    ui_config = load_ui_config()
    if not ui_config.jwt_secret:
        ui_config.jwt_secret = generate_jwt_secret()
        click.echo(f"Generated JWT secret")

    ui_config.enabled = True

    # Save UI config
    save_ui_config(ui_config)

    # Create admin user
    create_admin_user(username, password)

    click.echo(f"Web UI configured successfully!")
    click.echo(f"   Username: {username}")
    click.echo(f"Restart the API server with UI enabled:")
    click.echo(f"   TASKFLOWS_ENABLE_UI=1 tf api start")


@api.command("generate-secret")
def generate_secret():
    """Generate a JWT secret for use with environment variables.

    Use this to generate a secret for TF_JWT_SECRET when configuring
    authentication via environment variables instead of setup-ui.

    Example usage:
      export TF_JWT_SECRET=$(tf api generate-secret)
      export TF_ADMIN_USER=admin
      export TF_ADMIN_PASSWORD=yourpassword
      export TASKFLOWS_ENABLE_UI=1
      tf api start
    """
    from taskflows.admin.auth import generate_jwt_secret

    click.echo(generate_jwt_secret())


@cli.command
@click.option(
    "-l",
    "--limit",
    type=int,
    default=3,
    help="Number of most recent task runs to show.",
)
@click.option(
    "-m", "--match", help="Only show history for this task name or task name pattern."
)
@click.option(
    "--server",
    "-s",
    multiple=True,
    help="Server(s) to query. Can be specified multiple times. If not specified, queries all registered servers.",
)
@async_entrypoint(blocking=True)
async def history(limit: int, match: Optional[str] = None, server: tuple = ()):
    """Show task run history from specified servers."""
    kwargs = {"limit": limit}
    if match:
        kwargs["match"] = match

    results = await execute_command_on_servers("history", servers=server, **kwargs)
    for hostname, result in results.items():
        # Tables already have Host column, Text results need hostname prefix
        if isinstance(result, Table):
            result.console()
        else:
            click.echo(f"{hostname}:")
            result.console()


@cli.command(name="list")
@click.argument("match", required=False)
@click.option(
    "--server",
    "-s",
    multiple=True,
    help="Server(s) to query. Can be specified multiple times. If not specified, queries all registered servers.",
)
@async_entrypoint(blocking=True)
async def list_services(match: Optional[str] = None, server: tuple = ()):
    """List services from specified servers."""
    kwargs = {}
    if match:
        kwargs["match"] = match

    results = await execute_command_on_servers("list", servers=server, **kwargs)
    for hostname, result in results.items():
        # Tables already have Host column, Text results need hostname prefix
        if isinstance(result, Table):
            result.console()
        else:
            click.echo(f"{hostname}:")
            result.console()


@cli.command
@click.option(
    "-m",
    "--match",
    help="Only show history for this task name or task name pattern.",
)
@click.option(
    "-r",
    "--running",
    is_flag=True,
    help="Only show running services.",
)
@click.option(
    "-a",
    "--all",
    "show_all",
    is_flag=True,
    help="Show all services including stop-* and restart-* services.",
)
@click.option(
    "--server",
    "-s",
    multiple=True,
    help="Server(s) to query. Can be specified multiple times. If not specified, queries all registered servers.",
)
@async_entrypoint(blocking=True)
async def status(
    match: Optional[str] = None, running: bool = False, show_all: bool = False, server: tuple = ()
):
    """Show status of services from specified servers."""
    kwargs = {}
    if match:
        kwargs["match"] = match
    if running:
        kwargs["running"] = running
    if show_all:
        kwargs["all"] = show_all

    results = await execute_command_on_servers("status", servers=server, **kwargs)
    console = get_console_with_wrap()
    for hostname, result in results.items():
        # Tables already have Host column, Text results need hostname prefix
        if isinstance(result, Table):
            result.console(console)
        else:
            console.print(f"[bold]{hostname}:[/bold]")
            result.console(console)


@cli.command
@click.argument("service_name")
@click.option(
    "--server",
    "-s",
    help="Server to query. If not specified, queries the server that has the service.",
)
@click.option(
    "--n-lines",
    "-n",
    default=1000,
    help="Number of log lines to return (default: 1000)",
)
@async_entrypoint(blocking=True)
async def logs(service_name: str, n_lines: int, server: Optional[str] = None):
    """Show logs for a service from specified server."""
    results = await execute_command_on_servers(
        "logs", servers=server, service_name=service_name, n_lines=n_lines
    )
    for hostname, result in results.items():
        # Tables already have Host column, Text results need hostname prefix
        if isinstance(result, Table):
            result.console()
        else:
            click.echo(f"{hostname}:")
            result.console()


@cli.command(name="create")
@click.argument("search_in")
@click.option(
    "-i",
    "--include",
    type=str,
    help="Name or glob pattern of services/dashboards to include.",
)
@click.option(
    "-e",
    "--exclude",
    type=str,
    help="Name or glob pattern of services/dashboards to exclude.",
)
@click.option(
    "--server",
    "-s",
    multiple=True,
    help="Server(s) to create on. Can be specified multiple times. If not specified, creates on all registered servers.",
)
@async_entrypoint(blocking=True)
async def cli_create(search_in, include, exclude, server: tuple = ()):
    """Create services and dashboards on specified servers."""
    kwargs = {"search_in": search_in}
    if include:
        kwargs["include"] = include
    if exclude:
        kwargs["exclude"] = exclude

    results = await execute_command_on_servers("create", servers=server, **kwargs)
    for hostname, result in results.items():
        # Tables already have Host column, Text results need hostname prefix
        if isinstance(result, Table):
            result.console()
        else:
            click.echo(f"{hostname}:")
            result.console()


@cli.command
@click.argument("match", required=True)
@click.option(
    "--timers", "-t", is_flag=True, help="Affect timers matching provided pattern."
)
@click.option(
    "--services", is_flag=True, help="Affect services matching provided pattern."
)
@click.option(
    "--server",
    "-s",
    help="Server to execute on. If not specified, executes on the server that has the matching service.",
)
@async_entrypoint(blocking=True)
async def start(
    match: str,
    timers: bool = False,
    services: bool = False,
    server: Optional[str] = None,
):
    """Start services/timers on specified server."""
    kwargs = {"match": match}
    if timers:
        kwargs["timers"] = timers
    if services:
        kwargs["services"] = services

    results = await execute_command_on_servers("start", servers=server, **kwargs)
    for hostname, result in results.items():
        # Tables already have Host column, Text results need hostname prefix
        if isinstance(result, Table):
            result.console()
        else:
            click.echo(f"{hostname}:")
            result.console()


@cli.command
@click.argument("match", required=True)
@click.option(
    "--timers", "-t", is_flag=True, help="Affect timers matching provided pattern."
)
@click.option(
    "--services", is_flag=True, help="Affect services matching provided pattern."
)
@click.option(
    "--server",
    "-s",
    help="Server to execute on. If not specified, executes on the server that has the matching service.",
)
@async_entrypoint(blocking=True)
async def stop(
    match: str,
    timers: bool = False,
    services: bool = False,
    server: Optional[str] = None,
):
    """Stop services/timers on specified server."""
    kwargs = {"match": match}
    if timers:
        kwargs["timers"] = timers
    if services:
        kwargs["services"] = services

    results = await execute_command_on_servers("stop", servers=server, **kwargs)
    for hostname, result in results.items():
        # Tables already have Host column, Text results need hostname prefix
        if isinstance(result, Table):
            result.console()
        else:
            click.echo(f"{hostname}:")
            result.console()


@cli.command
@click.argument("match", required=True)
@click.option(
    "--server",
    "-s",
    help="Server to execute on. If not specified, executes on the server that has the matching service.",
)
@async_entrypoint(blocking=True)
async def restart(match: str, server: Optional[str] = None):
    """Restart services on specified server."""
    results = await execute_command_on_servers("restart", servers=server, match=match)
    for hostname, result in results.items():
        # Tables already have Host column, Text results need hostname prefix
        if isinstance(result, Table):
            result.console()
        else:
            click.echo(f"{hostname}:")
            result.console()


@cli.command
@click.argument("match", required=True)
@click.option(
    "--timers", "-t", is_flag=True, help="Enable timers matching provided pattern."
)
@click.option(
    "--services", is_flag=True, help="Enable services matching provided pattern."
)
@click.option(
    "--server",
    "-s",
    help="Server to execute on. If not specified, executes on the server that has the matching service.",
)
@async_entrypoint(blocking=True)
async def enable(
    match: str,
    timers: bool = False,
    services: bool = False,
    server: Optional[str] = None,
):
    """Enable services/timers on specified server."""
    kwargs = {"match": match}
    if timers:
        kwargs["timers"] = timers
    if services:
        kwargs["services"] = services

    results = await execute_command_on_servers("enable", servers=server, **kwargs)
    for hostname, result in results.items():
        # Tables already have Host column, Text results need hostname prefix
        if isinstance(result, Table):
            result.console()
        else:
            click.echo(f"{hostname}:")
            result.console()


@cli.command
@click.argument("match", required=True)
@click.option(
    "--timers", "-t", is_flag=True, help="Disable timers matching provided pattern."
)
@click.option(
    "--services", is_flag=True, help="Disable services matching provided pattern."
)
@click.option(
    "--server",
    "-s",
    help="Server to execute on. If not specified, executes on the server that has the matching service.",
)
@async_entrypoint(blocking=True)
async def disable(
    match: str,
    timers: bool = False,
    services: bool = False,
    server: Optional[str] = None,
):
    """Disable services/timers on specified server."""
    kwargs = {"match": match}
    if timers:
        kwargs["timers"] = timers
    if services:
        kwargs["services"] = services

    results = await execute_command_on_servers("disable", servers=server, **kwargs)
    for hostname, result in results.items():
        # Tables already have Host column, Text results need hostname prefix
        if isinstance(result, Table):
            result.console()
        else:
            click.echo(f"{hostname}:")
            result.console()


@cli.command
@click.argument("match", required=True)
@click.option(
    "--server",
    "-s",
    help="Server to execute on. If not specified, executes on the server that has the matching service.",
)
@async_entrypoint(blocking=True)
async def remove(match: str, server: Optional[str] = None):
    """Remove services/timers on specified server."""
    results = await execute_command_on_servers("remove", servers=server, match=match)
    for hostname, result in results.items():
        # Tables already have Host column, Text results need hostname prefix
        if isinstance(result, Table):
            result.console()
        else:
            click.echo(f"{hostname}:")
            result.console()


@cli.command
@click.argument("match", required=True)
@click.option(
    "--server",
    "-s",
    multiple=True,
    help="Server(s) to query. Can be specified multiple times. If not specified, queries all registered servers.",
)
@async_entrypoint(blocking=True)
async def show(match: str, server: tuple = ()):
    """Show service file contents from specified servers."""
    results = await execute_command_on_servers("show", servers=server, match=match)
    for hostname, result in results.items():
        # Tables already have Host column, Text results need hostname prefix
        if isinstance(result, Table):
            result.console()
        else:
            click.echo(f"{hostname}:")
            result.console()


def table_column_colors():
    """
    Returns a function that assigns colors to table columns.

    This function uses a cycle of predefined colors and a least-recently-used
    cache to generate a consistent color for each column name. The colors are
    cycled through as column names are provided.

    Returns:
        A function that takes a column name as input and returns a color string.
    """

    colors_gen = cycle(
        [
            "cyan",
            "light_steel_blue",
            "orchid",
            "magenta",
            "dodger_blue1",
        ]
    )

    @lru_cache
    def column_color(col_name: str) -> str:
        _ = col_name  # Parameter required for LRU cache key
        return next(colors_gen)

    return column_color
