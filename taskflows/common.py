import os
import re
import stat
import tempfile
from collections import defaultdict
from collections.abc import Iterable, Mapping
from contextlib import suppress
from pathlib import Path
from typing import Any

from pydantic_settings import BaseSettings, SettingsConfigDict

from .loggers import get_logger

# Logging is configured entirely from environment variables (TASKFLOWS_LOG_LEVEL,
# TASKFLOWS_NO_TERMINAL, TASKFLOWS_FILE_DIR, or their LOGGERS_ fallbacks). No log
# files are written unless TASKFLOWS_FILE_DIR is set.
logger = get_logger("taskflows")

_SYSTEMD_FILE_PREFIX = "taskflows-"

_default_data_dir = Path.home() / ".taskflows" / "data"

# Allow configuring data directory via environment variable for testing
services_data_dir = Path(os.environ.get("TASKFLOWS_DATA_DIR", str(_default_data_dir)))

systemd_dir = Path.home().joinpath(".config", "systemd", "user")


def ensure_data_dir() -> Path:
    """Create the taskflows data directory with owner-only permissions.

    Called by code that writes state files; importing taskflows performs no
    filesystem writes.
    """
    services_data_dir.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(services_data_dir, stat.S_IRWXU)
    except OSError as exc:
        logger.warning(f"Could not set secure permissions on {services_data_dir}: {exc}")
    return services_data_dir


class Config(BaseSettings):
    """taskflows settings, loaded from TASKFLOWS_-prefixed environment variables."""

    display_timezone: str = "UTC"
    # default log driver for Docker containers (e.g. "fluentd"); None uses Docker's default
    docker_log_driver: str | None = None
    fluent_bit: str = "localhost:24224"
    grafana: str = "localhost:3000"
    grafana_api_key: str | None = None
    loki_url: str = "http://localhost:3100"

    model_config = SettingsConfigDict(env_prefix="taskflows_")


config = Config()


def grafana_configured() -> bool:
    """True when Grafana/Loki has been explicitly configured.

    Used to decide whether alerts should include Grafana Explore log URLs;
    the localhost defaults alone don't count as configured (they would
    produce dead links on machines without the observability stack).
    """
    if config.grafana_api_key:
        return True
    return any(key.upper() in ("TASKFLOWS_GRAFANA", "TASKFLOWS_LOKI_URL") for key in os.environ)


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


def sort_service_names(services: Iterable[str]) -> list[str]:
    """Naturally order names while keeping raw stop units beside their service.

    The previous nearest-neighbour LCS sort was quadratic and dominated
    `tf list`/`tf status` at a few hundred services. This key-based ordering is
    deterministic and O(n log n).
    """
    stop_prefix = f"stop-{_SYSTEMD_FILE_PREFIX}"

    def natural_key(value: str) -> tuple[tuple[bool, int | str], ...]:
        return tuple(
            (part.isdigit(), int(part) if part.isdigit() else part.casefold())
            for part in re.split(r"(\d+)", value)
            if part
        )

    def key(value: str):
        is_stop = value.startswith(stop_prefix)
        base = value.removeprefix(stop_prefix) if is_stop else value
        return natural_key(base), is_stop, natural_key(value)

    return sorted(services, key=key)


def load_service_files(files: list[Path]) -> dict:
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
