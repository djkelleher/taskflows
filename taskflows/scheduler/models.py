from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

ScheduleKind = Literal["date", "interval", "cron"]
RunState = Literal[
    "queued",
    "starting",
    "running",
    "succeeded",
    "failed",
    "timed_out",
    "cancelled",
    "skipped",
    "missed",
    "interrupted",
]

# Portable jobs are deliberately bounded. Callers that truly need an unbounded
# process should use ``Service`` rather than silently turning the scheduler into
# a second service manager.
DEFAULT_TASK_TIMEOUT_SECONDS = 60 * 60
MIN_INTERVAL_SECONDS = 1.0
MAX_CATCH_UP_OCCURRENCES = 1_000
MAX_QUEUED_OCCURRENCES = 10_000
MAX_RUN_LOG_BYTES = 10 * 1024 * 1024


def utc_now() -> datetime:
    return datetime.now(UTC)


def parse_datetime(value: str | datetime) -> datetime:
    """Parse an ISO timestamp and require an unambiguous UTC offset."""
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("scheduled timestamps must include a UTC offset or Z")
    return parsed


def merge_environment(base: Mapping[str, str], overrides: Mapping[str, str]) -> dict[str, str]:
    """Overlay environment values without cross-platform name aliases.

    Windows treats names case-insensitively while POSIX does not. Removing an
    existing case-folded alias before applying each override makes definitions
    such as ``Path=...`` behave consistently and avoids handing Windows two
    conflicting PATH entries.
    """
    merged = dict(base)
    for name, value in overrides.items():
        folded_name = name.casefold()
        for previous in tuple(merged):
            if previous != name and previous.casefold() == folded_name:
                merged.pop(previous)
        merged[name] = value
    return merged


def resolve_working_directory(value: str | Path | None = None) -> str:
    """Return the absolute working directory persisted by every client.

    Native supervisors start in different directories.  Centralizing this
    normalization keeps creates and partial updates from accidentally restoring
    platform-dependent relative-path behavior.
    """

    try:
        path = Path(value).expanduser() if value is not None else Path.cwd()
        return str(path.resolve())
    except (OSError, RuntimeError) as exc:
        raise ValueError(f"could not resolve working directory: {exc}") from exc


@dataclass(frozen=True)
class ScheduleSpec:
    """Portable date, interval, or five-field cron schedule."""

    kind: ScheduleKind
    value: str | float
    timezone: str = "UTC"
    start_at: str | None = None

    def __post_init__(self) -> None:
        try:
            ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"unknown IANA time zone: {self.timezone}") from exc
        if self.kind == "date":
            parse_datetime(str(self.value))
        elif self.kind == "interval":
            try:
                interval = float(self.value)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    "interval must be a finite number greater than zero seconds"
                ) from exc
            if (
                isinstance(self.value, bool)
                or not math.isfinite(interval)
                or interval < MIN_INTERVAL_SECONDS
            ):
                raise ValueError(
                    "interval must be greater than zero and at least "
                    f"{MIN_INTERVAL_SECONDS:g} second"
                )
            if self.start_at is not None:
                parse_datetime(self.start_at)
        elif self.kind == "cron":
            fields = str(self.value).split()
            if len(fields) != 5:
                raise ValueError("cron schedules must contain exactly five fields")
            # Let APScheduler perform complete field validation.
            self.to_trigger()
        else:
            raise ValueError(f"unsupported schedule kind: {self.kind}")

    @classmethod
    def once(cls, run_at: str | datetime, *, timezone: str = "UTC") -> ScheduleSpec:
        return cls("date", parse_datetime(run_at).isoformat(), timezone=timezone)

    @classmethod
    def interval(
        cls,
        seconds: float,
        *,
        start_at: str | datetime | None = None,
        timezone: str = "UTC",
    ) -> ScheduleSpec:
        normalized_start = parse_datetime(start_at).isoformat() if start_at is not None else None
        return cls("interval", seconds, timezone=timezone, start_at=normalized_start)

    @classmethod
    def cron(cls, expression: str, *, timezone: str = "UTC") -> ScheduleSpec:
        return cls("cron", expression, timezone=timezone)

    def to_trigger(self):
        """Build an APScheduler trigger without exposing it in persisted data."""
        from apscheduler.triggers.cron import CronTrigger
        from apscheduler.triggers.date import DateTrigger
        from apscheduler.triggers.interval import IntervalTrigger

        timezone = ZoneInfo(self.timezone)
        if self.kind == "date":
            return DateTrigger(run_date=parse_datetime(str(self.value)), timezone=timezone)
        if self.kind == "interval":
            start_date = parse_datetime(self.start_at) if self.start_at else None
            return IntervalTrigger(
                seconds=float(self.value), start_date=start_date, timezone=timezone
            )
        return CronTrigger.from_crontab(str(self.value), timezone=timezone)

    def to_json(self) -> str:
        return json.dumps(
            {
                "kind": self.kind,
                "value": self.value,
                "timezone": self.timezone,
                "start_at": self.start_at,
            },
            separators=(",", ":"),
        )

    @classmethod
    def from_json(cls, value: str) -> ScheduleSpec:
        return cls(**json.loads(value))

    def describe(self) -> str:
        if self.kind == "date":
            return f"once at {self.value}"
        if self.kind == "interval":
            return (
                f"every {self.value:g}s"
                if isinstance(self.value, float)
                else f"every {self.value}s"
            )
        return f"cron {self.value} ({self.timezone})"

    def with_stable_anchor(self, now: datetime | None = None) -> ScheduleSpec:
        """Persist an interval anchor so reconciliation never shifts its cadence."""

        if self.kind != "interval" or self.start_at is not None:
            return self
        return replace(self, start_at=(now or utc_now()).isoformat())

    def next_fire_times(
        self,
        *,
        after: str | datetime | None = None,
        count: int = 5,
    ) -> tuple[datetime, ...]:
        """Preview upcoming occurrences using the actual portable trigger.

        This deliberately asks APScheduler's trigger rather than duplicating
        cron, interval, DST, or one-shot calculations in each CLI/API client.
        ``after`` is inclusive, matching APScheduler's trigger contract.
        """
        if isinstance(count, bool) or not isinstance(count, int) or count < 1:
            raise ValueError("count must be at least one")
        if count > 1000:
            raise ValueError("count cannot exceed 1000")

        cursor = parse_datetime(after) if after is not None else utc_now()
        trigger = self.to_trigger()
        previous: datetime | None = None
        occurrences: list[datetime] = []
        while len(occurrences) < count:
            next_fire = trigger.get_next_fire_time(previous, cursor)
            if next_fire is None:
                break
            if next_fire < cursor:
                # DateTrigger returns its single date on the first query even
                # when ``now`` is later. Consume that past occurrence so a
                # preview never advertises an already-expired one-off.
                previous = next_fire
                continue
            occurrences.append(next_fire)
            previous = next_fire
            cursor = next_fire
        return tuple(occurrences)


