"""
Simple test to verify the async task implementation works correctly.
"""

import asyncio
import pytest

from taskflows.tasks import task


@task(name="sample_async_task", retries=1)
async def sample_async_task():
    """Sample async task."""
    await asyncio.sleep(0.1)  # Simulate async work
    return "async_result"


@task(name="sample_sync_task", retries=1)
def sample_sync_task():
    """Sample sync task running in async context."""
    import time

    time.sleep(0.1)  # Simulate sync work
    return "sync_result"


@task(name="sample_error_task", retries=2)
async def sample_error_task():
    """Sample task that raises an error."""
    raise ValueError("Test error for logging")


@pytest.mark.asyncio
async def test_async_task_execution():
    """Test async task execution."""
    result = await sample_async_task()
    assert result == "async_result"


def test_sync_task_execution():
    """Test sync task execution."""
    result = sample_sync_task()
    assert result == "sync_result"


@pytest.mark.asyncio
async def test_error_task_execution():
    """Test error task execution."""
    # This should not raise since required=False by default
    result = await sample_error_task()
    assert result is None
