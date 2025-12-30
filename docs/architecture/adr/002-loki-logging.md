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
- Fluent Bit configured to read from journald
- Logs tagged with service metadata
- Loki stores logs with labels:
  - `service_name`: Systemd service name
  - `task_id`: Unique task execution ID
  - `level`: Log level (info, warning, error)
  - `hostname`: Server hostname
- LogQL queries embedded in task error alerts
- Grafana dashboards for log exploration

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

Example LogQL query:
```logql
{service_name="my-task"}
  |= "task_id=abc123"
  | json
  | level="error"
```

## References
- [Grafana Loki Documentation](https://grafana.com/docs/loki/latest/)
- [LogQL Query Language](https://grafana.com/docs/loki/latest/logql/)
- [Fluent Bit Configuration](https://docs.fluentbit.io/manual/)
