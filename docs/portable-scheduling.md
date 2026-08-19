# Portable scheduling

Taskflows uses APScheduler 3 behind a Taskflows-owned interface for short-lived
commands. One daemon runs per local registry; the OS only supervises that
daemon.

| Platform | Daemon registration |
| --- | --- |
| Linux | systemd user service |
| macOS | `~/Library/LaunchAgents/com.taskflows.scheduler.plist` |
| Windows | per-user Task Scheduler logon task |

The macOS launch agent and Linux user unit are written atomically with
owner-only permissions. The macOS agent is registered in the installing user's
GUI domain; reinstalling re-enables and restarts a previously loaded or
manually disabled agent. Reinstalling the Linux unit also restarts an active
daemon so updated paths and environment settings take effect immediately.

The Windows daemon intentionally runs as the installing interactive user. Its
principal and logon trigger are scoped to that account, it runs with least
privilege, and it remains active when a laptop switches to battery power. A
LocalSystem service would use a different home directory and would run user
commands with unnecessary privileges.

## Schedule semantics

- `date`: exactly one offset-aware ISO timestamp
- `interval`: elapsed seconds from a persisted start time
- `cron`: portable five-field cron with an IANA time zone
- `misfire_grace_time`: discard occurrences older than this limit
- `coalesce`: combine retained missed occurrences into one execution
- `max_instances`: per-task overlap limit; the default is one

APScheduler's persistent SQLAlchemy job store retains dispatch times during a
daemon outage. The `scheduled_tasks` table remains authoritative: startup and
runtime reconciliation removes stale scheduler jobs and updates changed ones.
Exactly-once execution cannot be guaranteed across machine crashes, so commands
should be idempotent. Once the stable runner reserves an attempt, it receives a
durable run record. A hard crash in the hand-off from APScheduler to the runner
can lose or duplicate an occurrence; this limitation is reported explicitly
rather than claiming stronger delivery semantics.

## Execution

The scheduler stores only the task ID and definition revision in APScheduler.
At dispatch, the stable runner loads the current definition, reserves a run
slot transactionally, and starts the command without a shell. Taskflows:

- overlays configured environment values on the daemon environment;
- uses a dedicated process group and terminates the process tree on timeout;
- captures stdout and stderr in owner-only run directories;
- records success, failure, timeout, missed, skipped, and interrupted states;
- marks orphaned `running` records interrupted on daemon startup and keeps
  checking them during reconciliation, releasing overlap slots after orphaned
  children exit without requiring another daemon restart.

Environment values are never returned from list APIs. The SQLite database and
run logs are created with owner-only permissions on POSIX systems.

## Operations

```bash
tf scheduler install
tf scheduler status
tf scheduler start
tf scheduler stop
tf scheduler restart
tf scheduler doctor [--json]
tf scheduler run              # foreground/debug mode
tf scheduler uninstall

tf schedule add NAME --at TIMESTAMP -- COMMAND [ARGS...]
tf schedule add NAME --interval 5m --timeout 2m -- COMMAND [ARGS...]
tf schedule add NAME --interval 1h --start-at TIMESTAMP -- COMMAND [ARGS...]
tf schedule add NAME --cron EXPRESSION --timezone ZONE -- COMMAND [ARGS...]
tf schedule add NAME --interval 1h --env-file .env --env MODE=prod -- COMMAND
tf schedule list --json
tf schedule show NAME [--json]
tf schedule history [NAME]
tf schedule logs NAME [--stream stdout|stderr|both] [--lines 200]
tf schedule prune [--older-than 30d] [--keep-latest 10] [--dry-run]
tf schedule run NAME
tf schedule enable NAME
tf schedule disable NAME
tf schedule remove NAME
```

`tf scheduler status --json` returns the shared `SchedulerStatus` contract. It
combines native manager state and automatic-start configuration with heartbeat,
registry identity, and task counts. `tf scheduler doctor` adds registration,
SQLite integrity/permission, heartbeat, and dispatch-readiness checks with
concrete remedies. Unhealthy results exit non-zero, making both commands useful
in shell scripts and monitoring checks.

Internally, systemd, launchd, and Windows Task Scheduler implement the same
`SchedulerSupervisor` lifecycle (`install`, `uninstall`, `start`, `stop`,
`restart`, and `status`). Scheduling remains inside Taskflows, so native
platform differences do not leak into task definitions or trigger semantics.
Stopping preserves login/boot registration on every platform; uninstalling
removes it.

History pruning never deletes active attempts and protects the requested number
of newest terminal attempts per task definition. Captured logs are removed only
when their resolved path is beneath the registry's Taskflows run directory.

`tf status` now uses the fast bulk systemd summary path for legacy Linux
services. Use `tf status --details` when last/next activation and timer
properties are needed for every matched service.

REST clients can use `/api/schedules`, `/api/schedule-runs`,
`/api/scheduler/status`, and `/api/scheduler/diagnostics`. These endpoints use
the existing HMAC/JWT authentication middleware. Schedule representations
include a `revision`; clients can send `expected_revision` when enabling or
disabling, replacing, or deleting a definition and receive HTTP 409 instead of
silently overwriting a concurrent change. CLI replacements offer the same
guard through `--replace --revision N`. `GET /api/schedules/{id-or-name}`
returns the same non-secret representation used by CLI JSON output. Interval
requests may provide an offset-aware `start_at` timestamp.

Human durations (`30s`, `5m`, `1.5h`, `2d`) are accepted by the CLI. Environment
files are resolved and copied into the registry when `schedule add` runs; they
are not re-read for every occurrence. Explicit `--env KEY=VALUE` options take
precedence. Public output includes environment variable names for diagnostics
but never their values.

## Native services

The portable scheduler is not a replacement for long-running or privileged
services. Linux `Service` objects continue to use systemd for cgroups,
watchdogs, dependencies, failure recovery, and native journald integration.
