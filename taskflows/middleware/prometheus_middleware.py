"""FastAPI middleware for Prometheus metrics."""

import time

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from taskflows.metrics import api_active_requests, api_request_count, api_request_duration


class PrometheusMiddleware(BaseHTTPMiddleware):
    """Middleware to track API requests in Prometheus."""

    async def dispatch(self, request: Request, call_next):
        """Track request metrics."""
        # Skip metrics endpoint to avoid recursion
        if request.url.path == "/metrics":
            return await call_next(request)

        method = request.method
        endpoint = request.url.path

        # Track active requests
        api_active_requests.labels(method=method, endpoint=endpoint).inc()

        # Track duration
        start_time = time.time()
        status_code = 500  # Default if error

        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            duration = time.time() - start_time

            # Record metrics
            api_request_duration.labels(
                method=method, endpoint=endpoint, status_code=status_code
            ).observe(duration)

            api_request_count.labels(
                method=method, endpoint=endpoint, status_code=status_code
            ).inc()

            api_active_requests.labels(method=method, endpoint=endpoint).dec()
