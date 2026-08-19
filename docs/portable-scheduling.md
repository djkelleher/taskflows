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
should be idempotent. Every attempt receives a durable run record.

## Execution

The scheduler stores only the task ID and definition revision in APScheduler.
At dispatch, the stable runner loads the current definition, reserves a run
slot transactionally, and starts the command without a shell. Taskflows:

- overlays configured environment values on the daemon environment;
- uses a dedicated process group and terminates the process tree on timeout;
- captures stdout and stderr in owner-only run directories;
- records success, failure, timeout, missed, skipped, and interrupted states;
- marks orphaned `running` records interrupted on daemon startup.

Environment values are never returned from list APIs. The SQLite database and
run logs are created with owner-only permissions on POSIX systems.

## Operations

```bash
tf scheduler install
tf scheduler status
tf scheduler run              # foreground/debug mode
tf scheduler uninstall

tf schedule add NAME --at TIMESTAMP -- COMMAND [ARGS...]
tf schedule add NAME --interval SECONDS -- COMMAND [ARGS...]
tf schedule add NAME --cron EXPRESSION --timezone ZONE -- COMMAND [ARGS...]
tf schedule list --json
tf schedule history [NAME]
tf schedule run NAME
tf schedule enable NAME
tf schedule disable NAME
tf schedule remove NAME
```

`tf status` now uses the fast bulk systemd summary path for legacy Linux
services. Use `tf status --details` when last/next activation and timer
properties are needed for every matched service.

REST clients can use `/api/schedules` and `/api/schedule-runs`. These endpoints
use the existing HMAC/JWT authentication middleware.

## Native services

The portable scheduler is not a replacement for long-running or privileged
services. Linux `Service` objects continue to use systemd for cgroups,
watchdogs, dependencies, failure recovery, and native journald integration.
