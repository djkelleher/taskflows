"""Security validation utilities for input sanitization and path validation.

Note: This module is separate from admin/security.py which handles HMAC/JWT authentication.
"""

import re
import tempfile
from pathlib import Path
from typing import Union

from taskflows.exceptions import SecurityError, ValidationError


def validate_env_file_path(
    path: Union[str, Path], allow_nonexistent: bool = False
) -> Path:
    """Validate env_file path is safe to read.

    Prevents:
    - Path traversal attacks
    - Reading system files outside allowed directories
    - Symlink escapes

    Args:
        path: Path to validate
        allow_nonexistent: If True, allows paths that don't exist yet

    Returns:
        Resolved absolute path

    Raises:
        SecurityError: If path is outside allowed directories or unsafe
    """
    path = Path(path).expanduser()

    # Resolve to absolute (follows symlinks)
    try:
        resolved = path.resolve(strict=not allow_nonexistent)
    except (OSError, RuntimeError) as e:
        raise SecurityError(f"Cannot resolve path {path}: {e}") from e

    # Define allowed directories. Test and service-discovery workflows commonly
    # stage env files under pytest's per-user temp root; keep that narrow rather
    # than allowing all of /tmp.
    pytest_tmp_base = Path(tempfile.gettempdir()) / f"pytest-of-{Path.home().name}"
    allowed_bases = [
        Path.home(),
        Path("/etc/taskflows"),
        Path.cwd(),
        pytest_tmp_base,
    ]

    # Check if under allowed directory
    is_allowed = False
    for base in allowed_bases:
        try:
            resolved.relative_to(base)
            is_allowed = True
            break
        except ValueError:
            continue

    if not is_allowed:
        raise SecurityError(
            f"Path {resolved} is outside allowed directories: "
            f"{', '.join(str(b) for b in allowed_bases)}"
        )

    # Ensure is regular file (if exists)
    if resolved.exists() and not resolved.is_file():
        raise SecurityError(f"Path {resolved} is not a regular file")

    return resolved


def validate_service_name(name: str) -> str:
    """Validate service name for safety.

    Args:
        name: Service name to validate

    Returns:
        Validated service name

    Raises:
        ValidationError: If service name is None, empty, or contains unsafe characters
    """
    # Check for None or empty
    if name is None:
        raise ValidationError(
            "Service name cannot be None. Please provide a name for the service."
        )
    if not isinstance(name, str):
        raise ValidationError(
            f"Service name must be a string, got {type(name).__name__}"
        )
    if not name:
        raise ValidationError("Invalid service name: cannot be empty")
    if name != name.strip():
        raise ValidationError(
            "Invalid service name: cannot start or end with whitespace"
        )

    # Allow only safe characters
    if not re.match(r"^[a-zA-Z0-9._-]+$", name):
        raise ValidationError(
            f"Invalid service name: {name!r}. "
            "Names must contain only letters, numbers, dots, dashes, underscores."
        )

    # Prevent path traversal
    if ".." in name or "/" in name:
        raise ValidationError(f"Service name cannot contain path separators: {name!r}")
    if name[0] in ".-" or name[-1] in ".-":
        raise ValidationError(
            f"Invalid service name: {name!r}. Names must start and end with a letter, number, or underscore."
        )

    # Prevent reserved names
    if name.lower() in {"systemd", "init", "system", "user"}:
        raise ValidationError(f"Service name cannot be reserved word: {name!r}")

    return name


def validate_command(command: str, allow_shell_features: bool = False) -> str:
    """Validate command string for safety.

    Args:
        command: Command string to validate
        allow_shell_features: If True, allows potentially dangerous shell patterns.
                              Use with extreme caution and only for trusted input.

    Returns:
        Validated command string

    Raises:
        ValidationError: If command contains unsafe patterns and allow_shell_features=False
        SecurityError: If command contains null bytes (always blocked)
    """
    if command is None:
        raise ValidationError("Command cannot be None")
    if not isinstance(command, str):
        raise ValidationError(f"Command must be a string, got {type(command).__name__}")
    if not command.strip():
        raise ValidationError("Command cannot be empty")

    # Check for null bytes (always blocked)
    if "\x00" in command:
        raise SecurityError("Command cannot contain null bytes")

    # Check for potentially dangerous patterns
    dangerous_patterns = [
        ("&&", "Command chaining with AND"),
        ("||", "Command chaining with OR"),
        (";", "Command separator"),
        ("|", "Pipe operator"),
        ("$(", "Command substitution"),
        ("`", "Command substitution (backticks)"),
        ("&", "Background execution"),
        (">", "Output redirection"),
        ("<", "Input redirection"),
        ("\n", "Newline (command separator)"),
    ]

    for pattern, description in dangerous_patterns:
        if pattern in command:
            from taskflows.common import logger

            if allow_shell_features:
                # Log warning but allow
                logger.warning(
                    f"Command contains dangerous pattern '{pattern}' ({description}): {command!r}. "
                    f"Allowed due to allow_shell_features=True"
                )
            else:
                # Block by default for security
                logger.error(
                    f"Command contains dangerous pattern '{pattern}' ({description}): {command!r}"
                )
                raise SecurityError(
                    f"Command contains potentially dangerous pattern '{pattern}' ({description}). "
                    f"If you need to use shell features, set allow_shell_features=True. "
                    f"Safer alternative: Use command arrays or separate commands."
                )

    return command


_SYSTEMD_ENV_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def validate_systemd_value(value: object, field_name: str = "systemd value") -> str:
    """Validate a value before embedding it in a systemd unit directive."""
    value = str(value)
    if any(ch in value for ch in ("\x00", "\n", "\r")):
        raise SecurityError(f"{field_name} cannot contain NUL or newline characters")
    return value


def validate_systemd_line(line: object) -> str:
    """Validate a fully-rendered systemd unit line."""
    line = validate_systemd_value(line, "systemd directive")
    if not line:
        raise ValidationError("systemd directive cannot be empty")
    return line


def format_systemd_environment(key: object, value: object) -> str:
    """Format a safe Environment= directive for a systemd unit file."""
    key = str(key)
    if not _SYSTEMD_ENV_KEY_RE.match(key):
        raise ValidationError(f"Invalid environment variable name: {key!r}")
    value = validate_systemd_value(value, f"environment variable {key}")
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'Environment="{key}={escaped}"'
