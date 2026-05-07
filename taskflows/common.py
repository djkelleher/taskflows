import os
import re
import stat
import tempfile
from collections import defaultdict
from collections.abc import Mapping
from contextlib import suppress
from pathlib import Path
from typing import Any, List, Optional

from .loggers import get_logger
from pydantic_settings import BaseSettings, SettingsConfigDict
from textdistance import lcsseq

# Set default logging configuration if not already set
# This ensures logs go to both terminal and file by default
# CLI will override these to disable terminal output
_default_data_dir = Path.home() / ".taskflows" / "data"
if "TASKFLOWS_FILE_DIR" not in os.environ:
    os.environ["TASKFLOWS_FILE_DIR"] = str(_default_data_dir / "logs")
if "TASKFLOWS_NO_TERMINAL" not in os.environ:
    os.environ["TASKFLOWS_NO_TERMINAL"] = "0"  # Enable terminal by default

# Initialize logger - it will use environment variables set above
logger = get_logger("taskflows")

_SYSTEMD_FILE_PREFIX = "taskflows-"

# Allow configuring data directory via environment variable for testing
services_data_dir = Path(os.environ.get("TASKFLOWS_DATA_DIR", str(_default_data_dir)))
services_data_dir.mkdir(parents=True, exist_ok=True)
try:
    os.chmod(services_data_dir, stat.S_IRWXU)
except OSError as exc:
    logger.warning(f"Could not set secure permissions on {services_data_dir}: {exc}")

systemd_dir = Path.home().joinpath(".config", "systemd", "user")


class Config(BaseSettings):
    """S3 configuration. Variables will be loaded from environment variables if set."""

    display_timezone: str = "UTC"
    fluent_bit: str = "localhost:24224"
    grafana: str = "localhost:3000"
    grafana_api_key: Optional[str] = None
    loki_url: str = "http://localhost:3100"

    model_config = SettingsConfigDict(env_prefix="taskflows_")


config = Config()


def secure_write_text(
    path: Path,
    content: str,
    mode: int = stat.S_IRUSR | stat.S_IWUSR,
    *,
    secure_parent: bool = False,
) -> None:
    """Atomically write a text file with owner-only permissions."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if secure_parent:
        try:
            os.chmod(path.parent, stat.S_IRWXU)
        except OSError as exc:
            logger.warning(f"Could not set secure permissions on {path.parent}: {exc}")

    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(content)
        os.chmod(tmp_path, mode)
        os.replace(tmp_path, path)
        os.chmod(path, mode)
    finally:
        if tmp_path.exists():
            with suppress(OSError):
                tmp_path.unlink()


_SENSITIVE_KEY_PARTS = (
    "authorization",
    "body",
    "content",
    "credential",
    "jwt",
    "key",
    "password",
    "secret",
    "token",
    "yaml_content",
)


def redact_sensitive(value: Any) -> Any:
    """Return a copy of value with secret-like fields redacted for logs."""
    if isinstance(value, Mapping):
        redacted = {}
        for key, item in value.items():
            key_text = str(key).lower()
            if any(part in key_text for part in _SENSITIVE_KEY_PARTS):
                redacted[key] = "<redacted>"
            else:
                redacted[key] = redact_sensitive(item)
        return redacted
    if isinstance(value, list):
        return [redact_sensitive(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_sensitive(item) for item in value)
    if isinstance(value, set):
        return {redact_sensitive(item) for item in value}
    return value


def logql_string(value: str) -> str:
    """Return value escaped as a LogQL double-quoted string."""
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def sort_service_names(services: List[str]) -> List[str]:
    """
    Sort service names to display in a list.

    This function takes a list of service names and sorts them intelligently,
    grouping stop services with their corresponding main services. The sorting
    uses text similarity to order related services together.

    Args:
        services (List[str]): A list of service names to sort.

    Returns:
        List[str]: A sorted list where stop services appear immediately after
                  their corresponding main services, ordered by similarity.

    The sorting algorithm:
    1. Separates services into stop services (prefixed with "stop-{prefix}") and regular services
    2. Normalizes service names by replacing hyphens and underscores with spaces
    3. Orders services by text similarity using longest common subsequence
    4. Places stop services immediately after their corresponding main services
    """
    # Define the prefix used for stopped services
    stop_prefix = f"stop-{_SYSTEMD_FILE_PREFIX}"

    # Separate services into two categories: those that start with the stop prefix and those that do not
    stop_services: List[str] = []
    non_stop_services_raw: List[str] = []
    for srv in services:
        if srv.startswith(stop_prefix):
            stop_services.append(srv)
        else:
            non_stop_services_raw.append(srv)
    remaining_stop_services = stop_services.copy()

    # Normalize non-stop service names by replacing hyphens and underscores with spaces for similarity comparison
    non_stop_services: List[tuple[str, str]] = [
        (s, s.replace("-", " ").replace("_", " ")) for s in non_stop_services_raw
    ]

    # Start the ordering process with the first non-stop service
    if not non_stop_services:
        # No non-stop services, just return the stop services or all services
        return services

    def append_with_stop(service_name: str) -> None:
        ordered.append(service_name)
        stop_service = f"{stop_prefix}{service_name}"
        if stop_service in remaining_stop_services:
            ordered.append(stop_service)
            remaining_stop_services.remove(stop_service)

    srv, filt_srv = non_stop_services.pop(0)
    ordered = []
    append_with_stop(srv)

    # Continue ordering the remaining non-stop services
    while non_stop_services:
        # Find the service with the greatest similarity to the current service
        best = max(non_stop_services, key=lambda o: lcsseq.similarity(filt_srv, o[1]))

        # Update the current service and filtered service to the best match found
        srv, filt_srv = best

        # Remove the matched service from the list and append it to the ordered list
        non_stop_services.remove(best)
        append_with_stop(srv)

    ordered.extend(remaining_stop_services)
    return ordered


def load_service_files(files: List[Path]) -> dict:
    """Load service files from paths.

    Args:
        files: List of service file paths

    Returns:
        Dictionary mapping service names to list of file info dicts
    """
    srv_files = defaultdict(list)
    for file in files:
        file = Path(file)
        srv_name = extract_service_name(file)
        srv_files[srv_name].append(
            {"path": str(file), "content": file.read_text(), "name": file.name}
        )
    return srv_files


def extract_service_name(unit: str | Path) -> str:
    prefix_pattern = re.escape(_SYSTEMD_FILE_PREFIX)
    return re.sub(rf"^(?:(?:stop|restart)-)?{prefix_pattern}", "", Path(unit).stem)
