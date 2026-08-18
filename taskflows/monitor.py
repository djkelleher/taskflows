"""Dead-man switch: alert when a scheduled service did NOT run.

Task alerts fire on start/error/finish — but the most common production
failure is silence: the timer never fired, the unit was disabled, or the last
run failed with nobody watching. Services opt in with::

    Service(
        name="nightly-etl",
        start_command="...",
        start_schedule=Calendar("Mon-Fri 07:00"),
        alert_on_missed_run=MissedRunAlert(send_to=SlackChannel(...), grace_seconds=600),
    )

`Service.create()` writes the config to a sidecar JSON next to the service's
pickles. A self-hosted monitor service (``tf monitor install``) periodically
runs :func:`check_missed_runs`, which inspects systemd timer/service state
over D-Bus and alerts when:

- the timer unit is missing or not active (e.g. disabled, machine rebooted
  without enable),
- the timer's next elapse is in the past beyond the grace period (overdue),
- the last service run left the unit in the "failed" state.

Note: the monitor runs on the same host, so it cannot page about the host
itself being down — pair it with external monitoring for that.
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from .alerts import ContentType, Emoji, FontSize, MsgDst, Text, send_alert
from .common import (
    _SYSTEMD_FILE_PREFIX,
    ensure_data_dir,
    logger,
    secure_write_text,
    services_data_dir,
)

MONITOR_SUFFIX = "#monitor.json"


class MissedRunAlert(BaseModel):
    """Dead-man-switch config for one service."""

    # destination(s) to alert (SlackChannel, EmailAddrs, ...)
    send_to: Any
    # how long past the expected run time before alerting
    grace_seconds: int = 300
    # also alert when the last run left the service in the failed state
    alert_on_failure: bool = True

    def model_post_init(self, __context=None) -> None:
        if not isinstance(self.send_to, (list, tuple)):
            self.send_to = [self.send_to]
        for destination in self.send_to:
            if not isinstance(destination, MsgDst):
                raise TypeError(
                    f"send_to entries must be alert destinations (MsgDst), "
                    f"got {type(destination).__name__}"
                )


def monitor_config_file(service_name: str) -> Path:
    return services_data_dir / f"{service_name}{MONITOR_SUFFIX}"


def write_monitor_config(service_name: str, config: MissedRunAlert) -> Path:
    """Persist a service's missed-run config for the monitor service."""
    from .serialization import to_dict

    ensure_data_dir()
    path = monitor_config_file(service_name)
    secure_write_text(path, json.dumps(to_dict(config), indent=2, default=str))
    logger.info(f"Wrote missed-run monitor config: {path}")
    return path


def load_monitor_configs() -> dict[str, MissedRunAlert]:
    """Load all persisted missed-run configs, keyed by service name."""
    from .serialization import from_dict

    configs: dict[str, MissedRunAlert] = {}
    if not services_data_dir.exists():
        return configs
    for path in sorted(services_data_dir.glob(f"*{MONITOR_SUFFIX}")):
        service_name = path.name[: -len(MONITOR_SUFFIX)]
        try:
            configs[service_name] = from_dict(json.loads(path.read_text()), MissedRunAlert)
        except Exception as err:
            logger.error(f"Could not load monitor config {path}: {err}")
    return configs


def _usec_to_datetime(raw: Any) -> datetime | None:
    value = getattr(raw, "value", raw)
    try:
        usec = int(value)
    except (TypeError, ValueError):
        return None
    if usec <= 0:
        return None
    return datetime.fromtimestamp(usec / 1_000_000, tz=UTC)


async def check_service(service_name: str, config: MissedRunAlert, now: datetime) -> list[str]:
    """Return human-readable problems for one monitored service (empty = healthy)."""
    from .systemd import get_schedule_info, get_units

    problems: list[str] = []
    unit_stem = f"{_SYSTEMD_FILE_PREFIX}{service_name.replace(' ', '_')}"

    units = {
        unit["unit_name"]: unit
        for unit in await get_units(match=service_name)
        if unit["unit_name"] in (f"{unit_stem}.timer", f"{unit_stem}.service")
    }

    timer = units.get(f"{unit_stem}.timer")
    if timer is None:
        problems.append("timer unit is not loaded (removed, or never enabled/started)")
    elif timer["active_state"] != "active":
        problems.append(f"timer unit is {timer['active_state']} (expected active)")
    else:
        info = await get_schedule_info(f"{unit_stem}.timer")
        next_start = _usec_to_datetime(info.get("Next Start"))
        if next_start is None:
            problems.append("timer has no scheduled next run")
        elif (now - next_start).total_seconds() > config.grace_seconds:
            overdue = int((now - next_start).total_seconds())
            problems.append(
                f"run is overdue: expected {next_start:%Y-%m-%d %H:%M:%S %Z}, {overdue}s ago"
            )

    if config.alert_on_failure:
        service_unit = units.get(f"{unit_stem}.service")
        if service_unit is not None and service_unit["active_state"] == "failed":
            problems.append("last run failed (service unit is in the failed state)")

    return problems


async def check_missed_runs(send_alerts: bool = True) -> dict[str, list[str]]:
    """Run one monitor pass over all configured services.

    Returns {service_name: [problems]} for services with problems; sends an
    alert per problematic service when send_alerts is True.
    """
    now = datetime.now(UTC)
    results: dict[str, list[str]] = {}
    configs = load_monitor_configs()
    logger.info(f"Checking {len(configs)} monitored services for missed runs")
    for service_name, config in configs.items():
        try:
            problems = await check_service(service_name, config, now)
        except Exception as err:
            problems = [f"monitor check errored: {err}"]
        if not problems:
            continue
        results[service_name] = problems
        if send_alerts:
            components = [
                Text(
                    f"{Emoji.red_exclamation} Missed-run alert: {service_name}",
                    font_size=FontSize.LARGE,
                    level=ContentType.ERROR,
                )
            ] + [
                Text(problem, font_size=FontSize.MEDIUM, level=ContentType.INFO)
                for problem in problems
            ]
            try:
                await send_alert(
                    content=components,
                    send_to=list(config.send_to),
                    subject=f"Missed-run alert: {service_name}",
                )
            except Exception as err:
                logger.error(f"Failed to send missed-run alert for {service_name}: {err}")
    return results


MONITOR_SERVICE_NAME = "monitor"


def build_monitor_service(period_seconds: int = 300):
    """Build the self-hosted taskflows-monitor service definition."""
    import shutil

    from .schedule import Periodic
    from .service import Service

    tf_exe = shutil.which("tf") or "tf"
    return Service(
        name=MONITOR_SERVICE_NAME,
        start_command=f"{tf_exe} monitor check",
        start_schedule=Periodic(start_on="boot", period=period_seconds, relative_to="finish"),
        description="taskflows missed-run monitor (dead-man switch)",
        enabled=True,
    )
