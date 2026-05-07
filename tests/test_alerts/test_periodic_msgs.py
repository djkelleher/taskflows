from unittest.mock import MagicMock, patch

import pytest
from taskflows.alerts import (
    ContentType,
    EmailAddrs,
    PeriodicMsgs,
    PeriodicMsgSender,
    Text,
    send_alert,
)


@pytest.fixture
def slack_channel():
    return "#test-channel"


@pytest.fixture
def email_config():
    return EmailAddrs(
        sender_addr="test@example.com",
        password="password",
        receiver_addr="recipient@example.com",
    )


class TestPeriodicMsgs:
    @patch("taskflows.alerts.alerts.send_alert")
    @pytest.mark.asyncio
    async def test_add_message(self, mock_send_alert, slack_channel):
        # Create a PeriodicMsgs instance
        periodic_msg = PeriodicMsgs(send_to=slack_channel, header="Test Header")

        # Add messages using add_message
        periodic_msg.add_message(Text("Test message 1", ContentType.INFO))
        periodic_msg.add_message(Text("Test message 2", ContentType.WARNING))

        # Check messages were added to buffer
        assert len(periodic_msg.msg_buffer) == 2

        # Publish the messages
        await periodic_msg.publish()

        # Check send_alert was called with correct parameters
        mock_send_alert.assert_called_once()
        # First argument should be the msg_buffer
        args, kwargs = mock_send_alert.call_args
        assert len(args[0]) == 2

        # Buffer should be cleared after publishing
        assert len(periodic_msg.msg_buffer) == 0

    @patch("taskflows.alerts.alerts.send_alert")
    @pytest.mark.asyncio
    async def test_publish_requeues_messages_when_send_fails(
        self,
        mock_send_alert,
        slack_channel,
    ):
        periodic_msg = PeriodicMsgs(send_to=slack_channel)
        message = Text("Test message 1", ContentType.INFO)
        periodic_msg.add_message(message)

        mock_send_alert.return_value = False

        result = await periodic_msg.publish()

        assert result is False
        assert periodic_msg.msg_buffer == [message]

    @patch("taskflows.alerts.alerts.send_alert")
    @pytest.mark.asyncio
    async def test_on_pub_func(self, mock_send_alert, slack_channel):
        # Create a callback function to be called after publishing
        callback = MagicMock()

        # Create a PeriodicMsgs with the callback
        periodic_msg = PeriodicMsgs(send_to=slack_channel, on_pub_func=callback)

        # Add a message and publish
        periodic_msg.add_message(Text("Test message"))
        await periodic_msg.publish()

        # Check callback was called
        callback.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_alert_returns_false_for_invalid_destinations(self):
        result = await send_alert(Text("Test message"), send_to=object())

        assert result is False


class TestPeriodicMsgSender:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("pub_freq", [0, -1])
    async def test_add_periodic_pub_group_member_rejects_nonpositive_frequency(
        self,
        slack_channel,
        pub_freq,
    ):
        sender = PeriodicMsgSender()
        periodic_msg = PeriodicMsgs(send_to=slack_channel)

        with pytest.raises(ValueError, match="pub_freq"):
            await sender.add_periodic_pub_group_member(periodic_msg, pub_freq)

    @pytest.mark.asyncio
    async def test_add_periodic_pub_group_member(self, slack_channel):
        # Create a PeriodicMsgSender
        sender = PeriodicMsgSender()

        # Create two PeriodicMsgs with different frequencies
        hourly_msg = PeriodicMsgs(send_to=slack_channel)
        daily_msg = PeriodicMsgs(send_to=slack_channel)

        # Add them to the sender with mocked publish methods
        with (
            patch.object(hourly_msg, "publish") as mock_hourly_publish,
            patch.object(daily_msg, "publish"),
            patch("asyncio.create_task") as mock_create_task,
            patch("asyncio.sleep") as mock_sleep,
        ):

            def close_coro(coro):
                coro.close()
                return MagicMock()

            mock_create_task.side_effect = close_coro

            # Configure sleep to break the infinite loop after one iteration
            mock_sleep.side_effect = [Exception("Stop test")]

            # Add the periodic messages
            await sender.add_periodic_pub_group_member(hourly_msg, 60)  # 60 minutes
            await sender.add_periodic_pub_group_member(daily_msg, 1440)  # 24 hours

            # Check they were added correctly
            assert 60 in sender._periodic_msgs
            assert 1440 in sender._periodic_msgs
            assert hourly_msg in sender._periodic_msgs[60]
            assert daily_msg in sender._periodic_msgs[1440]

            # Try to trigger the publish for the hourly group
            try:
                await sender._on_func_pub_period(60)
            except Exception as e:
                if "Stop test" not in str(e):
                    raise

            # Check publish was called
            mock_hourly_publish.assert_called_once()
            mock_sleep.assert_any_call(3600)

    @pytest.mark.asyncio
    async def test_shutdown_awaits_cancelled_tasks(self, slack_channel):
        sender = PeriodicMsgSender()
        periodic_msg = PeriodicMsgs(send_to=slack_channel)

        await sender.add_periodic_pub_group_member(periodic_msg, 60)

        await sender.shutdown()

        assert sender._periodic_tasks == {}
