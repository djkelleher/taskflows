import json
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
import ipaddress
from typing import Any, Dict, List

from .common import logger, secure_write_text, services_data_dir

# JSON file for server registry (replaces servers_table)
_servers_file = services_data_dir / "servers.json"
_servers_lock = threading.RLock()


@contextmanager
def _locked_servers(write: bool = False):
    lock_file_path = _servers_file.with_suffix(_servers_file.suffix + ".lock")
    lock_file_path.parent.mkdir(parents=True, exist_ok=True)
    with _servers_lock:
        with open(lock_file_path, "a+") as lock_file:
            try:
                import fcntl

                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            except ImportError:
                fcntl = None

            try:
                servers = _load_servers_unlocked()
                yield servers
                if write:
                    secure_write_text(
                        _servers_file, json.dumps(servers, indent=2, default=str)
                    )
            finally:
                if fcntl is not None:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _load_servers_unlocked() -> Dict[str, Any]:
    if not _servers_file.exists():
        return {}
    try:
        data = json.loads(_servers_file.read_text())
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"Server registry {_servers_file} is not valid JSON; refusing to overwrite it"
        ) from e
    if not isinstance(data, dict):
        raise RuntimeError(
            f"Server registry {_servers_file} must contain a JSON object"
        )
    for hostname, record in data.items():
        _validate_server_record(hostname, record)
    return data


def _load_servers() -> Dict[str, Any]:
    """Load servers from JSON file."""
    with _locked_servers(write=False) as servers:
        return dict(servers)


def _validate_server_hostname(hostname: str) -> str:
    if hostname is None:
        raise ValueError("Server hostname cannot be None")
    if not isinstance(hostname, str):
        raise TypeError(
            f"Server hostname must be a string, got {type(hostname).__name__}"
        )
    if not hostname.strip():
        raise ValueError("Server hostname cannot be empty")
    if hostname != hostname.strip():
        raise ValueError("Server hostname cannot start or end with whitespace")
    return hostname


def _validate_public_ipv4(public_ipv4: str) -> str:
    if public_ipv4 is None:
        raise ValueError("Server public_ipv4 cannot be None")
    if not isinstance(public_ipv4, str):
        raise TypeError(
            f"Server public_ipv4 must be a string, got {type(public_ipv4).__name__}"
        )
    try:
        parsed_ip = ipaddress.ip_address(public_ipv4)
    except ValueError as exc:
        raise ValueError(
            f"Server public_ipv4 is not a valid IP address: {public_ipv4!r}"
        ) from exc
    if parsed_ip.version != 4:
        raise ValueError(f"Server public_ipv4 must be IPv4, got {public_ipv4!r}")
    return public_ipv4


def _validate_server_record(hostname: str, record: Any) -> None:
    _validate_server_hostname(hostname)
    if not isinstance(record, dict):
        raise RuntimeError(f"Server registry entry for {hostname!r} must be an object")
    if "public_ipv4" not in record or "last_updated" not in record:
        raise RuntimeError(
            f"Server registry entry for {hostname!r} must contain public_ipv4 and last_updated"
        )
    _validate_public_ipv4(record["public_ipv4"])


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
    hostname = _validate_server_hostname(hostname)
    public_ipv4 = _validate_public_ipv4(public_ipv4)
    with _locked_servers(write=True) as servers:
        servers[hostname] = {
            "public_ipv4": public_ipv4,
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }
    logger.info(f"Updated server info: hostname={hostname}, public_ipv4={public_ipv4}")


def remove_server(hostname: str) -> bool:
    """Remove a server from the registry."""
    hostname = _validate_server_hostname(hostname)
    with _locked_servers(write=True) as servers:
        if hostname in servers:
            del servers[hostname]
            return True
        return False
