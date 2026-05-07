# from pydantic.dataclasses import dataclass
from dataclasses import dataclass
from datetime import datetime
from typing import Literal


def _validate_systemd_timer_value(value: str, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    if not value:
        raise ValueError(f"{field_name} cannot be empty")
    if any(char in value for char in ("\x00", "\n", "\r")):
        raise ValueError(f"{field_name} cannot contain NUL or newline characters")
    return value


class Schedule:
    """Base class for schedules."""

    def __init__(self, accuracy: str):
        accuracy = _validate_systemd_timer_value(accuracy, "accuracy")
        # AccuracySec controls the maximum delay systemd may add to timer events.
        # By default, systemd batches timer activations within a 1-minute window
        # for power efficiency (reduces CPU wake-ups). Setting a low accuracy like
        # "1ms" ensures timers fire at their exact scheduled time.
        self.unit_entries = {f"AccuracySec={accuracy}"}


@dataclass
class Calendar(Schedule):
    """Run a service at specified time(s)."""

    # when to start the service.
    # Format: DayOfWeek Year-Month-Day Hour:Minute:Second TimeZone
    # Time zone is optional. Day of week possible values are Sun,Mon,Tue,Wed,Thu,Fri,Sat
    # Examples:
    # Sun 17:00 America/New_York
    # Mon-Fri 16:00
    # Mon,Wed,Fri 16:30:30
    schedule: str
    # if machine is down at `schedule` time, start the service as soon as machine is back up.
    persistent: bool = True
    # max allowed deviation from declared start time.
    accuracy: str = "1ms"

    def __post_init__(self):
        self.schedule = _validate_systemd_timer_value(self.schedule, "schedule")
        super().__init__(self.accuracy)
        self.unit_entries.add(f"OnCalendar={self.schedule}")
        if self.persistent:
            self.unit_entries.add("Persistent=true")

    @classmethod
    def from_datetime(cls, dt: datetime):
        return cls(schedule=dt.strftime("%a %Y-%m-%d %H:%M:%S %Z").strip())


@dataclass
class Periodic(Schedule):
    """Run a service periodically."""

    # 'boot': Start service when machine is booted.
    # 'login': Start service when user logs in.
    # 'command': Don't automatically start service. Only start on explicit command from user.
    start_on: Literal["boot", "login", "command"]
    # Run the service every `period` seconds.
    period: int
    # 'start': Measure period from when the service started.
    # 'finish': Measure period from when the service last finished.
    relative_to: Literal["finish", "start"]
    # max allowed deviation from declared start time.
    accuracy: str = "1ms"

    def __post_init__(self):
        if self.start_on not in ("boot", "login", "command"):
            raise ValueError("start_on must be one of: boot, login, command")
        if self.relative_to not in ("finish", "start"):
            raise ValueError("relative_to must be one of: finish, start")
        if self.period <= 0:
            raise ValueError("period must be greater than 0 seconds")
        super().__init__(self.accuracy)
        # start on
        if self.start_on == "boot":
            # start 1 second after boot.
            self.unit_entries.add("OnBootSec=1")
        elif self.start_on == "login":
            # start 1 second after the service manager is started (which is on login).
            self.unit_entries.add("OnStartupSec=1")
        # relative_to
        if self.relative_to == "start":
            # defines a timer relative to when the unit the timer unit is activating was last activated.
            self.unit_entries.add(f"OnUnitActiveSec={self.period}s")
        elif self.relative_to == "finish":
            # defines a timer relative to when the unit the timer unit is activating was last deactivated.
            self.unit_entries.add(f"OnUnitInactiveSec={self.period}s")
