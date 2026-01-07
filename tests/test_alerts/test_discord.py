"""
Tests for Discord integration in dl-alerts
"""

from unittest.mock import AsyncMock, Mock, patch

import pytest
from alerts import ContentType, FontSize, Map, PeriodicMsgs, Table, Text
from alerts.alerts import get_alerts_log, send_alert
from alerts.discord import (
    DiscordChannel,
    _send_single_discord_message,
    _split_message,
    send_discord_message,
)
from alerts.report import render_components_md


class TestDiscordChannel:
    def test_discord_channel_creation(self):
        """Test DiscordChannel creation."""
        webhook_url = "https://discord.com/api/webhooks/123/test"
        channel = DiscordChannel(webhook_url=webhook_url)
        assert channel.webhook_url == webhook_url

    def test_discord_channel_invalid_url(self):
        """Test DiscordChannel with invalid URL."""
        webhook_url = "not-a-valid-url"
        channel = DiscordChannel(webhook_url=webhook_url)
        assert channel.webhook_url == webhook_url
        assert str(channel) == webhook_url


class TestDiscordMarkdown:
    def test_text_discord_markdown(self):
        """Test text component Discord markdown rendering."""
        
        text_component = Text("Test message", ContentType.INFO, FontSize.MEDIUM)
        result = render_components_md([text_component], discord_format=True)

        assert "Test message" in result
        # INFO level with MEDIUM font size returns plain text, not bold

    def test_map_discord_markdown(self):
        """Test map component Discord markdown rendering."""

        map_data = {"key1": "value1", "key2": "value2"}
        map_component = Map(map_data)
        result = render_components_md([map_component], discord_format=True)

        assert "key1" in result
        assert "value1" in result
        assert "key2" in result
        assert "value2" in result

    def test_map_discord_markdown_inline(self):
        """Test map component Discord markdown rendering with inline format."""
        
        map_data = {"key1": "value1"}
        map_component = Map(map_data, inline=True)
        result = render_components_md([map_component], discord_format=True)

        assert "key1" in result
        assert "value1" in result

    def test_table_discord_markdown(self):
        """Test table component Discord markdown rendering."""

        table_data = [
            {"col1": "val1", "col2": "val2"},
            {"col1": "val3", "col2": "val4"},
        ]
        table_component = Table(table_data, title="Test Table")
        result = render_components_md([table_component], discord_format=True)

        assert "Test Table" in result
        assert "col1" in result
        assert "col2" in result
        assert "val1" in result
        assert "val2" in result

    def test_table_discord_markdown_no_title(self):
        """Test table component Discord markdown rendering without title."""

        table_data = [{"col1": "val1"}]
        table_component = Table(table_data)
        result = render_components_md([table_component], discord_format=True)

        assert "col1" in result
        assert "val1" in result

    def test_render_components_md_discord(self):
        """Test rendering multiple components for Discord."""

        components = [
            Text("Header", ContentType.IMPORTANT, FontSize.LARGE),
            Map({"key": "value"}),
            Table([{"col": "val"}], title="Test"),
        ]

        result = render_components_md(components, discord_format=True)

        assert "Header" in result
        assert "key" in result
        assert "value" in result
        assert "Test" in result
        assert "col" in result
        assert "val" in result


