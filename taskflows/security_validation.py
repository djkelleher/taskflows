"""Security validation utilities for input sanitization and path validation.

Note: This module is separate from admin/security.py which handles HMAC/JWT authentication.
"""

import re
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
    path = Path(path)

    # Resolve to absolute (follows symlinks)
    try:
        resolved = path.resolve(strict=not allow_nonexistent)
    except (OSError, RuntimeError) as e:
        raise SecurityError(f"Cannot resolve path {path}: {e}") from e

    # Define allowed directories
    allowed_bases = [
        Path.home(),
        Path("/etc/taskflows"),
        Path.cwd(),
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
        ValidationError: If service name contains unsafe characters
    """
    # Allow only safe characters
    if not re.match(r"^[a-zA-Z0-9._-]+$", name):
        raise ValidationError(
            f"Invalid service name: {name!r}. "
            "Names must contain only letters, numbers, dots, dashes, underscores."
        )

    # Prevent path traversal
    if ".." in name or "/" in name:
        raise ValidationError(f"Service name cannot contain path separators: {name!r}")

    # Prevent reserved names
    if name.lower() in {"systemd", "init", "system", "user"}:
        raise ValidationError(f"Service name cannot be reserved word: {name!r}")

    return name


def validate_command(command: str) -> str:
    """Validate command string for safety.

    Args:
        command: Command string to validate

    Returns:
        Validated command string

    Raises:
        ValidationError: If command contains unsafe patterns
    """
    # Check for null bytes
    if "\x00" in command:
        raise ValidationError("Command cannot contain null bytes")

    # Warn about potentially dangerous patterns (but allow them)
    dangerous_patterns = [
        ("&&", "Command chaining"),
        ("||", "Command chaining"),
        (";", "Command separator"),
        ("|", "Pipe"),
        ("$(", "Command substitution"),
        ("`", "Command substitution"),
    ]

    for pattern, description in dangerous_patterns:
        if pattern in command:
            # Just log warning, don't block (shell features are sometimes needed)
            from taskflows.common import logger

            logger.warning(
                f"Command contains potentially dangerous pattern '{pattern}' ({description}): {command!r}"
            )

    return command
