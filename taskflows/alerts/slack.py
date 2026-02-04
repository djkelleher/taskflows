from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional, Sequence

from pydantic import PositiveInt, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from slack_sdk.web.async_client import AsyncWebClient
from toolz import partition_all

from .components import Component
from .report import render_components_md
from .utils import AttachmentFile, logger, prepare_attachments


@dataclass
class SlackChannel:
    channel: str

    def __str__(self):
        return self.channel

    def __repr__(self):
        return f"SlackChannel(channel={self.channel})"


class SlackSettings(BaseSettings):
    """Settings and config for Slack."""

    bot_token: Optional[SecretStr] = None
    attachment_max_size_mb: PositiveInt = 20
    inline_tables_max_rows: PositiveInt = 200

    model_config = SettingsConfigDict(env_prefix="slack_")


slack_settings = SlackSettings()


@lru_cache
def get_async_client():
    """Return the AsyncWebClient instance."""
    if slack_settings.bot_token is None:
        raise ValueError(
            "Slack bot token is not configured. Please set the SLACK_BOT_TOKEN environment variable."
        )
    return AsyncWebClient(token=slack_settings.bot_token.get_secret_value())


async def try_post_message(
    client: AsyncWebClient,
    channel: str | SlackChannel,
    text: str,
    mrkdwn: bool = True,
    retries: int = 1,
    **kwargs,
):
    """Post a message to a slack channel, with retries."""
    if not text:
        return False
    for _ in range(retries + 1):
        try:
            resp = await client.chat_postMessage(
                channel=str(channel), text=text, mrkdwn=mrkdwn, **kwargs
            )
            if resp.status_code == 200:
                logger.info("Slack alert sent successfully.")
                return True
            logger.error(f"[{resp.status_code}] {channel}")
        except Exception as e:
            logger.error(f"Error posting message to Slack: {e}")
    logger.error("Failed to send Slack alert.")
    return False


async def send_slack_message(
    channel: str | SlackChannel,
    content: Optional[Sequence[Component] | Sequence[Sequence[Component]]] = None,
    retries: int = 1,
    subject: Optional[str] = None,
    attachment_files: Optional[Sequence[str | Path | AttachmentFile]] = None,
    zip_attachment_files: bool = False,
    **_,
) -> bool:
    """Send a message to a Slack channel.

    Args:
        content (Optional[Sequence[Component] | Sequence[Sequence[Component]]]): A message or messages (each message should be Sequence[Component]). If None, only attachments will be sent.
        channel: Slack config.
        retries (int, optional): Number of times to retry sending. Defaults to 1.
        subject (Optional[str], optional): Large bold text to display at the top of the message. Defaults to None.
        attachment_files: Optional[Sequence[str | Path | AttachmentFile]]: Files to attach to the message. Defaults to None.
        zip_attachment_files (bool, optional): Whether to zip the attachment files. Defaults to False.

    Returns:
        bool: Whether the message was sent successfully or not.
    """
    # Only wrap content if not None and not already a list/tuple
    if content is not None and not isinstance(content, (list, tuple)):
        content = [content]  # type: ignore
    client = get_async_client()
    file_ids = []
    kwargs = {}
    if attachment_files:

        async def upload_file(content, filename):
            # Upload the file to Slack
            for _ in range(3):
                try:
                    resp = await client.files_upload_v2(
                        channel=str(channel),
                        file=content,
                        filename=filename,
                    )
                    if resp.status_code == 200:
                        file_ids.append(resp["file"]["id"])
                        return
                except Exception as e:
                    logger.error(f"Error uploading file to Slack: {e}")
                    pass
            logger.warning(
                "Failed to upload file `%s` to Slack channel %s.",
                filename,
                channel,
            )

        # Use the unified prepare_attachments function
        individual_attachments, zip_attachment = prepare_attachments(
            attachment_files,
            force_zip=zip_attachment_files,
            size_threshold_mb=slack_settings.attachment_max_size_mb,
        )

        # Upload either the zip or individual files
        if zip_attachment:
            await upload_file(zip_attachment.read_content(), zip_attachment.filename)
        else:
            for attachment in individual_attachments:
                await upload_file(attachment.read_content(), attachment.filename)

        if file_ids:
            kwargs["files"] = file_ids
    # If neither content nor attachments, nothing to send
    if (content is None or not content) and not attachment_files:
        logger.warning("No content or attachments to send to Slack.")
        return False
    # If only attachments, send a minimal message
    if (content is None or not content) and attachment_files:
        text = subject or "See attached files."
        return await try_post_message(client, channel, text, retries=retries, **kwargs)
    # If content is present, proceed as before
    if content is not None and not isinstance(content[0], (list, tuple)):
        if not subject:
            text = render_components_md(
                components=content,  # type: ignore
                slack_format=True,
            )
            return await try_post_message(
                client, channel, text, retries=retries, **kwargs
            )
        content = [content]  # type: ignore
    messages = [render_components_md(msg, slack_format=True) for msg in content]  # type: ignore
    blocks = [{"type": "divider"}]
    if subject:
        blocks.append(
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": subject,
                    "emoji": True,
                },
            }  # type: ignore
        )
    sent_ok = []
    # Use batches to comply with Slack block limits.
    for batch in partition_all(23, messages):
        for message in batch:
            blocks.append(
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": message,
                        },
                    ],
                }
            )
            blocks.append({"type": "divider"})
        client = get_async_client()
        sent_ok.append(
            await try_post_message(
                client,
                channel,
                text=subject or "dl-alerts",
                retries=retries,
                blocks=blocks,
            )
        )
        blocks.clear()
    return all(sent_ok)
