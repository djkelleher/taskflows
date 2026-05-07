"""Named environment management for storing reusable Venv/DockerContainer configurations.

This module provides functionality to create, store, and manage named environments
(Venv or DockerContainer configurations) that can be referenced by services.

Uses the general-purpose serialization module for YAML/JSON support.
"""

import json
import re
import shlex
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel

from taskflows.common import logger, secure_write_text, services_data_dir
from taskflows.service import Venv
from taskflows.docker import DockerContainer
from taskflows.serialization import to_dict, from_dict, serialize, deserialize

# File path
environments_file = services_data_dir / "environments.json"
_environments_lock = threading.RLock()
_ENVIRONMENT_NAME_RE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9_.-]*[A-Za-z0-9]$|^[A-Za-z0-9]$"
)


@contextmanager
def _locked_environments(write: bool = False):
    lock_path = environments_file.with_suffix(environments_file.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with _environments_lock:
        with open(lock_path, "a+") as lock_file:
            try:
                import fcntl

                lock_mode = fcntl.LOCK_EX if write else fcntl.LOCK_SH
                fcntl.flock(lock_file.fileno(), lock_mode)
            except ImportError:
                fcntl = None

            try:
                environments = _load_environments_unlocked()
                yield environments
                if write:
                    save_environments(environments)
            finally:
                if fcntl is not None:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


class NamedEnvironment(BaseModel):
    """Named environment configuration storing a full Venv or DockerContainer."""

    name: str
    description: Optional[str] = None
    type: Literal["venv", "docker"]
    environment: Dict[str, Any]  # Serialized Venv or DockerContainer
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    def to_json(self, indent: int = 2) -> str:
        """Serialize this environment to JSON."""
        return serialize(self, format="json", indent=indent)

    def to_yaml(self) -> str:
        """Serialize this environment to YAML."""
        return serialize(self, format="yaml")

    @classmethod
    def from_json(cls, data: str) -> "NamedEnvironment":
        """Deserialize a NamedEnvironment from JSON."""
        return deserialize(data, cls, format="json")

    @classmethod
    def from_yaml(cls, data: str) -> "NamedEnvironment":
        """Deserialize a NamedEnvironment from YAML."""
        return deserialize(data, cls, format="yaml")


def _serialize_environment(env: Union[Venv, DockerContainer]) -> Dict[str, Any]:
    """Serialize a Venv or DockerContainer to a dict, filtering None values."""
    data = to_dict(env, include_none=False)
    # Remove type as we track type separately in NamedEnvironment
    data.pop("type", None)
    return data


def _deserialize_environment(
    data: Dict[str, Any], env_type: str
) -> Union[Venv, DockerContainer]:
    """Reconstruct a Venv or DockerContainer from serialized data."""
    if env_type == "venv":
        return from_dict(data, Venv)
    if env_type == "docker":
        return from_dict(data, DockerContainer)
    raise ValueError(f"Unknown environment type: {env_type!r}")


def _validate_environment_name(name: str) -> str:
    """Validate a named environment identifier."""
    if name is None:
        raise ValueError("Environment name cannot be None")
    if not isinstance(name, str):
        raise TypeError(f"Environment name must be a string, got {type(name).__name__}")
    if not name:
        raise ValueError("Environment name cannot be empty")
    if name != name.strip():
        raise ValueError("Environment name cannot start or end with whitespace")
    if ".." in name or "/" in name or "\\" in name:
        raise ValueError(f"Environment name cannot contain path separators: {name!r}")
    if not _ENVIRONMENT_NAME_RE.match(name):
        raise ValueError(
            "Environment names must start and end with a letter or number, "
            "and contain only letters, numbers, dots, dashes, and underscores."
        )
    return name


def load_environments() -> Dict[str, NamedEnvironment]:
    """Load all named environments from file."""
    with _locked_environments(write=False) as environments:
        return dict(environments)


def _load_environments_unlocked() -> Dict[str, NamedEnvironment]:
    if not environments_file.exists():
        return {}
    try:
        env_data = json.loads(environments_file.read_text())
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"Environment registry {environments_file} is not valid JSON; refusing to overwrite it"
        ) from exc
    if not isinstance(env_data, dict):
        raise RuntimeError(
            f"Environment registry {environments_file} must contain a JSON object"
        )
    environments = {}
    for name, data in env_data.items():
        _validate_environment_name(name)
        env = NamedEnvironment(**data)
        _validate_environment_definition(env)
        if env.name != name:
            raise RuntimeError(
                f"Environment registry key {name!r} does not match payload name {env.name!r}"
            )
        environments[name] = env
    return environments


