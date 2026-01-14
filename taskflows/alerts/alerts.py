import asyncio
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Literal, Optional, Sequence, Union

from async_lru import alru_cache

from .components import Component, ContentType, Text
from .discord import DiscordChannel, send_discord_message
from .emails import EmailAddrs, send_email
from .slack import AttachmentFile, SlackChannel, send_slack_message
from .utils import Emoji, logger

MsgDst = Union[EmailAddrs | SlackChannel | DiscordChannel]


@dataclass
class PeriodicMsgs:
    send_to: MsgDst | Sequence[MsgDst]
    msg_buffer: List[Union[str, Component]] = field(default_factory=list)
    on_pub_func: Optional[Callable] = None
    header: Optional[str] = None

    def add_message(self, message: Union[str, Component]):
        """Add a message component to the message buffer.

        Args:
            message (Union[str, Component]): The message component or string to add.
        """
        self.msg_buffer.append(message)

    async def publish(self):
        if self.msg_buffer:
            # Convert strings to Text components for send_alert
            converted_content = []
            for item in self.msg_buffer:
                if isinstance(item, str):
                    converted_content.append(Text(item, ContentType.INFO))
                else:
                    converted_content.append(item)
            await send_alert(converted_content, self.send_to)
            self.msg_buffer.clear()
        if self.on_pub_func:
            self.on_pub_func()


class PeriodicMsgSender:
    """Buffer alerts and concatenate into one message.

    FIXED: Added task tracking, cancellation support, proper error handling,
    and fixed time unit bug (pub_freq is in minutes, not seconds).
    """

    def __init__(self) -> None:
        self._periodic_msgs: Dict[int, List[PeriodicMsgs]] = {}
        # Track tasks for proper cleanup and cancellation
        self._periodic_tasks: Dict[int, asyncio.Task] = {}
        self._shutting_down: bool = False

    async def add_periodic_pub_group_member(self, config: PeriodicMsgs, pub_freq: int):
        """
        Add a function to call at specified frequency.

        Args:
            config: Configuration for periodic messages
            pub_freq: Publish frequency in minutes (will be converted to seconds)
        """
        if pub_freq in self._periodic_msgs:
            self._periodic_msgs[pub_freq].append(config)
        else:
            self._periodic_msgs[pub_freq] = [config]
            # Create and track the periodic task
            task = asyncio.create_task(self._on_func_pub_period(pub_freq))
            self._periodic_tasks[pub_freq] = task

    async def _on_func_pub_period(self, pub_freq: int):
        """Periodic task loop with proper error handling and cancellation support."""
        freq_seconds = pub_freq * 60  # Convert minutes to seconds
        logger.info(f"Started periodic message sender (every {pub_freq} minutes)")

        while not self._shutting_down:
            try:
                cfgs = self._periodic_msgs.get(pub_freq, [])
                for cfg in cfgs:
                    try:
                        await cfg.publish()
                    except Exception as e:
                        logger.error(f"Error publishing periodic message: {e}", exc_info=True)
                        # Continue with other configs even if one fails

                # Sleep for the specified frequency
                await asyncio.sleep(freq_seconds)

            except asyncio.CancelledError:
                logger.info(f"Periodic message sender cancelled (freq={pub_freq} min)")
                break
            except Exception as e:
                logger.error(f"Unexpected error in periodic message loop: {e}", exc_info=True)
                # Wait a bit before retrying to avoid tight error loops
                await asyncio.sleep(min(freq_seconds, 60))

    def cancel_periodic_tasks(self):
        """Cancel all periodic message tasks. Call during shutdown."""
        self._shutting_down = True
        for pub_freq, task in list(self._periodic_tasks.items()):
            if not task.done():
                logger.debug(f"Cancelling periodic task for freq={pub_freq} min")
                task.cancel()
        self._periodic_tasks.clear()

    async def shutdown(self):
        """Graceful shutdown: cancel all tasks and wait for them to complete."""
        self.cancel_periodic_tasks()
        # Wait for all tasks to actually cancel
        if self._periodic_tasks:
            await asyncio.gather(*self._periodic_tasks.values(), return_exceptions=True)


