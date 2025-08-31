# taskflows: Task Management, Scheduling, and Alerting System

## TODO
cgroup sharing

I want to make a couple different loki config files so that we have different options for log archive/retention. I definitely want log rotation to s3 / other s3 compatible object stores. and I also want drop after specified number of days policy that we currently have now. is there other common configs that you would suggest? maybe we can use a jinja template to create the configs?

fix loki log json encoding
distributed -- queue, service templates?

review the current service function serializarion. it doesn't currently work on docker becaude the serialized file needs to be mounted to docker container. can we set this up to automatically mount the volume? also review the whole process to see if there are ways we can make it simpler/more robust. look at exec.py and other files

####

taskflows is a Python library that provides robust task management, scheduling, and alerting capabilities. It allows you to convert regular functions into managed tasks with logging, alerts, retries, and more. taskflows also supports creating system services that run on specified schedules with flexible constraints.

## Features
- Convert any Python function into a managed task
- Task execution logging and metadata storage
- Configurable alerting via Slack and Email
- Automated retries and timeout handling
- Schedule-based execution using system services
- Support for various scheduling patterns (calendar-based, periodic)
- System resource constraint options

## Setup

### Prerequisites
```bash
sudo apt install dbus
loginctl enable-linger
```

### Security Configuration (Authentication)

The taskflows system uses HMAC-SHA256 authentication to secure communication between components. This prevents unauthorized access to service management operations.

#### Initial Setup

1. **Generate HMAC Secret**:
   ```bash
   dls security setup
   ```
   This command will:
   - Generate a secure HMAC secret
   - Enable authentication by default
   - Save configuration to `~/.services/security.json`

2. **View Current Security Settings**:
   ```bash
   dls security status
   ```

3. **Regenerate Secret** (if needed):
   ```bash
   dls security regenerate-secret
   ```
   Note: After regenerating, all clients (CLI, Slack bot) will need to be restarted to use the new secret.

#### What This Protects

- **Service Management Operations**: All commands that start, stop, create, or modify services
- **Multi-Server Communication**: Ensures commands come from trusted sources
- **API Access**: Prevents unauthorized access to the underlying API
- **Replay Attack Protection**: Uses timestamps with a 5-minute validity window

#### Important Notes

- The HMAC secret is stored in `~/.services/security.json`
- Keep this file secure and don't share the secret
- Authentication is enabled by default after running `dls security setup`
- The system can work without authentication (not recommended for production):
  ```bash
  dls security disable  # ⚠️ Not recommended
  ```

### Database Configuration
Task execution metadata is stored in either:
- SQLite (default, no configuration needed)
- PostgreSQL (requires configuration)

To use a custom database:
```bash
# For SQLite
export DL_SERVICES_DB_URL="sqlite:///path/to/your/database.db"

# For PostgreSQL
export DL_SERVICES_DB_URL="postgresql://user:password@localhost:5432/dbname"
export DL_SERVICES_DB_SCHEMA="custom_schema"  # Optional, defaults to 'services'
```

## Usage

### Command Line Interface
Admin commands are accessed via the `tf` command line tool:
```bash
# Get help on available commands
tf --help

# Create services defined in a Python file
tf create my_services.py

# List active services
tf list

# Stop a service
tf stop service-name
```

### Creating Tasks
Turn any function (optionally async) into a managed task:

```python
import os
from taskflows import task, Alerts, Slack, Email

alerts=[
    Alerts(
        send_to=[
            Slack(
                channel="critical_alerts"
            ),
            Email(
                addr="sender@gmail.com",
                password=os.getenv("EMAIL_PWD"),
                receiver_addr=["someone@gmail.com", "someone@yahoo.com"]
            )
        ],
        send_on=["start", "error", "finish"]
    )
]

@task(
    name='some-task',
    required=True,
    retries=1,
    timeout=30,
    alerts=alerts
)
async def hello():
    print("Hi.")

# Execute the task
if __name__ == "__main__":
    hello()
```

### Task Parameters
- `name`: Unique identifier for the task
- `required`: Whether task failure should halt execution
- `retries`: Number of retry attempts if the task fails
- `timeout`: Maximum execution time in seconds
- `alerts`: Alert configurations for the task

