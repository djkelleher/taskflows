# ADR 005: Portable scheduling for short-lived commands

## Status

Accepted

## Context

Creating a native service and timer for every short-lived task made bulk status
queries expensive and tied scheduling to Linux. macOS launchd and Windows Task
Scheduler have different schedule and supervision semantics. Taskflows needs a
consistent user-facing contract across all three platforms.

## Decision

Use APScheduler 3.x inside one Taskflows daemon for bounded scheduled commands.
Persist portable task definitions and run history in SQLite. Use APScheduler's
persistent SQLAlchemy job store as dispatch state, while reconciling it from the
Taskflows tables. Register only the daemon with the native OS manager.

Keep systemd-backed `Service` as the Linux execution path for persistent,
privileged, resource-controlled, or dependency-aware processes.

## Consequences

### Positive

- Identical date, interval, cron, timezone, overlap, and misfire controls.
- One fast SQLite bulk query replaces hundreds of per-unit D-Bus queries.
- One daemon definition instead of native artifacts for every task.
- Durable run history and portable stdout/stderr locations.
- Commands are data; APScheduler serializes only stable IDs.

### Negative

- The daemon is a single local scheduling dependency and must be OS-supervised.
- Task execution is at-least-once around hard crashes, not exactly-once.
- Wake-from-sleep and privileged execution remain native-platform concerns.
- APScheduler 3 job stores must not be shared by multiple scheduler processes;
  Taskflows enforces a local singleton lock.

## Alternatives

- **One native timer per task:** strong OS integration, but three incompatible
  implementations and poor portable semantics.
- **Supervisor:** useful process supervision but no calendar scheduler and no
  native Windows support.
- **Custom scheduler:** unnecessary clock, DST, persistence, and misfire risk.
