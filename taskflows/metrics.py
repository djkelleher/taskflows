"""Prometheus metrics for taskflows.

Metrics are created lazily on first use via :func:`get_metrics` so that
importing taskflows does not register collectors in the global Prometheus
registry (which breaks repeated imports in tests and pollutes processes that
never use metrics). They are exposed via the /metrics HTTP endpoint when the
API server is running.

Metric Types:
    - Counter: Cumulative value that only increases (e.g., total requests)
    - Gauge: Value that can go up or down (e.g., active connections)
    - Histogram: Samples observations and counts them in buckets (e.g., request duration)
    - Info: Key-value pairs for static information (e.g., version info)

Usage:
    from taskflows.metrics import get_metrics

    metrics = get_metrics()
    with metrics.task_duration.labels(task_name="my_task", status="success").time():
        run_task()
    metrics.task_count.labels(task_name="my_task", status="success").inc()
"""

import platform
import socket
import sys
from dataclasses import dataclass
from functools import cache

from prometheus_client import Counter, Gauge, Histogram, Info

from taskflows.constants import Metrics


@dataclass(frozen=True)
class TaskflowsMetrics:
    """All taskflows Prometheus collectors."""

    # Task execution: duration ("success"/"failure"/"timeout" status), counts,
    # errors by type, and retry attempts.
    task_duration: Histogram
    task_count: Counter
    task_errors: Counter
    task_retries: Counter
    # Service state: 1=active, 0=inactive, -1=failed; restart counts; uptime.
    service_state: Gauge
    service_restarts: Counter
    service_uptime: Gauge
    # API requests: duration/counts by method+endpoint+status, in-flight gauge.
    api_request_duration: Histogram
    api_request_count: Counter
    api_active_requests: Gauge
    # Static system details (hostname, platform, python_version).
    system_info: Info


@cache
def get_metrics() -> TaskflowsMetrics:
    """Create and register all collectors on first call; return the singleton."""
    system_info = Info(f"{Metrics.NAMESPACE}_system", "System information")
    system_info.info(
        {
            "hostname": socket.gethostname(),
            "platform": platform.platform(),
            "python_version": (
                f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
            ),
        }
    )
    return TaskflowsMetrics(
        task_duration=Histogram(
            f"{Metrics.NAMESPACE}_{Metrics.TASK_DURATION}",
            "Task execution duration in seconds",
            ["task_name", "status"],
            buckets=Metrics.DURATION_BUCKETS,
        ),
        task_count=Counter(
            f"{Metrics.NAMESPACE}_{Metrics.TASK_COUNT}",
            "Total number of tasks executed",
            ["task_name", "status"],
        ),
        task_errors=Counter(
            f"{Metrics.NAMESPACE}_{Metrics.TASK_ERRORS}",
            "Total number of task errors",
            ["task_name", "error_type"],
        ),
        task_retries=Counter(
            f"{Metrics.NAMESPACE}_task_retries_total",
            "Total number of task retries",
            ["task_name"],
        ),
        service_state=Gauge(
            f"{Metrics.NAMESPACE}_{Metrics.SERVICE_STATE}",
            "Service state (1=active, 0=inactive, -1=failed)",
            ["service_name", "state"],
        ),
        service_restarts=Counter(
            f"{Metrics.NAMESPACE}_service_restarts_total",
            "Total number of service restarts",
            ["service_name", "reason"],
        ),
        service_uptime=Gauge(
            f"{Metrics.NAMESPACE}_service_uptime_seconds",
            "Service uptime in seconds",
            ["service_name"],
        ),
        api_request_duration=Histogram(
            f"{Metrics.NAMESPACE}_{Metrics.API_REQUEST_DURATION}",
            "API request duration in seconds",
            ["method", "endpoint", "status_code"],
            buckets=Metrics.DURATION_BUCKETS,
        ),
        api_request_count=Counter(
            f"{Metrics.NAMESPACE}_api_requests_total",
            "Total API requests",
            ["method", "endpoint", "status_code"],
        ),
        api_active_requests=Gauge(
            f"{Metrics.NAMESPACE}_api_active_requests",
            "Number of active API requests",
            ["method", "endpoint"],
        ),
        system_info=system_info,
    )
