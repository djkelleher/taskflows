"""General-purpose serialization for taskflows dataclasses and models.

Provides YAML and JSON serialization for Service, DockerContainer, Venv,
Schedule, CgroupConfig, and other taskflows types.

Usage:
    from taskflows.serialization import serialize, deserialize, load_services_from_yaml

    # Serialize a Service to JSON/YAML
    service = Service(name="my-service", start_command="python app.py")
    json_str = serialize(service, format="json")
    yaml_str = serialize(service, format="yaml")

    # Deserialize back to object
    service = deserialize(json_str, Service, format="json")
    service = deserialize(yaml_str, Service, format="yaml")

    # Load multiple services from a YAML file
    services = load_services_from_yaml("services.yaml")
    for service in services:
        await service.create()

    # Serialize to dict (for further processing)
    data = to_dict(service)
    service = from_dict(data, Service)

Human-Readable Values:
    YAML files support human-readable memory sizes and time durations:

    Memory sizes (memory_limit, memory_high, etc.):
        - "1GB", "512MB", "100KB", "1.5g"
        - Units: B, K/KB, M/MB, G/GB, T/TB

    Time durations (period, timeout, delay, etc.):
        - "1h", "30m", "5min", "300s"
        - Units: s/sec/seconds, m/min/minutes, h/hr/hours, d/day/days, w/week/weeks

    Example YAML:
        cgroup_config:
          memory_limit: 2GB
          memory_high: 1.5GB
        timeout: 5m
        restart_schedule:
          period: 1h
          start_on: boot
"""
import json
import re
from dataclasses import fields, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import (
    Any,
    Dict,
    List,
    Literal,
    Optional,
    Sequence,
    Type,
    TypeVar,
    Union,
    get_args,
    get_origin,
)

import yaml
from pydantic import BaseModel

from taskflows.common import logger


# =============================================================================
# Human-Readable Value Parsing
# =============================================================================

# Memory size units (case-insensitive)
_MEMORY_UNITS = {
    "b": 1,
    "k": 1024,
    "kb": 1024,
    "m": 1024 ** 2,
    "mb": 1024 ** 2,
    "g": 1024 ** 3,
    "gb": 1024 ** 3,
    "t": 1024 ** 4,
    "tb": 1024 ** 4,
}

# Time units in seconds
_TIME_UNITS = {
    "s": 1,
    "sec": 1,
    "second": 1,
    "seconds": 1,
    "m": 60,
    "min": 60,
    "minute": 60,
    "minutes": 60,
    "h": 3600,
    "hr": 3600,
    "hour": 3600,
    "hours": 3600,
    "d": 86400,
    "day": 86400,
    "days": 86400,
    "w": 604800,
    "week": 604800,
    "weeks": 604800,
}

# Fields that should be parsed as memory sizes
_MEMORY_FIELDS = {
    "memory_limit",
    "memory_high",
    "memory_low",
    "memory_min",
    "memory_reservation",
    "memory_swap_limit",
    "memory_swap_max",
    "mem_limit",
    "memswap_limit",
    "mem_reservation",
    "shm_size",
    "amount",  # Memory constraint amount field
}

# Fields that should be parsed as time/duration values (result in seconds)
_TIME_FIELDS = {
    "period",
    "timeout",
    "timeout_start",
    "timeout_stop",
    "delay",
    "window",
}

# Regex patterns for parsing
_MEMORY_PATTERN = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([a-zA-Z]+)?\s*$")
_TIME_PATTERN = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([a-zA-Z]+)?\s*$")


def parse_memory_size(value: Any) -> int:
    """Parse a human-readable memory size to bytes.

    Supports formats:
        - Integer: returned as-is (assumed bytes)
        - String without unit: parsed as bytes (e.g., "1073741824")
        - String with unit: parsed with unit (e.g., "1GB", "512 MB", "1.5g")

    Units (case-insensitive):
        - B: bytes
        - K, KB: kilobytes (1024 bytes)
        - M, MB: megabytes (1024^2 bytes)
        - G, GB: gigabytes (1024^3 bytes)
        - T, TB: terabytes (1024^4 bytes)

    Args:
        value: Memory size as int, float, or string.

    Returns:
        Size in bytes as integer.

    Raises:
        ValueError: If the format is invalid or unit is unknown.

    Examples:
        >>> parse_memory_size(1024)
        1024
        >>> parse_memory_size("1GB")
        1073741824
        >>> parse_memory_size("512 MB")
        536870912
        >>> parse_memory_size("1.5g")
        1610612736
    """
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return int(value)

    if not isinstance(value, str):
        raise ValueError(f"Cannot parse memory size from {type(value).__name__}: {value}")

    match = _MEMORY_PATTERN.match(value)
    if not match:
        raise ValueError(f"Invalid memory size format: {value}")

    number_str, unit = match.groups()
    number = float(number_str)

    if unit is None:
        # No unit specified, assume bytes
        return int(number)

    unit_lower = unit.lower()
    if unit_lower not in _MEMORY_UNITS:
        raise ValueError(f"Unknown memory unit '{unit}'. Valid units: {', '.join(sorted(set(_MEMORY_UNITS.keys())))}")

    return int(number * _MEMORY_UNITS[unit_lower])


