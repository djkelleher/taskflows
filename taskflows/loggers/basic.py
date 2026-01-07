import os
import sys
from pathlib import Path
from typing import Literal, Optional, Union

from loguru import logger


def any_case_env_var(var: str, default: Optional[str] = None) -> Union[str, None]:
    value = os.getenv(var) or os.getenv(var.lower()) or os.getenv(var.upper())
    if value is None:
        return default
    if (vl := value.lower()) == "true":
        return True
    if vl == "false":
        return False
    return value


# Store configured loggers to prevent reconfiguration
_configured_loggers = set()


def get_logger(
    name: Optional[str] = None,
    level: Optional[Union[str, int]] = None,
    no_terminal: Optional[bool] = None,
    file_dir: Optional[Union[str, Path]] = None,
    show_source: Optional[Literal["pathname", "filename"]] = "filename",
    file_max_bytes: Optional[int] = 20_000_000,
    max_rotations: Optional[int] = 2,
):
    """Create a new logger or return an existing logger with the given name.

    All arguments besides for `name` can be set via environment variables in the form `{LOGGER NAME}_{VARIABLE NAME}` or `loggers_{VARIABLE NAME}`.
    Variables including logger name will be chosen before `loggers_` variables. Variables can be uppercase or lowercase.

    Args:
        name (Optional[str], optional): Name for the logger. Defaults to None.
        level (Optional[Union[str, int]], optional): Logging level -- CRITICAL: 50, ERROR: 40, WARNING: 30, INFO: 20, DEBUG: 10. Defaults to None.
        no_terminal (bool): If True, don't write logs to terminal. Defaults to False.
        file_dir (Optional[Union[str, Path]], optional): Directory where log files should be written. Defaults to None.
        show_source (Optional[bool], optional): `pathname`: Show absolute file path in log string prefix. `filename`: Show file name in log string prefix. Defaults to "filename".
        file_max_bytes (int): Max number of bytes to store in one log file. Defaults to 20MB.
        max_rotations (int): Number of log rotations to keep. Defaults to 2.

    Returns:
        logger: The configured loguru logger.
    """
    # Check if this logger has already been configured
    logger_key = name or "root"
    if logger_key in _configured_loggers:
        return logger.bind(logger_name=name) if name else logger

    # Mark this logger as configured
    _configured_loggers.add(logger_key)

    # Resolve configuration from environment variables
    if no_terminal is None:
        if name:
            no_terminal = any_case_env_var(f"{name}_NO_TERMINAL")
        no_terminal = no_terminal or any_case_env_var("loggers_NO_TERMINAL")

    if file_dir is None:
        if name:
            file_dir = any_case_env_var(f"{name}_FILE_DIR")
        file_dir = file_dir or any_case_env_var("loggers_FILE_DIR")

    if level is None:
        if name:
            level = any_case_env_var(f"{name}_LOG_LEVEL")
        level = level or any_case_env_var("loggers_LOG_LEVEL", "INFO")

    if show_source is None:
        if name:
            show_source = any_case_env_var(f"{name}_SHOW_SOURCE")
        show_source = show_source or any_case_env_var("loggers_SHOW_SOURCE", "filename")

    if file_max_bytes is None:
        if name:
            file_max_bytes = any_case_env_var(f"{name}_FILE_MAX_BYTES")
        file_max_bytes = file_max_bytes or any_case_env_var("loggers_FILE_MAX_BYTES")
    if file_max_bytes:
        file_max_bytes = int(file_max_bytes)

    if max_rotations is None:
        if name:
            max_rotations = any_case_env_var(f"{name}_MAX_ROTATIONS")
        max_rotations = max_rotations or any_case_env_var("loggers_MAX_ROTATIONS")
    if max_rotations:
        max_rotations = int(max_rotations)

    # Convert numeric level to string
    if isinstance(level, int):
        level_map = {50: "CRITICAL", 40: "ERROR", 30: "WARNING", 20: "INFO", 10: "DEBUG"}
        level = level_map.get(level, "INFO")

    # Remove default handler only on first configuration
    if logger_key == "root" and len(_configured_loggers) == 1:
        logger.remove()

    # Build format string
    format_parts = ["<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green>", "<level>{level: <8}</level>"]

    if name:
        format_parts.append(f"<cyan>[{name}]</cyan>")

    if show_source == "pathname":
        format_parts.append("<blue>{file.path}:{line}</blue>")
    elif show_source == "filename":
        format_parts.append("<blue>{file.name}:{line}</blue>")

    format_parts.append("<level>{message}</level>")
    format_string = " ".join(format_parts)

    # Add terminal handler if not disabled
    if not no_terminal:
        logger.add(
            sys.stderr,
            format=format_string,
            level=level.upper() if isinstance(level, str) else level,
            filter=lambda record: record["extra"].get("logger_name") == name if name else True,
        )

    # Add file handler if directory specified
    if file_dir:
        file_path = Path(file_dir) / f"{name or f'python_{os.getpid()}'}.log"
        file_path.parent.mkdir(exist_ok=True, parents=True)

        logger.add(
            str(file_path),
            format=format_string,
            level=level.upper() if isinstance(level, str) else level,
            rotation=file_max_bytes,
            retention=max_rotations,
            filter=lambda record: record["extra"].get("logger_name") == name if name else True,
        )

    # Return a bound logger with the name
    return logger.bind(logger_name=name) if name else logger