def _validate_environment_definition(env: NamedEnvironment) -> None:
    """Validate the serialized environment payload matches its declared type."""
    env.name = _validate_environment_name(env.name)
    if env.type == "venv":
        if "env_name" not in env.environment:
            raise ValueError("env_name is required for venv type")
    elif env.type == "docker":
        if "image" not in env.environment:
            raise ValueError("image is required for docker type")


def save_environments(environments: Dict[str, NamedEnvironment]) -> None:
    """Save all environments to file."""
    env_data = {name: env.model_dump(mode="json") for name, env in environments.items()}
    with _environments_lock:
        secure_write_text(
            environments_file, json.dumps(env_data, indent=2, default=str)
        )


def get_environment(name: str) -> Optional[NamedEnvironment]:
    """Get a named environment by name."""
    environments = load_environments()
    return environments.get(name)


def get_environment_object(name: str) -> Optional[Union[Venv, DockerContainer]]:
    """Get the actual Venv or DockerContainer object for a named environment."""
    named_env = get_environment(name)
    if not named_env:
        return None
    return _deserialize_environment(named_env.environment, named_env.type)


def create_environment(env: NamedEnvironment) -> NamedEnvironment:
    """Create a new named environment."""
    with _locked_environments(write=True) as environments:
        if env.name in environments:
            raise ValueError(f"Environment '{env.name}' already exists")

        _validate_environment_definition(env)

        # Set timestamps
        now = datetime.now(timezone.utc)
        env.created_at = now
        env.updated_at = now

        environments[env.name] = env

    logger.info(f"Created environment '{env.name}' (type: {env.type})")
    return env


def update_environment(name: str, updated_env: NamedEnvironment) -> NamedEnvironment:
    """Update an existing environment."""
    with _locked_environments(write=True) as environments:
        if name not in environments:
            raise ValueError(f"Environment '{name}' not found")
        if name != updated_env.name and updated_env.name in environments:
            raise ValueError(f"Environment '{updated_env.name}' already exists")
        _validate_environment_definition(updated_env)

        # Preserve created_at, update updated_at
        updated_env.created_at = environments[name].created_at
        updated_env.updated_at = datetime.now(timezone.utc)

        # If name changed, remove old entry
        if name != updated_env.name:
            del environments[name]

        environments[updated_env.name] = updated_env

    logger.info(f"Updated environment '{updated_env.name}'")
    return updated_env


def delete_environment(name: str) -> None:
    """Delete an environment."""
    with _locked_environments(write=True) as environments:
        if name not in environments:
            raise ValueError(f"Environment '{name}' not found")

        del environments[name]

    logger.info(f"Deleted environment '{name}'")


def list_environments() -> List[NamedEnvironment]:
    """List all environments."""
    environments = load_environments()
    return list(environments.values())


def _unit_uses_environment(unit_content: str, env_name: str) -> bool:
    expected = f"TASKFLOWS_NAMED_ENV={env_name}"
    for line in unit_content.splitlines():
        if not line.startswith("Environment="):
            continue
        try:
            assignments = shlex.split(line[len("Environment=") :])
        except ValueError:
            continue
        if expected in assignments:
            return True
    return False


def find_services_using_environment(env_name: str) -> List[str]:
    """Find all services that reference a given environment.

    Services created from named environments include a marker environment
    variable in their systemd unit so environment deletion can be blocked.
    Returns a list of service names.
    """
    from taskflows.common import _SYSTEMD_FILE_PREFIX, extract_service_name, systemd_dir

    services = []
    for unit_file in systemd_dir.glob(f"{_SYSTEMD_FILE_PREFIX}*.service"):
        try:
            if _unit_uses_environment(unit_file.read_text(), env_name):
                services.append(extract_service_name(unit_file))
        except OSError as exc:
            logger.warning(f"Could not inspect service unit {unit_file}: {exc}")
    return sorted(set(services))
