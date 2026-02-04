import random
import sys
import zipfile
from dataclasses import dataclass
from io import BytesIO, StringIO
from itertools import cycle
from pathlib import Path
from typing import List, Optional, Sequence, Tuple, Union

import emoji
from loguru import logger


def get_logger(name: str = None):
    """Get a loguru logger instance."""
    return logger


class Emoji:
    # there is no green up arrow :(
    red_down_arrow = "🔻"
    red_exclamation = "❗"
    red_x = "❌"
    hollow_red_circle = "⭕"
    red_circle = "🔴"
    yellow_circle = "🟡"
    blue_circle = "🔵"
    purple_circle = "🟣"
    brown_circle = "🟤"
    green_circle = "🟢"
    green_check = "✅"
    warning = "⚠️"
    rocket = "🚀"
    fire = "🔥"
    turtle = "🐢"
    alarm_clock = "⏰"
    clock = "🕒"
    info = "ℹ️"
    lightbulb = "💡"
    bell = "🔔"
    person = "👤"


@dataclass
class AttachmentFile:
    content: BytesIO | StringIO
    filename: str

    @classmethod
    def from_file(cls, file: str | Path):
        """Create AttachmentFile from a file path."""
        file = Path(file)
        return cls(content=BytesIO(file.read_bytes()), filename=file.name)

    def read_content(self) -> bytes | str:
        """Read the content of the file."""
        self.content.seek(0)  # Ensure we read from the start
        return self.content.read()


def price_dir_emoji(value):
    return Emoji.red_circle if value < 0 else Emoji.green_circle


class EmojiCycle:
    def __init__(self):
        """
        Initializes the EmojiCycle instance by creating a shuffled iterator of emojis.

        This method collects all emoji characters from the emoji data set whose length
        is less than or equal to 2. It then shuffles them randomly to ensure variety
        in emoji selection and initializes an iterator to cycle through these emojis.
        """
        all_emojis = [e for e in emoji.EMOJI_DATA.keys() if len(e) <= 2]
        random.shuffle(all_emojis)
        self.emoji_iter = cycle(all_emojis)
        # Cache for group names to emoji mapping
        self._group_cache = {}

    def __next__(self):
        return self.next_emoji()

    def next_emoji(self):
        return next(self.emoji_iter)

    def group_emoji(self, name: str):
        """Get a consistent emoji for a group name."""
        if name not in self._group_cache:
            self._group_cache[name] = self.next_emoji()
        return self._group_cache[name]


def as_code_block(text: str) -> str:
    """Format text as code block."""
    if text == "":
        return "```\n```"
    return f"```\n{text}\n```"


def use_inline_tables(tables: Sequence["Table"], inline_tables_max_rows: int) -> bool:
    """Check if tables are small enough to be displayed inline in the message.

    Args:
        tables (Sequence[Table]): All tables that are to be included in the message.
        inline_tables_max_rows (int): Max number of table rows that can be used in the message.

    Returns:
        bool: Whether inline tables should be used.
    """
    if not tables:
        return True  # No tables to display, so inline is appropriate
    if (
        sum(len(t.rows) if t.rows is not None else 0 for t in tables)
        < inline_tables_max_rows
    ):
        return True
    return False


def attach_tables(tables: Sequence["Table"], attachments_max_size_mb: int) -> bool:
    """Check if tables are small enough to be attached as files.

    Args:
        tables (Sequence[Table]): The tables that should be attached as files.
        attachments_max_size_mb (int): Max total size of all attachment files.

    Returns:
        bool: Whether files can should be attached.
    """
    if tables:
        tables_size_mb = (
            sum(sys.getsizeof(t.rows) if t.rows is not None else 0 for t in tables)
            / 10**6
        )
        if tables_size_mb < attachments_max_size_mb:
            logger.debug(f"Adding {len(tables)} tables as attachments.")
            return True
        else:
            logger.debug(
                "Can not add tables as attachments because size %fmb exceeds max %f",
                tables_size_mb,
                attachments_max_size_mb,
            )
            return False
    return False


