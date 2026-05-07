from types import SimpleNamespace

import pytest

from taskflows.middleware import prometheus_middleware
from taskflows.middleware.prometheus_middleware import PrometheusMiddleware


class RecordingMetric:
    def __init__(self):
        self.calls = []
        self.current_labels = None

    def labels(self, **labels):
        self.current_labels = labels
        return self

    def inc(self):
        self.calls.append(("inc", self.current_labels))

    def dec(self):
        self.calls.append(("dec", self.current_labels))

    def observe(self, value):
        self.calls.append(("observe", self.current_labels, value))


@pytest.mark.asyncio
async def test_prometheus_middleware_uses_monotonic_duration(monkeypatch):
    duration_metric = RecordingMetric()
    count_metric = RecordingMetric()
    active_metric = RecordingMetric()

    monkeypatch.setattr(
        prometheus_middleware, "api_request_duration", duration_metric
    )
    monkeypatch.setattr(prometheus_middleware, "api_request_count", count_metric)
    monkeypatch.setattr(prometheus_middleware, "api_active_requests", active_metric)

    perf_values = iter([10.0, 11.25])
    monkeypatch.setattr(
        prometheus_middleware.time,
        "perf_counter",
        lambda: next(perf_values),
    )

    request = SimpleNamespace(method="GET", url=SimpleNamespace(path="/health"))
    response = SimpleNamespace(status_code=204)

    async def call_next(_request):
        return response

    middleware = PrometheusMiddleware(app=SimpleNamespace())

    assert await middleware.dispatch(request, call_next) is response

    assert duration_metric.calls == [
        (
            "observe",
            {"method": "GET", "endpoint": "/health", "status_code": 204},
            1.25,
        )
    ]
    assert count_metric.calls == [
        ("inc", {"method": "GET", "endpoint": "/health", "status_code": 204})
    ]
    assert active_metric.calls == [
        ("inc", {"method": "GET", "endpoint": "/health"}),
        ("dec", {"method": "GET", "endpoint": "/health"}),
    ]
