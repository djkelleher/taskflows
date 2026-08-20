import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal, cast

from loguru import logger


def any_case_env_var(var: str, default: str | None = None) -> str | bool | None:
    value = os.getenv(var) or os.getenv(var.lower()) or os.getenv(var.upper())
    if value is None:
        wanted = var.lower()
        for key, env_value in os.environ.items():
            if key.lower() == wanted:
                value = env_value
                break
    if value is None:
        return default
    vl = value.strip().lower()
    if vl in {"1", "true", "yes", "y", "on"}:
        return True
    if vl in {"0", "false", "no", "n", "off"}:
        return False
    return value


_configured_loggers: set[str] = set()
_configured_file_sinks: dict[Path, int] = {}
_logger_levels: dict[str, int] = {}
_logger_file_paths: dict[str, Path] = {}


def _logger_key(name: str | None) -> str:
    return name or "root"


def _normalize_level(level: str | int | None) -> tuple[str | int, int]:
    if level is None:
        level = "INFO"
    if isinstance(level, int):
        return level, level
    level_name = level.upper()
    return level_name, logger.level(level_name).no


def _build_format_string(
    name: str | None,
    show_source: Literal["pathname", "filename"] | None,
    *,
    dynamic_name: bool = False,
) -> str:
    format_parts = [
        "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green>",
        "<level>{level: <8}</level>",
    ]

    if dynamic_name:
        format_parts.append("<cyan>[{extra[logger_name]}]</cyan>")
    elif name:
        format_parts.append(f"<cyan>[{name}]</cyan>")

    if show_source == "pathname":
        format_parts.append("<blue>{file.path}:{line}</blue>")
    elif show_source == "filename":
        format_parts.append("<blue>{file.name}:{line}</blue>")

    format_parts.append("<level>{message}</level>")
    return " ".join(format_parts)


def _shared_file_filter(file_path: Path) -> Callable[[Any], bool]:
    def filter_record(record: Any) -> bool:
        logger_name = record["extra"].get("logger_name")
        if logger_name is None:
            return False
        if _logger_file_paths.get(logger_name) != file_path:
            return False
        minimum_level = _logger_levels.get(logger_name)
        return minimum_level is None or record["level"].no >= minimum_level

    return filter_record


def _env_bool(var: str, default: str | None = None) -> bool | None:
    value = any_case_env_var(var, default)
    if value is None or isinstance(value, bool):
        return value
    raise ValueError(f"{var} must be a boolean value")


def _env_text(var: str, default: str | None = None) -> str | None:
    value = any_case_env_var(var, default)
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError(f"{var} must be a text value")
    return value


def _env_int(var: str) -> int | None:
    value = _env_text(var)
    if value is None:
        return None
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{var} must be an integer") from exc


def _env_source(var: str, default: str | None = None) -> Literal["pathname", "filename"] | None:
    value = _env_text(var, default)
    if value is None:
        return None
    if value not in {"pathname", "filename"}:
        raise ValueError(f"{var} must be 'pathname' or 'filename'")
    return cast(Literal["pathname", "filename"], value)


