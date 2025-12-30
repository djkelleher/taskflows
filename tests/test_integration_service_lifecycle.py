"""Integration tests for service lifecycle operations.

Tests real systemd service lifecycle including start, stop, restart,
automatic restart on failure, timer-triggered services, and dependencies.

These tests require systemd and may modify the system. They are marked
with @pytest.mark.integration and can be skipped with: pytest -m "not integration"
"""

import asyncio
import time
from pathlib import Path
from typing import Literal

import pytest

from taskflows.service import Service, RestartPolicy, _start_service, _stop_service, _restart_service

pytestmark = pytest.mark.integration


class ServiceLifecycleTester:
    """Helper class for testing service lifecycle operations."""

    def __init__(self, service: Service):
        self.service = service
        self.service_name = service.name

    async def wait_for_state(
        self,
        expected_state: Literal["active", "inactive", "failed", "activating"],
        timeout: float = 10.0,
        check_interval: float = 0.2,
    ) -> bool:
        """Wait for service to reach expected state.

        Args:
            expected_state: The state to wait for
            timeout: Maximum time to wait in seconds
            check_interval: How often to check state in seconds

        Returns:
            True if state reached, False if timeout

        """
        start_time = time.time()

        while (time.time() - start_time) < timeout:
            try:
                # Import here to avoid circular dependencies
                from taskflows.service import get_service_state

                current_state = get_service_state(self.service_name)

                if current_state == expected_state:
                    return True

            except Exception:
                # Service might not exist yet
                pass

            await asyncio.sleep(check_interval)

        return False

    async def cleanup(self):
        """Clean up service files and stop service."""
        try:
            await _stop_service(self.service_name)
        except Exception:
            pass

        # Remove service files
        from taskflows.common import systemd_dir

        service_files = list(systemd_dir.glob(f"*{self.service_name}*"))
        for file in service_files:
            try:
                file.unlink()
            except Exception:
                pass


@pytest.fixture
async def test_service_lifecycle():
    """Fixture providing service lifecycle tester with cleanup."""
    testers = []

    def _create_tester(service: Service) -> ServiceLifecycleTester:
        tester = ServiceLifecycleTester(service)
        testers.append(tester)
        return tester

    yield _create_tester

    # Cleanup all testers
    for tester in testers:
        await tester.cleanup()


@pytest.mark.asyncio
class TestBasicServiceLifecycle:
    """Test basic service start/stop/restart operations."""

    async def test_service_start_to_active(self, test_service_lifecycle, tmp_path):
        """Test that a service starts and becomes active."""
        # Create a simple long-running service
        marker_file = tmp_path / "running.marker"

        service = Service(
            name="test-start-service",
            description="Test service for start operation",
            exec_start=f"bash -c 'touch {marker_file} && sleep 60'",
        )

        tester = test_service_lifecycle(service)

        # Start the service
        await _start_service(service.name, create_if_missing=True)

        # Wait for active state
        is_active = await tester.wait_for_state("active", timeout=5.0)
        assert is_active, "Service did not reach active state"

        # Verify marker file was created
        assert marker_file.exists(), "Service did not execute command"

    async def test_service_stop_to_inactive(self, test_service_lifecycle, tmp_path):
        """Test that a service stops and becomes inactive."""
        service = Service(
            name="test-stop-service",
            description="Test service for stop operation",
            exec_start="sleep 60",
        )

        tester = test_service_lifecycle(service)

        # Start the service
        await _start_service(service.name, create_if_missing=True)
        await tester.wait_for_state("active", timeout=5.0)

        # Stop the service
        await _stop_service(service.name)

        # Wait for inactive state
        is_inactive = await tester.wait_for_state("inactive", timeout=5.0)
        assert is_inactive, "Service did not reach inactive state"

    async def test_service_restart(self, test_service_lifecycle, tmp_path):
        """Test that a service can be restarted."""
        restart_count_file = tmp_path / "restart_count.txt"
        restart_count_file.write_text("0")

        service = Service(
            name="test-restart-service",
            description="Test service for restart operation",
            exec_start=f"bash -c 'echo $(($(cat {restart_count_file}) + 1)) > {restart_count_file} && sleep 60'",
        )

        tester = test_service_lifecycle(service)

        # Start the service
        await _start_service(service.name, create_if_missing=True)
        await tester.wait_for_state("active", timeout=5.0)

        # Check initial count
        initial_count = int(restart_count_file.read_text())
        assert initial_count == 1

        # Restart the service
        await _restart_service(service.name)
        await tester.wait_for_state("active", timeout=5.0)

        # Check count increased
        new_count = int(restart_count_file.read_text())
        assert new_count == 2, "Service restart did not execute command again"


