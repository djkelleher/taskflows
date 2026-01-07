import json
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Optional, Sequence

import aiohttp
from pydantic import PositiveInt, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from .components import Component
from .report import render_components_md
from .utils import AttachmentFile, logger, prepare_attachments


@dataclass
class DiscordChannel:
    webhook_url: str

    def __str__(self):
        return self.webhook_url

    def __repr__(self):
        return f"DiscordChannel(webhook_url={self.webhook_url})"


class DiscordSettings(BaseSettings):
    """Settings and config for Discord."""

    webhook_url: Optional[SecretStr] = None
    attachment_max_size_mb: PositiveInt = 20
    inline_tables_max_rows: PositiveInt = 2000
    # Message and request limits
    message_max_length: PositiveInt = 2000  # Discord character limit
    max_attachments: PositiveInt = 10  # Discord file attachment limit
    request_timeout_seconds: PositiveInt = 60  # HTTP request timeout
    retry_attempts: PositiveInt = 3  # Number of retry attempts
    retry_base_delay: float = 2.0  # Base delay for exponential backoff

    model_config = SettingsConfigDict(env_prefix="discord_")


discord_settings = DiscordSettings()


async def send_discord_message(
    content: Sequence[Component],
    channel: DiscordChannel | str,
    username: str = "dl-alerts",
    retries: int = 3,
    attachment_files: Optional[Sequence[str | Path | AttachmentFile]] = None,
    **kwargs,
) -> bool:
    """Send a message to a Discord channel via webhook.

    Args:
        content (Sequence[Component]): The content to include in the message.
        channel (DiscordChannel | str): Discord channel webhook URL or DiscordChannel object.
        username (str, optional): Username for the webhook. Defaults to "dl-alerts".
        retries (int, optional): Number of retry attempts. Defaults to 3.
        attachment_files (Optional[Sequence[str | Path | AttachmentFile]], optional): Files to attach. Defaults to None.

    Returns:
        bool: Whether the message was sent successfully.
    """
    if isinstance(channel, str):
        webhook_url = channel
    else:
        webhook_url = channel.webhook_url

    # Render content as Discord-compatible markdown
    message_text = render_components_md(content, discord_format=True)

    # Use prepare_attachments to handle file processing and potential zipping
    individual_attachments, zip_attachment = prepare_attachments(
        attachment_files, size_threshold_mb=discord_settings.attachment_max_size_mb
    )

    # Use either the zip or individual attachments
    processed_attachments = (
        [zip_attachment] if zip_attachment else individual_attachments
    )

    # Discord has a character limit for messages
    # If we have attachments or message is not too long, send single message
    if (
        processed_attachments
        or len(message_text) <= discord_settings.message_max_length
    ):
        return await _send_single_discord_message(
            webhook_url, message_text, username, retries, processed_attachments
        )
    else:
        # Split into multiple messages if too long and no attachments
        chunks = _split_message(message_text, discord_settings.message_max_length)
        success = True
        for i, chunk in enumerate(chunks):
            # Only send attachments with the first chunk
            chunk_attachments = processed_attachments if i == 0 else []
            success &= await _send_single_discord_message(
                webhook_url, chunk, username, retries, chunk_attachments
            )
        return success


