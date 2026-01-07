import hashlib
import logging
import os
import time
import uuid
from contextvars import ContextVar
from typing import Any, Dict, Optional, Union

import structlog
from structlog.contextvars import (
    bind_contextvars,
    clear_contextvars,
    unbind_contextvars,
)

# Context variable for request tracking
request_id_var: ContextVar[Optional[str]] = ContextVar("request_id", default=None)
trace_id_var: ContextVar[Optional[str]] = ContextVar("trace_id", default=None)


# Custom processor to add static labels for Loki
def add_loki_labels(logger, method_name, event_dict):
    """Add static labels that Loki can use for indexing"""
    # Core labels for Loki indexing (keep minimal for performance)
    event_dict["app"] = os.getenv("APP_NAME", "dl-logging")
    event_dict["environment"] = os.getenv("ENVIRONMENT", "production")
    event_dict["hostname"] = os.getenv("HOSTNAME", "unknown")

    # Add request/trace IDs if available
    request_id = request_id_var.get()
    if request_id:
        event_dict["request_id"] = request_id

    trace_id = trace_id_var.get()
    if trace_id:
        event_dict["trace_id"] = trace_id

    return event_dict


# Custom processor to ensure proper severity levels for Loki
def normalize_log_level(logger, method_name, event_dict):
    """Normalize log level names for Loki compatibility"""
    if "level" in event_dict:
        event_dict["severity"] = event_dict["level"].upper()
        # Map Python levels to syslog severity for better Loki queries
        level_map = {
            "DEBUG": "debug",
            "INFO": "info",
            "WARNING": "warning",
            "ERROR": "error",
            "CRITICAL": "critical",
        }
        event_dict["level_name"] = level_map.get(event_dict["severity"], "info")
    return event_dict


# Add nanosecond timestamp for better Loki precision
def add_nano_timestamp(logger, method_name, event_dict):
    """Add nanosecond precision timestamp for Loki"""
    event_dict["timestamp_ns"] = time.time_ns()
    return event_dict


# Add event fingerprint for deduplication
def add_event_fingerprint(logger, method_name, event_dict):
    """Add event fingerprint for identifying duplicate events"""
    # Create fingerprint from stable fields
    fingerprint_fields = [
        event_dict.get("event", ""),
        event_dict.get("logger", ""),
        event_dict.get("filename", ""),
        event_dict.get("func_name", ""),
        event_dict.get("lineno", ""),
    ]
    fingerprint_str = "|".join(str(f) for f in fingerprint_fields)
    event_dict["event_fingerprint"] = hashlib.md5(fingerprint_str.encode()).hexdigest()[
        :8
    ]
    return event_dict


# Processor to move non-indexed fields to nested structure
def organize_fields_for_loki(logger, method_name, event_dict):
    """Organize fields to minimize Loki cardinality"""
    # Fields that should be indexed (labels)
    indexed_fields = {
        "app",
        "environment",
        "hostname",
        "severity",
        "level_name",
        "logger",
        "request_id",
        "trace_id",
        "service_name",
        "container_name",
    }

    # Move non-indexed fields to a nested 'context' dict
    context = {}
    keys_to_move = []

    for key, value in event_dict.items():
        if key not in indexed_fields and not key.startswith("_"):
            # Keep timestamp and event message at top level
            if key not in {
                "timestamp",
                "event",
                "message",
                "timestamp_ns",
                "event_fingerprint",
            }:
                context[key] = value
                keys_to_move.append(key)

    # Remove moved keys and add context
    for key in keys_to_move:
        del event_dict[key]

    if context:
        event_dict["context"] = context

    return event_dict


# Default structlog configuration (can be overridden by configure_loki_logging)
_default_processors = [
    # Add context early
    structlog.contextvars.merge_contextvars,
    structlog.processors.add_log_level,
    structlog.stdlib.add_logger_name,
    # Add timestamps
    structlog.processors.TimeStamper(fmt="iso", utc=True),
    add_nano_timestamp,
    # Add static labels for Loki indexing
    add_loki_labels,
    normalize_log_level,
    # Add source location info
    structlog.processors.CallsiteParameterAdder(
        parameters=[
            structlog.processors.CallsiteParameter.FILENAME,
            structlog.processors.CallsiteParameter.LINENO,
            structlog.processors.CallsiteParameter.FUNC_NAME,
        ]
    ),
    # Add event fingerprint
    add_event_fingerprint,
    # Process positional arguments
    structlog.stdlib.PositionalArgumentsFormatter(),
    # Handle exceptions with better formatting
    structlog.processors.StackInfoRenderer(),
    structlog.processors.format_exc_info,
    # Ensure unicode
    structlog.processors.UnicodeDecoder(),
    # Organize fields for Loki (minimize cardinality)
    organize_fields_for_loki,
    # Filter by level before rendering
    structlog.stdlib.filter_by_level,
    # Render as JSON for Fluent Bit parsing
    structlog.processors.JSONRenderer(
        sort_keys=False,  # Better performance
        ensure_ascii=False,  # Support unicode properly
    ),
]

# Initialize with default config
structlog.configure(
    processors=_default_processors,
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
    cache_logger_on_first_use=True,
)