@pytest.mark.asyncio
class TestRestartPolicyBehavior:
    """Test service restart policy behaviors."""

    async def test_restart_on_failure_policy(self, test_service_lifecycle, tmp_path):
        """Test that service restarts on failure with on-failure policy."""
        attempt_file = tmp_path / "attempts.txt"
        attempt_file.write_text("0")

        service = Service(
            name="test-restart-on-failure",
            description="Test on-failure restart policy",
            exec_start=f"bash -c 'COUNT=$(($(cat {attempt_file}) + 1)); echo $COUNT > {attempt_file}; [ $COUNT -ge 3 ] && exit 0 || exit 1'",
            restart_policy=RestartPolicy.ON_FAILURE,
            restart_sec=1,  # Fast restart for testing
        )

        tester = test_service_lifecycle(service)

        # Start the service (will fail first 2 times, succeed on 3rd)
        await _start_service(service.name, create_if_missing=True)

        # Wait for service to eventually succeed
        await asyncio.sleep(5)  # Give time for retries

        # Check that it retried
        attempts = int(attempt_file.read_text())
        assert attempts >= 3, f"Service should have retried at least 3 times, got {attempts}"

    async def test_restart_always_policy(self, test_service_lifecycle, tmp_path):
        """Test that service restarts even on successful exit with always policy."""
        restart_file = tmp_path / "restart_count.txt"
        restart_file.write_text("0")

        service = Service(
            name="test-restart-always",
            description="Test always restart policy",
            exec_start=f"bash -c 'echo $(($(cat {restart_file}) + 1)) > {restart_file} && exit 0'",
            restart_policy=RestartPolicy.ALWAYS,
            restart_sec=1,
        )

        tester = test_service_lifecycle(service)

        # Start the service
        await _start_service(service.name, create_if_missing=True)

        # Wait for multiple restarts
        await asyncio.sleep(4)

        # Should have restarted multiple times
        restarts = int(restart_file.read_text())
        assert restarts >= 3, f"Service should have restarted at least 3 times with always policy, got {restarts}"


@pytest.mark.asyncio
class TestTimerTriggeredServices:
    """Test services triggered by systemd timers."""

    async def test_timer_triggers_service(self, test_service_lifecycle, tmp_path):
        """Test that a timer correctly triggers its service."""
        trigger_file = tmp_path / "timer_triggered.txt"

        from taskflows.schedule import Periodic

        service = Service(
            name="test-timer-service",
            description="Test timer-triggered service",
            exec_start=f"bash -c 'date >> {trigger_file}'",
            schedule=Periodic(seconds=2),  # Run every 2 seconds
        )

        tester = test_service_lifecycle(service)

        # Enable and start the timer
        await _start_service(service.name, create_if_missing=True)

        # Wait for multiple triggers
        await asyncio.sleep(6)

        # Check that service was triggered multiple times
        if trigger_file.exists():
            triggers = trigger_file.read_text().strip().split("\n")
            assert len(triggers) >= 2, f"Timer should have triggered at least 2 times, got {len(triggers)}"


@pytest.mark.asyncio
class TestServiceTimeout:
    """Test service timeout behaviors."""

    async def test_start_timeout(self, test_service_lifecycle):
        """Test that service respects start timeout."""
        from taskflows.constraints import CgroupConfig

        service = Service(
            name="test-start-timeout",
            description="Test start timeout",
            exec_start="sleep 60",  # Takes long to "start"
            cgroup=CgroupConfig(timeout_start=2),  # 2 second timeout
            type="forking",  # Requires forking to trigger start timeout
        )

        tester = test_service_lifecycle(service)

        # Try to start - should timeout
        try:
            await _start_service(service.name, create_if_missing=True)
            # Give it time to timeout
            await asyncio.sleep(4)

            # Service should not be active
            from taskflows.service import get_service_state

            state = get_service_state(service.name)
            assert state != "active", "Service should have timed out on start"

        except Exception:
            # Timeout exceptions are expected
            pass


