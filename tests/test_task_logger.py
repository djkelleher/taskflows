import random
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from alerts import MsgDst

from taskflows.tasks import Alerts, TaskLogger, build_loki_query_url


def test_build_loki_query_url_basic():
    """Test basic Loki URL generation."""
    task_name = "test_task"
    start_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    end_time = datetime(2024, 1, 1, 13, 0, 0, tzinfo=timezone.utc)

    url = build_loki_query_url(task_name, start_time, end_time)

    assert "localhost:3000" in url
    assert "explore" in url
    assert "test_task" in url
    assert "loki" in url


def test_build_loki_query_url_error_only():
    """Test Loki URL generation with error filter."""
    task_name = "test_task"
    start_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    end_time = datetime(2024, 1, 1, 13, 0, 0, tzinfo=timezone.utc)

    url = build_loki_query_url(task_name, start_time, end_time, error_only=True)

    assert "ERROR" in url
    assert "test_task" in url


def test_build_loki_query_url_timestamps():
    """Test that timestamps are properly converted to milliseconds."""
    task_name = "test_task"
    start_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    end_time = datetime(2024, 1, 1, 13, 0, 0, tzinfo=timezone.utc)

    url = build_loki_query_url(task_name, start_time, end_time)

    # Check that timestamps are in milliseconds (13 digits for current epoch)
    from_ts = str(int(start_time.timestamp() * 1000))
    to_ts = str(int(end_time.timestamp() * 1000))

    assert from_ts in url
    assert to_ts in url


@pytest.mark.asyncio
async def test_task_logger_creation():
    """Test TaskLogger creation without database."""
    task_logger = await TaskLogger.create(
        name="test_task",
        required=False,
    )

    assert task_logger.name == "test_task"
    assert task_logger.required is False
    assert task_logger.alerts == []
    assert task_logger.errors == []


@pytest.mark.asyncio
async def test_task_logger_on_task_start():
    """Test task start records time."""
    task_logger = await TaskLogger.create(
        name="test_task",
        required=False,
    )

    await task_logger.on_task_start()

    assert hasattr(task_logger, "start_time")
    assert isinstance(task_logger.start_time, datetime)
    assert task_logger.start_time.tzinfo == timezone.utc


@pytest.mark.asyncio
async def test_task_logger_on_task_error():
    """Test task error is recorded in errors list."""
    task_logger = await TaskLogger.create(
        name="test_task",
        required=False,
    )
    await task_logger.on_task_start()

    error = ValueError("Test error")
    await task_logger.on_task_error(error)

    assert len(task_logger.errors) == 1
    assert task_logger.errors[0] is error


@pytest.mark.asyncio
async def test_task_logger_on_task_finish_success():
    """Test successful task finish."""
    task_logger = await TaskLogger.create(
        name="test_task",
        required=False,
    )
    await task_logger.on_task_start()

    # Should not raise
    await task_logger.on_task_finish(
        success=True,
        retries=0,
        return_value="test_result",
    )


@pytest.mark.asyncio
async def test_task_logger_on_task_finish_with_errors_required():
    """Test that required task raises on errors."""
    task_logger = await TaskLogger.create(
        name="test_task",
        required=True,
    )
    await task_logger.on_task_start()

    error = ValueError("Test error")
    await task_logger.on_task_error(error)

    with pytest.raises(ValueError, match="Test error"):
        await task_logger.on_task_finish(success=False, retries=0)


@pytest.mark.asyncio
async def test_task_logger_on_task_finish_with_multiple_errors():
    """Test that multiple errors are aggregated."""
    task_logger = await TaskLogger.create(
        name="test_task",
        required=True,
    )
    await task_logger.on_task_start()

    # Add multiple errors of same type
    await task_logger.on_task_error(ValueError("Error 1"))
    await task_logger.on_task_error(ValueError("Error 2"))

    with pytest.raises(ValueError, match="2 errors"):
        await task_logger.on_task_finish(success=False, retries=0)


@pytest.mark.asyncio
@patch("taskflows.tasks.send_alert")
async def test_task_logger_error_alert_includes_loki_url(mock_send_alert):
    """Test that error alerts include Loki URL."""
    mock_send_alert.return_value = None

    # Create a mock MsgDst
    mock_dst = MagicMock(spec=MsgDst)
    alerts = [Alerts(send_to=mock_dst, send_on=["error"])]

    task_logger = await TaskLogger.create(
        name="test_task",
        required=False,
        alerts=alerts,
    )
    await task_logger.on_task_start()

    error = ValueError("Test error")
    await task_logger.on_task_error(error)

    # Verify send_alert was called
    assert mock_send_alert.called

    # Check that Loki URL is in the alert content
    call_args = mock_send_alert.call_args
    components = call_args.kwargs.get("content", call_args.args[0] if call_args.args else [])

    # Should have at least 2 components: error message and Loki URL
    assert len(components) >= 2

    # Check that one component contains the Loki URL
    loki_url_found = False
    for component in components:
        if hasattr(component, "content") and "Loki" in str(component.content):
            loki_url_found = True
            break
    assert loki_url_found


@pytest.mark.asyncio
@patch("taskflows.tasks.send_alert")
async def test_task_logger_finish_alert_includes_loki_url(mock_send_alert):
    """Test that finish alerts include Loki URL."""
    mock_send_alert.return_value = None

    # Create a mock MsgDst
    mock_dst = MagicMock(spec=MsgDst)
    alerts = [Alerts(send_to=mock_dst, send_on=["finish"])]

    task_logger = await TaskLogger.create(
        name="test_task",
        required=False,
        alerts=alerts,
    )
    await task_logger.on_task_start()
    await task_logger.on_task_finish(success=True, retries=0)

    # Verify send_alert was called
    assert mock_send_alert.called

    # Check that Loki URL is in the alert content
    call_args = mock_send_alert.call_args
    components = call_args.kwargs.get("content", call_args.args[0] if call_args.args else [])

    # Check that one component contains the Loki URL
    loki_url_found = False
    for component in components:
        if hasattr(component, "content") and "Loki" in str(component.content):
            loki_url_found = True
            break
    assert loki_url_found