def parse_time_duration(value: Any) -> int:
    """Parse a human-readable time duration to seconds.

    Supports formats:
        - Integer: returned as-is (assumed seconds)
        - String without unit: parsed as seconds (e.g., "300")
        - String with unit: parsed with unit (e.g., "5m", "1h", "30 seconds")

    Units (case-insensitive):
        - s, sec, second, seconds: seconds
        - m, min, minute, minutes: minutes (60 seconds)
        - h, hr, hour, hours: hours (3600 seconds)
        - d, day, days: days (86400 seconds)
        - w, week, weeks: weeks (604800 seconds)

    Args:
        value: Time duration as int, float, or string.

    Returns:
        Duration in seconds as integer.

    Raises:
        ValueError: If the format is invalid or unit is unknown.

    Examples:
        >>> parse_time_duration(300)
        300
        >>> parse_time_duration("5m")
        300
        >>> parse_time_duration("1h")
        3600
        >>> parse_time_duration("1.5 hours")
        5400
    """
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return int(value)

    if not isinstance(value, str):
        raise ValueError(f"Cannot parse time duration from {type(value).__name__}: {value}")

    match = _TIME_PATTERN.match(value)
    if not match:
        raise ValueError(f"Invalid time duration format: {value}")

    number_str, unit = match.groups()
    number = float(number_str)

    if unit is None:
        # No unit specified, assume seconds
        return int(number)

    unit_lower = unit.lower()
    if unit_lower not in _TIME_UNITS:
        raise ValueError(f"Unknown time unit '{unit}'. Valid units: {', '.join(sorted(set(_TIME_UNITS.keys())))}")

    return int(number * _TIME_UNITS[unit_lower])


def _maybe_parse_value(value: Any, field_name: str) -> Any:
    """Parse a value if it matches a known field that needs conversion.

    Args:
        value: The raw value.
        field_name: The field name for context.

    Returns:
        Parsed value, or original if no parsing needed.
    """
    if value is None:
        return None

    # Check if this field should be parsed as memory
    if field_name in _MEMORY_FIELDS:
        try:
            return parse_memory_size(value)
        except (ValueError, TypeError):
            # If parsing fails, return original value
            # (it might already be an int, or might be something else)
            return value

    # Check if this field should be parsed as time
    if field_name in _TIME_FIELDS:
        try:
            return parse_time_duration(value)
        except (ValueError, TypeError):
            return value

    return value

T = TypeVar("T")


# Type registry for polymorphic deserialization
_TYPE_REGISTRY: Dict[str, Type] = {}

# Field name to type mapping for automatic inference
_FIELD_TYPE_MAP: Dict[str, str] = {
    "restart_policy": "RestartPolicy",
    "cgroup_config": "CgroupConfig",
    "start_schedule": "Schedule",
    "stop_schedule": "Schedule",
    "restart_schedule": "Schedule",
}

# Keys that uniquely identify a type (for content-based inference)
_TYPE_SIGNATURE_KEYS: Dict[frozenset, str] = {
    # Venv: has env_name
    frozenset(["env_name"]): "Venv",
    # DockerContainer: has image
    frozenset(["image"]): "DockerContainer",
    # Calendar: has schedule (string pattern)
    frozenset(["schedule"]): "Calendar",
    # Periodic: has period and start_on
    frozenset(["period", "start_on"]): "Periodic",
    frozenset(["period"]): "Periodic",
    # Volume: has host_path and container_path
    frozenset(["host_path", "container_path"]): "Volume",
    # RestartPolicy: has condition (when it's a dict)
    frozenset(["condition"]): "RestartPolicy",
    # Memory constraint
    frozenset(["amount", "constraint"]): "Memory",
    # CPUPressure constraint
    frozenset(["max_percent", "timespan"]): "CPUPressure",
    frozenset(["max_percent"]): "CPUPressure",
    # CgroupConfig: has memory_limit or cpu_quota (common cgroup fields)
    frozenset(["memory_limit"]): "CgroupConfig",
    frozenset(["cpu_quota"]): "CgroupConfig",
    frozenset(["cpu_shares"]): "CgroupConfig",
    frozenset(["pids_limit"]): "CgroupConfig",
}


