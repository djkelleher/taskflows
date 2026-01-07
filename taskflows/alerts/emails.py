from copy import deepcopy
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import List, Optional, Sequence

import aiosmtplib
from pydantic import BaseModel, PositiveInt, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .components import Component, Table
from .report import render_components_html
from .utils import (
    AttachmentFile,
    attach_tables,
    logger,
    prepare_attachments,
    use_inline_tables,
)


class EmailSettings(BaseSettings):
    attachment_max_size_mb: PositiveInt = 20
    inline_tables_max_rows: PositiveInt = 2000

    model_config = SettingsConfigDict(env_prefix="email_")


email_settings = EmailSettings()


class EmailAddrs(BaseModel):
    """Configuration for email alerts."""

    sender_addr: str
    password: SecretStr
    receiver_addr: str | List[str]
    smtp_server: str = "smtp.gmail.com"
    smtp_port: PositiveInt = 465

    @field_validator("receiver_addr")
    @classmethod
    def receiver_addr_listify(cls, v: str) -> List[str]:
        if isinstance(v, str):
            return [v]
        return v


async def send_email(
    content: Sequence[Component],
    send_to: EmailAddrs,
    subject: str = "Alert From dl-alerts",
    retries: int = 1,
    attachment_files: Optional[Sequence[str | Path | AttachmentFile]] = None,
    **_,
) -> bool:
    """Send an email.

    Args:
        content (Sequence[Component]): Components used to construct the message.
        send_to (Optional[EmailAddrs]): How/where to send the message.
        subject (str, optional): Subject line. Defaults to "Alert From dl-alerts".
        retries (int, optional): Number of times to retry sending. Defaults to 1.
        attachment_files (Optional[Sequence[str | Path | AttachmentFile]], optional): Files to attach. Defaults to None.
    Returns:
        bool: Whether the message was sent successfully or not.
    """
    # Collect attachment files including table attachments
    attachments_to_process = list(attachment_files) if attachment_files else []

    tables = [t for t in content if isinstance(t, Table)]
    # check if table CSVs should be added as attachments.
    if (
        len(tables)
        and attach_tables(tables, email_settings.attachment_max_size_mb)
        and not use_inline_tables(tables, email_settings.inline_tables_max_rows)
    ):
        for table in tables:
            attachments_to_process.append(table.attach_rows_as_file())

    # Use prepare_attachments to handle file processing and potential zipping
    individual_attachments, zip_attachment = prepare_attachments(
        attachments_to_process, size_threshold_mb=email_settings.attachment_max_size_mb
    )

    # Use either the zip or individual attachments
    final_attachments = [zip_attachment] if zip_attachment else individual_attachments
    # generate HTML from components.
    body = render_components_html(content)
    message = MIMEMultipart("mixed")
    message["From"] = send_to.sender_addr
    message["Subject"] = subject
    message.attach(MIMEText(body, "html"))

    async def try_send_message(attachments=None) -> bool:
        """Send a message using async SMTP.

        Args:
            attachments (Dict[str, StringIO], optional): Map file name to file body. Defaults to None.

        Returns:
            bool: Whether the message was sent successfully or not.
        """
        msg = deepcopy(message)
        if attachments:
            for attachment in attachments:

                file_content = attachment.read_content()
                filename = attachment.filename

                # Determine MIME type based on file extension
                if filename.endswith(".csv"):
                    p = MIMEText(file_content, _subtype="csv")
                elif filename.endswith(".txt"):
                    p = MIMEText(file_content, _subtype="plain")
                elif filename.endswith(".json"):
                    p = MIMEText(file_content, _subtype="json")
                else:
                    # For binary files or unknown types, use base MIME
                    p = MIMEBase("application", "octet-stream")
                    if isinstance(file_content, str):
                        file_content = file_content.encode("utf-8")
                    p.set_payload(file_content)
                    encoders.encode_base64(p)

                p.add_header("Content-Disposition", f"attachment; filename={filename}")
                msg.attach(p)

        for _ in range(retries + 1):
            try:
                await aiosmtplib.send(
                    msg,
                    hostname=send_to.smtp_server,
                    port=send_to.smtp_port,
                    use_tls=True,
                    username=send_to.sender_addr,
                    password=send_to.password.get_secret_value(),
                )
                logger.info("Email sent successfully.")
                return True
            except Exception as err:
                logger.error(f"{type(err)} Error sending email: {err}")
        logger.error(
            "Exceeded max number of retries (%s). Email can not be sent.", retries
        )
        return False

    sent_ok = []
    for addr in send_to.receiver_addr:
        message["To"] = addr
        if await try_send_message(final_attachments):
            sent_ok.append(True)
        else:
            # try sending again, but without attachments if they failed
            if attachment_files:
                # TODO incluade names of failed attachments in subject?
                logger.warning(
                    f"Failed to send email with {len(attachment_files)} attachments, retrying without attachments"
                )
                subject += f" ({len(attachment_files)} Failed Attachments)"
                message["Subject"] = subject
                sent_ok.append(await try_send_message())
            else:
                sent_ok.append(False)
    return all(sent_ok)
