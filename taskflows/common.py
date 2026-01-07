import logging
import os
import re
from collections import defaultdict
from pathlib import Path
from typing import List, Optional

from .loggers import get_logger
from pydantic_settings import BaseSettings, SettingsConfigDict
from textdistance import lcsseq

# Set default logging configuration if not already set
# This ensures logs go to both terminal and file by default
# CLI will override these to disable terminal output
_default_data_dir = Path.home() / ".taskflows" / "data"
if 'TASKFLOWS_FILE_DIR' not in os.environ:
    os.environ['TASKFLOWS_FILE_DIR'] = str(_default_data_dir / "logs")
if 'TASKFLOWS_NO_TERMINAL' not in os.environ:
    os.environ['TASKFLOWS_NO_TERMINAL'] = '0'  # Enable terminal by default

# Initialize logger - it will use environment variables set above
logger = get_logger("taskflows")

# _SYSTEMD_FILE_PREFIX = "taskflows-"
_SYSTEMD_FILE_PREFIX = "taskflows-"

# Allow configuring data directory via environment variable for testing
services_data_dir = Path(os.environ.get("TASKFLOWS_DATA_DIR", str(_default_data_dir)))
services_data_dir.mkdir(parents=True, exist_ok=True)

systemd_dir = Path.home().joinpath(".config", "systemd", "user")


class Config(BaseSettings):
    """S3 configuration. Variables will be loaded from environment variables if set."""

    display_timezone: str = "UTC"
    fluent_bit: str = "localhost:24224"
    grafana: str = "localhost:3000"
    grafana_api_key: Optional[str] = "glsa_eNGkj4CK08K3Huj4UyuS5TfD0eCcHOoZ_633dd6e8"
    loki_url: str = "http://localhost:3100"

    model_config = SettingsConfigDict(env_prefix="taskflows_")


config = Config()


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

    # Normalize non-stop service names by replacing hyphens and underscores with spaces for similarity comparison
    non_stop_services: List[tuple[str, str]] = [
        (s, s.replace("-", " ").replace("_", " ")) for s in non_stop_services_raw
    ]

    # Start the ordering process with the first non-stop service
    if not non_stop_services:
        # No non-stop services, just return the stop services or all services
        return services
    srv, filt_srv = non_stop_services.pop(0)
    ordered = [srv]

    # Continue ordering the remaining non-stop services
    while non_stop_services:
        # Find the service with the greatest similarity to the current service
        best = max(non_stop_services, key=lambda o: lcsseq.similarity(filt_srv, o[1]))

        # Update the current service and filtered service to the best match found
        srv, filt_srv = best

        # Remove the matched service from the list and append it to the ordered list
        non_stop_services.remove(best)
        ordered.append(srv)

        # Check if the corresponding stop service exists and append it if found
        if (stp_srv := f"{stop_prefix}{srv}") in stop_services:
            ordered.append(stp_srv)

    # Return the fully ordered list of services
    return ordered  # Return the fully ordered list of services


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
        srv_name = re.sub(f"^(?:stop-)?{_SYSTEMD_FILE_PREFIX}", "", file.stem)
        srv_files[srv_name].append(
            {"path": str(file), "content": file.read_text(), "name": file.name}
        )
    return srv_files


def extract_service_name(unit: str | Path) -> str:
    return re.sub(f"^{_SYSTEMD_FILE_PREFIX}", "", Path(unit).stem)
