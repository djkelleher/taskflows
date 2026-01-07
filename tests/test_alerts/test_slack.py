from io import BytesIO
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from taskflows.alerts import ContentType, FontSize, Text
from taskflows.alerts.slack import AttachmentFile, SlackChannel, send_slack_message


class TestSlackChannel:
    def test_slack_channel_creation(self):
        """Test SlackChannel creation."""
        channel = SlackChannel("#test-channel")
        assert channel.channel == "#test-channel"

    def test_slack_channel_str_conversion(self):
        """Test SlackChannel string conversion."""
        channel = SlackChannel("#test-channel")
        assert str(channel) == "#test-channel"
        assert repr(channel) == "SlackChannel(channel=#test-channel)"


class TestSendSlackMessage:
    @pytest.fixture
    def mock_client(self):
        """Mock AsyncWebClient."""
        client = AsyncMock()
        client.chat_postMessage.return_value = MagicMock(status_code=200)
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.file = {"id": "test_file_id"}
        client.files_upload_v2.return_value = mock_response
        return client

    @pytest.fixture
    def test_components(self):
        """Test components for Slack messages."""
        return [
            Text("Test message", ContentType.INFO, FontSize.MEDIUM),
            Text("Another test message", ContentType.WARNING, FontSize.SMALL),
        ]

    @patch("taskflows.alerts.slack.get_async_client")
    @pytest.mark.asyncio
    async def test_send_simple_message(
        self, mock_get_client, mock_client, test_components
    ):
        """Test sending a simple message without attachments."""
        mock_get_client.return_value = mock_client
        channel = SlackChannel("#test")

        result = await send_slack_message(
            content=test_components, channel=channel, subject="Test Subject"
        )

        assert result is True
        mock_client.chat_postMessage.assert_called()

        # Check that the call was made with the correct parameters
        call_args = mock_client.chat_postMessage.call_args
        assert call_args[1]["channel"] == "#test"
        assert call_args[1]["text"] == "Test Subject"
        assert "blocks" in call_args[1]

    @patch("taskflows.alerts.slack.get_async_client")
    @pytest.mark.asyncio
    async def test_send_message_with_file_paths(
        self, mock_get_client, mock_client, test_components, tmp_path
    ):
        """Test sending a message with file path attachments."""
        mock_get_client.return_value = mock_client
        channel = SlackChannel("#test")

        # Create temporary files
        test_file1 = tmp_path / "test1.txt"
        test_file2 = tmp_path / "test2.txt"
        test_file1.write_text("Content 1")
        test_file2.write_text("Content 2")

        result = await send_slack_message(
            content=test_components,
            channel=channel,
            attachment_files=[test_file1, test_file2],
        )

        assert result is True
        assert mock_client.files_upload_v2.call_count == 2

        # Check file upload calls
        upload_calls = mock_client.files_upload_v2.call_args_list
        assert upload_calls[0][1]["filename"] == "test1.txt"
        assert upload_calls[1][1]["filename"] == "test2.txt"

    @patch("taskflows.alerts.slack.get_async_client")
    @pytest.mark.asyncio
    async def test_send_message_with_attachment_files(
        self, mock_get_client, mock_client, test_components
    ):
        """Test sending a message with AttachmentFile objects."""
        mock_get_client.return_value = mock_client
        channel = SlackChannel("#test")

        # Create AttachmentFile objects
        content1 = BytesIO(b"Attachment content 1")
        content2 = BytesIO(b"Attachment content 2")
        attachment1 = AttachmentFile(content=content1, filename="attachment1.txt")
        attachment2 = AttachmentFile(content=content2, filename="attachment2.txt")

        result = await send_slack_message(
            content=test_components,
            channel=channel,
            attachment_files=[attachment1, attachment2],
        )

        assert result is True
        assert mock_client.files_upload_v2.call_count == 2

        # Check file upload calls
        upload_calls = mock_client.files_upload_v2.call_args_list
        assert upload_calls[0][1]["filename"] == "attachment1.txt"
        assert upload_calls[1][1]["filename"] == "attachment2.txt"

    @patch("taskflows.alerts.slack.get_async_client")
    @pytest.mark.asyncio
    async def test_send_message_with_mixed_attachments(
        self, mock_get_client, mock_client, test_components, tmp_path
    ):
        """Test sending a message with mixed file paths and AttachmentFile objects."""
        mock_get_client.return_value = mock_client
        channel = SlackChannel("#test")

        # Create temporary file
        test_file = tmp_path / "test.txt"
        test_file.write_text("File content")

        # Create AttachmentFile
        content = BytesIO(b"Attachment content")
        attachment = AttachmentFile(content=content, filename="attachment.txt")

        result = await send_slack_message(
            content=test_components,
            channel=channel,
            attachment_files=[test_file, attachment],
        )

        assert result is True
        assert mock_client.files_upload_v2.call_count == 2

    @patch("taskflows.alerts.slack.get_async_client")
    @pytest.mark.asyncio
    async def test_send_message_with_zip_attachments(
        self, mock_get_client, mock_client, test_components, tmp_path
    ):
        """Test sending a message with zipped attachments."""
        mock_get_client.return_value = mock_client
        channel = SlackChannel("#test")

        # Create temporary files
        test_file1 = tmp_path / "test1.txt"
        test_file2 = tmp_path / "test2.txt"
        test_file1.write_text("Content 1")
        test_file2.write_text("Content 2")

        # Create AttachmentFile
        content = BytesIO(b"Attachment content")
        attachment = AttachmentFile(content=content, filename="attachment.txt")

        result = await send_slack_message(
            content=test_components,
            channel=channel,
            attachment_files=[test_file1, test_file2, attachment],
            zip_attachment_files=True,
        )

        assert result is True
        assert mock_client.files_upload_v2.call_count == 1

        # Check that a zip file was uploaded
        upload_call = mock_client.files_upload_v2.call_args
        assert upload_call[1]["filename"] == "files.zip"

    @patch("taskflows.alerts.slack.get_async_client")
    @pytest.mark.asyncio
    async def test_send_message_with_single_zip_attachment(
        self, mock_get_client, mock_client, test_components, tmp_path
    ):
        """Test sending a message with a single file zipped."""
        mock_get_client.return_value = mock_client
        channel = SlackChannel("#test")

        # Create temporary file
        test_file = tmp_path / "test.txt"
        test_file.write_text("Content")

        result = await send_slack_message(
            content=test_components,
            channel=channel,
            attachment_files=[test_file],
            zip_attachment_files=True,
        )

        assert result is True
        assert mock_client.files_upload_v2.call_count == 1

        # Check that the zip file uses the original filename
        upload_call = mock_client.files_upload_v2.call_args
        assert upload_call[1]["filename"] == "test.txt.zip"

    @patch("taskflows.alerts.slack.get_async_client")
    @pytest.mark.asyncio
    async def test_send_message_with_single_attachment_file_zip(
        self, mock_get_client, mock_client, test_components
    ):
        """Test sending a message with a single AttachmentFile zipped."""
        mock_get_client.return_value = mock_client
        channel = SlackChannel("#test")

        # Create AttachmentFile
        content = BytesIO(b"Attachment content")
        attachment = AttachmentFile(content=content, filename="attachment.txt")

        result = await send_slack_message(
            content=test_components,
            channel=channel,
            attachment_files=[attachment],
            zip_attachment_files=True,
        )

        assert result is True
        assert mock_client.files_upload_v2.call_count == 1

        # Check that the zip file uses the original filename
        upload_call = mock_client.files_upload_v2.call_args
        assert upload_call[1]["filename"] == "attachment.txt.zip"

    @patch("taskflows.alerts.slack.get_async_client")
    @pytest.mark.asyncio
    async def test_send_message_multiple_batches(self, mock_get_client, mock_client):
        """Test sending multiple message batches."""
        mock_get_client.return_value = mock_client
        channel = SlackChannel("#test")

        # Create many messages to trigger batching
        messages = []
        for i in range(30):  # More than the batch size of 23
            messages.append([Text(f"Message {i}", ContentType.INFO, FontSize.SMALL)])

        result = await send_slack_message(
            content=messages, channel=channel, subject="Test Subject"
        )

        assert result is True
        # Should be called twice due to batching
        assert mock_client.chat_postMessage.call_count == 2

    @patch("taskflows.alerts.slack.get_async_client")
    @pytest.mark.asyncio
    async def test_send_message_failure(
        self, mock_get_client, mock_client, test_components
    ):
        """Test sending a message with failure."""
        mock_get_client.return_value = mock_client
        mock_client.chat_postMessage.return_value = MagicMock(status_code=500)
        channel = SlackChannel("#test")

        result = await send_slack_message(
            content=test_components, channel=channel, retries=2
        )

        assert result is False
        # Should be called 3 times (initial + 2 retries)
        assert mock_client.chat_postMessage.call_count == 3

    @patch("taskflows.alerts.slack.get_async_client")
    @pytest.mark.asyncio
    async def test_send_message_with_string_channel(
        self, mock_get_client, mock_client, test_components
    ):
        """Test sending a message with string channel."""
        mock_get_client.return_value = mock_client
        channel = "#test-string"

        result = await send_slack_message(content=test_components, channel=channel)

        assert result is True
        mock_client.chat_postMessage.assert_called()

        # Check that the call was made with the correct channel
        call_args = mock_client.chat_postMessage.call_args
        assert call_args[1]["channel"] == "#test-string"
        assert call_args[1]["channel"] == "#test-string"