def get_logger(
    name: str | None = None,
    level: str | int | None = None,
    no_terminal: bool | None = None,
    file_dir: str | Path | None = None,
    show_source: Literal["pathname", "filename"] | None = "filename",
    file_max_bytes: int | None = 20_000_000,
    max_rotations: int | None = 2,
    file_name: str | Path | None = None,
    single_file: bool | None = None,
) -> Any:
    """Create a new logger or return an existing logger with the given name.

    All arguments besides for `name` can be set via environment variables in the form `{LOGGER NAME}_{VARIABLE NAME}` or `LOGGERS_{VARIABLE NAME}`.
    Variables including logger name will be chosen before `LOGGERS_` variables. Variables can be uppercase or lowercase.

    Args:
        name (Optional[str], optional): Name for the logger. Defaults to None.
        level (Optional[Union[str, int]], optional): Logging level -- CRITICAL: 50, ERROR: 40, WARNING: 30, INFO: 20, DEBUG: 10. Defaults to None.
        no_terminal (bool): If True, don't write logs to terminal. Defaults to False.
        file_dir (Optional[Union[str, Path]], optional): Directory where log files should be written. Defaults to None.
        show_source (Optional[bool], optional): `pathname`: Show absolute file path in log string prefix. `filename`: Show file name in log string prefix. Defaults to "filename".
        file_max_bytes (int): Max number of bytes to store in one log file. Defaults to 20MB.
        max_rotations (int): Number of log rotations to keep. Defaults to 2.
        file_name (Optional[Union[str, Path]], optional): Shared log file name when
            single_file is enabled. Defaults to ``taskflows.log``.
        single_file (Optional[bool], optional): If True, all named loggers that use the
            same file directory write to one shared log file. Set to False to restore
            the legacy one-file-per-logger behavior. Defaults to True.

    Returns:
        logger: The configured loguru logger.
    """
    # Check if this logger has already been configured
    logger_key = _logger_key(name)
    if logger_key in _configured_loggers:
        return logger.bind(logger_name=logger_key)

    # Resolve configuration from environment variables, named overrides global
    if no_terminal is None:
        if name:
            no_terminal = _env_bool(f"{name}_NO_TERMINAL")
        if no_terminal is None:
            no_terminal = _env_bool("LOGGERS_NO_TERMINAL")

    if file_dir is None:
        if name:
            file_dir = _env_text(f"{name}_FILE_DIR")
        if file_dir is None:
            file_dir = _env_text("LOGGERS_FILE_DIR")

    if level is None:
        if name:
            level = _env_text(f"{name}_LOG_LEVEL")
        if level is None:
            level = _env_text("LOGGERS_LOG_LEVEL", "INFO")

    if show_source is None:
        if name:
            show_source = _env_source(f"{name}_SHOW_SOURCE")
        if show_source is None:
            show_source = _env_source("LOGGERS_SHOW_SOURCE", "filename")

    if file_max_bytes is None:
        if name:
            file_max_bytes = _env_int(f"{name}_FILE_MAX_BYTES")
        if file_max_bytes is None:
            file_max_bytes = _env_int("LOGGERS_FILE_MAX_BYTES")

    if max_rotations is None:
        if name:
            max_rotations = _env_int(f"{name}_MAX_ROTATIONS")
        if max_rotations is None:
            max_rotations = _env_int("LOGGERS_MAX_ROTATIONS")

    if single_file is None:
        if name:
            single_file = _env_bool(f"{name}_SINGLE_FILE")
        if single_file is None:
            single_file = _env_bool("LOGGERS_SINGLE_FILE", "true")
    single_file = bool(single_file)

    if file_name is None:
        if name:
            file_name = _env_text(f"{name}_FILE_NAME")
        if file_name is None:
            file_name = _env_text("LOGGERS_FILE_NAME", "taskflows.log")

    normalized_level, level_no = _normalize_level(level)

    # Remove default handler only on first configuration
    if logger_key == "root" and not _configured_loggers:
        logger.remove()

    terminal_format = _build_format_string(name, show_source)

    # Add terminal handler if not disabled
    if not no_terminal:
        logger.add(
            sys.stderr,
            format=terminal_format,
            level=normalized_level,
            filter=lambda record: (
                record["extra"].get("logger_name") == logger_key if name else True
            ),
        )

    # Add file handler if directory specified
    if file_dir:
        if single_file:
            file_name_path = Path(str(file_name or "taskflows.log"))
            file_path = (
                file_name_path if file_name_path.is_absolute() else Path(file_dir) / file_name_path
            )
            file_path = file_path.resolve()
            _logger_file_paths[logger_key] = file_path
            _logger_levels[logger_key] = level_no
            if file_path not in _configured_file_sinks:
                file_path.parent.mkdir(exist_ok=True, parents=True)
                sink_id = logger.add(
                    str(file_path),
                    format=_build_format_string(name, show_source, dynamic_name=True),
                    level="TRACE",
                    rotation=file_max_bytes,
                    retention=max_rotations,
                    filter=_shared_file_filter(file_path),
                )
                _configured_file_sinks[file_path] = sink_id
        else:
            file_path = Path(file_dir) / f"{name or f'python_{os.getpid()}'}.log"
            file_path.parent.mkdir(exist_ok=True, parents=True)

            logger.add(
                str(file_path),
                format=terminal_format,
                level=normalized_level,
                rotation=file_max_bytes,
                retention=max_rotations,
                filter=lambda record: (
                    record["extra"].get("logger_name") == logger_key if name else True
                ),
            )

    _logger_levels.setdefault(logger_key, level_no)
    _configured_loggers.add(logger_key)

    # Return a bound logger with the name
    return logger.bind(logger_name=logger_key)