def get_struct_logger(
    name: Optional[str] = None,
    request_id: Optional[str] = None,
    trace_id: Optional[str] = None,
    **context: Any
) -> structlog.BoundLogger:
    """Get a structured logger with optional context.

    Args:
        name: Logger name
        request_id: Optional request ID for correlation
        trace_id: Optional trace ID for distributed tracing
        **context: Additional context to bind to the logger

    Returns:
        Bound structured logger
    """
    # Set context variables if provided
    if request_id:
        request_id_var.set(request_id)
    if trace_id:
        trace_id_var.set(trace_id)

    logger = structlog.get_logger(name)

    # Add any additional context
    if context:
        logger = logger.bind(**context)

    return logger


def set_request_context(
    request_id: Optional[str] = None, trace_id: Optional[str] = None, **kwargs
) -> None:
    """Set request-scoped context that will be included in all logs.

    Args:
        request_id: Request ID for correlation
        trace_id: Trace ID for distributed tracing
        **kwargs: Additional context to bind
    """
    if request_id:
        request_id_var.set(request_id)
        bind_contextvars(request_id=request_id)

    if trace_id:
        trace_id_var.set(trace_id)
        bind_contextvars(trace_id=trace_id)

    if kwargs:
        bind_contextvars(**kwargs)


def clear_request_context() -> None:
    """Clear request-scoped context."""
    request_id_var.set(None)
    trace_id_var.set(None)
    clear_contextvars()


def generate_request_id() -> str:
    """Generate a unique request ID."""
    return str(uuid.uuid4())


def configure_loki_logging(
    app_name: str = "dl-logging",
    environment: str = None,
    extra_labels: Dict[str, str] = None,
    log_level: str = "INFO",
    enable_console_renderer: bool = False,
    max_string_length: int = 1000,
    include_hostname: bool = True,
    include_process_info: bool = False,
) -> None:
    """Configure structlog specifically for Loki ingestion via Fluent Bit.

    Args:
        app_name: Application name for Loki labels
        environment: Environment name (defaults to ENV var or 'production')
        extra_labels: Additional static labels for Loki
        log_level: Minimum log level
        enable_console_renderer: Use console renderer for development
        max_string_length: Maximum string length before truncation
        include_hostname: Include hostname in logs
        include_process_info: Include process/thread info
    """
    # Set environment variables for processors to use
    os.environ["APP_NAME"] = app_name
    if environment:
        os.environ["ENVIRONMENT"] = environment

    labels = extra_labels or {}

    def add_custom_loki_labels(logger, method_name, event_dict):
        """Add static labels that Loki can use for indexing"""
        event_dict["app"] = app_name
        event_dict["environment"] = environment or os.getenv(
            "ENVIRONMENT", "production"
        )

        if include_hostname:
            event_dict["hostname"] = os.getenv("HOSTNAME", "unknown")

        # Add extra labels
        for key, value in labels.items():
            event_dict[key] = value

        # Add request/trace IDs if available
        request_id = request_id_var.get()
        if request_id:
            event_dict["request_id"] = request_id

        trace_id = trace_id_var.get()
        if trace_id:
            event_dict["trace_id"] = trace_id

        return event_dict

    def truncate_strings(logger, method_name, event_dict):
        """Truncate long strings to prevent huge log entries"""

        def truncate(obj, max_len=max_string_length):
            if isinstance(obj, str) and len(obj) > max_len:
                return obj[:max_len] + "... (truncated)"
            elif isinstance(obj, dict):
                return {k: truncate(v, max_len) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [truncate(item, max_len) for item in obj]
            return obj

        return truncate(event_dict)

    # Build processor list
    processors = [
        # Add context early
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.stdlib.add_logger_name,
    ]

    # Add process info if requested
    if include_process_info:
        processors.extend(
            [
                # Add process and thread info
                structlog.processors.add_log_level,
            ]
        )

    processors.extend(
        [
            # Add timestamps
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            add_nano_timestamp,
            # Add static labels for Loki indexing
            add_custom_loki_labels,
            normalize_log_level,
            # Add source location info
            structlog.processors.CallsiteParameterAdder(
                parameters=[
                    structlog.processors.CallsiteParameter.FILENAME,
                    structlog.processors.CallsiteParameter.LINENO,
                    structlog.processors.CallsiteParameter.FUNC_NAME,
                ]
            ),
            # Add event fingerprint
            add_event_fingerprint,
            # Process positional arguments
            structlog.stdlib.PositionalArgumentsFormatter(),
            # Handle exceptions
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            # Ensure unicode
            structlog.processors.UnicodeDecoder(),
            # Truncate long strings
            truncate_strings,
            # Organize fields for Loki
            organize_fields_for_loki,
            # Filter by level before rendering
            structlog.stdlib.filter_by_level,
        ]
    )

    # Choose renderer based on environment
    if enable_console_renderer:
        processors.append(structlog.dev.ConsoleRenderer())
    else:
        processors.append(
            structlog.processors.JSONRenderer(sort_keys=False, ensure_ascii=False)
        )

    structlog.configure(
        processors=processors,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, log_level.upper())
        ),
        cache_logger_on_first_use=True,
    )