def schedule_preview(
    task: ScheduledTask,
    *,
    after: str | datetime | None = None,
    count: int = 5,
) -> dict[str, Any]:
    """Return one stable CLI/REST projection of upcoming task occurrences."""
    preview_from = parse_datetime(after) if after is not None else utc_now()
    occurrences = task.schedule.next_fire_times(after=preview_from, count=count)
    timezone = ZoneInfo(task.schedule.timezone)
    return {
        "id": task.id,
        "name": task.name,
        "revision": task.revision,
        "enabled": task.enabled,
        "timezone": task.schedule.timezone,
        "from": preview_from.astimezone(UTC).isoformat(),
        "occurrences": [
            {
                "utc": occurrence.astimezone(UTC).isoformat(),
                "local": occurrence.astimezone(timezone).isoformat(),
            }
            for occurrence in occurrences
        ],
    }


@dataclass(frozen=True)
class ScheduledTask:
    """Persisted definition of one short-lived command."""

    id: str
    name: str
    command: tuple[str, ...]
    schedule: ScheduleSpec
    enabled: bool = True
    timeout: float | None = DEFAULT_TASK_TIMEOUT_SECONDS
    cwd: str | None = None
    environment: Mapping[str, str] = field(default_factory=dict)
    misfire_grace_time: int | None = 3600
    coalesce: bool = True
    max_instances: int = 1
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    revision: int = 1
    next_run_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.id or not self.name.strip():
            raise ValueError("task id and name cannot be empty")
        if self.name != self.name.strip():
            raise ValueError("task name cannot have leading or trailing whitespace")
        if any(ord(character) < 32 or ord(character) == 127 for character in self.id + self.name):
            raise ValueError("task id and name cannot contain control characters")
        if not self.command or not isinstance(self.command[0], str) or not self.command[0]:
            raise ValueError("command must start with a non-empty executable")
        if any(not isinstance(part, str) for part in self.command):
            raise TypeError("command arguments must be strings")
        if any("\x00" in part for part in self.command):
            raise ValueError("command arguments cannot contain NUL bytes")
        if self.timeout is not None and (
            isinstance(self.timeout, bool) or not math.isfinite(self.timeout) or self.timeout <= 0
        ):
            raise ValueError("timeout must be greater than zero")
        if self.misfire_grace_time is not None and (
            isinstance(self.misfire_grace_time, bool)
            or not isinstance(self.misfire_grace_time, int)
            or self.misfire_grace_time <= 0
        ):
            raise ValueError("misfire_grace_time must be positive or None")
        if (
            isinstance(self.max_instances, bool)
            or not isinstance(self.max_instances, int)
            or self.max_instances < 1
        ):
            raise ValueError("max_instances must be at least one")
        if (
            isinstance(self.revision, bool)
            or not isinstance(self.revision, int)
            or self.revision < 1
        ):
            raise ValueError("revision must be at least one")
        if self.cwd is not None and (not str(self.cwd).strip() or "\x00" in str(self.cwd)):
            raise ValueError("cwd cannot be empty or contain NUL bytes")
        environment_names: set[str] = set()
        for key, value in self.environment.items():
            if not isinstance(key, str) or not isinstance(value, str):
                raise TypeError("environment keys and values must be strings")
            if not key or "=" in key or "\x00" in key or "\x00" in value:
                raise ValueError("environment variables must have valid, NUL-free names and values")
            # Windows environment names are case-insensitive. Reject aliases
            # such as PATH/Path everywhere so a portable definition cannot
            # have platform-dependent or order-dependent behavior.
            normalized_key = key.casefold()
            if normalized_key in environment_names:
                raise ValueError("environment variable names must be unique ignoring case")
            environment_names.add(normalized_key)
        # A frozen dataclass should not expose a mutable mapping through one of
        # its fields. Copy first so changes to the caller's dictionary cannot
        # silently alter a persisted definition after validation.
        object.__setattr__(self, "environment", MappingProxyType(dict(self.environment)))

    @classmethod
    def create(
        cls,
        name: str,
        command: Sequence[str],
        schedule: ScheduleSpec,
        **kwargs: Any,
    ) -> ScheduledTask:
        if isinstance(command, (str, bytes)):
            raise TypeError("command must be a sequence of arguments, not a string")
        now = utc_now()
        schedule = schedule.with_stable_anchor(now)
        # Native supervisors do not share a guaranteed working directory.
        # Persist an absolute creation-time path even when the caller omits
        # ``cwd`` so relative command arguments behave the same under systemd,
        # launchd, Task Scheduler, foreground mode, and manual execution.
        kwargs["cwd"] = resolve_working_directory(kwargs.get("cwd"))
        return cls(
            id=str(uuid4()),
            name=name,
            command=tuple(command),
            schedule=schedule,
            created_at=now,
            updated_at=now,
            **kwargs,
        )

    @property
    def working_directory(self) -> Path | None:
        return Path(self.cwd) if self.cwd else None

    def to_public_dict(self) -> dict[str, Any]:
        """Return the non-secret representation shared by the CLI and API.

        Environment values are intentionally omitted.  Keeping this projection
        beside the model avoids subtly different public contracts across the
        command line, REST API, and future platform-specific clients.
        """
        return {
            "id": self.id,
            "name": self.name,
            "command": list(self.command),
            "schedule": {
                "kind": self.schedule.kind,
                "value": self.schedule.value,
                "timezone": self.schedule.timezone,
                "start_at": self.schedule.start_at,
                "description": self.schedule.describe(),
            },
            "enabled": self.enabled,
            "timeout": self.timeout,
            "cwd": self.cwd,
            "environment_names": sorted(self.environment, key=str.casefold),
            "misfire_grace_time": self.misfire_grace_time,
            "coalesce": self.coalesce,
            "max_instances": self.max_instances,
            "revision": self.revision,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "next_run_at": self.next_run_at.isoformat() if self.next_run_at else None,
        }