### Review Task Status/Results
Tasks can send alerts via Slack and/or Email, as shown in the above example. Internally, alerts are sent using the [alert-msgs](https://github.com/djkelleher/alert-msgs) package.
Task start/finish times, status, retry count, return values can be found in the `task_runs` table.
Any errors that occurred during the execution of a task can be found in the `task_errors` table.

### Creating taskflows
*Note: To use services, your system must have systemd (the init system on most modern Linux distributions)*

taskflows run commands on a specified schedule. See [Service](services/service/service.py#35) for service configuration options.

To create the service(s), use the `create` method (e.g. `srv.create()`), or use the CLI `create` command (e.g. `tf create my_services.py`)

### Service Examples

#### Calendar-based Scheduling
Run a command at specific calendar days/times:

```python
from taskflows import Calendar, Service

# Run every day at 2:00 PM Eastern Time
srv = Service(
    name="daily-backup",
    start_command="docker start backup-service",
    start_schedule=Calendar("Mon-Sun 14:00 America/New_York"),
)

# Create and register the service
srv.create()
```

#### One-time Scheduling
Run a command once at a specific time:

```python
from datetime import datetime, timedelta
from taskflows import Calendar, Service

# Run once, 30 minutes from now
run_time = datetime.now() + timedelta(minutes=30)
srv = Service(
    name='write-message',
    start_command="bash -c 'echo hello >> hello.txt'",
    start_schedule=Calendar.from_datetime(run_time),
)
srv.create()
```

#### Periodic Scheduling with Constraints
Run a command periodically with system resource constraints:

```python
from taskflows import Service, Periodic, CPUPressure

# Run after system boot, then every 5 minutes
# Skip if CPU usage is over 80% for the last 5 minutes
service = Service(
    name="resource-aware-task",
    start_command="docker start my-service",
    start_schedule=Periodic(start_on="boot", period=60*5, relative_to="start"),
    system_load_constraints=CPUPressure(max_percent=80, timespan="5min", silent=True)
)
service.create()
```

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| DL_SERVICES_DB_URL | Database connection URL | sqlite:///~/.local/share/services/services.db |
| DL_SERVICES_DB_SCHEMA | PostgreSQL schema name | services |
| DL_SERVICES_DISPLAY_TIMEZONE | Timezone for display purposes | UTC |
| DL_SERVICES_DOCKER_LOG_DRIVER | Docker logging driver | json-file |
| DL_SERVICES_FLUENT_BIT_HOST | Fluent Bit host for logging | localhost |
| DL_SERVICES_FLUENT_BIT_PORT | Fluent Bit port for logging | 24224 |

# taskflows Logging Configuration

This module provides optimized logging configurations for the journald → Fluent Bit → Loki pipeline.

## Features

- **Minimal Label Cardinality**: Only essential fields are exposed as Loki labels to maintain performance
- **Nanosecond Timestamps**: Better log ordering in Loki
- **Event Fingerprinting**: Helps identify duplicate events
- **Request Tracing**: Built-in support for request and trace IDs
- **Context Management**: Proper handling of thread-local and async contexts
- **Field Organization**: Non-indexed fields are nested to reduce Loki cardinality
- **JSON Output**: Optimized for Fluent Bit parsing with UTF-8 support
- **Exception Formatting**: Rich traceback with frame limiting
- **String Truncation**: Prevents massive log entries
- **Performance**: Disabled key sorting, lazy evaluation

## Usage

### Basic Usage

```python
from dl.loggers import get_struct_logger, configure_loki_logging

# Configure logging for Loki (call once at startup)
configure_loki_logging(
    app_name="my-service",
    environment="production",
    log_level="INFO"
)

# Get a logger
logger = get_struct_logger("my_module")

# Log with structured data
logger.info("user_action", user_id=123, action="login", ip="192.168.1.1")
```

### Request Context

```python
from dl.loggers import set_request_context, clear_request_context, generate_request_id

# In your request handler
request_id = generate_request_id()
set_request_context(
    request_id=request_id,
    user_id=user.id,
    endpoint="/api/users"
)

try:
    # All logs within this context will include request_id, user_id, and endpoint
    logger.info("processing_request")
    # ... handle request ...
finally:
    clear_request_context()
```

### Advanced Configuration

```python
configure_loki_logging(
    app_name="my-service",
    environment="staging",
    extra_labels={"team": "platform", "version": "1.2.3"},
    log_level="DEBUG",
    enable_console_renderer=False,  # Use JSON output
    max_string_length=2000,  # Truncate long strings
    include_hostname=True,
    include_process_info=False  # Don't include PID/thread info
)
```

## Architecture Overview

```
Application (structlog) → journald → Fluent Bit → Loki → Grafana
                       ↓
                    Log Files → Fluent Bit →
```

## Loki Label Strategy

**Indexed Labels (searchable in Loki):**
- `app`: Application name
- `environment`: Deployment environment
- `hostname`: Host machine
- `severity`: Log level (ERROR, INFO, etc.)
- `level_name`: Syslog-compatible level name
- `logger`: Logger name
- `request_id`: Request correlation ID
- `trace_id`: Distributed trace ID
- `service_name`: Service identifier (from Fluent Bit)
- `container_name`: Container name (from Fluent Bit)

**Non-indexed Fields (in log body):**
- All other fields stored as JSON in log line
- Searchable via LogQL but not indexed

**Fluent Bit Integration:**
- `timestamp`: ISO format timestamp
- `timestamp_ns`: Nanosecond precision timestamp
- `event`: The log message
- `event_fingerprint`: Unique identifier for deduplication

## Fluent Bit Configuration

The provided `fluent-bit.conf` includes:

1. **Multiple Inputs**:
   - Systemd journal for host services
   - JSON log files from applications
   - Docker container logs via journald

2. **Smart Parsing**:
   - `json_structlog` parser for structured logs
   - Automatic JSON parsing with UTF-8 support
   - Field reservation for processing

3. **Label Extraction**:
   - Lua script (`extract_labels.lua`) extracts only necessary labels
   - Prevents high cardinality issues in Loki
   - Handles optional labels gracefully

4. **Outputs**:
   - Primary: Loki with optimized label configuration
   - Debug: Local file and stdout

### Environment Variables

```bash
export LOKI_HOST=localhost      # Default: localhost
export LOKI_PORT=3100          # Default: 3100
export ENVIRONMENT=production   # Default: production
export HOSTNAME=$(hostname)     # Auto-detected
export APP_NAME=my-service     # Used by structlog
```

### Running with Docker Compose

```bash
docker-compose up -d loki fluent-bit
```

## Loki Query Examples

With the improved structure, you can efficiently query logs:

```logql
# Basic queries by labels
{app="my-service", environment="production"}
{app="my-service", severity="ERROR"}
{app="my-service", request_id="abc-123"}

# Search log content
{app="my-service"} |= "database connection"
{app="my-service"} |= "event_fingerprint"

# Parse JSON and filter nested context
{app="my-service"} | json | context_user_id="user-123"

# Performance analysis
{app="my-service"}
  | json
  | context_duration_ms > 1000
  | line_format "Slow request: {{.event}} took {{.context_duration_ms}}ms"

# Error rate by hostname
sum by (hostname) (
  rate({app="my-service", severity="ERROR"}[5m])
)

# Request latency percentiles
{app="my-service"}
  | json
  | context_response_time_ms > 0
  | histogram_quantile(0.95,
      sum by (le) (
        rate(context_response_time_ms[5m])
      )
    )

# Trace specific request
{trace_id="trace-abc123"} | json
```

## Best Practices

1. **Keep Labels Low Cardinality**:
   - Don't use user IDs, timestamps, or unique values as labels
   - Aim for < 1000 unique values per label

2. **Use Request Context**:
   ```python
   # Good: Set context at request boundaries
   set_request_context(request_id=generate_request_id())
   ```

3. **Consistent Event Names**:
   ```python
   # Good: Use descriptive, consistent event names
   logger.info("user_login_success", user_id=123)
   logger.error("database_connection_failed", error=str(e))
   ```

4. **Monitor Label Cardinality**:
   - Check Loki metrics: `loki_index_entries_per_chunk`
   - Use Grafana to monitor label usage

5. **Structure Complex Data**:
   ```python
   # Complex data will be nested under 'context' automatically
   logger.info("order_processed",
               order_id=12345,
               items=[{"sku": "ABC", "qty": 2}],
               total_amount=99.99)
   ```

## Testing

Run the comprehensive test script:

```bash
python test_structlog.py
```

Check logs:
- Local: `tail -f /var/log/fluent-bit/services-logs | jq .`
- Loki: Query `{app="dl-logging-test"}` in Grafana

## Performance Considerations

- JSON rendering optimized with `sort_keys=False` for speed
- Context variables use Python 3.7+ `contextvars` for async safety
- String truncation prevents huge log entries
- Event fingerprinting uses MD5 hash (first 8 chars)
- Non-indexed fields moved to `context` sub-object

## Troubleshooting

1. **Logs not in Loki**:
   - Check Fluent Bit: `curl http://localhost:2020/api/v1/health`
   - Verify Loki: `curl http://localhost:3100/ready`

2. **High memory usage**:
   - Reduce label cardinality
   - Lower `max_string_length` in configuration
   - Check Loki ingestion rate limits

3. **Missing fields in queries**:
   - Non-indexed fields are under `context`
   - Use: `| json | context_field_name="value"`

4. **Timestamp issues**:
   - Ensure NTP sync on all hosts
   - Use `timestamp_ns` field for precise ordering


## Development Resources
dbus documentation:
- https://www.freedesktop.org/software/systemd/man/latest/org.freedesktop.systemd1.html
- https://pkg.go.dev/github.com/coreos/go-systemd/dbus

## taskflows Slack Bot Installation

1. Go to https://api.slack.com/apps and create a new app
2. Under "OAuth & Permissions", add these scopes:
   - chat:write
   - chat:write.public
   - commands
   - app_mentions:read
   - im:read
   - im:write
   - channels:read
   - groups:read
   - files:write
   - users:read
3. Under "App Home":
   - Enable App Home
   - Enable "Allow users to send Slash commands and messages from the messages tab"
4. Under "Interactivity & Shortcuts":
   - Enable Interactivity
   - Set Request URL to your bot's URL + /slack/events
   - Add Global Shortcut:
     - Name: taskflows Quick Actions
     - Callback ID: services_quick_actions
5. Create slash commands:
   - "/tf" with the URL to your bot + /slack/events
   - "/tf-dashboard" with the URL to your bot + /slack/events
   - "/tf-health" with the URL to your bot + /slack/events
6. Install the app to your workspace
7. Set these environment variables:
   - SERVICES_SLACK_BOT_TOKEN=xoxb-your-token
   - SERVICES_SLACK_SIGNING_SECRET=your-signing-secret
   - SERVICES_SLACK_ALLOWED_USERS=U12345,U67890 (optional)
   - SERVICES_SLACK_ALLOWED_CHANNELS=C12345,C67890 (optional)
   - SERVICES_SLACK_USE_SOCKET_MODE=true (optional)
   - SERVICES_SLACK_APP_TOKEN=xapp-your-token (required if using socket mode)
   - SERVICES_SLACK_RATE_LIMIT_PER_MINUTE=10 (optional, default: 10)
   - SERVICES_SLACK_DANGEROUS_COMMANDS=remove,stop,disable (optional)
8. Run "tf-slack start" to start the bot

🎛️ Dashboard Options:
📱 App Home Dashboard - Click the app in your sidebar (Recommended)
💬 Channel Dashboard - Use `/tf dashboard` or `/tf-dashboard`
🖥️ Modal Dashboard - Use `/tf-dashboard modal`
🌐 Web Integration - Use `/tf-dashboard web`


## TODO params


| Setting                          | `systemd`                       | `docker`                       | Notes                                              |
| -------------------------------- | ------------------------------- | ------------------------------ | -------------------------------------------------- |
| **Memory limit**                 | `MemoryMax=`                    | `--memory` or `--memory-limit` | Hard memory limit                                  |
| **Memory reservation**           | `MemoryLow=` / `MemoryMin=`     | `--memory-reservation`         | Preferred memory; soft limit                       |
| **CPU limit (quota)**            | `CPUQuota=`                     | `--cpu-quota`, `--cpu-period`  | Limit CPU time available                           |
| **CPU shares (relative weight)** | `CPUShares=`                    | `--cpu-shares`                 | Relative CPU priority                              |
| **CPUs allowed (affinity)**      | `AllowedCPUs=` (cgroup v2)      | `--cpuset-cpus`                | Which CPUs to run on                               |
| **Block IO weight**              | `IOWeight=` or `BlockIOWeight=` | `--blkio-weight`               | Relative disk IO weight                            |
| **PIDs limit**                   | `TasksMax=`                     | `--pids-limit`                 | Max number of processes                            |
| **Cgroup delegation**            | `Delegate=yes`                  | N/A                            | Required for containers to manage their own cgroup |
| **OOMScoreAdjust**               | `OOMScoreAdjust=`               | `--oom-score-adj`              | Adjusts OOM killer preference                      |
| **Swappiness**                   | `MemorySwapMax=` (cgroup v2)    | `--memory-swap`                | Controls swap behavior                             |

| Setting                 | `systemd`                               | `docker`                           | Notes                        |
| ----------------------- | --------------------------------------- | ---------------------------------- | ---------------------------- |
| **Read-only root FS**   | `ReadOnlyPaths=` / `ProtectSystem=full` | `--read-only`                      | Makes FS immutable           |
| **Capability control**  | `CapabilityBoundingSet=`                | `--cap-add`, `--cap-drop`          | Restricts Linux capabilities |
| **User Namespaces**     | `User=` with `DynamicUser=yes`          | `--userns`                         | Isolate UID/GID mappings     |
| **Mount propagation**   | `MountFlags=` or mount units            | `--mount`, `--volume`, `--tmpfs`   | Manage mount visibility      |
| **Device restrictions** | `DeviceAllow=`                          | `--device`, `--device-cgroup-rule` | Limit device access          |

| Feature                   | `systemd`                             | `docker`                | Notes                   |
| ------------------------- | ------------------------------------- | ----------------------- | ----------------------- |
| **Restart policy**        | `Restart=`                            | `--restart`             | Auto-restart on failure |
| **Logging**               | `StandardOutput=journal`              | `--log-driver=journald` | Use journald for logs   |
| **Environment variables** | `Environment=`                        | `--env`                 | Set process environment |
| **Timeouts**              | `TimeoutStartSec=`, `TimeoutStopSec=` | `--stop-timeout`        | Graceful stop time      |
| **Exec command**          | `ExecStart=`                          | `CMD`, `ENTRYPOINT`     | Main process to run     |


| What you control                      | systemd directive                           | Docker flag / Compose key                                | Notes                                                                                       |
| ------------------------------------- | ------------------------------------------- | -------------------------------------------------------- | ------------------------------------------------------------------------------------------- |
| **Relative share** (v2) / shares (v1) | `CPUWeight=` (or `CPUShares=` on v1)        | `--cpu-shares`                                           | Higher weight ⇒ more cycles. ([freedesktop.org][1], [docs.docker.com][2])                   |
| **Hard ceiling**                      | `CPUQuota=` + optional `CPUQuotaPeriodSec=` | `--cpu-quota`, `--cpu-period`, or the shorthand `--cpus` | Limits μs of CPU per period (defaults 100 ms). ([freedesktop.org][1], [docs.docker.com][2]) |
| **CPU affinity**                      | `AllowedCPUs=` / `CPUAffinity=`             | `--cpuset-cpus`                                          | Pins to specific cores. ([freedesktop.org][1], [docs.docker.com][2])                        |

[1]: https://www.freedesktop.org/software/systemd/man/systemd.resource-control.html "systemd.resource-control"
[2]: https://docs.docker.com/engine/containers/resource_constraints/ "Resource constraints | Docker Docs"


| What you control           | systemd directive | Docker flag            | Notes                                                                            |
| -------------------------- | ----------------- | ---------------------- | -------------------------------------------------------------------------------- |
| **Hard limit**             | `MemoryMax=`      | `--memory` (`-m`)      | Process killed when limit exceeded. ([freedesktop.org][1], [docs.docker.com][2]) |
| **Soft / high-water mark** | `MemoryHigh=`     | `--memory-reservation` | Reclaim begins when crossed.                                                     |
| **Swap allowance**         | `MemorySwapMax=`  | `--memory-swap`        | Total = RAM + swap.                                                              |

[1]: https://www.freedesktop.org/software/systemd/man/systemd.resource-control.html?utm_source=chatgpt.com "systemd.resource-control - Freedesktop.org"
[2]: https://docs.docker.com/engine/containers/resource_constraints/ "Resource constraints | Docker Docs
"


| systemd     | Docker         | Effect                                                                                          |
| ----------- | -------------- | ----------------------------------------------------------------------------------------------- |
| `TasksMax=` | `--pids-limit` | Caps the number of simultaneous threads/processes. ([freedesktop.org][1], [docs.docker.com][2]) |

[1]: https://www.freedesktop.org/software/systemd/man/systemd.resource-control.html "systemd.resource-control"
[2]: https://docs.docker.com/reference/cli/docker/container/run/?utm_source=chatgpt.com "docker container run - Docker Docs"

| What you control              | systemd                                        | Docker                                                                                 |                                                                        |
| ----------------------------- | ---------------------------------------------- | -------------------------------------------------------------------------------------- | ---------------------------------------------------------------------- |
| **Relative I/O weight**       | `IOWeight=`                                    | `--blkio-weight`                                                                       | Competes for device time. ([freedesktop.org][1], [docs.docker.com][2]) |
| **Throttle bandwidth / IOPS** | `IOReadBandwidthMax=` / `IOWriteBandwidthMax=` | `--device-read-bps`, `--device-write-bps`, `--device-read-iops`, `--device-write-iops` | Per-device limits.                                                     |

[1]: https://www.freedesktop.org/software/systemd/man/250/systemd.resource-control.html?utm_source=chatgpt.com "systemd.resource-control - Freedesktop.org"
[2]: https://docs.docker.com/reference/cli/docker/container/update/?utm_source=chatgpt.com "docker container update - Docker Docs"


| Purpose            | systemd                                          | Docker                             |
| ------------------ | ------------------------------------------------ | ---------------------------------- |
| Device allow/deny  | `DeviceAllow=`, `DevicePolicy=`                  | `--device`, `--device-cgroup-rule` |
| Linux capabilities | `CapabilityBoundingSet=`, `AmbientCapabilities=` | `--cap-add`, `--cap-drop`          |
| Read-only root FS  | `ProtectSystem=strict` / `ReadOnlyPaths=`        | `--read-only`                      |


| Resource controller     | systemd unit directive                                                        | Docker CLI flag(s)                                                                                                   | Notes                                                                                               |
| ----------------------- | ----------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------- |
| **CPU shares**          | `CPUAccounting=yes`<br>`CPUShares=` *n*<br>`CPUWeight=` *w*                   | `--cpu-shares` *n*<br>`--cpu-weight` *w* (cgroup v2 only)                                                            | Shares are a relative weight.  In cgroup v2 you’d normally use `CPUWeight` rather than `CPUShares`. |
| **CPU quota**           | `CPUQuota=` *percent*%                                                        | `--cpu-period=100000 --cpu-quota=` *microseconds*                                                                    | e.g. `CPUQuota=50%` ≈ `--cpu-period=100000 --cpu-quota=50000`                                       |
| **CPU affinity**        | `CPUAffinity=` *mask*                                                         | `--cpuset-cpus=` *cpus*                                                                                              | Pin the unit/container to specific CPU cores.                                                       |
| **Memory limit**        | `MemoryAccounting=yes`<br>`MemoryMax=` *bytes*                                | `--memory=` *bytes*<br>`--memory-swap=` *bytes*                                                                      | Systemd also has `MemoryHigh`, `MemoryLow`, `MemoryMin` on cgroup v2.                               |
| **Memory reservation**  | —— (not directly)                                                             | `--memory-reservation=` *bytes*                                                                                      | On cgroup v2 you’d use `MemoryLow=` for a soft-limit.                                               |
| **Swap limit**          | `MemorySwapMax=` *bytes*                                                      | `--memory-swap=` *bytes*                                                                                             | Swap-limit must be ≥ memory limit.                                                                  |
| **Block IO weight**     | `BlockIOWeight=` *w*                                                          | `--blkio-weight=` *w*                                                                                                | Weight from 10 to 1000.                                                                             |
| **Block IO throttle**   | `BlockIODeviceWeight=`<br>`BlockIOReadBandwidth=`<br>`BlockIOWriteBandwidth=` | `--device-read-bps=` *path\:rate*<br>`--device-write-bps=` *path\:rate*<br>`--blkio-weight-device=` *device\:weight* | Per-device throttling.                                                                              |
| **PIDs limit**          | `TasksMax=` *n*<br>`PIDsMax=` *n*                                             | `--pids-limit=` *n*                                                                                                  | `TasksMax` also limits total threads/processes.                                                     |
| **Unified cgroup path** | `Slice=` *name*.slice<br>`Delegate=` *yes/no*                                 | `--cgroup-parent=` *path*                                                                                            | Attach containers or units under a specific cgroup tree.                                            |


Some IO limits (blkio, io.*) may not work reliably across nested cgroups.

Device restrictions (DeviceAllow=) do not apply to the container unless done explicitly in Docker.