def prepare_attachments(
    attachment_files: Optional[Sequence[Union[str, Path, AttachmentFile]]],
    force_zip: bool = False,
    size_threshold_mb: float = 20.0,
    zip_filename: Optional[str] = None,
) -> Tuple[List[AttachmentFile], Optional[AttachmentFile]]:
    """Prepare attachments for sending, optionally zipping them if needed.

    This function handles the logic for processing attachments that can be used
    across email, Slack, and Discord. It will zip files if:
    1. force_zip is True, OR
    2. The total size of attachments exceeds size_threshold_mb

    Args:
        attachment_files: Files to attach (can be paths or AttachmentFile objects)
        force_zip: Force zipping regardless of size
        size_threshold_mb: Size threshold in MB to trigger automatic zipping
        zip_filename: Custom name for the zip file (defaults to single file name + .zip or "files.zip")

    Returns:
        Tuple of (individual_attachments, zip_attachment) where:
        - individual_attachments: List of AttachmentFile objects if not zipped
        - zip_attachment: Single AttachmentFile with zipped content if zipped, None otherwise
    """
    if not attachment_files:
        return [], None

    # Normalize input to list
    if not isinstance(attachment_files, (list, tuple)):
        attachment_files = [attachment_files]

    # Separate AttachmentFile objects from file paths
    attachment_contents: List[AttachmentFile] = []
    file_paths: List[Path] = []
    total_size_bytes = 0

    for item in attachment_files:
        if isinstance(item, AttachmentFile):
            attachment_contents.append(item)
            # Estimate size from content
            item.content.seek(0, 2)  # Seek to end
            total_size_bytes += item.content.tell()
            item.content.seek(0)  # Reset to beginning
        else:
            file_path = Path(item)
            if file_path.exists():
                file_paths.append(file_path)
                total_size_bytes += file_path.stat().st_size
            else:
                logger.warning(f"Attachment file not found: {file_path}")

    # Calculate total size in MB
    total_size_mb = total_size_bytes / (1024 * 1024)

    # Determine if we should zip
    should_zip = force_zip or (total_size_mb > size_threshold_mb)

    if should_zip:
        logger.debug(
            f"Zipping {len(attachment_files)} attachments "
            f"(force_zip={force_zip}, size={total_size_mb:.2f}MB, threshold={size_threshold_mb}MB)"
        )

        # Create zip file in memory
        zip_content = BytesIO()
        with zipfile.ZipFile(zip_content, "w", zipfile.ZIP_DEFLATED) as zf:
            # Add file paths to zip
            for file_path in file_paths:
                zf.write(file_path, arcname=file_path.name)
                logger.debug(f"Added {file_path.name} to zip")

            # Add AttachmentFile objects to zip
            for attachment in attachment_contents:
                content = attachment.read_content()
                # Handle both string and bytes content
                if isinstance(content, str):
                    content = content.encode("utf-8")
                zf.writestr(attachment.filename, content)
                logger.debug(f"Added {attachment.filename} to zip")

        zip_content.seek(0)

        # Determine zip filename
        if zip_filename:
            final_zip_name = zip_filename
        elif len(attachment_files) == 1:
            # Use single file's name + .zip
            if attachment_contents:
                final_zip_name = attachment_contents[0].filename + ".zip"
            else:
                final_zip_name = file_paths[0].name + ".zip"
        else:
            final_zip_name = "files.zip"

        # Create AttachmentFile for the zip
        zip_attachment = AttachmentFile(content=zip_content, filename=final_zip_name)
        return [], zip_attachment
    else:
        # Return individual attachments without zipping
        all_attachments: List[AttachmentFile] = []

        # Convert file paths to AttachmentFile objects
        for file_path in file_paths:
            all_attachments.append(AttachmentFile.from_file(file_path))

        # Add existing AttachmentFile objects
        all_attachments.extend(attachment_contents)

        return all_attachments, None
