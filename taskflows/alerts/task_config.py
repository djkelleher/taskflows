"""Task alert configuration and built-in sending.

Alert destinations are `MsgDst` instances (SlackChannel, EmailAddrs,
DiscordChannel, ...). New destination types only need to be added to taskflows.alerts;
taskflows accepts any MsgDst. Alert sending is best-effort: a failing alert is
logged and never fails the task that triggered it.
"""

from collections.abc import Sequence
from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel

from ..common import logger
from . import ContentType, Emoji, FontSize, MsgDst, Text

TaskEvent = Literal["start", "error", "finish"]


class Alerts(BaseModel):
    # where to send the alerts (any alert destination, e.g. SlackChannel, EmailAddrs)
    send_to: Any
    # when to send the alerts (start, error, finish)
    send_on: Sequence[TaskEvent] | TaskEvent = ["start", "error", "finish"]

    def model_post_init(self, __context=None) -> None:
        if not isinstance(self.send_to, (list, tuple)):
            self.send_to = [self.send_to]
        for destination in self.send_to:
            if not isinstance(destination, MsgDst):
                raise TypeError(
                    f"send_to entries must be alert destinations (MsgDst), "
                    f"got {type(destination).__name__}"
                )
        if isinstance(self.send_on, str):
            self.send_on = [self.send_on]


def normalize_alerts(
    alerts: Optional["Alerts | MsgDst | Sequence[Alerts | MsgDst]"],
) -> list[Alerts] | None:
    """Normalize alert configuration to a list of Alerts objects."""
    if not alerts:
        return None
    if isinstance(alerts, (Alerts, MsgDst)):
        alerts = [alerts]
    return [a if isinstance(a, Alerts) else Alerts(send_to=a) for a in alerts]


async def _safe_send(task_name: str, event: str, **kwargs) -> None:
    """Send an alert; log and swallow failures so alerts never fail the task."""
    # Resolve through the package at call time so applications can replace or
    # instrument the public sender without reaching into this implementation.
    from . import send_alert

    try:
        await send_alert(**kwargs)
    except Exception as error:
        logger.error(f"Failed to send {event} alert for task {task_name}: {error}")


async def send_start_alert(name: str, send_to: list[MsgDst]) -> None:
    components = [
        Text(
            f"{Emoji.blue_circle} Starting: {name}",
            font_size=FontSize.LARGE,
            level=ContentType.IMPORTANT,
        )
    ]
    await _safe_send(name, "start", content=components, send_to=send_to)


async def send_error_alert(
    name: str,
    error: Exception,
    send_to: list[MsgDst],
    logs_url: str | None = None,
    error_msg_max_length: int = 5000,
) -> None:
    subject = f"{type(error).__name__} Error executing task {name}"
    components = [
        Text(
            f"{Emoji.red_circle} {subject}: {error}",
            font_size=FontSize.LARGE,
            level=ContentType.ERROR,
            max_length=error_msg_max_length,
        )
    ]
    if logs_url:
        components.append(
            Text(
                f"View error logs in Loki: {logs_url}",
                font_size=FontSize.MEDIUM,
                level=ContentType.INFO,
            )
        )
    await _safe_send(name, "error", content=components, send_to=send_to, subject=subject)


async def send_finish_alert(
    name: str,
    send_to: list[MsgDst],
    success: bool,
    start_time: datetime,
    finish_time: datetime,
    return_value: Any = None,
    errors: Sequence[Exception] = (),
    logs_url: str | None = None,
    error_msg_max_length: int = 5000,
) -> None:
    components = [
        Text(
            f"{Emoji.green_circle if success else Emoji.red_circle} Finished: {name} "
            f"| {start_time} - {finish_time} ({finish_time - start_time})",
            font_size=FontSize.LARGE,
            level=(ContentType.IMPORTANT if success else ContentType.ERROR),
        )
    ]
    if return_value is not None:
        components.append(
            Text(
                f"Result: {return_value}",
                font_size=FontSize.MEDIUM,
                level=ContentType.IMPORTANT,
            )
        )
    if errors:
        components.append(
            Text(
                f"ERRORS{Emoji.red_exclamation}",
                font_size=FontSize.LARGE,
                level=ContentType.ERROR,
            )
        )
        for e in errors:
            components.append(
                Text(
                    f"{type(e).__name__}: {e}",
                    font_size=FontSize.MEDIUM,
                    level=ContentType.INFO,
                    max_length=error_msg_max_length,
                )
            )
    if logs_url:
        components.append(
            Text(
                f"View logs in Loki: {logs_url}",
                font_size=FontSize.MEDIUM,
                level=ContentType.INFO,
            )
        )
    await _safe_send(name, "finish", content=components, send_to=send_to)