async def _send_single_discord_message(
    webhook_url: str,
    content: str,
    username: str,
    retries: int,
    attachments: Optional[list[AttachmentFile]] = None,
) -> bool:
    """Send a single message to Discord webhook.

    Args:
        webhook_url (str): Discord webhook URL.
        content (str): Message content.
        username (str): Username for the webhook.
        retries (int): Number of retry attempts.
        attachments (Optional[list[AttachmentFile]], optional): Files to attach. Defaults to None.

    Returns:
        bool: Whether the message was sent successfully.
    """
    timeout = aiohttp.ClientTimeout(total=discord_settings.request_timeout_seconds)

    for attempt in range(retries + 1):
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                if attachments:
                    # Use multipart form data for file uploads
                    data = aiohttp.FormData()

                    # Add payload as JSON
                    payload = {
                        "content": content,
                        "username": username,
                    }
                    data.add_field(
                        "payload_json",
                        json.dumps(payload),
                        content_type="application/json",
                    )

                    # Add file attachments
                    for i, attachment in enumerate(
                        attachments[: discord_settings.max_attachments]
                    ):
                        attachment.content.seek(0)
                        file_data = attachment.content.read()

                        # Ensure we have bytes for upload
                        if isinstance(file_data, str):
                            file_data = file_data.encode("utf-8")

                        data.add_field(
                            f"files[{i}]",
                            file_data,
                            filename=attachment.filename,
                            content_type="application/octet-stream",
                        )

                    async with session.post(webhook_url, data=data) as response:
                        if response.status == 200:  # Discord webhook success with files
                            logger.info(
                                f"Discord message with {len(attachments)} attachments sent successfully on attempt {attempt + 1}"
                            )
                            return True
                        elif response.status == 429:  # Rate limited
                            retry_after = response.headers.get("Retry-After", 1)
                            logger.warning(
                                f"Discord rate limited, waiting {retry_after}s before retry"
                            )
                            import asyncio

                            await asyncio.sleep(float(retry_after))
                            continue
                        else:
                            response_text = await response.text()
                            logger.error(
                                f"Discord webhook failed with status {response.status}: {response_text}"
                            )
                else:
                    # Standard JSON payload for messages without attachments
                    payload = {
                        "content": content,
                        "username": username,
                    }
                    headers = {
                        "Content-Type": "application/json",
                    }

                    async with session.post(
                        webhook_url,
                        data=json.dumps(payload),
                        headers=headers,
                    ) as response:
                        if response.status == 204:  # Discord webhook success
                            logger.info(
                                f"Discord message sent successfully on attempt {attempt + 1}"
                            )
                            return True
                        elif response.status == 429:  # Rate limited
                            retry_after = response.headers.get("Retry-After", 1)
                            logger.warning(
                                f"Discord rate limited, waiting {retry_after}s before retry"
                            )
                            import asyncio

                            await asyncio.sleep(float(retry_after))
                            continue
                        else:
                            response_text = await response.text()
                            logger.error(
                                f"Discord webhook failed with status {response.status}: {response_text}"
                            )

        except Exception as e:
            logger.error(
                f"Discord webhook request failed on attempt {attempt + 1}: {e}"
            )

        if attempt < retries:
            import asyncio

            await asyncio.sleep(
                discord_settings.retry_base_delay**attempt
            )  # Exponential backoff

    logger.error(
        f"Failed to send Discord message after {discord_settings.retry_attempts + 1} attempts"
    )
    return False


def _split_message(message: str, max_length: int) -> list[str]:
    """Split a message into chunks that fit Discord's character limit.

    Args:
        message (str): The message to split.
        max_length (int): Maximum length for each chunk.

    Returns:
        list[str]: List of message chunks.
    """
    if len(message) <= max_length:
        return [message]

    # If message has no newlines and is longer than max_length, split directly
    if "\n" not in message and len(message) > max_length:
        chunks = []
        for i in range(0, len(message), max_length):
            chunks.append(message[i : i + max_length])
        return chunks

    chunks = []
    lines = message.split("\n")
    current_chunk = ""

    for line in lines:
        # If adding this line would exceed the limit, start a new chunk
        if len(current_chunk) + len(line) + 1 > max_length:
            if current_chunk:
                chunks.append(current_chunk.strip())
                current_chunk = ""

        # If a single line is too long, split it
        if len(line) > max_length:
            # If we have a current chunk, add it to chunks first
            if current_chunk:
                chunks.append(current_chunk.strip())
                current_chunk = ""

            # Split long lines at word boundaries
            words = line.split(" ")
            temp_line = ""
            for word in words:
                if len(temp_line) + len(word) + 1 > max_length:
                    if temp_line:
                        chunks.append(temp_line.strip())
                        temp_line = ""
                    # If single word is too long, just truncate it
                    if len(word) > max_length:
                        word = word[: max_length - 3] + "..."

                if temp_line:
                    temp_line += " " + word
                else:
                    temp_line = word

            if temp_line:
                current_chunk = temp_line
        else:
            if current_chunk:
                current_chunk += "\n" + line
            else:
                current_chunk = line

    if current_chunk:
        chunks.append(current_chunk.strip())

    return chunks
