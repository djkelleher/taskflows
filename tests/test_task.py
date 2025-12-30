import asyncio
from datetime import datetime, timedelta, timezone
from time import sleep

import pytest
from taskflows import task
from taskflows.tasks import build_loki_query_url, _RuntimeManager


@pytest.mark.parametrize("required", [True, False])
@pytest.mark.parametrize("retries", [0, 1])
@pytest.mark.parametrize("timeout", [None, 2])
def test_good_task(required, retries, timeout):
    @task(
        name="test",
        required=required,
        retries=retries,
        timeout=timeout,
    )
    def return_100() -> int:
        return 100

    result = return_100()
    assert result == 100


@pytest.mark.asyncio
@pytest.mark.parametrize("required", [True, False])
@pytest.mark.parametrize("retries", [0, 1])
@pytest.mark.parametrize("timeout", [None, 2])
async def test_good_async_task(required, retries, timeout):
    @task(
        name="test",
        required=required,
        retries=retries,
        timeout=timeout,
    )
    async def return_100() -> int:
        return 100

    result = await return_100()
    assert result == 100


@pytest.mark.parametrize("required", [True, False])
@pytest.mark.parametrize("retries", [0, 1])
@pytest.mark.parametrize("timeout", [None, 2])
def test_task_exception(required, retries, timeout):
    @task(
        name="test",
        required=required,
        retries=retries,
        timeout=timeout,
    )
    def throws_exception():
        raise RuntimeError("This task failed.")

    if required:
        with pytest.raises(RuntimeError):
            throws_exception()
    else:
        assert throws_exception() is None


@pytest.mark.asyncio
@pytest.mark.parametrize("required", [True, False])
@pytest.mark.parametrize("retries", [0, 1])
@pytest.mark.parametrize("timeout", [None, 2])
async def test_async_task_exception(required, retries, timeout):
    @task(
        name="test",
        required=required,
        retries=retries,
        timeout=timeout,
    )
    async def throws_exception():
        raise RuntimeError("This task failed.")

    if required:
        with pytest.raises(RuntimeError):
            await throws_exception()
    else:
        assert await throws_exception() is None


@pytest.mark.parametrize("required", [True, False])
@pytest.mark.parametrize("retries", [0, 1])
def test_task_timeout(required, retries):
    @task(
        name="test",
        required=required,
        retries=retries,
        timeout=0.25,
    )
    def do_sleep():
        sleep(0.5)

    if required:
        with pytest.raises(TimeoutError):
            do_sleep()
    else:
        assert do_sleep() is None


@pytest.mark.asyncio
@pytest.mark.parametrize("required", [True, False])
@pytest.mark.parametrize("retries", [0, 1])
async def test_async_task_timeout(required, retries):
    @task(
        name="test",
        required=required,
        retries=retries,
        timeout=0.25,
    )
    async def do_sleep():
        await asyncio.sleep(0.5)

    if required:
        with pytest.raises(TimeoutError):
            await do_sleep()
    else:
        assert await do_sleep() is None


def test_loki_query_url_default_time_range():
    """Test that Loki query URL defaults to 1 hour lookback window."""
    task_name = "test_task"

    # Call without time parameters
    url = build_loki_query_url(task_name)

    # Verify URL is generated (basic smoke test)
    assert "test_task" in url
    assert "explore" in url

    # Test with explicit end_time but no start_time
    end_time = datetime.now(timezone.utc)
    url = build_loki_query_url(task_name, end_time=end_time)

    # Extract timestamps from URL
    import re
    from_match = re.search(r'"from":"(\d+)"', url)
    to_match = re.search(r'"to":"(\d+)"', url)

    assert from_match and to_match
    from_ts = int(from_match.group(1))
    to_ts = int(to_match.group(1))

    # Verify approximately 1 hour difference (in milliseconds)
    time_diff_ms = to_ts - from_ts
    expected_diff = 3600 * 1000  # 1 hour in milliseconds

    # Allow 1 second tolerance for execution time
    assert abs(time_diff_ms - expected_diff) < 1000


def test_loki_query_url_with_explicit_times():
    """Test that explicit start/end times are preserved."""
    task_name = "test_task"
    start_time = datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
    end_time = datetime(2024, 1, 1, 11, 0, 0, tzinfo=timezone.utc)

    url = build_loki_query_url(task_name, start_time=start_time, end_time=end_time)

    # Verify both timestamps are in the URL
    expected_from = str(int(start_time.timestamp() * 1000))
    expected_to = str(int(end_time.timestamp() * 1000))

    assert expected_from in url
    assert expected_to in url


def test_runtime_manager_handles_none_thread():
    """Test that RuntimeManager handles None thread gracefully."""
    # Create a new RuntimeManager instance
    manager = _RuntimeManager()

    # Manually set _initialized to True without initializing _thread
    # This simulates the race condition
    manager._initialized = True
    manager._portal = None
    manager._thread = None  # Explicitly None

    # This should not raise AttributeError
    portal = manager.get_portal()
    assert portal is not None

    # Verify thread was created
    assert manager._thread is not None
    assert manager._thread.is_alive()