def _infer_type_from_content(data: Dict[str, Any], field_name: Optional[str] = None) -> Optional[str]:
    """Infer the type from dict content based on its keys.

    Args:
        data: The dictionary to analyze.
        field_name: Optional field name for context.

    Returns:
        The inferred type name, or None if can't be determined.
    """
    if not isinstance(data, dict):
        return None

    keys = set(data.keys()) - {"type"}  # Exclude type key itself

    # Check for signature keys (most specific first - larger sets)
    for signature_keys, type_name in sorted(_TYPE_SIGNATURE_KEYS.items(), key=lambda x: -len(x[0])):
        if signature_keys <= keys:
            return type_name

    # Use field name to infer type if content-based inference fails
    if field_name and field_name in _FIELD_TYPE_MAP:
        return _FIELD_TYPE_MAP[field_name]

    return None


def _infer_schedule_type(value: Any) -> Optional[str]:
    """Infer schedule type from value.

    - String with day/time pattern -> Calendar
    - Dict with 'schedule' key -> Calendar
    - Dict with 'period' key -> Periodic
    """
    if isinstance(value, str):
        # A string schedule is always Calendar format
        return "Calendar"

    if isinstance(value, dict):
        if "schedule" in value:
            return "Calendar"
        if "period" in value:
            return "Periodic"

    return None


def register_type(cls: Type) -> Type:
    """Register a type for polymorphic deserialization.

    Args:
        cls: The class to register.

    Returns:
        The same class (allows use as decorator).
    """
    _TYPE_REGISTRY[cls.__name__] = cls
    return cls


def get_registered_type(name: str) -> Optional[Type]:
    """Get a registered type by name.

    Args:
        name: The class name.

    Returns:
        The registered class, or None if not found.
    """
    return _TYPE_REGISTRY.get(name)


def _get_type_name(obj: Any) -> str:
    """Get the type name for an object."""
    return type(obj).__name__


def _is_pydantic_model(cls: Type) -> bool:
    """Check if a class is a Pydantic BaseModel."""
    try:
        return issubclass(cls, BaseModel)
    except TypeError:
        return False


def _serialize_value(value: Any, include_none: bool = False) -> Any:
    """Serialize a single value to a JSON-compatible type.

    Args:
        value: The value to serialize.
        include_none: Whether to include None values in dicts.

    Returns:
        A JSON-compatible representation of the value.
    """
    if value is None:
        return None

    # Handle datetime
    if isinstance(value, datetime):
        return {"type": "datetime", "value": value.isoformat()}

    # Handle Path
    if isinstance(value, Path):
        return str(value)

    # Handle Pydantic models
    if isinstance(value, BaseModel):
        data = value.model_dump(mode="json")
        data["type"] = _get_type_name(value)
        return _filter_none(data, include_none)

    # Handle dataclasses
    if is_dataclass(value) and not isinstance(value, type):
        data = {}
        data["type"] = _get_type_name(value)
        for field in fields(value):
            field_value = getattr(value, field.name)
            serialized = _serialize_value(field_value, include_none)
            if include_none or serialized is not None:
                data[field.name] = serialized
        return data

    # Handle callables (functions) - store reference only, not actual function
    if callable(value) and not isinstance(value, type):
        # We can't serialize arbitrary functions, but we can note their presence
        return {"type": "callable", "name": getattr(value, "__name__", "<lambda>")}

    # Handle sequences (but not strings)
    if isinstance(value, (list, tuple)):
        return [_serialize_value(v, include_none) for v in value]

    # Handle dicts
    if isinstance(value, dict):
        return {k: _serialize_value(v, include_none) for k, v in value.items()}

    # Handle sets
    if isinstance(value, set):
        return {"type": "set", "values": list(value)}

    # Primitive types pass through
    return value


def _filter_none(data: Dict[str, Any], include_none: bool) -> Dict[str, Any]:
    """Filter out None values from a dict if include_none is False."""
    if include_none:
        return data
    return {k: v for k, v in data.items() if v is not None}


