import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from .common import logger, services_data_dir

# JSON file for server registry (replaces servers_table)
_servers_file = services_data_dir / "servers.json"


def _load_servers() -> Dict[str, Any]:
    """Load servers from JSON file."""
    if not _servers_file.exists():
        return {}
    try:
        return json.loads(_servers_file.read_text())
    except Exception as e:
        logger.error(f"Error loading servers file: {e}")
        return {}


def _save_servers(servers: Dict[str, Any]) -> None:
    """Save servers to JSON file."""
    try:
        _servers_file.write_text(json.dumps(servers, indent=2, default=str))
    except Exception as e:
        logger.error(f"Error saving servers file: {e}")


def get_servers() -> List[Dict[str, Any]]:
    """Get list of all registered servers."""
    servers = _load_servers()
    return [
        {
            "hostname": hostname,
            "public_ipv4": data["public_ipv4"],
            "last_updated": data["last_updated"],
        }
        for hostname, data in sorted(servers.items())
    ]


def upsert_server(hostname: str, public_ipv4: str) -> None:
    """Add or update a server in the registry."""
    servers = _load_servers()
    servers[hostname] = {
        "public_ipv4": public_ipv4,
        "last_updated": datetime.now(timezone.utc).isoformat(),
    }
    _save_servers(servers)
    logger.info(f"Updated server info: hostname={hostname}, public_ipv4={public_ipv4}")


def remove_server(hostname: str) -> bool:
    """Remove a server from the registry."""
    servers = _load_servers()
    if hostname in servers:
        del servers[hostname]
        _save_servers(servers)
        return True
    return False
