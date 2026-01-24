# ADR 002: Loki Logging Integration

## Status
Accepted

## Context
Taskflows manages multiple long-running services and tasks that generate logs. We needed:
- Centralized log aggregation across all services
- Efficient log storage and querying
- Integration with Grafana for visualization
- Structured logging with metadata (service name, task ID, etc.)
- Low overhead and resource usage

## Decision
We chose Grafana Loki as our logging backend, using Fluent Bit as the log shipper.

## Rationale

### Advantages of Loki
1. **Label-Based Indexing**: Only indexes metadata (labels), not full text - very efficient
2. **Grafana Integration**: Native integration with Grafana dashboards
3. **LogQL**: Powerful query language similar to PromQL
4. **Cost Effective**: Minimal storage requirements compared to Elasticsearch
5. **Cloud Native**: Designed for Kubernetes/containerized environments
6. **Horizontal Scaling**: Can scale to handle high log volume

### Architecture
```
Services/Tasks (systemd)
    ↓ journald
    ↓
Fluent Bit (log shipper)
    ↓ Loki protocol
    ↓
Loki (storage + query)
    ↓
Grafana (visualization)
```

### Alternatives Considered

**Elasticsearch + Kibana**
- ❌ Heavy resource usage (RAM, CPU, disk)
- ❌ Complex setup and maintenance
- ❌ Indexes full text (expensive)
- ✅ More advanced search capabilities

**Splunk**
- ❌ Commercial/expensive
- ❌ Heavyweight
- ✅ Feature-rich

**CloudWatch Logs**
- ❌ AWS-only
- ❌ Vendor lock-in
- ❌ Cost at scale

**Plain Files + grep**
- ❌ No centralization
- ❌ Poor query performance
- ❌ No visualization

## Implementation

### Structured Logging with structlog

Python services use `structlog` via `taskflows.loggers.structured` to emit JSON-formatted logs:

```python
from taskflows.loggers.structured import configure_loki_logging, get_logger

configure_loki_logging(
    app_name="my-service",
    environment="production",
    log_level="INFO"
)

log = get_logger()
log.info("task_started", task_id="abc123", user_id=42)
```

This produces JSON output:
```json
{"timestamp": "2024-01-15T10:30:00Z", "level_name": "INFO", "logger": "my-service", "app": "my-service", "environment": "production", "event": "task_started", "task_id": "abc123", "user_id": 42}
```

### Fluent Bit JSON Parsing

Fluent Bit reads logs from journald and uses a Lua script (`log_processor.lua`) to:

1. **Detect JSON messages** - Checks if message starts with `{`
2. **Parse and extract labels** - Pulls out key fields for Loki indexing
3. **Preserve the full message** - Keeps complete JSON for detailed queries

Extracted fields become Loki labels:
- `level` - Log level (INFO, WARNING, ERROR)
- `logger` - Logger name
- `app` - Application name
- `environment` - Deployment environment

The Fluent Bit Loki output is configured with:
```yaml
label_keys: $service_name,$level,$logger,$app,$environment
```

### Loki Label Strategy

Labels are indexed and enable fast filtering. We extract only low-cardinality fields:

| Label | Source | Cardinality |
|-------|--------|-------------|
| `service_name` | Systemd unit name | Low |
| `level` | Log level | Very low (5 values) |
| `logger` | Logger name | Low |
| `app` | Application name | Low |
| `environment` | prod/staging/dev | Very low |
| `log_source` | systemd/docker | Very low |
| `host` | Hostname | Low |

High-cardinality fields (task_id, user_id, request_id) remain in the JSON body and are accessed via `| json` pipeline.

### Log Retention
- Default: 30 days
- High-volume services: 7 days
- Critical errors: 90 days

## Consequences

### Positive
- Fast log queries by label
- Low storage costs
- Easy Grafana integration
- Structured logging encourages good practices
- LogQL learning curve shared with PromQL

### Negative
- Full-text search less efficient than Elasticsearch
- Requires Fluent Bit as intermediary
- Limited support for complex log parsing
- Self-hosted infrastructure required

## Task Integration
TaskLogger class automatically:
- Generates unique task_id for correlation
- Builds Loki query URLs for errors
- Includes query links in alert messages
- Provides context for debugging

### Example LogQL Queries

**Fast label-based filtering** (no parsing required):
```logql
{app="my-service", level="ERROR"}
{service_name="worker", environment="production"}
```

**Filter with JSON field extraction** (for high-cardinality fields):
```logql
{service_name="my-task"} | json | task_id="abc123"
{app="api"} | json | user_id=42 | line_format "{{.event}}"
```

**Combined label + JSON filtering**:
```logql
{app="my-service", level="ERROR"}
  | json
  | duration > 5000
  | line_format "{{.event}} took {{.duration}}ms"
```

## References
- [Grafana Loki Documentation](https://grafana.com/docs/loki/latest/)
- [LogQL Query Language](https://grafana.com/docs/loki/latest/logql/)
- [Fluent Bit Configuration](https://docs.fluentbit.io/manual/)