class TestDiscordMessageSending:
    def test_split_message_short(self):
        """Test message splitting with short message."""
        message = "Short message"
        chunks = _split_message(message, 100)
        assert chunks == [message]

    def test_split_message_long(self):
        """Test message splitting with long message."""
        message = "A" * 3000  # 3000 character message
        chunks = _split_message(message, 1000)

        assert len(chunks) > 1
        assert all(len(chunk) <= 1000 for chunk in chunks)
        assert "".join(chunks) == message

    def test_split_message_with_newlines(self):
        """Test message splitting with newlines."""
        message = "Line 1\n" * 100 + "Line 100"
        chunks = _split_message(message, 50)

        assert len(chunks) > 1
        assert all(len(chunk) <= 50 for chunk in chunks)

    @patch("alerts.discord.aiohttp.ClientSession")
    @pytest.mark.asyncio
    async def test_send_single_discord_message_success(self, mock_session):
        """Test successful Discord message sending"""

        # Create a proper async context manager mock
        class MockResponseContext:
            def __init__(self, status):
                self.status = status
                self.headers = {}

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                return None

            async def text(self):
                return "OK"

        class MockSessionContext:
            def __init__(self, response_context):
                self.response_context = response_context

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                return None

            def post(self, *args, **kwargs):
                return self.response_context

        # Set up the mocks
        mock_response = MockResponseContext(204)
        mock_session_instance = MockSessionContext(mock_response)
        mock_session.return_value = mock_session_instance

        webhook_url = "https://discord.com/api/webhooks/123/test"
        content = "Test message"
        username = "test-bot"

        result = await _send_single_discord_message(webhook_url, content, username, 1)

        assert result is True

    @patch("alerts.discord.aiohttp.ClientSession")
    @pytest.mark.asyncio
    async def test_send_single_discord_message_failure(self, mock_session):
        """Test Discord message sending failure"""

        # Create a proper async context manager mock
        class MockResponseContext:
            def __init__(self, status):
                self.status = status
                self.headers = {}

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                return None

            async def text(self):
                return "Internal Server Error"

        class MockSessionContext:
            def __init__(self, response_context):
                self.response_context = response_context
                self.post_calls = 0

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                return None

            def post(self, *args, **kwargs):
                self.post_calls += 1
                return self.response_context

        # Set up the mocks
        mock_response = MockResponseContext(500)
        mock_session_instance = MockSessionContext(mock_response)
        mock_session.return_value = mock_session_instance

        webhook_url = "https://discord.com/api/webhooks/123/test"
        content = "Test message"
        username = "test-bot"

        result = await _send_single_discord_message(webhook_url, content, username, 1)

        assert result is False
        # Should be called twice (initial + 1 retry)
        assert mock_session_instance.post_calls == 2

    @patch("alerts.discord.aiohttp.ClientSession")
    @pytest.mark.asyncio
    async def test_send_single_discord_message_rate_limit(self, mock_session):
        """Test Discord rate limiting handling"""

        # Create proper async context manager mocks
        class MockResponseContext:
            def __init__(self, status, headers=None):
                self.status = status
                self.headers = headers or {}

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                return None

            async def text(self):
                return "OK"

        class MockSessionContext:
            def __init__(self, response_contexts):
                self.response_contexts = response_contexts
                self.post_calls = 0

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                return None

            def post(self, *args, **kwargs):
                response = self.response_contexts[self.post_calls]
                self.post_calls += 1
                return response

        # Set up the mocks
        rate_limit_response = MockResponseContext(429, {"Retry-After": "1"})
        success_response = MockResponseContext(204)
        mock_session_instance = MockSessionContext(
            [rate_limit_response, success_response]
        )
        mock_session.return_value = mock_session_instance

        webhook_url = "https://discord.com/api/webhooks/123/test"
        content = "Test message"
        username = "test-bot"

        with patch("asyncio.sleep") as mock_sleep:
            result = await _send_single_discord_message(
                webhook_url, content, username, 1
            )

        assert result is True
        assert mock_session_instance.post_calls == 2
        mock_sleep.assert_called()

    @pytest.mark.asyncio
    async def test_send_discord_message_short_content(self):
        """Test send_discord_message with short content"""
        with patch(
            "alerts.discord._send_single_discord_message"
        ) as mock_send_single:
            mock_send_single.return_value = True

            components = [Text("Short message")]
            channel = DiscordChannel(
                webhook_url="https://discord.com/api/webhooks/123/test"
            )

            result = await send_discord_message(components, channel)

            assert result is True
            mock_send_single.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_discord_message_long_content(self):
        """Test send_discord_message with long content that needs splitting"""
        with patch(
            "alerts.discord._send_single_discord_message"
        ) as mock_send_single:
            mock_send_single.return_value = True

            # Create a table with many rows to exceed 2000 chars
            large_table_data = [
                {
                    "Index": str(i),
                    "Value": f"Value_{i}",
                    "Description": f"This is a longer description for row {i}",
                }
                for i in range(100)  # This should create a very long message
            ]

            components = [Table(large_table_data, title="Large Table")]
            channel = DiscordChannel(
                webhook_url="https://discord.com/api/webhooks/123/test"
            )

            result = await send_discord_message(components, channel)

            assert result is True
            # Should be called multiple times due to message splitting
            assert mock_send_single.call_count >= 2


