# ADR 003: Prometheus Metrics and Observability

## Status
Accepted

## Context
As taskflows grew to manage hundreds of services and tasks, we needed:
- Real-time monitoring of service health
- Task execution metrics (duration, success rate, errors)
- API request performance tracking
- Resource usage visibility
- Alerting on anomalies
- Historical trend analysis

## Decision
We chose Prometheus for metrics collection with the following implementation:
- prometheus-client library for Python instrumentation
- Custom middleware for automatic API metrics
- Service lifecycle metrics at key transition points
- Task execution metrics in the task decorator

## Rationale

### Advantages of Prometheus
1. **Pull-Based Model**: Prometheus scrapes /metrics endpoints (more reliable than push)
2. **PromQL**: Powerful query language for aggregation and analysis
3. **Grafana Integration**: Native Prometheus datasource
4. **Service Discovery**: Automatic target discovery
5. **Alertmanager**: Built-in alerting with routing/deduplication
6. **High Cardinality**: Handles many label combinations efficiently
7. **Industry Standard**: Wide adoption, good ecosystem

### Alternatives Considered

**StatsD + Graphite**
- ❌ Push-based (can overwhelm server)
- ❌ Limited query capabilities
- ❌ Aging technology
- ✅ Simpler setup

**InfluxDB**
- ❌ Push-based
- ❌ Proprietary query language
- ✅ Better for high write volume

**DataDog / New Relic**
- ❌ Commercial/expensive
- ❌ Vendor lock-in
- ✅ Managed service

**OpenTelemetry**
- ✅ Modern standard
- ❌ More complex setup
- ℹ️ Consider for future

## Implementation

### Metric Types

#### Task Metrics
```python
task_duration = Histogram(
    'taskflows_task_duration_seconds',
    'Task execution duration',
    ['task_name', 'status'],  # Labels
    buckets=(0.1, 0.5, 1.0, 5.0, 10.0, 30.0, 60.0, 300.0, 600.0)
)

task_count = Counter(
    'taskflows_task_total',
    'Total task executions',
    ['task_name', 'status']
)

task_errors = Counter(
    'taskflows_task_errors_total',
    'Task errors by type',
    ['task_name', 'error_type']
)

task_retries = Counter(
    'taskflows_task_retries_total',
    'Task retry attempts',
    ['task_name']
)
```

#### Service Metrics
```python
service_state = Gauge(
    'taskflows_service_state',
    'Service state (1=active, 0=inactive, -1=failed)',
    ['service_name', 'state']
)

service_restarts = Counter(
    'taskflows_service_restarts_total',
    'Service restart count',
    ['service_name', 'reason']
)
```

#### API Metrics
```python
api_request_duration = Histogram(
    'taskflows_api_request_duration_seconds',
    'API request duration',
    ['method', 'endpoint', 'status_code']
)

api_request_count = Counter(
    'taskflows_api_request_total',
    'Total API requests',
    ['method', 'endpoint', 'status_code']
)

api_active_requests = Gauge(
    'taskflows_api_active_requests',
    'Currently active API requests',
    ['method', 'endpoint']
)
```

### Prometheus Middleware (FastAPI)
Automatic instrumentation of all API endpoints:
- Request duration (histogram)
- Request count (counter)
- Active requests (gauge)
- Status code tracking
- Excludes /metrics endpoint to avoid recursion

### Instrumentation Points

**Task Execution** (taskflows/tasks.py):
- Start time recorded
- Success/failure/timeout tracked
- Error types classified
- Retries counted

**Service Lifecycle** (taskflows/service.py):
- State changes: active, inactive, failed
- Restart reasons: manual, failure, dependency
- Uptime tracking

**API Layer** (taskflows/middleware/prometheus_middleware.py):
- Every request automatically tracked
- No code changes needed for new endpoints

## Metric Naming Conventions

Following Prometheus best practices:
- Namespace: `taskflows_*`
- Metric type suffix: `_total`, `_seconds`, `_bytes`
- Labels: lowercase, snake_case
- Label cardinality: kept low (<1000 unique combinations)

## Scrape Configuration

```yaml
scrape_configs:
  - job_name: 'taskflows-api'
    scrape_interval: 15s
    static_configs:
      - targets: ['localhost:7777']
```

## Consequences

### Positive
- **Visibility**: Real-time view into system behavior
- **Debugging**: Correlate metrics with logs (same timestamps)
- **Alerting**: Proactive detection of issues
- **Capacity Planning**: Historical trends for scaling decisions
- **Performance**: Minimal overhead (~0.5ms per metric update)

### Negative
- **Cardinality**: Must avoid high-cardinality labels (e.g., user_id)
- **Storage**: Metrics accumulate over time (30-day retention default)
- **Complexity**: PromQL has learning curve
- **Pull Model**: Requires endpoints to be accessible

## Alerting Examples

### Task Failure Rate
```promql
rate(taskflows_task_errors_total[5m]) /
rate(taskflows_task_total[5m]) > 0.1
```

### Slow API Requests
```promql
histogram_quantile(0.95,
  rate(taskflows_api_request_duration_seconds_bucket[5m])
) > 1.0
```

### Service Restarts
```promql
increase(taskflows_service_restarts_total[1h]) > 5
```

## Dashboard Integration

Grafana dashboards provide:
- Task execution overview (success rate, duration percentiles)
- Service health matrix (all services, state colors)
- API performance (request rate, latency, errors)
- Resource usage (when combined with node_exporter)

## Future Enhancements
- Add `system_cpu_usage`, `system_memory_usage` metrics
- Instrument Docker container metrics
- Add database query duration tracking
- Export metrics to remote storage (Thanos, Cortex)

## References
- [Prometheus Documentation](https://prometheus.io/docs/)
- [Prometheus Best Practices](https://prometheus.io/docs/practices/naming/)
- [prometheus_client (Python)](https://github.com/prometheus/client_python)
- [PromQL Query Examples](https://prometheus.io/docs/prometheus/latest/querying/examples/)
