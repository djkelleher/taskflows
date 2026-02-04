"""Test all service operations on a simple bash command service."""

import subprocess
from pathlib import Path
from shutil import rmtree
from time import sleep, time

import pytest
from taskflows.common import _SYSTEMD_FILE_PREFIX
from taskflows.service import Service, systemd_dir


def create_test_name():
    return f"test_bash_{time()}".replace(".", "")


def get_service_state(name: str) -> str:
    """Get the ActiveState of a systemd service."""
    unit_name = f"{_SYSTEMD_FILE_PREFIX}{name}.service"
    result = subprocess.run(
        ["systemctl", "--user", "show", unit_name, "--property=ActiveState"],
        capture_output=True,
        text=True,
    )
    # Output is like "ActiveState=active\n"
    if result.returncode == 0 and "=" in result.stdout:
        return result.stdout.strip().split("=")[1]
    return "unknown"


@pytest.fixture
def output_dir():
    """Create and cleanup test output directory."""
    d = Path(__file__).parent / "bash_test_output"
    d.mkdir(exist_ok=True)
    yield d
    rmtree(d, ignore_errors=True)


pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_create_generates_unit_file(output_dir):
    """Test create() generates systemd service file."""
    name = create_test_name()
    srv = Service(name=name, start_command="echo test")

    try:
        await srv.create()
        service_file = systemd_dir / f"{_SYSTEMD_FILE_PREFIX}{name}.service"
        assert service_file.is_file()
        assert "ExecStart" in service_file.read_text()
    finally:
        await srv.remove()


@pytest.mark.asyncio
async def test_start_executes_command(output_dir):
    """Test start() executes the bash command."""
    name = create_test_name()
    output_file = output_dir / f"{name}.txt"
    srv = Service(name=name, start_command=f"bash -c 'echo started > {output_file}'")

    try:
        await srv.create()
        await srv.start()
        sleep(1)
        assert output_file.read_text().strip() == "started"
    finally:
        await srv.remove()


@pytest.mark.asyncio
async def test_stop_terminates_service(output_dir):
    """Test stop() terminates a running service."""
    name = create_test_name()
    srv = Service(name=name, start_command="sleep 60")

    try:
        await srv.create()
        await srv.start()
        sleep(0.5)
        assert get_service_state(name) == "active"

        await srv.stop()
        sleep(0.5)
        assert get_service_state(name) in ("inactive", "failed", "deactivating")
    finally:
        await srv.remove()


@pytest.mark.asyncio
async def test_restart_re_executes_command(output_dir):
    """Test restart() re-runs the service."""
    name = create_test_name()
    counter_file = output_dir / f"{name}_count.txt"
    counter_file.write_text("0")

    srv = Service(
        name=name,
        start_command=f"bash -c 'echo $(($(cat {counter_file}) + 1)) > {counter_file} && sleep 60'"
    )

    try:
        await srv.create()
        await srv.start()
        sleep(1)
        assert int(counter_file.read_text().strip()) == 1

        await srv.restart()
        sleep(1)
        assert int(counter_file.read_text().strip()) == 2
    finally:
        await srv.remove()


@pytest.mark.asyncio
async def test_enable_disable_service(output_dir):
    """Test enable() and disable() operations."""
    name = create_test_name()
    srv = Service(name=name, start_command="echo test")

    try:
        await srv.create()

        # enable should not raise
        await srv.enable()

        # disable should not raise
        await srv.disable()
    finally:
        await srv.remove()


@pytest.mark.asyncio
async def test_remove_deletes_all_files(output_dir):
    """Test remove() deletes service files."""
    name = create_test_name()
    srv = Service(name=name, start_command="echo test")

    await srv.create()
    service_file = systemd_dir / f"{_SYSTEMD_FILE_PREFIX}{name}.service"
    assert service_file.exists()

    await srv.remove()
    assert not service_file.exists()


@pytest.mark.asyncio
async def test_full_lifecycle(output_dir):
    """Test complete service lifecycle: create -> start -> stop -> restart -> remove."""
    name = create_test_name()
    output_file = output_dir / f"{name}_lifecycle.txt"
    srv = Service(
        name=name,
        start_command=f"bash -c 'date >> {output_file} && sleep 30'"
    )

    try:
        # Create
        await srv.create()
        service_file = systemd_dir / f"{_SYSTEMD_FILE_PREFIX}{name}.service"
        assert service_file.exists(), "Service file should be created"

        # Start
        await srv.start()
        sleep(1)
        assert output_file.exists(), "Output file should exist after start"
        initial_content = output_file.read_text()
        assert len(initial_content) > 0, "Output file should have content"

        # Verify running
        assert get_service_state(name) == "active", "Service should be active"

        # Stop
        await srv.stop()
        sleep(0.5)
        assert get_service_state(name) in ("inactive", "failed"), "Service should be stopped"

        # Restart (will start again since it's stopped)
        await srv.restart()
        sleep(1)
        new_content = output_file.read_text()
        assert len(new_content) > len(initial_content), "Restart should append new output"

    finally:
        await srv.remove()
        assert not service_file.exists(), "Service file should be removed"