@dataclass(frozen=True)
class RunHandle:
    """Stable result of accepting one manual or scheduled execution request."""

    id: str
    task_id: str | None
    task_name: str
    task_revision: int | None
    scheduled_for: str | None
    status: RunState
    started_at: str | None = None
    finished_at: str | None = None
    exit_code: int | None = None
    error: str | None = None
    stdout_path: str | None = None
    stderr_path: str | None = None

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> RunHandle:
        return cls(
            id=str(row["id"]),
            task_id=row.get("task_id"),
            task_name=str(row["task_name"]),
            task_revision=row.get("task_revision"),
            scheduled_for=row.get("scheduled_for"),
            status=row["status"],
            started_at=row.get("started_at"),
            finished_at=row.get("finished_at"),
            exit_code=row.get("exit_code"),
            error=row.get("error"),
            stdout_path=row.get("stdout_path"),
            stderr_path=row.get("stderr_path"),
        )

    @property
    def terminal(self) -> bool:
        return self.status not in {"queued", "starting", "running"}

    def to_dict(self, *, include_log_paths: bool = False) -> dict[str, Any]:
        result = {
            "id": self.id,
            "task_id": self.task_id,
            "task_name": self.task_name,
            "task_revision": self.task_revision,
            "scheduled_for": self.scheduled_for,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "exit_code": self.exit_code,
            "error": self.error,
        }
        if include_log_paths:
            result.update(stdout_path=self.stdout_path, stderr_path=self.stderr_path)
        return result
