# ADR 001: Systemd Integration for Service Management

## Status
Accepted

## Context
Taskflows needed a robust way to manage long-running services and scheduled tasks. The solution required:
- Process isolation and resource limits
- Automatic restart on failure
- Scheduled execution (cron-like)
- Logging integration
- Service dependencies
- System-wide persistence across reboots

## Decision
We chose to use systemd as the primary service management layer instead of building a custom process manager or using alternatives like supervisord or Docker Compose.

## Rationale

### Advantages of Systemd
1. **Native OS Integration**: systemd is the standard init system on modern Linux distributions
2. **Resource Control**: Built-in cgroup support for CPU, memory, I/O limits
3. **Timers**: Native scheduling via systemd timers (more reliable than cron)
4. **Logging**: Integrated with journald for structured logging
5. **Dependencies**: Sophisticated dependency management (After=, Requires=, Wants=)
6. **D-Bus API**: Programmatic control via D-Bus for Python integration
7. **User Services**: Support for user-level services without root

### Alternatives Considered

**supervisord**
- ❌ No cgroup v2 support
- ❌ No native timer/scheduling
- ❌ Requires separate process

**Docker Compose**
- ❌ Overkill for simple processes
- ❌ Requires Docker daemon
- ✅ Good for containerized workloads (we use both!)

**Custom Process Manager**
- ❌ Reinventing the wheel
- ❌ Missing features (timers, logging, cgroups)
- ❌ Maintenance burden

## Implementation
- Services defined as Python dataclasses (Service)
- Unit files generated programmatically
- D-Bus communication via dbus-python
- User services in ~/.config/systemd/user/
- Timers for scheduled execution

## Consequences

### Positive
- Leverages battle-tested, well-documented system
- Excellent resource isolation
- Seamless logging integration with Loki/Grafana
- Service persistence across reboots
- Standard tooling (systemctl, journalctl)

### Negative
- Linux-only (not portable to Windows/macOS)
- Requires systemd-enabled distributions
- D-Bus API can be complex
- User service limitations (no system-wide services without root)

## References
- [systemd Documentation](https://www.freedesktop.org/wiki/Software/systemd/)
- [systemd.service - Service unit configuration](https://www.freedesktop.org/software/systemd/man/systemd.service.html)
- [systemd.timer - Timer unit configuration](https://www.freedesktop.org/software/systemd/man/systemd.timer.html)