class AlertLogger:
    """Connect to Slack, Discord, or Email and send messages."""

    def __init__(self):
        self.channel: Optional[Union[SlackChannel, DiscordChannel]] = None
        self.disable_messages: bool = False
        self.msg_max_freq: int = 2
        self._log: Optional[Callable] = None
        self._periodic_sender: Optional[PeriodicMsgSender] = None
        self._periodic_msgs: Optional[PeriodicMsgs] = None

    @classmethod
    async def create(
        cls,
        channel: SlackChannel | DiscordChannel | str,
        # default number of seconds to buffer messages before sending.
        msg_max_freq: int = 2,
        disable_messages: bool = False,
    ) -> "AlertLogger":
        self = cls()

        if isinstance(channel, str):
            # Try to determine if it's a Discord webhook URL
            if channel.startswith("https://discord.com/api/webhooks/"):
                self.channel = DiscordChannel(webhook_url=channel)
            else:
                self.channel = SlackChannel(channel=channel)
        else:
            self.channel = channel

        self.disable_messages = disable_messages
        self.msg_max_freq = msg_max_freq
        if self.disable_messages:
            self._log = self._log_msg
        else:
            self._log = self._log_channel
        self._periodic_sender = PeriodicMsgSender()
        self._periodic_msgs = PeriodicMsgs(
            send_to="" if self.disable_messages else self.channel,
        )
        await self._periodic_sender.add_periodic_pub_group_member(
            self._periodic_msgs, pub_freq=self.msg_max_freq
        )
        return self

    async def add_periodic_pub_group_member(
        self, config: PeriodicMsgs, pub_freq: Optional[int] = None
    ):
        if not self.disable_messages and self._periodic_sender:
            await self._periodic_sender.add_periodic_pub_group_member(
                config=config, pub_freq=pub_freq or self.msg_max_freq
            )

    def info(
        self,
        msg: str,
        nowait: bool = False,
    ):
        if self._log:
            self._log(msg=msg, level="info", nowait=nowait)

    def warning(
        self,
        msg: str,
        nowait: bool = False,
    ):
        if self._log:
            self._log(msg=msg, level="warning", nowait=nowait)

    def error(
        self,
        msg: str,
        nowait: bool = False,
    ):
        if self._log:
            self._log(msg=msg, level="error", nowait=nowait)

    def _log_channel(
        self,
        msg: str,
        level: Literal["info", "warning", "error"] = "info",
        nowait: bool = False,
    ):
        self._log_msg(
            msg=msg,
            level=level,
        )
        if self._periodic_msgs:
            self._periodic_msgs.msg_buffer.append(msg)
            if nowait:
                asyncio.create_task(self._periodic_msgs.publish())

    def _log_msg(
        self,
        msg: str,
        level: Literal["info", "warning", "error"] = "info",
        **_,
    ):
        """Send error message to Slack error channel."""
        if level == "error":
            msg = f"{Emoji.red_exclamation} {msg}"
        elif level == "warning":
            msg = f"{Emoji.warning} {msg}"
        getattr(logger, level)(msg, stacklevel=3)
        return msg


@alru_cache(maxsize=10_000)
async def get_alerts_log(channel: str | SlackChannel | DiscordChannel) -> AlertLogger:
    return await AlertLogger.create(channel)


async def send_alert(
    content: Sequence[Component] | Component,
    send_to: MsgDst | Sequence[MsgDst],
    **kwargs,
) -> bool:
    """Send a message via Slack and/or Email.

    Args:
        content (Sequence[Component] | Component): The content to include in the message.
        send_to (MsgDst | Sequence[MsgDst]): Where/how the message should be sent.

    Returns:
        bool: Whether the message was sent successfully.
    """
    if not content:
        return False
    if not isinstance(send_to, (list, tuple)):
        send_to = [send_to]

    # Ensure content is a sequence
    if not isinstance(content, (list, tuple)):
        content = [content]

    # Check for Text components that need file attachments
    attachment_files = []
    for component in content:
        if hasattr(component, "create_attachment_if_needed"):
            attachment_info = component.create_attachment_if_needed()
            if attachment_info:
                filename, file_obj = attachment_info
                attachment_files.append(
                    AttachmentFile(filename=filename, content=file_obj)
                )

    # Add attachment files to kwargs if any exist
    if attachment_files:
        kwargs["attachment_files"] = (
            kwargs.get("attachment_files", []) + attachment_files
        )

    # Create tasks for concurrent execution
    tasks = []
    for st in send_to:
        if isinstance(st, SlackChannel):
            tasks.append(send_slack_message(content=content, channel=str(st), **kwargs))
        elif isinstance(st, EmailAddrs):
            tasks.append(send_email(content=content, send_to=st, **kwargs))
        elif isinstance(st, DiscordChannel):
            tasks.append(send_discord_message(content=content, channel=st, **kwargs))
        else:
            logger.error(
                "Unknown alert destination type (%s): %s. Valid choices: Email, Slack, Discord.",
                type(st),
                st,
            )

    # Execute all tasks concurrently
    sent_ok = await asyncio.gather(*tasks, return_exceptions=True)

    # Handle exceptions and convert to boolean results
    # FIXED: Improved error handling and logging for partial failures
    results = []
    for i, result in enumerate(sent_ok):
        if isinstance(result, Exception):
            # Log detailed exception information
            logger.error(
                f"Error sending alert to {send_to[i]} (type: {type(send_to[i]).__name__}): {result}",
                exc_info=result,
            )
            results.append(False)
        elif isinstance(result, bool):
            results.append(result)
        else:
            # Unexpected return type - log warning and treat as success if truthy
            logger.warning(
                f"Unexpected return type from send alert: {type(result)} = {result!r}"
            )
            results.append(bool(result))

    n_ok = sum(results)
    n_total = len(results)
    if n_ok == n_total:
        logger.info(f"Sent all {n_total} alerts successfully to: {send_to}")
    elif n_ok == 0:
        logger.error(f"Failed to send all {n_total} alerts to: {send_to}")
    else:
        logger.warning(f"Partial success: Sent {n_ok}/{n_total} alerts to: {send_to}")
    return all(results)
