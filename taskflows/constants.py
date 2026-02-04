"""Centralized constants for the taskflows application."""

from typing import Final


class API:
    """API server configuration constants."""

    DEFAULT_HOST: Final[str] = "localhost"
    DEFAULT_PORT: Final[int] = 7777
    HEALTH_ENDPOINT: Final[str] = "/health"
    METRICS_ENDPOINT: Final[str] = "/metrics"

    # Timeouts (seconds)
    DEFAULT_TIMEOUT: Final[int] = 10
    LOGS_TIMEOUT: Final[int] = 30
    CREATE_TIMEOUT: Final[int] = 30

    # Response limits
    MAX_RESPONSE_SIZE: Final[int] = 8000
    MAX_TRACEBACK_LINES: Final[int] = 40


class Security:
    """Security and authentication constants."""

    HMAC_WINDOW_SECONDS: Final[int] = 300  # 5 minutes
    JWT_EXPIRATION_SECONDS: Final[int] = 3600  # 1 hour
    JWT_REFRESH_EXPIRATION_SECONDS: Final[int] = 86400  # 24 hours
    SECRET_MIN_LENGTH: Final[int] = 32

    HMAC_HEADER: Final[str] = "X-HMAC-Signature"
    TIMESTAMP_HEADER: Final[str] = "X-Timestamp"


class Service:
    """Service management constants."""

    DEFAULT_RESTART_DELAY: Final[int] = 10
    DEFAULT_STOP_TIMEOUT: Final[int] = 120
    DOCKER_STOP_TIMEOUT: Final[int] = 30

    SYSTEMD_FILE_PREFIX: Final[str] = "taskflows-"
    SYSTEMD_TIMEOUT_STOP: Final[str] = "120s"


class Logging:
    """Logging and monitoring constants."""

    DEFAULT_LOG_LINES: Final[int] = 1000
    MAX_LOG_LINES: Final[int] = 10000


class Metrics:
    """Prometheus metrics configuration."""

    NAMESPACE: Final[str] = "taskflows"

    # Metric names
    TASK_DURATION: Final[str] = "task_duration_seconds"
    TASK_COUNT: Final[str] = "task_total"
    TASK_ERRORS: Final[str] = "task_errors_total"
    SERVICE_STATE: Final[str] = "service_state"
    API_REQUEST_DURATION: Final[str] = "api_request_duration_seconds"

    # Histogram buckets (seconds)
    DURATION_BUCKETS: Final[tuple] = (0.1, 0.5, 1.0, 5.0, 10.0, 30.0, 60.0, 300.0, 600.0)
