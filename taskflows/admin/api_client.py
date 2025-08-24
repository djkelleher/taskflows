
from typing import Dict, Optional

from alert_msgs.components import (CodeBlock, Map, MsgComp, StatusIndicator,
                                   Table, Text)
from taskflows.admin.common import call_api, list_servers


def api_health(host: Optional[str] = None) -> StatusIndicator:
    """Call the /health endpoint and return a StatusIndicator component.

    Args:
        base_url (str): Base URL of the admin API server

    Returns:
        StatusIndicator: Component showing health status
    """
    # health does not require auth; call_api skips HMAC for /health

    data = call_api(host, "/health", method="GET", timeout=10)
    if "error" in data:
        return StatusIndicator(f"Service Error: {data['error']}", color="red")
    elif data.get("status") == "ok":
        return StatusIndicator("Service Healthy", color="green")
    else:
        return StatusIndicator("Service Unhealthy", color="red")


def api_list_servers(host: Optional[str] = None) -> Table:
    """Call the /list-servers endpoint and return a Table component.

    Args:
        base_url (str): Base URL of the admin API server

    Returns:
        Table: Table showing registered servers
    """
    data = call_api(host, "/list-servers", method="GET", timeout=10)
    if "error" in data:
        return Table([{"Error": data["error"]}], title="Server List - Error")

    servers = data.get("servers", [])
    if not servers:
        return Table([], title="Registered Servers (None)")

    return Table(
        servers, title=f"Registered Servers ({data.get('count', len(servers))})"
    )


def api_history(
    host: Optional[str] = None, limit: int = 3, match: Optional[str] = None
) -> Table:
    """Call the /history endpoint and return a Table component.

    Args:
        base_url (str): Base URL of the admin API server
        limit (int): Number of recent task runs to show
        match (str): Optional pattern to filter task names

    Returns:
        Table: Table showing task run history
    """
    params = {"limit": limit}
    if match:
        params["match"] = match
    data = call_api(host, "/history", method="GET", params=params, timeout=10)
    if "error" in data:
        return Table([{"Error": data["error"]}], title="Task History - Error")

    history = data.get("history", [])
    title = f"Task History (Last {limit})"
    if match:
        title += f" - Matching '{match}'"

    if not history:
        return Table([], title=f"{title} (None)")

    return Table(history, title=title)


def api_list_services(
    host: Optional[str] = None, match: Optional[str] = None
) -> Table:
    """Call the /list endpoint and return a Table component.

    Args:
        base_url (str): Base URL of the admin API server
        match (str): Optional pattern to filter services

    Returns:
        Table: Table showing available services
    """
    params = {}
    if match:
        params["match"] = match
    data = call_api(host, "/list", method="GET", params=params, timeout=10)
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


def api_status(
    host: Optional[str] = None, match: Optional[str] = None, running: bool = False
) -> Table:
    """Call the /status endpoint and return a Table component.

    Args:
        base_url (str): Base URL of the admin API server
        match (str): Optional pattern to filter services
        running (bool): Only show running services

    Returns:
        Table: Table showing service status
    """
    params = {"running": running}
    if match:
        params["match"] = match
    data = call_api(host, "/status", method="GET", params=params, timeout=10)

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
        base_url (str): Base URL of the admin API server
        service_name (str): Name of the service to get logs for
        n_lines (int): Number of log lines to return.

    Returns:
        CodeBlock: Component showing service logs
    """
    if not service_name:
        return CodeBlock("Error: service_name is required", language="text")

    params = {"n_lines": n_lines} if n_lines else {}
    data = call_api(host, f"/logs/{service_name}", method="GET", timeout=30, params=params)
    if "error" in data:
        return CodeBlock(f"Error fetching logs: {data['error']}", language="text")

    logs = data.get("logs", "No logs available")
    return CodeBlock(logs, language="text", show_line_numbers=False)


def api_show(host: Optional[str] = None, match: Optional[str] = None) -> Table:
    """Call the /show/{match} endpoint and return a Table component.

    Args:
        base_url (str): Base URL of the admin API server
        match (str): Name or pattern of services to show

    Returns:
        Table: Table showing service file contents
    """
    if not match:
        return Table(
            [{"Error": "match parameter is required"}], title="Service Files - Error"
        )

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
        base_url (str): Base URL of the admin API server
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
        base_url (str): Base URL of the admin API server
        match (str): Pattern to match services/timers
        timers (bool): Whether to start timers
        services (bool): Whether to start services

    Returns:
        Table: Component showing started items
    """
    if not match:
        return Table([{"Error": "match parameter is required"}], title="Start - Error")

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
        base_url (str): Base URL of the admin API server
        match (str): Pattern to match services/timers
        timers (bool): Whether to stop timers
        services (bool): Whether to stop services

    Returns:
        Table: Component showing stopped items
    """
    if not match:
        return Table([{"Error": "match parameter is required"}], title="Stop - Error")

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
        base_url (str): Base URL of the admin API server
        match (str): Pattern to match services

    Returns:
        Table: Component showing restarted items
    """
    if not match:
        return Table(
            [{"Error": "match parameter is required"}], title="Restart - Error"
        )

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
        base_url (str): Base URL of the admin API server
        match (str): Pattern to match services/timers
        timers (bool): Whether to enable timers
        services (bool): Whether to enable services

    Returns:
        Table: Component showing enabled items
    """
    if not match:
        return Table([{"Error": "match parameter is required"}], title="Enable - Error")

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
        base_url (str): Base URL of the admin API server
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
        base_url (str): Base URL of the admin API server
        match (str): Pattern to match services

    Returns:
        Table: Component showing removed items
    """
    if not match:
        return Table([{"Error": "match parameter is required"}], title="Remove - Error")

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
                 If None/empty, defaults to localhost:7777.
        **kwargs: JSON parameters to forward to the API

    Returns:
        Dictionary mapping hostname to MsgComp response
    """
    # Normalize servers argument
    if not servers:
        servers = [{"address": "localhost:7777"}]
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
        servers = normalized or [{"address": "localhost:7777"}]
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
        hostname = server["address"]
        # pass hostname (normalized) directly as host parameter
        results[hostname] = func(host=hostname, **kwargs)

    return results
    return results
