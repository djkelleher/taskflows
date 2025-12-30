"""Named environment management for storing reusable Venv/DockerContainer configurations."""
import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel

from taskflows.common import logger, services_data_dir
from taskflows.service import Venv
from taskflows.docker import DockerContainer, Volume

# File path
environments_file = services_data_dir / "environments.json"


class NamedEnvironment(BaseModel):
    """Named environment configuration storing a full Venv or DockerContainer."""

    name: str
    description: Optional[str] = None
    type: Literal["venv", "docker"]
    environment: Dict[str, Any]  # Serialized Venv or DockerContainer
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


def _serialize_environment(env: Union[Venv, DockerContainer]) -> Dict[str, Any]:
    """Serialize a Venv or DockerContainer to a dict, filtering None values."""
    data = asdict(env)
    # Filter out None values for cleaner JSON
    return {k: v for k, v in data.items() if v is not None}


def _deserialize_environment(data: Dict[str, Any], env_type: str) -> Union[Venv, DockerContainer]:
    """Reconstruct a Venv or DockerContainer from serialized data."""
    if env_type == "venv":
        return Venv(env_name=data["env_name"])
    else:
        # Handle Volume objects specially - they're nested dataclasses
        if "volumes" in data and data["volumes"]:
            volumes = []
            for v in data["volumes"]:
                if isinstance(v, dict):
                    volumes.append(Volume(**v))
                else:
                    volumes.append(v)
            data["volumes"] = volumes
        return DockerContainer(**data)


def load_environments() -> Dict[str, NamedEnvironment]:
    """Load all named environments from file."""
    if environments_file.exists():
        env_data = json.loads(environments_file.read_text())
        return {name: NamedEnvironment(**data) for name, data in env_data.items()}
    return {}


def save_environments(environments: Dict[str, NamedEnvironment]) -> None:
    """Save all environments to file."""
    environments_file.parent.mkdir(parents=True, exist_ok=True)
    env_data = {name: env.model_dump(mode="json") for name, env in environments.items()}
    environments_file.write_text(json.dumps(env_data, indent=2, default=str))


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
    environments = load_environments()

    if env.name in environments:
        raise ValueError(f"Environment '{env.name}' already exists")

    # Validate based on type
    if env.type == "venv":
        if "env_name" not in env.environment:
            raise ValueError("env_name is required for venv type")
    elif env.type == "docker":
        if "image" not in env.environment:
            raise ValueError("image is required for docker type")

    # Set timestamps
    now = datetime.now(timezone.utc)
    env.created_at = now
    env.updated_at = now

    environments[env.name] = env
    save_environments(environments)

    logger.info(f"Created environment '{env.name}' (type: {env.type})")
    return env


def update_environment(name: str, updated_env: NamedEnvironment) -> NamedEnvironment:
    """Update an existing environment."""
    environments = load_environments()

    if name not in environments:
        raise ValueError(f"Environment '{name}' not found")

    # Preserve created_at, update updated_at
    updated_env.created_at = environments[name].created_at
    updated_env.updated_at = datetime.now(timezone.utc)

    # If name changed, remove old entry
    if name != updated_env.name:
        del environments[name]

    environments[updated_env.name] = updated_env
    save_environments(environments)

    logger.info(f"Updated environment '{updated_env.name}'")
    return updated_env


def delete_environment(name: str) -> None:
    """Delete an environment."""
    environments = load_environments()

    if name not in environments:
        raise ValueError(f"Environment '{name}' not found")

    del environments[name]
    save_environments(environments)

    logger.info(f"Deleted environment '{name}'")


def list_environments() -> List[NamedEnvironment]:
    """List all environments."""
    environments = load_environments()
    return list(environments.values())


def find_services_using_environment(env_name: str) -> List[str]:
    """Find all services that reference a given environment.

    This requires scanning service files for environment references.
    Returns a list of service names.
    """
    # TODO: Implement service file scanning
    # For now, return empty list
    # In the future, scan service files or maintain a registry
    return []