class TestDiscordIntegration:
    """Test Discord integration with the main alert system"""

    @pytest.mark.asyncio
    async def test_send_alert_with_discord(self):
        """Test send_alert function with Discord destination"""
        with patch("alerts.discord._send_single_discord_message") as mock_send:
            mock_send.return_value = True

            components = [Text("Test alert")]
            discord_channel = DiscordChannel(
                webhook_url="https://discord.com/api/webhooks/123/test"
            )

            result = await send_alert(components, discord_channel)

            assert result is True
            mock_send.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_alert_mixed_destinations(self):
        """Test send_alert with mixed destinations including Discord"""
        with (
            patch("alerts.discord._send_single_discord_message") as mock_discord,
            patch("alerts.slack.get_async_client") as mock_get_client,
            patch("alerts.slack.try_post_message") as mock_post,
        ):

            # Mock Slack client and posting
            mock_client = AsyncMock()
            mock_get_client.return_value = mock_client
            mock_post.return_value = True
            mock_discord.return_value = True

            components = [Text("Multi-platform alert")]

            from alerts import SlackChannel

            destinations = [
                DiscordChannel(webhook_url="https://discord.com/api/webhooks/123/test"),
                SlackChannel("#test-channel"),
            ]

            result = await send_alert(components, destinations)

            assert result is True
            mock_discord.assert_called_once()
            mock_get_client.assert_called_once()
            mock_post.assert_called_once()

    def test_periodic_msgs_with_discord(self):
        """Test PeriodicMsgs with Discord destination"""
        discord_channel = DiscordChannel(
            webhook_url="https://discord.com/api/webhooks/123/test"
        )

        periodic_msgs = PeriodicMsgs(
            send_to=discord_channel, header="Test Periodic Messages"
        )

        # Add some messages
        periodic_msgs.add_message(Text("Message 1"))
        periodic_msgs.add_message(Text("Message 2"))

        assert len(periodic_msgs.msg_buffer) == 2
        assert periodic_msgs.send_to == discord_channel

    @pytest.mark.asyncio
    async def test_alert_logger_discord_webhook_detection(self):
        """Test AlertLogger auto-detects Discord webhooks"""
        discord_webhook = "https://discord.com/api/webhooks/123456789/test-webhook"

        with patch("alerts.alerts.PeriodicMsgSender") as mock_sender:
            mock_sender_instance = Mock()
            mock_sender.return_value = mock_sender_instance

            # Create a proper async mock that accepts the correct parameters
            async def mock_add_periodic(config, pub_freq):
                return None

            mock_sender_instance.add_periodic_pub_group_member = mock_add_periodic

            logger = await get_alerts_log(discord_webhook)

            # Should have created a DiscordChannel
            assert hasattr(logger, "channel")
            assert isinstance(logger.channel, DiscordChannel)
            assert logger.channel.webhook_url == discord_webhook

    @pytest.mark.asyncio
    async def test_alert_logger_slack_channel_detection(self):
        """Test AlertLogger still works with Slack channels"""
        slack_channel = "#test-channel"

        with patch("alerts.alerts.PeriodicMsgSender") as mock_sender:
            mock_sender_instance = Mock()
            mock_sender.return_value = mock_sender_instance

            # Create a proper async mock that accepts the correct parameters
            async def mock_add_periodic(config, pub_freq):
                return None

            mock_sender_instance.add_periodic_pub_group_member = mock_add_periodic

            logger = await get_alerts_log(slack_channel)

            # Should have created a SlackChannel
            from alerts import SlackChannel

            assert hasattr(logger, "channel")
            assert isinstance(logger.channel, SlackChannel)
            assert str(logger.channel) == slack_channel


class TestDiscordSettings:
    """Test Discord settings and configuration"""

    def test_discord_settings_defaults(self):
        """Test Discord settings default values"""
        from alerts.discord import discord_settings

        assert discord_settings.attachment_max_size_mb == 20
        assert discord_settings.inline_tables_max_rows == 2000

    def test_discord_settings_env_prefix(self):
        """Test Discord settings use correct environment variable prefix"""
        from alerts.discord import DiscordSettings

        settings = DiscordSettings()
        assert settings.model_config["env_prefix"] == "discord_"


# Integration test that can be run manually with real Discord webhook
@pytest.mark.integration
class TestDiscordIntegrationManual:
    """Manual integration tests - require real Discord webhook"""

    def test_real_discord_send(self, request):
        """Test sending to real Discord webhook (requires --discord-webhook)"""
        webhook_url = request.config.getoption("--discord-webhook")
        if not webhook_url:
            pytest.skip("--discord-webhook not provided")

        # This test would send a real message to Discord
        # Implementation would depend on the specific requirements
