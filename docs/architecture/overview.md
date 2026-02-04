# Taskflows Architecture Overview

## System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      Client Applications                     │
│  (Python scripts, Jupyter notebooks, CLI commands)          │
└───────────────────┬─────────────────────────────────────────┘
                    │
                    ▼
         ┌──────────────────────┐
         │   taskflows Library   │
         │   - @task decorator   │
         │   - Service class     │
         │   - Schedule objects  │
         └──────────┬────────────┘
                    │
        ┌───────────┴───────────┐
        │                       │
        ▼                       ▼
┌───────────────┐       ┌──────────────┐
│  Systemd User │       │  Admin API   │
│    Services   │       │  (FastAPI)   │
│               │       │  Port 7777   │
│ - Timers      │       └──────┬───────┘
│ - Restarts    │              │
│ - Cgroups     │              │
└───────┬───────┘              │
        │                      │
        │                ┌─────┴──────┐
        │                │  D-Bus     │
        │                │  (Control) │
        │                └────────────┘
        │
        ▼
┌───────────────────────────────────────┐
│         Docker Containers             │
│  (Optional for containerized tasks)   │
└────────────┬──────────────────────────┘
             │
             ▼
      ┌──────────────┐
      │  Logging &   │
      │  Monitoring  │
      └──────────────┘
             │
      ┌──────┴──────────┐
      │                 │
      ▼                 ▼
┌──────────┐    ┌───────────────┐
│  Loki    │    │  Prometheus   │
│ (Logs)   │    │  (Metrics)    │
└────┬─────┘    └───────┬───────┘
     │                  │
     └────────┬─────────┘
              ▼
        ┌──────────┐
        │ Grafana  │
        │(Dashboards)
        └──────────┘
```

## Core Components

### 1. Task System
**File**: `taskflows/tasks.py`

The `@task` decorator transforms Python functions into managed, observable tasks:
- **Execution**: Sync and async function support
- **Retries**: Automatic retry with configurable backoff
- **Timeouts**: Hard timeout limits
- **Logging**: Structured logging with unique task IDs
- **Metrics**: Automatic Prometheus instrumentation
- **Alerts**: Failure notifications with Loki query links

Example:
```python
from taskflows import task

@task(name="data-ingestion", timeout=300, retries=3)
async def ingest_data(source: str):
    # Task code here
    pass
```

### 2. Service Management
**File**: `taskflows/service.py`

The `Service` class provides declarative service definitions that compile to systemd units:
- **Types**: Simple, forking, oneshot, notify
- **Scheduling**: Periodic, calendar-based (via timers)
- **Resources**: CPU, memory, I/O limits (cgroups)
- **Restart**: Policies for automatic recovery
- **Dependencies**: After, Requires, Wants

Example:
```python
from taskflows import Service, Periodic, CgroupConfig

service = Service(
    name="api-server",
    description="FastAPI application",
    exec_start="uvicorn app:app --host 0.0.0.0",
    schedule=Periodic(hours=1),  # Run hourly
    cgroup=CgroupConfig(
        memory_limit=2 * 1024 ** 3,  # 2 GB
        cpu_quota=200000,  # 2 CPUs
    ),
    restart_policy="on-failure",
)
```

### 3. Admin API
**File**: `taskflows/admin/api.py`

FastAPI-based REST API for remote service management:
- **Endpoints**: start, stop, restart, enable, disable, status, logs
- **Authentication**: HMAC and JWT support
- **Documentation**: Swagger UI at `/docs`
- **Metrics**: Prometheus metrics at `/metrics`
- **Multi-Server**: Coordinate services across machines

### 4. Docker Integration
**File**: `taskflows/docker.py`

Services can run as Docker containers with full cgroup parity:
- **Container Management**: Automatic container lifecycle
- **Resource Limits**: CPU, memory, I/O (mapped to Docker args)
- **Networking**: Bridge, host, custom networks
- **Volumes**: Mount points for data persistence
- **Environment**: Env vars and env files

### 5. Constraints & Resource Limits
**File**: `taskflows/constraints.py`

Unified cgroup configuration for both systemd and Docker:
- **CPU**: Quota, weight, affinity
- **Memory**: Limits, soft limits, swap
- **I/O**: Weight, device bandwidth/IOPS
- **PIDs**: Process count limits
- **Security**: OOM score, capabilities, read-only rootfs

### 6. Scheduling
**File**: `taskflows/schedule.py`

Two scheduling primitives:
- **Periodic**: Run every N seconds/minutes/hours
- **Calendar**: Cron-like calendar expressions (systemd OnCalendar)

Example:
```python
from taskflows import Schedule

# Run every 30 minutes
schedule1 = Periodic(minutes=30)

# Run daily at 3 AM
schedule2 = Calendar("daily 03:00")

