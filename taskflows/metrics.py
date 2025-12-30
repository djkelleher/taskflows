"""Prometheus metrics for taskflows."""

import platform
import socket
import sys

from prometheus_client import Counter, Gauge, Histogram, Info

from taskflows.constants import Metrics

# Task execution metrics
task_duration = Histogram(
    f"{Metrics.NAMESPACE}_{Metrics.TASK_DURATION}",
    "Task execution duration in seconds",
    ["task_name", "status"],  # status: success, failure, timeout
    buckets=Metrics.DURATION_BUCKETS,
)

task_count = Counter(
    f"{Metrics.NAMESPACE}_{Metrics.TASK_COUNT}",
    "Total number of tasks executed",
    ["task_name", "status"],
)

task_errors = Counter(
    f"{Metrics.NAMESPACE}_{Metrics.TASK_ERRORS}",
    "Total number of task errors",
    ["task_name", "error_type"],
)

task_retries = Counter(
    f"{Metrics.NAMESPACE}_task_retries_total",
    "Total number of task retries",
    ["task_name"],
)

# Service state metrics
service_state = Gauge(
    f"{Metrics.NAMESPACE}_{Metrics.SERVICE_STATE}",
    "Service state (1=active, 0=inactive, -1=failed)",
    ["service_name", "state"],
)

service_restarts = Counter(
    f"{Metrics.NAMESPACE}_service_restarts_total",
    "Total number of service restarts",
    ["service_name", "reason"],
)

service_uptime = Gauge(
    f"{Metrics.NAMESPACE}_service_uptime_seconds",
    "Service uptime in seconds",
    ["service_name"],
)

# API metrics
api_request_duration = Histogram(
    f"{Metrics.NAMESPACE}_{Metrics.API_REQUEST_DURATION}",
    "API request duration in seconds",
    ["method", "endpoint", "status_code"],
    buckets=Metrics.DURATION_BUCKETS,
)

api_request_count = Counter(
    f"{Metrics.NAMESPACE}_api_requests_total",
    "Total API requests",
    ["method", "endpoint", "status_code"],
)

api_active_requests = Gauge(
    f"{Metrics.NAMESPACE}_api_active_requests",
    "Number of active API requests",
    ["method", "endpoint"],
)

# System info
system_info = Info(f"{Metrics.NAMESPACE}_system", "System information")

# Initialize system info
system_info.info(
    {
        "hostname": socket.gethostname(),
        "platform": platform.platform(),
        "python_version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
    }
)