def _parse_volume_string(value: str) -> Any:
    """Parse a volume string like '/host:/container' or '/host:/container:ro'.

    Supports formats:
        - "/host:/container" -> Volume(host_path="/host", container_path="/container")
        - "/host:/container:ro" -> Volume(host_path="/host", container_path="/container", read_only=True)
        - "/host:/container:rw" -> Volume(host_path="/host", container_path="/container", read_only=False)
    """
    volume_cls = get_registered_type("Volume")
    if not volume_cls:
        return value

    parts = value.rsplit(":", 2)

    if len(parts) == 3 and parts[2] in ("ro", "rw"):
        # Format: /host:/container:ro or /host:/container:rw
        host_path = parts[0]
        container_path = parts[1]
        read_only = parts[2] == "ro"
    elif len(parts) == 2:
        # Format: /host:/container
        host_path = parts[0]
        container_path = parts[1]
        read_only = False
    else:
        # Can't parse, return as-is
        return value

    return volume_cls(host_path=host_path, container_path=container_path, read_only=read_only)


def _deserialize_value(value: Any, target_type: Optional[Type] = None, field_name: Optional[str] = None) -> Any:
    """Deserialize a value from JSON-compatible format.

    Args:
        value: The value to deserialize.
        target_type: Optional type hint for the expected type.
        field_name: Optional field name for context-based inference.

    Returns:
        The deserialized Python object.
    """
    if value is None:
        return None

    # Handle string values that might need conversion based on field name
    if isinstance(value, str):
        # Schedule fields with string values are Calendar schedules
        if field_name in ("start_schedule", "stop_schedule", "restart_schedule"):
            calendar_cls = get_registered_type("Calendar")
            if calendar_cls:
                return calendar_cls(schedule=value)

        # Volume strings in format "/host:/container" or "/host:/container:ro"
        if field_name == "volumes" and ":" in value:
            volume_cls = get_registered_type("Volume")
            if volume_cls:
                return _parse_volume_string(value)
        # restart_policy as string is just a string, not RestartPolicy object
        return value

    # Handle dicts
    if isinstance(value, dict):
        # Check for explicit type first
        if "type" in value:
            type_name = value["type"]

            # Handle datetime
            if type_name == "datetime":
                return datetime.fromisoformat(value["value"])

            # Handle set
            if type_name == "set":
                return set(value["values"])

            # Handle callable placeholder
            if type_name == "callable":
                logger.warning(
                    f"Cannot deserialize callable '{value.get('name', 'unknown')}'. "
                    "Callables must be provided at runtime."
                )
                return None

            # Look up in type registry
            registered_cls = get_registered_type(type_name)
            if registered_cls:
                data = {k: v for k, v in value.items() if k != "type"}
                return from_dict(data, registered_cls)

            # If we have a target type hint, try to use it
            if target_type:
                data = {k: v for k, v in value.items() if k != "type"}
                return from_dict(data, target_type)

            # Return the dict as-is if we can't resolve the type
            logger.warning(f"Unknown type '{type_name}' during deserialization")
            return {k: v for k, v in value.items() if k != "type"}

        # No explicit type - try to infer from content
        inferred_type = _infer_type_from_content(value, field_name)

        # Special handling for schedule fields
        if field_name in ("start_schedule", "stop_schedule", "restart_schedule") and not inferred_type:
            inferred_type = _infer_schedule_type(value)

        if inferred_type:
            registered_cls = get_registered_type(inferred_type)
            if registered_cls:
                return from_dict(value, registered_cls)

        # If we have a target type hint, use it
        if target_type and target_type is not type(None):
            origin = get_origin(target_type)
            # Don't try to instantiate Union types directly
            if origin is not Union:
                try:
                    return from_dict(value, target_type)
                except (TypeError, ValueError):
                    pass

        # Return as plain dict with recursively deserialized values
        return {k: _deserialize_value(v) for k, v in value.items()}

    # Handle lists
    if isinstance(value, list):
        # Get element type from target_type if available
        element_type = None
        if target_type:
            origin = get_origin(target_type)
            if origin in (list, List, Sequence):
                args = get_args(target_type)
                if args:
                    element_type = args[0]

        # For schedule and volume lists, pass field_name for type inference
        if field_name in ("start_schedule", "stop_schedule", "restart_schedule", "volumes"):
            return [_deserialize_value(v, element_type, field_name) for v in value]

        return [_deserialize_value(v, element_type) for v in value]

    # Primitives pass through
    return value


