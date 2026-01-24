# taskflows

A Python library for task management, service scheduling, and alerting. Convert functions into managed tasks with logging, alerts, and retries. Create systemd services that run on flexible schedules with resource constraints.

## Table of Contents

- [Features](#features)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [Tasks](#tasks)
  - [Task Decorator](#task-decorator)
  - [Programmatic Task Execution](#programmatic-task-execution)
  - [Alerts](#alerts)
- [Services](#services)
  - [Service Configuration](#service-configuration)
  - [Scheduling](#scheduling)
  - [Service Dependencies](#service-dependencies)
  - [Restart Policies](#restart-policies)
  - [ServiceRegistry](#serviceregistry)
- [Environments](#environments)
  - [Virtual Environments](#virtual-environments)
  - [Docker Containers](#docker-containers)
  - [Named Environments](#named-environments)
- [Resource Constraints](#resource-constraints)
  - [Hardware Constraints](#hardware-constraints)
  - [System Load Constraints](#system-load-constraints)
  - [Cgroup Configuration](#cgroup-configuration)
- [CLI Reference](#cli-reference)
- [Web UI](#web-ui)
- [API Server](#api-server)
- [Security](#security)
- [Logging & Monitoring](#logging--monitoring)
- [Slack Bot](#slack-bot)
- [Environment Variables](#environment-variables)

## Features

- **Tasks**: Convert any Python function (sync or async) into a managed task with:
  - Automatic retries on failure
  - Configurable timeouts
  - Alerts via Slack and Email
  - Structured logging with Loki integration
  - Context tracking with `get_current_task_id()`

- **Services**: Create systemd services with:
  - Calendar-based scheduling (cron-like)
  - Periodic scheduling with boot/login triggers
  - Service dependencies and relationships
  - Configurable restart policies
  - Resource constraints (CPU, memory, I/O)

- **Environments**: Run services in:
  - Conda/Mamba virtual environments
  - Docker containers with full configuration
  - Named reusable environment configurations

- **Management**: Control services via:
  - CLI (`tf` command)
  - Web UI with JWT authentication
  - REST API
  - Slack bot with interactive commands

## Installation

```bash
pip install taskflows
```

### Prerequisites

```bash
# Required for systemd integration
sudo apt install dbus libdbus-1-dev

# Enable user services to run without login
loginctl enable-linger
```

## Quick Start

### Create a Task

```python
from taskflows import task, Alerts
from alerts import Slack

@task(
    name="my-task",
    retries=3,
    timeout=60,
    alerts=Alerts(
        send_to=Slack(channel="alerts"),
        send_on=["start", "error", "finish"]
    )
)
async def process_data():
    # Your code here
    return "Done"

# Execute the task
if __name__ == "__main__":
    process_data()
```

### Create a Service

```python
from taskflows import Service, Calendar

srv = Service(
    name="daily-job",
    start_command="python /path/to/script.py",
    start_schedule=Calendar("Mon-Fri 09:00 America/New_York"),
    enabled=True,  # Start on boot
)
srv.create()
```

## Tasks

### Task Decorator

The `@task` decorator wraps any function with managed execution:

```python
from taskflows import task, Alerts, get_current_task_id
from alerts import Slack, Email

@task(
    name="data-pipeline",        # Task identifier (default: function name)
    required=True,               # Raise exception on failure
    retries=3,                   # Retry attempts on failure
    timeout=300,                 # Timeout in seconds
    alerts=Alerts(
        send_to=[
            Slack(channel="alerts"),
            Email(
                addr="sender@example.com",
                password="...",
                receiver_addr=["team@example.com"]
            )
        ],
        send_on=["start", "error", "finish"]
    )
)
async def run_pipeline():
    # Access current task ID for correlation
    task_id = get_current_task_id()
    print(f"Running task: {task_id}")
    # ... your code ...
```

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `name` | `str` | Function name | Unique task identifier |
| `required` | `bool` | `False` | If `True`, exceptions are re-raised after all retries |
| `retries` | `int` | `0` | Number of retry attempts on failure |
| `timeout` | `float` | `None` | Execution timeout in seconds |
| `alerts` | `Alerts` | `None` | Alert configuration |
| `logger` | `Logger` | Default | Custom logger instance |

### Programmatic Task Execution

Run functions as tasks without the decorator:

```python
from taskflows import run_task

async def my_function(x, y):
    return x + y

result = await run_task(
    my_function,
    name="add-numbers",
    retries=2,
    timeout=30,
    x=1, y=2
)
```

### Alerts

Configure when and where to send alerts:

```python
from taskflows import Alerts
from alerts import Slack, Email

alerts = Alerts(
    send_to=[
        Slack(channel="critical"),
        Email(
            addr="sender@gmail.com",
            password="app-password",
            receiver_addr=["oncall@company.com"]
        )
    ],
    send_on=["start", "error", "finish"]  # Events to trigger alerts
)
```

**Alert Events:**
- `start`: Task execution begins
- `error`: An exception occurred (sent per retry)
- `finish`: Task execution completed (includes success/failure status)

Alerts include Grafana/Loki URLs for viewing task logs directly.

## Services

### Service Configuration

Services are systemd units that run commands on schedules:

```python
from taskflows import Service, Calendar, Periodic, Venv

srv = Service(
    # Identity
    name="my-service",
    description="Processes daily reports",

    # Commands
    start_command="python process.py",
    stop_command="pkill -f process.py",       # Optional
    restart_command="python process.py reload", # Optional

    # Scheduling
    start_schedule=Calendar("Mon-Fri 09:00"),
    stop_schedule=Calendar("Mon-Fri 17:00"),  # Optional
    restart_schedule=Periodic(                 # Optional
        start_on="boot",
        period=3600,
        relative_to="finish"
    ),

    # Environment
    environment=Venv("myenv"),  # Or DockerContainer, or named env string
    working_directory="/app",
    env={"DEBUG": "1"},
    env_file="/path/to/.env",

    # Behavior
    enabled=True,               # Auto-start on boot
    timeout=300,                # Max runtime in seconds
    kill_signal="SIGTERM",
    restart_policy="on-failure",
)
srv.create()
```

**Key Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `name` | `str` | Service identifier |
| `start_command` | `str \| Callable` | Command or function to execute |
| `stop_command` | `str` | Command to stop the service |
| `environment` | `Venv \| DockerContainer \| str` | Execution environment |
| `start_schedule` | `Calendar \| Periodic` | When to start |
| `stop_schedule` | `Schedule` | When to stop |
| `restart_schedule` | `Schedule` | When to restart |
| `enabled` | `bool` | Start on boot |
| `timeout` | `int` | Max runtime (seconds) |
| `restart_policy` | `str \| RestartPolicy` | Restart behavior |

### Scheduling

#### Calendar Schedule

Run at specific times using systemd calendar syntax:

```python
from taskflows import Calendar

# Daily at 2 PM Eastern
Calendar("Mon-Sun 14:00 America/New_York")

# Weekdays at 9 AM
Calendar("Mon-Fri 09:00")

# Specific days and time
Calendar("Mon,Wed,Fri 16:30:30")

# From a datetime object
from datetime import datetime, timedelta
Calendar.from_datetime(datetime.now() + timedelta(hours=1))
```

**Calendar Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `schedule` | `str` | Required | Calendar expression |
| `persistent` | `bool` | `True` | Run on wake if missed |
| `accuracy` | `str` | `"1ms"` | Max deviation from scheduled time |

#### Periodic Schedule

Run at intervals after a trigger:

```python
from taskflows import Periodic

# Every 5 minutes after boot
Periodic(
    start_on="boot",        # "boot", "login", or "command"
    period=300,             # Interval in seconds
    relative_to="finish",   # "start" or "finish"
    accuracy="1ms"
)
```

**Periodic Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `start_on` | `Literal["boot", "login", "command"]` | Initial trigger |
| `period` | `int` | Interval in seconds |
| `relative_to` | `Literal["start", "finish"]` | Measure from start or finish |
| `accuracy` | `str` | Max deviation |

### Service Dependencies

Control service startup order and relationships:

```python
srv = Service(
    name="app-server",
    start_command="./start.sh",

    # Ordering
    start_after=["database", "cache"],      # Start after these
    start_before=["monitoring"],            # Start before these

    # Dependencies
    requires=["database"],      # Fail if dependency fails
    wants=["cache"],           # Start together, don't fail if cache fails
    binds_to=["database"],     # Stop when database stops
    part_of=["app-stack"],     # Propagate stop/restart

    # Failure handling
    on_failure=["alert-service"],   # Activate on failure
    on_success=["cleanup-service"], # Activate on success

    # Mutual exclusion
    conflicts=["maintenance-mode"],
)
```

### Restart Policies

Configure automatic restart behavior:

```python
from taskflows import Service, RestartPolicy

# Simple string policy
srv = Service(
    name="worker",
    start_command="python worker.py",
    restart_policy="always",  # "no", "always", "on-failure", "on-abnormal", etc.
)

# Detailed policy
srv = Service(
    name="worker",
    start_command="python worker.py",
    restart_policy=RestartPolicy(
        condition="on-failure",  # When to restart
        delay=10,                # Seconds between restarts
        max_attempts=5,          # Max restarts in window
        window=300,              # Time window in seconds
    ),
)
```

**Restart Conditions:**
- `no`: Never restart
- `always`: Always restart
- `on-success`: Restart on clean exit
- `on-failure`: Restart on non-zero exit
- `on-abnormal`: Restart on signal/timeout
- `on-abort`: Restart on abort signal
- `on-watchdog`: Restart on watchdog timeout

### ServiceRegistry

Manage multiple services together:

```python
from taskflows import Service, ServiceRegistry

registry = ServiceRegistry(
    Service(name="web", start_command="./web.sh"),
    Service(name="worker", start_command="./worker.sh"),
    Service(name="scheduler", start_command="./scheduler.sh"),
)

# Add more services
registry.add(Service(name="monitor", start_command="./monitor.sh"))

# Bulk operations
registry.create()    # Create all services
registry.start()     # Start all services
registry.stop()      # Stop all services
registry.restart()   # Restart all services
registry.enable()    # Enable all services
registry.disable()   # Disable all services
registry.remove()    # Remove all services

# Access individual services
registry["web"].logs()
```

## Environments

### Virtual Environments

Run services in Conda/Mamba environments:

```python
from taskflows import Service, Venv

srv = Service(
    name="ml-pipeline",
    start_command="python train.py",
    environment=Venv("ml-env"),  # Conda environment name
)
```

Automatically detects Mamba, Miniforge, or Miniconda installations.

### Docker Containers

Run services in Docker containers:

```python
from taskflows import Service, DockerContainer, DockerImage, Volume, CgroupConfig

# Using existing image
srv = Service(
    name="api-server",
    environment=DockerContainer(
        image="python:3.11",
        command="python app.py",
        ports={"8080/tcp": 8080},
        volumes=[
            Volume(
                host_path="/data",
                container_path="/app/data",
                read_only=False
            )
        ],
        environment={"ENV": "production"},
        network_mode="bridge",
        restart_policy="no",  # Let systemd handle restarts
        persisted=True,       # Keep container between restarts
        cgroup_config=CgroupConfig(
            memory_limit=1024 * 1024 * 1024,  # 1GB
            cpu_quota=50000,  # 50% CPU
        ),
    ),
)

# Building from Dockerfile
srv = Service(
    name="custom-app",
    environment=DockerContainer(
        image=DockerImage(
            tag="myapp:latest",
            path="/path/to/app",
            dockerfile="Dockerfile",
        ),
        command="./start.sh",
    ),
)
```

**DockerContainer Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `image` | `str \| DockerImage` | Image name or build config |
| `command` | `str \| Callable` | Command to run |
| `name` | `str` | Container name (auto-generated if not set) |
| `persisted` | `bool` | Keep container between restarts |
| `ports` | `dict` | Port mappings |
| `volumes` | `list[Volume]` | Volume mounts |
| `environment` | `dict` | Environment variables |
| `network_mode` | `str` | Network mode |
| `cgroup_config` | `CgroupConfig` | Resource limits |

### Named Environments

Store reusable environment configurations:

```python
from taskflows import Service

# Reference a named environment by string
srv = Service(
    name="my-service",
    start_command="python app.py",
    environment="production-docker",  # Named environment
)
```

Create named environments via the Web UI or API. They store complete Venv or DockerContainer configurations that can be reused across services.

## Resource Constraints

### Hardware Constraints

Require minimum hardware before starting:

```python
from taskflows import Service, Memory, CPUs

srv = Service(
    name="ml-training",
    start_command="python train.py",
    startup_requirements=[
        Memory(amount=8 * 1024**3, constraint=">="),  # 8GB RAM
        CPUs(amount=4, constraint=">="),              # 4+ CPUs
    ],
)
```

**Constraint Operators:** `<`, `<=`, `=`, `!=`, `>=`, `>`

Set `silent=True` to skip silently instead of failing:

```python
Memory(amount=16 * 1024**3, constraint=">=", silent=True)
```

### System Load Constraints

Wait for system load to be acceptable:

```python
from taskflows import Service, CPUPressure, MemoryPressure, IOPressure

srv = Service(
    name="batch-job",
    start_command="python process.py",
    startup_requirements=[
        CPUPressure(max_percent=80, timespan="5min"),
        MemoryPressure(max_percent=70, timespan="1min"),
        IOPressure(max_percent=90, timespan="10sec"),
    ],
)
```

**Timespan Options:** `"10sec"`, `"1min"`, `"5min"`

### Cgroup Configuration

Fine-grained resource control for services and containers:

```python
from taskflows import Service, CgroupConfig

srv = Service(
    name="limited-service",
    start_command="python app.py",
    cgroup_config=CgroupConfig(
        # CPU limits
        cpu_quota=50000,           # Microseconds per period (50% of 1 CPU)
        cpu_period=100000,         # Period in microseconds (default 100ms)
        cpu_shares=512,            # Relative weight
        cpuset_cpus="0-3",         # Pin to CPUs 0-3

        # Memory limits
        memory_limit=2 * 1024**3,  # 2GB hard limit
        memory_high=1.5 * 1024**3, # 1.5GB soft limit
        memory_swap_limit=4 * 1024**3,

        # I/O limits
        io_weight=100,             # I/O priority (1-10000)
        device_read_bps={"/dev/sda": 100 * 1024**2},   # 100MB/s read
        device_write_bps={"/dev/sda": 50 * 1024**2},   # 50MB/s write

        # Process limits
        pids_limit=100,            # Max processes

        # Security
        oom_score_adj=500,         # OOM killer priority
        cap_drop=["NET_RAW"],      # Drop capabilities
    ),
)
```

## CLI Reference

The `tf` command provides service management:

```bash
# Service discovery
tf list [PATTERN]                        # List services matching pattern
tf status [-m PATTERN] [--running] [--all]  # Show service status
tf history [-l LIMIT] [-m PATTERN]       # Show task history
tf logs SERVICE [-n LINES]               # View service logs
tf show PATTERN                          # Show service file contents

# Service control (PATTERN matches service names)
tf create SEARCH_IN [-i INCLUDE] [-e EXCLUDE]  # Create services from Python file/directory
tf start PATTERN [-t/--timers] [--services]    # Start matching services/timers
tf stop PATTERN [-t/--timers] [--services]     # Stop matching services/timers
tf restart PATTERN                              # Restart matching services
tf enable PATTERN [-t/--timers] [--services]   # Enable auto-start
tf disable PATTERN [-t/--timers] [--services]  # Disable auto-start
tf remove PATTERN                               # Remove matching services

# Multi-server (with -s/--server)
tf list -s server1 -s server2
tf status --server prod-host
tf start my-service -s prod-host
```

### API Management

```bash
# Start/stop API server (runs as systemd service)
tf api start
tf api stop
tf api restart

# Setup web UI authentication (interactive, file-based)
tf api setup-ui --username admin
```

To enable the web UI, set the environment variable before starting:
```bash
export TASKFLOWS_ENABLE_UI=1
tf api start
```

Alternatively, use environment variables for Docker/automation:
```bash
export TF_JWT_SECRET=$(tf api generate-secret)
export TF_ADMIN_USER=admin
export TF_ADMIN_PASSWORD=yourpassword
export TASKFLOWS_ENABLE_UI=1
tf api start
```

Or run the API directly (not as a service):
```bash
_start_srv_api --enable-ui
```

### Security Management

```bash
# Setup HMAC authentication
tf api security setup [-r/--regenerate-secret]
tf api security status
tf api security disable
tf api security set-secret SECRET
```

## Web UI

A modern React SPA located in `frontend/`.

#### Setup

```bash
cd frontend

# Install dependencies
npm install

# Development (with hot reload)
npm run dev

# Production build
npm run build
```

#### Running

**Development mode:**
```bash
# Terminal 1: Start the API server
tf api start

# Terminal 2: Start React dev server (proxies API to localhost:7777)
cd frontend && npm run dev
```

Access at **http://localhost:3000**

**Production mode:**
```bash
# Build the frontend
cd frontend && npm run build

# Start API server with UI enabled (serves from frontend/dist/)
export TASKFLOWS_ENABLE_UI=1
tf api start
```

Access at **http://localhost:7777**

#### Tech Stack

- React 19 + TypeScript + Vite
- React Router v7 (protected routes)
- Zustand (auth, UI state)
- React Query (server state with polling)
- TailwindCSS 4

See `frontend/README.md` for detailed documentation.

### Features

- **Dashboard**: Real-time service status with auto-refresh
- **Multi-select**: Select and operate on multiple services
- **Search**: Filter services by name
- **Batch Operations**: Start/stop/restart multiple services
- **Log Viewer**: Search and auto-scroll logs
- **Named Environments**: Create and manage reusable environments

## API Server

The API server provides REST endpoints for service management.

### Starting the Server

```bash
tf api start                      # Default port 7777
TASKFLOWS_ENABLE_UI=1 tf api start  # With web UI
```

### Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/services` | List all services |
| GET | `/services/{name}/status` | Get service status |
| POST | `/services/{name}/start` | Start service |
| POST | `/services/{name}/stop` | Stop service |
| POST | `/services/{name}/restart` | Restart service |
| GET | `/services/{name}/logs` | Get service logs |
| GET | `/environments` | List named environments |
| POST | `/environments` | Create environment |

### Authentication

The API uses HMAC-SHA256 authentication. Include these headers:

```
X-HMAC-Signature: <signature>
X-HMAC-Timestamp: <unix-timestamp>
```

## Security

Taskflows implements multiple security layers to protect against common vulnerabilities and unauthorized access.

### Authentication

#### HMAC Authentication (API)

Secure API communication with HMAC-SHA256 request signing:

```bash
# Initial setup
tf api security setup

# View settings
tf api security status

# Regenerate secret (requires client restart)
tf api security setup --regenerate-secret
```

Configuration stored in `~/.services/security.json`.

**How it works:**
1. Shared secret distributed to authorized clients
2. Each request signed with HMAC-SHA256(secret, timestamp + body)
3. Server validates signature and timestamp (5-minute window)
4. Prevents replay attacks and request tampering

**Protected Operations:**
- Service start/stop/restart
- Service creation/removal
- Environment management

#### JWT Authentication (Web UI)

The web UI uses JWT tokens with bcrypt password hashing. There are two methods to configure authentication:

**Method 1: File-based (Interactive Setup)**

```bash
tf api setup-ui --username admin
# Prompts for password interactively
```

Configuration stored in `~/.taskflows/data/ui_config.json` and `~/.taskflows/data/users.json`.

**Method 2: Environment Variables (Docker/Automation)**

```bash
# Generate a JWT secret
export TF_JWT_SECRET=$(tf api generate-secret)
export TF_ADMIN_USER=admin
export TF_ADMIN_PASSWORD=yourpassword
export TASKFLOWS_ENABLE_UI=1
tf api start
```

Environment variables take precedence over file-based configuration.

**Token Features:**
- Bcrypt hashed passwords (12 rounds) for file-based auth
- 1-hour token expiration
- Automatic refresh on activity
- Secure HTTP-only cookies (when HTTPS enabled)

### Input Validation & Sanitization

Taskflows validates all user input to prevent injection attacks:

#### Path Traversal Prevention
All file paths (`env_file`, working directories) are validated:

```python
# ✅ Safe - absolute path validated
Service(name="my-service", env_file="/home/user/app/.env")

# ❌ Blocked - directory traversal attempt
Service(name="bad", env_file="../../../etc/passwd")  # Raises SecurityError

# ❌ Blocked - symlink escape
Service(name="bad", env_file="/tmp/link-to-etc-passwd")  # Raises SecurityError
```

**Protection mechanisms:**
- Resolves to absolute paths
- Checks against allowed directories
- Detects and blocks symlink escapes
- Prevents `..` path components

#### Service Name Validation
Service names are sanitized to prevent injection:

```python
# ✅ Safe - alphanumeric, dashes, dots, underscores
Service(name="my-service-v2.0_prod")

# ❌ Blocked - path characters
Service(name="../malicious")  # Raises SecurityError
Service(name="/etc/passwd")   # Raises SecurityError

# ❌ Blocked - special characters
Service(name="bad; rm -rf /")  # Raises SecurityError
```

**Allowed characters:** `[a-zA-Z0-9._-]+` only

#### Command Injection Prevention
Docker commands are strictly validated using shell quoting:

```python
# ✅ Safe - properly quoted
DockerContainer(command='python script.py --arg "value with spaces"')

# ❌ Rejected - malformed quotes
DockerContainer(command='python script.py --arg "unterminated')  # Raises ValueError
```

**Protection:** Uses Python's `shlex.split()` with no unsafe fallback

### Credential Management

**Best Practices:**

1. **Never commit secrets** to version control
   ```bash
   # Use .env files (add to .gitignore)
   echo "API_KEY=secret123" > .env

   # Reference in service
   Service(name="app", env_file=".env")
   ```

2. **Use environment variables** for sensitive configuration
   ```python
   import os
   Service(
       name="app",
       environment={
           "DB_PASSWORD": os.getenv("DB_PASSWORD"),
           "API_KEY": os.getenv("API_KEY"),
       }
   )
   ```

3. **Restrict file permissions**
   ```bash
   chmod 600 ~/.services/security.json
   chmod 600 .env
   ```

4. **Rotate secrets regularly**
   ```bash
   tf api security setup --regenerate-secret
   ```

### Docker Socket Security

⚠️ **Warning:** Services with Docker access have root-equivalent permissions.

When using `docker_container`, the service accesses Docker's Unix socket (`/var/run/docker.sock`), which grants:
- Ability to run containers as root
- Access to host filesystem via volume mounts
- Network configuration capabilities

**Mitigation strategies:**

1. **Principle of least privilege** - only use Docker when necessary
   ```python
   # Prefer direct execution
   Service(name="app", exec_start="python app.py")

   # Only containerize when isolation needed
   Service(name="app", docker_container=DockerContainer(...))
   ```

2. **Resource limits** - constrain container resources
   ```python
   DockerContainer(
       name="app",
       cgroup=CgroupConfig(
           memory_limit=1 * 1024**3,  # 1 GB max
           cpu_quota=100000,          # 1 CPU max
           pids_limit=100,             # Max 100 processes
           read_only_rootfs=True,      # Immutable filesystem
       )
   )
   ```

3. **Drop capabilities** - remove unnecessary Linux capabilities
   ```python
   DockerContainer(
       name="app",
       cgroup=CgroupConfig(
           cap_drop=["ALL"],           # Drop all capabilities
           cap_add=["NET_BIND_SERVICE"],  # Only add what's needed
       )
   )
   ```

4. **Network isolation** - use custom networks
   ```python
   DockerContainer(name="app", network_mode="isolated_net")
   ```

### Security Audit Checklist

- [ ] HMAC authentication enabled for API
- [ ] Strong passwords for web UI (12+ characters)
- [ ] Secrets in environment variables or `.env` files
- [ ] `.env` files in `.gitignore`
- [ ] File permissions: `chmod 600` on sensitive files
- [ ] Regular secret rotation schedule
- [ ] Docker used only when necessary
- [ ] Resource limits on all Docker containers
- [ ] Capabilities dropped on Docker containers
- [ ] Review service permissions (user/group)

### Reporting Security Issues

For security vulnerabilities, please **do not** open a public issue. Instead:
1. Email security concerns to: [maintainer email]
2. Include detailed reproduction steps
3. Allow 90 days for patch before disclosure

### Security References

- [OWASP Top 10](https://owasp.org/www-project-top-ten/)
- [Docker Security Best Practices](https://docs.docker.com/engine/security/)
- [systemd Security Features](https://www.freedesktop.org/software/systemd/man/systemd.exec.html#Security)
- [Python Security Best Practices](https://python.readthedocs.io/en/stable/library/security.html)

## Logging & Monitoring

### Architecture

```
Application (structlog) → journald → Fluent Bit → Loki → Grafana
```

### Configuration

```python
from loggers import configure_loki_logging, get_struct_logger

configure_loki_logging(
    app_name="my-service",
    environment="production",
    log_level="INFO",
)

logger = get_struct_logger("my_module")
logger.info("user_action", user_id=123, action="login")
```

### Loki Queries

```logql
# All logs for a service
{service_name=~".*my-service.*"}

# Errors only
{service_name=~".*my-service.*"} |= "ERROR"

# By app and environment
{app="my-service", environment="production"}

# Parse JSON and filter
{app="my-service"} | json | context_duration_ms > 1000
```

### Alert Integration

Task alerts include Grafana URLs with pre-configured Loki queries for viewing:
- Task execution logs
- Error traces
- Historical runs

## Slack Alerts

Send task alerts and notifications to Slack channels.

### Setup

1. Create a Slack app at https://api.slack.com/apps

2. Add OAuth scopes:
   - `chat:write`, `chat:write.public`
   - `files:write`

3. Install the app to your workspace and get the Bot Token

4. Set the environment variable:
   ```bash
   export SLACK_BOT_TOKEN=xoxb-...
   ```

### Usage

```python
from taskflows import task, Alerts
from taskflows.alerts import Slack

@task(
    name="my-task",
    alerts=Alerts(
        send_to=Slack(channel="alerts"),
        send_on=["start", "error", "finish"]
    )
)
async def my_task():
    # Your code here
    pass
```

### Programmatic Usage

```python
from taskflows.alerts.slack import send_slack_message
from taskflows.alerts.components import Text, Table

await send_slack_message(
    channel="alerts",
    subject="Task Complete",
    content=[Text("Processing finished successfully")],
)
```

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `TASKFLOWS_ENABLE_UI` | Enable web UI serving | `0` |
| `TASKFLOWS_DISPLAY_TIMEZONE` | Display timezone | `UTC` |
| `TASKFLOWS_FLUENT_BIT` | Fluent Bit endpoint | `localhost:24224` |
| `TASKFLOWS_GRAFANA` | Grafana URL | `localhost:3000` |
| `TASKFLOWS_GRAFANA_API_KEY` | Grafana API key | - |
| `TASKFLOWS_LOKI_URL` | Loki URL | `http://localhost:3100` |
| `LOKI_HOST` | Loki host | `localhost` |
| `LOKI_PORT` | Loki port | `3100` |
| `ENVIRONMENT` | Environment name | `production` |
| `APP_NAME` | Application name | - |

### Slack Alert Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `SLACK_BOT_TOKEN` | Slack Bot OAuth token | - |
| `SLACK_ATTACHMENT_MAX_SIZE_MB` | Max attachment size in MB | `20` |
| `SLACK_INLINE_TABLES_MAX_ROWS` | Max rows for inline tables | `200` |

## Development

### DBus Documentation

- [systemd DBus API](https://www.freedesktop.org/software/systemd/man/latest/org.freedesktop.systemd1.html)
- [go-systemd/dbus](https://pkg.go.dev/github.com/coreos/go-systemd/dbus)

### Testing

```bash
pytest tests/
```

## License

MIT
