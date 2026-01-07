from pathlib import Path
from tempfile import NamedTemporaryFile
from unittest.mock import patch

import pytest
from alerts import EmailAddrs, send_email, send_slack_message


def slack_channel(request):
    return request.config.getoption("--slack-channel")


@pytest.mark.parametrize("nested_components", [False, True])
@pytest.mark.asyncio
async def test_send_slack_message(components, request, nested_components):
    # Skip test if Slack configuration is not available
    if not request.config.getoption("--slack-channel") or not request.config.getoption(
        "--slack-bot-token"
    ):
        pytest.skip("Slack configuration not provided")

    if nested_components:
        components = [components for _ in range(3)]
    await send_slack_message(content=components, channel=slack_channel(request))


@pytest.mark.parametrize("zip_attachments", [False, True])
@pytest.mark.parametrize("n_files", [1, 4])
@pytest.mark.asyncio
async def test_message_attachment(components, request, zip_attachments, n_files):
    # Skip test if Slack configuration is not available
    if not request.config.getoption("--slack-channel") or not request.config.getoption(
        "--slack-bot-token"
    ):
        pytest.skip("Slack configuration not provided")

    files = []
    for _ in range(n_files):
        file = Path(NamedTemporaryFile().name)
        file.write_text("test\ntest\ntest")
        files.append(file)
    await send_slack_message(
        content=components,
        channel=slack_channel(request),
        attachment_files=files,
        zip_attachment_files=zip_attachments,
    )


@pytest.mark.asyncio
async def test_send_email(components, request):
    # Skip test if email configuration is not available
    if not request.config.getoption("--email-addr") or not request.config.getoption(
        "--email-pass"
    ):
        pytest.skip("Email configuration not provided")

    send_to = EmailAddrs(
        sender_addr=request.config.getoption("--email-addr"),
        password=request.config.getoption("--email-pass"),
        receiver_addr=request.config.getoption("--email-addr"),
    )
    await send_email(content=components, send_to=send_to)


@pytest.mark.parametrize("retry_count", [0, 1, 3])
@pytest.mark.asyncio
async def test_slack_message_retries(components, request, retry_count):
    """Test that retry functionality works as expected."""
    # Skip test if Slack configuration is not available
    if not request.config.getoption("--slack-channel") or not request.config.getoption(
        "--slack-bot-token"
    ):
        pytest.skip("Slack configuration not provided")

    # Patch the 'try_post_message' function in the 'alerts.slack' module
    # This allows us to simulate different behaviors for the 'try_post_message' without actually sending messages
    with patch("alerts.slack.try_post_message") as mock_post:
        # Configure the mock to return False, simulating a failure in sending messages
        mock_post.return_value = False

        # Attempt to send a Slack message with a specified number of retries
        result = await send_slack_message(
            content=components, channel=slack_channel(request), retries=retry_count
        )

        # Assert that the result is False, since all attempts to send the message should fail
        assert not result

        # Verify that 'try_post_message' was called exactly once
        # This is because the retry logic is handled internally by 'try_post_message'
        assert mock_post.call_count == 1


@pytest.mark.parametrize("retry_count", [0, 1, 3])
@pytest.mark.asyncio
async def test_email_retries(components, request, retry_count):
    """Test that retry functionality works as expected for email.

    This test uses a mock of the SMTP object to simulate an error
    when trying to send an email. It then verifies that the send_email
    function correctly retries the send operation the specified number
    of times.
    """
    # Skip test if email configuration is not available
    if not request.config.getoption("--email-addr") or not request.config.getoption(
        "--email-pass"
    ):
        pytest.skip("Email configuration not provided")

    with patch("aiosmtplib.send") as mock_send:
        # Configure the mock to raise an error
        mock_send.side_effect = Exception("Test error")

        # Set up the email destination
        send_to = EmailAddrs(
            sender_addr=request.config.getoption("--email-addr"),
            password=request.config.getoption("--email-pass"),
            receiver_addr=request.config.getoption("--email-addr"),
        )

        # Try to send the email with retries
        result = await send_email(
            content=components, send_to=send_to, retries=retry_count
        )

        # Check that the result is False since all attempts failed
        assert not result

        # Check that the correct number of attempts were made
        # The number of attempts will be the number of retries specified
        # plus 1 (since the send_email function will try to send the
        # email at least once).
        assert mock_send.call_count == retry_count + 1
