# taskflows: Task Management, Scheduling, and Alerting System

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
sudo apt install dbus libdbus-1-dev
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

### Loki Configuration
Task execution logs and metadata are stored in Loki for centralized log aggregation. Configure your Loki and Grafana endpoints:

```bash
# Grafana URL (for alert links)
export TASKFLOWS_GRAFANA="http://localhost:3000"

# Loki URL (for log queries)
export TASKFLOWS_LOKI_URL="http://localhost:3100"

# Grafana API key (for dashboard creation)
export TASKFLOWS_GRAFANA_API_KEY="your_api_key"
```

Server registry is stored in a JSON file at `/opt/taskflows/data/servers.json`.

## Usage

### Web UI

taskflows includes a modern web interface for managing services and viewing logs.

#### Setup
```bash
# Install UI dependencies (first time only)
cd taskflows/ui && npm install && cd ../..

# Build the UI
./build_ui.sh

# Setup authentication (first time only)
tf api setup-ui --username admin
# You'll be prompted to create a password

# Start the API with UI enabled
tf api start --enable-ui
```

#### Access
Navigate to **http://localhost:7777** in your browser.

**Features:**
- 🔐 Secure JWT authentication
- 📊 Dashboard with real-time service status
- 🔍 Multi-select and search services
- ⚡ Batch operations (start/stop/restart multiple services)
- 📝 Log viewer with search and auto-scroll
- 🌍 Named environments (reusable venv/docker configurations)
- 🔄 Auto-refresh status every 5 seconds

#### Named Environments
Create reusable environment configurations that can be shared across multiple services:

```python
# Create a named environment via UI or API
# Then reference it in your services:
from taskflows import Service

srv = Service(
    name="my-service",
    start_command="python my_script.py",
    environment="production-venv",  # References named environment
)
```

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

**Loki-First Approach**: Task logs, execution history, and errors are now accessed through Loki log queries instead of database tables. When alerts are sent, they include Grafana/Loki URLs with pre-configured queries to view:
- Task execution logs
- Error traces and stack traces
- Historical task runs

Visit your Grafana instance at `/explore` to query task logs using LogQL. Example query:
```
{service_name=~".*your_task_name.*"}
```

To filter for errors only:
```
{service_name=~".*your_task_name.*"} |= "ERROR"
```

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
| TASKFLOWS_DISPLAY_TIMEZONE | Timezone for display purposes | UTC |
| TASKFLOWS_FLUENT_BIT | Fluent Bit endpoint | localhost:24224 |
| TASKFLOWS_GRAFANA | Grafana URL for alert links | localhost:3000 |
| TASKFLOWS_GRAFANA_API_KEY | Grafana API key for dashboard creation | - |
| TASKFLOWS_LOKI_URL | Loki URL for log queries | http://localhost:3100 |

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
from quicklogs import get_struct_logger, configure_loki_logging

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
from quicklogs import set_request_context, clear_request_context, generate_request_id

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
