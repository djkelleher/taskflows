"""Prometheus metrics for taskflows.

This module defines all Prometheus metrics used throughout the taskflows application
for observability and monitoring. Metrics are automatically exposed via the /metrics
HTTP endpoint when the API server is running.

Metric Types:
    - Counter: Cumulative value that only increases (e.g., total requests)
    - Gauge: Value that can go up or down (e.g., active connections)
    - Histogram: Samples observations and counts them in buckets (e.g., request duration)
    - Info: Key-value pairs for static information (e.g., version info)

Usage:
    from taskflows.metrics import task_duration, task_count, task_errors

    # Time a task execution using context manager
    with task_duration.labels(task_name="my_task", status="success").time():
        run_task()

    # Increment a counter
    task_count.labels(task_name="my_task", status="success").inc()

    # Set a gauge value
    service_uptime.labels(service_name="worker").set(3600)

    # Record an error with its type
    task_errors.labels(task_name="my_task", error_type="timeout").inc()
"""

import platform
import socket
import sys

from prometheus_client import Counter, Gauge, Histogram, Info

from taskflows.constants import Metrics

# =============================================================================
# Task Execution Metrics
# =============================================================================
# These metrics track the execution of individual tasks, including their
# duration, success/failure counts, errors, and retry attempts.

# Histogram tracking task execution duration in seconds.
# Labels:
#   - task_name: Name of the task being executed
#   - status: Execution result ("success", "failure", or "timeout")
task_duration = Histogram(
    f"{Metrics.NAMESPACE}_{Metrics.TASK_DURATION}",
    "Task execution duration in seconds",
    ["task_name", "status"],
    buckets=Metrics.DURATION_BUCKETS,
)

# Counter for total number of tasks executed.
# Labels:
#   - task_name: Name of the task
#   - status: Execution result ("success", "failure", or "timeout")
task_count = Counter(
    f"{Metrics.NAMESPACE}_{Metrics.TASK_COUNT}",
    "Total number of tasks executed",
    ["task_name", "status"],
)

# Counter for task errors, categorized by error type.
# Labels:
#   - task_name: Name of the task that errored
#   - error_type: Type/class of the error (e.g., "timeout", "connection_error")
task_errors = Counter(
    f"{Metrics.NAMESPACE}_{Metrics.TASK_ERRORS}",
    "Total number of task errors",
    ["task_name", "error_type"],
)

# Counter tracking the number of retry attempts for tasks.
# Labels:
#   - task_name: Name of the task being retried
task_retries = Counter(
    f"{Metrics.NAMESPACE}_task_retries_total",
    "Total number of task retries",
    ["task_name"],
)

# =============================================================================
# Service State Metrics
# =============================================================================
# These metrics track the state and health of long-running services,
# including their current state, restart history, and uptime.

# Gauge representing the current state of a service.
# Values: 1 = active/running, 0 = inactive/stopped, -1 = failed/error
# Labels:
#   - service_name: Name of the service
#   - state: Human-readable state name (e.g., "running", "stopped", "failed")
service_state = Gauge(
    f"{Metrics.NAMESPACE}_{Metrics.SERVICE_STATE}",
    "Service state (1=active, 0=inactive, -1=failed)",
    ["service_name", "state"],
)

# Counter tracking the total number of service restarts.
# Labels:
#   - service_name: Name of the service that restarted
#   - reason: Why the service restarted (e.g., "crash", "manual", "config_change")
service_restarts = Counter(
    f"{Metrics.NAMESPACE}_service_restarts_total",
    "Total number of service restarts",
    ["service_name", "reason"],
)

# Gauge tracking how long a service has been running in seconds.
# Labels:
#   - service_name: Name of the service
service_uptime = Gauge(
    f"{Metrics.NAMESPACE}_service_uptime_seconds",
    "Service uptime in seconds",
    ["service_name"],
)

# =============================================================================
# API Metrics
# =============================================================================
# These metrics track HTTP API request performance and usage, including
# request duration, total request counts, and concurrent active requests.

# Histogram tracking API request duration in seconds.
# Labels:
#   - method: HTTP method (GET, POST, PUT, DELETE, etc.)
#   - endpoint: API endpoint path (e.g., "/api/tasks", "/api/services")
#   - status_code: HTTP response status code (e.g., "200", "404", "500")
api_request_duration = Histogram(
    f"{Metrics.NAMESPACE}_{Metrics.API_REQUEST_DURATION}",
    "API request duration in seconds",
    ["method", "endpoint", "status_code"],
    buckets=Metrics.DURATION_BUCKETS,
)

# Counter for total number of API requests.
# Labels:
#   - method: HTTP method
#   - endpoint: API endpoint path
#   - status_code: HTTP response status code
api_request_count = Counter(
    f"{Metrics.NAMESPACE}_api_requests_total",
    "Total API requests",
    ["method", "endpoint", "status_code"],
)

# Gauge tracking the number of currently active (in-flight) API requests.
# Useful for monitoring concurrency and detecting request pile-ups.
# Labels:
#   - method: HTTP method
#   - endpoint: API endpoint path
api_active_requests = Gauge(
    f"{Metrics.NAMESPACE}_api_active_requests",
    "Number of active API requests",
    ["method", "endpoint"],
)

# =============================================================================
# System Information
# =============================================================================
# Static information about the system running taskflows. This is set once
# at module import time and provides context for all other metrics.

# Info metric containing static system details.
# Fields:
#   - hostname: Machine hostname
#   - platform: OS and architecture info
#   - python_version: Python interpreter version
system_info = Info(f"{Metrics.NAMESPACE}_system", "System information")

# Initialize system info with current environment details.
# This runs once when the module is imported.
system_info.info(
    {
        "hostname": socket.gethostname(),
        "platform": platform.platform(),
        "python_version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
    }
)
