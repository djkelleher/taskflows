import asyncio
import json
from datetime import datetime, timezone
from time import sleep
from urllib.parse import parse_qs, unquote, urlparse

import pytest
from taskflows import task
from taskflows.tasks import build_loki_query_url, run_task, _RuntimeManager


class RecordingMetric:
    def __init__(self):
        self.calls = []
        self.current_labels = None

    def labels(self, **labels):
        self.current_labels = labels
        return self

    def inc(self):
        self.calls.append(("inc", self.current_labels))

    def observe(self, value):
        self.calls.append(("observe", self.current_labels, value))


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


def test_task_passes_positional_and_keyword_arguments_to_sync_function():
    @task(name="test_args", required=True)
    def combine(prefix: str, value: int, *, suffix: str) -> str:
        return f"{prefix}-{value}-{suffix}"

    assert combine("item", 7, suffix="done") == "item-7-done"


@pytest.mark.parametrize("retries", [-1, -5])
def test_task_rejects_negative_retries(retries):
    with pytest.raises(ValueError, match="retries"):

        @task(name="invalid_retries", retries=retries)
        def do_work():
            return 1


@pytest.mark.parametrize("timeout", [0, -1])
def test_task_rejects_nonpositive_timeout(timeout):
    with pytest.raises(ValueError, match="timeout"):

        @task(name="invalid_timeout", timeout=timeout)
        def do_work():
            return 1


@pytest.mark.asyncio
async def test_run_task_rejects_invalid_execution_options():
    def do_work():
        return 1

    with pytest.raises(ValueError, match="retries"):
        await run_task(do_work, retries=-1)

    with pytest.raises(ValueError, match="timeout"):
        await run_task(do_work, timeout=0)


@pytest.mark.asyncio
async def test_run_task_records_duration_with_monotonic_clock(monkeypatch):
    from taskflows import metrics
    import time

    duration_metric = RecordingMetric()
    count_metric = RecordingMetric()
    monkeypatch.setattr(metrics, "task_duration", duration_metric)
    monkeypatch.setattr(metrics, "task_count", count_metric)

    perf_values = iter([5.0, 7.5])
    monkeypatch.setattr(time, "perf_counter", lambda: next(perf_values))

    async def do_work():
        return "done"

    assert await run_task(do_work, name="duration_test") == "done"

    assert duration_metric.calls == [
        (
            "observe",
            {"task_name": "duration_test", "status": "success"},
            2.5,
        )
    ]


@pytest.mark.asyncio
async def test_task_passes_positional_and_keyword_arguments_to_async_function():
    @task(name="test_async_args", required=True)
    async def combine(prefix: str, value: int, *, suffix: str) -> str:
        return f"{prefix}-{value}-{suffix}"

    assert await combine("item", 7, suffix="done") == "item-7-done"


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

    # Extract timestamps from URL - decode first since it's URL-encoded
    import re
    from urllib.parse import unquote

    decoded_url = unquote(url)

    # Try quoted format: "from":"1234567890"
    from_match = re.search(r'["\']from["\']\s*:\s*["\'](\d+)["\']', decoded_url)
    to_match = re.search(r'["\']to["\']\s*:\s*["\'](\d+)["\']', decoded_url)

    # Try unquoted format: from=1234567890 or from:1234567890
    if not from_match:
        from_match = re.search(r"from[=:](\d+)", decoded_url)
    if not to_match:
        to_match = re.search(r"to[=:](\d+)", decoded_url)

    assert from_match and to_match, (
        f"Could not find timestamps in decoded URL: {decoded_url[:200]}"
    )
    from_ts = int(from_match.group(1))
    to_ts = int(to_match.group(1))

    # Verify approximately 1 hour difference (in milliseconds)
    time_diff_ms = to_ts - from_ts
    expected_diff = 3600 * 1000  # 1 hour in milliseconds

    # Allow 1 second tolerance for execution time
    assert abs(time_diff_ms - expected_diff) < 1000, (
        f"Time diff: {time_diff_ms}ms, expected: {expected_diff}ms"
    )


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


def test_loki_query_url_escapes_task_name_as_regex_literal():
    """Task names should not be able to alter the generated LogQL regex."""
    url = build_loki_query_url('worker.*"prod\\job', error_only=True)
    query_params = parse_qs(urlparse(url).query)
    left = json.loads(unquote(query_params["left"][0]))
    expr = left["queries"][0]["expr"]

    assert expr == r'{service_name=~".*worker\\.\\*\"prod\\\\job.*"} |= "ERROR"'


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


def test_runtime_manager_fast_path_rechecks_portal_health():
    """A stale healthy flag should not return a missing portal."""
    manager = _RuntimeManager()
    manager._portal = None
    manager._thread = None
    manager._portal_healthy = True
    manager._last_health_check = datetime.now(timezone.utc).timestamp()

    portal = manager.get_portal()

    assert portal is not None
    assert manager._thread is not None
    assert manager._thread.is_alive()


@pytest.mark.parametrize(
    "retries,expected_attempts",
    [
        (0, 1),  # Initial attempt only, no retries
        (1, 2),  # Initial attempt + 1 retry
        (3, 4),  # Initial attempt + 3 retries
        (5, 6),  # Initial attempt + 5 retries
    ],
)
def test_retry_count_behavior(retries, expected_attempts):
    """Test that retries parameter gives correct number of total attempts.

    Verifies documented behavior in tasks.py:
    - retries=0 -> 1 attempt (initial only)
    - retries=1 -> 2 attempts (initial + 1 retry)
    - retries=3 -> 4 attempts (initial + 3 retries)

    The formula is: total_attempts = retries + 1
    """
    attempt_count = 0

    @task(
        name="test_retry_count",
        required=True,
        retries=retries,
    )
    def count_attempts():
        nonlocal attempt_count
        attempt_count += 1
        # Always fail to force retries
        raise RuntimeError(f"Attempt {attempt_count}")

    # Should exhaust all retries and raise
    with pytest.raises(RuntimeError):
        count_attempts()

    # Verify the correct number of attempts were made
    assert attempt_count == expected_attempts, (
        f"Expected {expected_attempts} attempts (retries={retries}), "
        f"but got {attempt_count}"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "retries,expected_attempts",
    [
        (0, 1),  # Initial attempt only, no retries
        (1, 2),  # Initial attempt + 1 retry
        (3, 4),  # Initial attempt + 3 retries
    ],
)
async def test_async_retry_count_behavior(retries, expected_attempts):
    """Test that retries parameter gives correct number of total attempts for async tasks.

    Verifies documented behavior matches async task execution.
    """
    attempt_count = 0

    @task(
        name="test_async_retry_count",
        required=True,
        retries=retries,
    )
    async def count_attempts():
        nonlocal attempt_count
        attempt_count += 1
        # Always fail to force retries
        raise RuntimeError(f"Attempt {attempt_count}")

    # Should exhaust all retries and raise
    with pytest.raises(RuntimeError):
        await count_attempts()

    # Verify the correct number of attempts were made
    assert attempt_count == expected_attempts, (
        f"Expected {expected_attempts} attempts (retries={retries}), "
        f"but got {attempt_count}"
    )