# Run on weekdays at 9 AM
schedule3 = Calendar("Mon..Fri 09:00")
```

### 7. Security
**Files**: `taskflows/security_validation.py`, `taskflows/admin/security.py`

Multi-layered security:
- **Input Validation**: Path traversal prevention, service name sanitization
- **Authentication**: HMAC request signing, JWT tokens
- **Authorization**: Role-based access control
- **Command Safety**: Strict shell quoting validation
- **Secrets**: Passlib for password hashing (bcrypt)

### 8. Observability
**Files**: `taskflows/metrics.py`, `taskflows/middleware/`

Comprehensive observability stack:
- **Metrics**: Prometheus metrics for tasks, services, API
- **Logging**: Structured logs to Loki via Fluent Bit
- **Tracing**: Task IDs for request correlation
- **Dashboards**: Pre-built Grafana dashboards

## Data Flow

### Task Execution Flow
```
1. User calls @task-decorated function
   ↓
2. Task wrapper generates unique task_id
   ↓
3. TaskLogger configured with context
   ↓
4. Prometheus metrics timer started
   ↓
5. Function executes (with timeout, retries)
   ↓
6. Success/failure recorded in metrics
   ↓
7. Logs sent to Loki with task_id label
   ↓
8. Alerts sent on errors (with Loki query URL)
```

### Service Lifecycle
```
1. Service() object created in Python
   ↓
2. .enable() generates systemd unit files
   ↓
3. Unit files written to ~/.config/systemd/user/
   ↓
4. systemctl --user daemon-reload
   ↓
5. systemctl --user start <service>
   ↓
6. Systemd starts process (with cgroups)
   ↓
7. Logs → journald → Fluent Bit → Loki
   ↓
8. Metrics updated (service_state gauge)
   ↓
9. On failure: restart policy triggered
```

## Key Design Decisions

See Architecture Decision Records (ADRs):
- [ADR-001: Systemd Integration](adr/001-systemd-integration.md)
- [ADR-002: Loki Logging](adr/002-loki-logging.md)
- [ADR-003: Prometheus Metrics](adr/003-prometheus-metrics.md)
- [ADR-004: Constants Module](adr/004-constants-module.md)

## Extension Points

### Custom Service Types
Subclass `Service` to add domain-specific behavior:
```python
class WebService(Service):
    def __init__(self, app_module: str, port: int, **kwargs):
        super().__init__(
            exec_start=f"uvicorn {app_module} --port {port}",
            **kwargs
        )
```

### Custom Metrics
Add application-specific metrics:
```python
from prometheus_client import Counter

my_metric = Counter('my_app_events_total', 'Custom events', ['event_type'])
```

### Task Hooks
TaskLogger supports event hooks:
```python
class MyTaskLogger(TaskLogger):
    def on_task_error(self, error: Exception):
        super().on_task_error(error)
        # Custom error handling
        notify_slack(error)
```

## Technology Stack

- **Python**: 3.12+
- **Systemd**: Process management
- **D-Bus**: Systemd communication
- **Docker**: Container runtime (optional)
- **FastAPI**: REST API framework
- **Pydantic**: Data validation
- **Prometheus**: Metrics storage
- **Grafana Loki**: Log aggregation
- **Fluent Bit**: Log shipping
- **Grafana**: Visualization

## Directory Structure

```
taskflows/
├── __init__.py           # Public API exports
├── tasks.py              # @task decorator, TaskLogger
├── service.py            # Service class, systemd integration
├── docker.py             # DockerContainer, Docker integration
├── schedule.py           # Periodic, Calendar scheduling
├── constraints.py        # CgroupConfig, resource limits
├── security_validation.py # Input validation, sanitization
├── exceptions.py         # Exception hierarchy
├── constants.py          # Centralized constants
├── metrics.py            # Prometheus metrics definitions
├── middleware/           # FastAPI middleware
│   ├── __init__.py
│   └── prometheus_middleware.py
├── admin/                # Admin API and utilities
│   ├── __init__.py
│   ├── api.py            # FastAPI application
│   ├── core.py           # Service operations
│   ├── security.py       # Authentication
│   ├── auth.py           # JWT handling
│   ├── models.py         # Type definitions
│   └── utils.py          # Helper functions
├── common.py             # Shared utilities
├── db.py                 # Database integration
└── dashboard.py          # Grafana dashboards

docs/
├── architecture/
│   ├── overview.md       # This file
│   └── adr/              # Architecture Decision Records
│       ├── 001-systemd-integration.md
│       ├── 002-loki-logging.md
│       ├── 003-prometheus-metrics.md
│       └── 004-constants-module.md

tests/
├── test_security.py      # Security validation tests
├── test_cgroup_properties.py  # Property-based tests (Hypothesis)
├── test_integration_service_lifecycle.py  # Integration tests
├── test_task.py          # Task execution tests
├── test_service.py       # Service management tests
└── test_docker.py        # Docker integration tests
```