def _get_field_type(cls: Type, field_name: str) -> Optional[Type]:
    """Get the type annotation for a field on a class."""
    if is_dataclass(cls):
        for field in fields(cls):
            if field.name == field_name:
                return field.type
    elif _is_pydantic_model(cls):
        model_fields = cls.model_fields
        if field_name in model_fields:
            return model_fields[field_name].annotation
    return None


def to_dict(obj: Any, include_none: bool = False) -> Dict[str, Any]:
    """Convert an object to a dictionary representation.

    Args:
        obj: The object to serialize.
        include_none: Whether to include None values.

    Returns:
        A dictionary representation of the object.
    """
    return _serialize_value(obj, include_none)


def from_dict(data: Dict[str, Any], cls: Type[T]) -> T:
    """Create an object from a dictionary representation.

    Args:
        data: The dictionary data.
        cls: The class to instantiate.

    Returns:
        An instance of the specified class.
    """
    if not isinstance(data, dict):
        raise TypeError(f"Expected dict, got {type(data).__name__}")

    # Remove type if present (already used for type dispatch)
    data = {k: v for k, v in data.items() if k != "type"}

    # Handle Pydantic models
    if _is_pydantic_model(cls):
        # Deserialize nested values based on field types
        processed_data = {}
        for key, value in data.items():
            field_type = _get_field_type(cls, key)
            # Apply human-readable parsing first (memory sizes, time durations)
            value = _maybe_parse_value(value, key)
            processed_data[key] = _deserialize_value(value, field_type, field_name=key)
        return cls(**processed_data)

    # Handle dataclasses
    if is_dataclass(cls):
        processed_data = {}
        for field in fields(cls):
            if field.name in data:
                value = data[field.name]
                field_type = field.type

                # Apply human-readable parsing first (memory sizes, time durations)
                value = _maybe_parse_value(value, field.name)

                # Handle Union types (e.g., Optional, Union[A, B])
                origin = get_origin(field_type)
                if origin is Union:
                    args = get_args(field_type)
                    # For Optional[X], try to deserialize as X
                    non_none_args = [a for a in args if a is not type(None)]
                    if len(non_none_args) == 1:
                        field_type = non_none_args[0]
                    elif value is not None and isinstance(value, dict) and "type" in value:
                        # Use type to determine which union member
                        type_name = value["type"]
                        for arg in non_none_args:
                            if hasattr(arg, "__name__") and arg.__name__ == type_name:
                                field_type = arg
                                break

                processed_data[field.name] = _deserialize_value(value, field_type, field_name=field.name)
            elif field.default is not field.default_factory:
                # Use default if available
                pass  # Let the dataclass handle defaults

        return cls(**processed_data)

    # For regular classes, just pass the data
    return cls(**data)


def serialize(obj: Any, format: Literal["json", "yaml"] = "json", indent: int = 2, include_none: bool = False) -> str:
    """Serialize an object to JSON or YAML string.

    Args:
        obj: The object to serialize.
        format: Output format ("json" or "yaml").
        indent: Indentation level for pretty printing.
        include_none: Whether to include None values.

    Returns:
        The serialized string.

    Raises:
        ValueError: If an unknown format is specified.
    """
    data = to_dict(obj, include_none)

    if format == "json":
        return json.dumps(data, indent=indent, default=str)
    elif format == "yaml":
        return yaml.dump(data, default_flow_style=False, allow_unicode=True, sort_keys=False)
    else:
        raise ValueError(f"Unknown format: {format}")


def deserialize(data: str, cls: Type[T], format: Literal["json", "yaml"] = "json") -> T:
    """Deserialize a JSON or YAML string to an object.

    Args:
        data: The serialized string.
        cls: The class to deserialize to.
        format: Input format ("json" or "yaml").

    Returns:
        An instance of the specified class.

    Raises:
        ValueError: If an unknown format is specified.
    """
    if format == "json":
        parsed = json.loads(data)
    elif format == "yaml":
        parsed = yaml.safe_load(data)
    else:
        raise ValueError(f"Unknown format: {format}")

    return from_dict(parsed, cls)


def serialize_to_file(obj: Any, path: Union[str, Path], format: Optional[Literal["json", "yaml"]] = None, indent: int = 2, include_none: bool = False) -> None:
    """Serialize an object to a file.

    Args:
        obj: The object to serialize.
        path: The file path.
        format: Output format. If None, inferred from file extension.
        indent: Indentation level for pretty printing.
        include_none: Whether to include None values.
    """
    path = Path(path)

    if format is None:
        if path.suffix in (".yaml", ".yml"):
            format = "yaml"
        else:
            format = "json"

    content = serialize(obj, format=format, indent=indent, include_none=include_none)
    path.write_text(content)