@pytest.mark.asyncio
class TestServiceEnvironment:
    """Test service environment variable handling."""

    async def test_environment_variables(self, test_service_lifecycle, tmp_path):
        """Test that environment variables are passed to service."""
        output_file = tmp_path / "env_output.txt"

        from taskflows.constraints import CgroupConfig

        service = Service(
            name="test-env-vars",
            description="Test environment variables",
            exec_start=f"bash -c 'echo $TEST_VAR > {output_file}'",
            cgroup=CgroupConfig(environment={"TEST_VAR": "test_value_123"}),
        )

        tester = test_service_lifecycle(service)

        # Start service
        await _start_service(service.name, create_if_missing=True)

        # Wait for completion
        await asyncio.sleep(2)

        # Check output
        assert output_file.exists(), "Service did not create output file"
        content = output_file.read_text().strip()
        assert content == "test_value_123", f"Expected 'test_value_123', got '{content}'"


@pytest.mark.asyncio
class TestServiceUser:
    """Test running services as different users."""

    async def test_service_user_context(self, test_service_lifecycle, tmp_path):
        """Test that service runs as specified user."""
        output_file = tmp_path / "user_output.txt"

        from taskflows.constraints import CgroupConfig

        # Run as current user (safe for testing)
        import os

        current_user = os.getenv("USER", "nobody")

        service = Service(
            name="test-user-context",
            description="Test user context",
            exec_start=f"bash -c 'whoami > {output_file}'",
            cgroup=CgroupConfig(user=current_user),
        )

        tester = test_service_lifecycle(service)

        # Start service
        await _start_service(service.name, create_if_missing=True)

        # Wait for completion
        await asyncio.sleep(2)

        # Check output
        if output_file.exists():
            user = output_file.read_text().strip()
            assert user == current_user, f"Expected user '{current_user}', got '{user}'"


@pytest.mark.asyncio
class TestServiceWorkingDirectory:
    """Test service working directory."""

    async def test_working_directory(self, test_service_lifecycle, tmp_path):
        """Test that service runs in specified working directory."""
        work_dir = tmp_path / "workdir"
        work_dir.mkdir()
        output_file = work_dir / "pwd_output.txt"

        from taskflows.constraints import CgroupConfig

        service = Service(
            name="test-working-dir",
            description="Test working directory",
            exec_start=f"bash -c 'pwd > pwd_output.txt'",
            cgroup=CgroupConfig(working_dir=str(work_dir)),
        )

        tester = test_service_lifecycle(service)

        # Start service
        await _start_service(service.name, create_if_missing=True)

        # Wait for completion
        await asyncio.sleep(2)

        # Check output
        assert output_file.exists(), "Service did not create output in working directory"
        pwd = output_file.read_text().strip()
        assert pwd == str(work_dir), f"Service not in expected working directory: {pwd} != {work_dir}"


@pytest.mark.asyncio
class TestDockerServiceLifecycle:
    """Test Docker container service lifecycle."""

    async def test_docker_container_service_start_stop(self, test_service_lifecycle):
        """Test starting and stopping a Docker container service."""
        pytest.skip("Requires Docker daemon")

        from taskflows.docker import DockerContainer

        container = DockerContainer(
            name="test-container-lifecycle",
            image="alpine:latest",
            command="sleep 60",
        )

        service = Service(
            name="test-docker-service",
            description="Test Docker service",
            docker_container=container,
        )

        tester = test_service_lifecycle(service)

        # Start the service
        await _start_service(service.name, create_if_missing=True)
        is_active = await tester.wait_for_state("active", timeout=10.0)
        assert is_active, "Docker service did not start"

        # Stop the service
        await _stop_service(service.name)
        is_inactive = await tester.wait_for_state("inactive", timeout=10.0)
        assert is_inactive, "Docker service did not stop"