def deserialize_from_file(path: Union[str, Path], cls: Type[T], format: Optional[Literal["json", "yaml"]] = None) -> T:
    """Deserialize an object from a file.

    Args:
        path: The file path.
        cls: The class to deserialize to.
        format: Input format. If None, inferred from file extension.

    Returns:
        An instance of the specified class.
    """
    path = Path(path)

    if format is None:
        if path.suffix in (".yaml", ".yml"):
            format = "yaml"
        else:
            format = "json"

    content = path.read_text()
    return deserialize(content, cls, format=format)


# Register all taskflows types for polymorphic deserialization
def _register_taskflows_types():
    """Register all taskflows types in the type registry."""
    # Import here to avoid circular imports
    from taskflows.service import Venv, Service, RestartPolicy
    from taskflows.docker import DockerContainer, DockerImage, Volume, Ulimit, ContainerLimits
    from taskflows.schedule import Calendar, Periodic
    from taskflows.constraints import (
        CgroupConfig,
        HardwareConstraint,
        Memory,
        CPUs,
        SystemLoadConstraint,
        MemoryPressure,
        CPUPressure,
        IOPressure,
    )

    # Service types
    register_type(Venv)
    register_type(Service)
    register_type(RestartPolicy)

    # Docker types
    register_type(DockerContainer)
    register_type(DockerImage)
    register_type(Volume)
    register_type(Ulimit)
    register_type(ContainerLimits)

    # Schedule types
    register_type(Calendar)
    register_type(Periodic)

    # Constraint types
    register_type(CgroupConfig)
    register_type(HardwareConstraint)
    register_type(Memory)
    register_type(CPUs)
    register_type(SystemLoadConstraint)
    register_type(MemoryPressure)
    register_type(CPUPressure)
    register_type(IOPressure)


# Register types on import
_register_taskflows_types()


def load_services_from_yaml(path: Union[str, Path]) -> List["Service"]:
    """Load multiple services from a YAML file.

    The YAML file should contain a 'taskflows_services' key with a list of service definitions.
    Types are automatically inferred from content - no need for explicit 'type' fields.

    Example YAML file:
        taskflows_services:
          - name: web-server
            start_command: python -m http.server 8080
            description: Simple web server
            restart_policy: always

          - name: data-processor
            start_command: python process_data.py
            environment:
              env_name: data-env        # Inferred as Venv (has env_name)
            start_schedule: Mon-Fri 09:00  # Inferred as Calendar (string schedule)

          - name: docker-worker
            start_command: python worker.py
            environment:
              image: python:3.11        # Inferred as DockerContainer (has image)
            start_schedule:
              period: 3600              # Inferred as Periodic (has period)
              start_on: boot
              relative_to: finish

    Args:
        path: Path to the YAML file.

    Returns:
        A list of Service instances.

    Raises:
        ValueError: If the YAML file doesn't contain a 'taskflows_services' key.
        FileNotFoundError: If the file doesn't exist.
    """
    from taskflows.service import Service

    path = Path(path)
    content = path.read_text()
    data = yaml.safe_load(content)

    if not isinstance(data, dict):
        raise ValueError(f"YAML file must contain a mapping, got {type(data).__name__}")

    if "taskflows_services" not in data:
        raise ValueError("YAML file must contain a 'taskflows_services' key with a list of service definitions")

    services_data = data["taskflows_services"]
    if not isinstance(services_data, list):
        raise ValueError(f"'services' must be a list, got {type(services_data).__name__}")

    services = []
    for service_data in services_data:
        service = from_dict(service_data, Service)
        services.append(service)

    logger.info(f"Loaded {len(services)} services from {path}")
    return services


def save_services_to_yaml(services: List["Service"], path: Union[str, Path], include_none: bool = False) -> None:
    """Save multiple services to a YAML file.

    Args:
        services: List of Service instances to save.
        path: Path to the YAML file.
        include_none: Whether to include None values in the output.
    """
    path = Path(path)

    services_data = [to_dict(s, include_none=include_none) for s in services]
    # Remove type from top-level since we know these are services
    for s in services_data:
        s.pop("type", None)

    data = {"services": services_data}
    content = yaml.dump(data, default_flow_style=False, allow_unicode=True, sort_keys=False)
    path.write_text(content)

    logger.info(f"Saved {len(services)} services to {path}")
