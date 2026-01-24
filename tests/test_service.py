from datetime import datetime, timedelta, timezone
from pathlib import Path
from shutil import rmtree
from time import sleep, time

import pytest
from taskflows import constraints
from taskflows.common import _SYSTEMD_FILE_PREFIX
from taskflows.constraints import CgroupConfig
from taskflows.schedule import Calendar, Periodic
from taskflows.service import Service, ServiceRegistry, systemd_dir


@pytest.fixture
def log_dir():
    d = Path(__file__).parent / "logs"
    d.mkdir(exist_ok=True)
    yield d
    rmtree(d)


def create_test_name():
    return f"test_{time()}".replace(".", "")


def test_config():
    v = Calendar("Sun 17:00 America/New_York")
    assert isinstance(v.unit_entries, set)

    v = Periodic(start_on="boot", period=10, relative_to="start")
    assert isinstance(v.unit_entries, set)

    v = Periodic("login", 1, "start")
    assert isinstance(v.unit_entries, set)

    v = constraints.Memory(amount=1000000, constraint=">=", silent=True)
    assert isinstance(v.unit_entries, set)

    v = constraints.Memory(amount=908902, constraint="=", silent=False)
    assert isinstance(v.unit_entries, set)

    v = constraints.CPUs(amount=9, constraint=">=", silent=True)
    assert isinstance(v.unit_entries, set)

    v = constraints.CPUPressure(max_percent=80, timespan="5min", silent=True)
    assert isinstance(v.unit_entries, set)

    v = constraints.MemoryPressure(max_percent=90, timespan="5min", silent=False)
    assert isinstance(v.unit_entries, set)

    v = constraints.CPUPressure(max_percent=80, timespan="1min", silent=False)
    assert isinstance(v.unit_entries, set)

    v = constraints.IOPressure(max_percent=80, timespan="10sec", silent=True)
    assert isinstance(v.unit_entries, set)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_service_management(log_dir):
    # create a minimal service.
    test_name = create_test_name()
    log_file = (log_dir / f"{test_name}.log").resolve()
    srv = Service(
        name=test_name, start_command=f"bash -c 'echo {test_name} >> {log_file}'"
    )
    await srv.create()
    service_file = systemd_dir / f"{_SYSTEMD_FILE_PREFIX}{test_name}.service"
    assert service_file.is_file()
    assert len(service_file.read_text())
    await srv.start()
    sleep(0.5)
    assert log_file.is_file()
    assert log_file.read_text().strip() == test_name
    await srv.remove()
    assert not service_file.exists()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_schedule(log_dir):
    test_name = create_test_name()
    log_file = (log_dir / f"{test_name}.log").resolve()
    run_time = datetime.now(timezone.utc) + timedelta(seconds=1)
    srv = Service(
        name=test_name,
        start_command=f"bash -c 'echo {test_name} >> {log_file}'",
        start_schedule=Calendar.from_datetime(run_time),
    )
    await srv.create()
    timer_file = systemd_dir / f"{_SYSTEMD_FILE_PREFIX}{test_name}.timer"
    assert timer_file.is_file()
    assert len(timer_file.read_text())
    assert not log_file.is_file()
    sleep((run_time - datetime.now(timezone.utc)).total_seconds() + 0.5)
    assert log_file.is_file()
    assert log_file.read_text().strip() == test_name
    await srv.remove()
    assert not timer_file.exists()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_service_enable_without_arguments(log_dir):
    """Test that Service.enable() works without arguments (default parameter)."""
    test_name = create_test_name()
    log_file = (log_dir / f"{test_name}.log").resolve()
    srv = Service(
        name=test_name,
        start_command=f"bash -c 'echo {test_name} >> {log_file}'",
        start_schedule=Calendar.from_datetime(datetime.now(timezone.utc) + timedelta(seconds=10)),
    )
    await srv.create()

    # This should not raise TypeError (the bug we fixed)
    # Just verify it doesn't crash - enable() has no return value
    try:
        await srv.enable()
        enable_succeeded = True
    except TypeError:
        enable_succeeded = False

    assert enable_succeeded, "enable() should work without arguments"

    await srv.remove()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_service_enable_timers_only(log_dir):
    """Test that Service.enable(timers_only=True) accepts the parameter."""
    test_name = create_test_name()
    log_file = (log_dir / f"{test_name}.log").resolve()
    srv = Service(
        name=test_name,
        start_command=f"bash -c 'echo {test_name} >> {log_file}'",
        start_schedule=Calendar.from_datetime(datetime.now(timezone.utc) + timedelta(seconds=10)),
    )
    await srv.create()

    # This should not raise TypeError (verify parameter works)
    try:
        await srv.enable(timers_only=True)
        enable_succeeded = True
    except TypeError:
        enable_succeeded = False

    assert enable_succeeded, "enable(timers_only=True) should work"

    await srv.remove()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_service_registry_enable():
    """Test that ServiceRegistry.enable() works correctly."""
    test_name1 = create_test_name()
    test_name2 = create_test_name()

    srv1 = Service(name=test_name1, start_command="echo test1")
    srv2 = Service(name=test_name2, start_command="echo test2")

    # Create a registry and add services
    registry = ServiceRegistry()
    registry.add(srv1, srv2)

    try:
        await srv1.create()
        await srv2.create()

        # This should not raise TypeError (the bug we fixed)
        try:
            await registry.enable()
            enable_succeeded = True
        except TypeError:
            enable_succeeded = False

        assert enable_succeeded, "ServiceRegistry.enable() should work without errors"

    finally:
        # Clean up
        await srv1.remove()
        await srv2.remove()


def test_cgroup_multiple_device_limits():
    """Test that multiple device bandwidth limits are preserved in systemd directives."""
    cgroup = CgroupConfig(
        device_read_bps={
            "/dev/sda": 1048576,  # 1 MB/s
            "/dev/sdb": 2097152,  # 2 MB/s
        },
        device_write_bps={
            "/dev/sda": 524288,  # 512 KB/s
            "/dev/sdb": 1048576,  # 1 MB/s
        },
    )

    directives = cgroup.to_systemd_directives()

    # Verify all device limits are present with numbered keys
    assert "IOReadBandwidthMax_0" in directives
    assert "IOReadBandwidthMax_1" in directives
    assert "IOWriteBandwidthMax_0" in directives
    assert "IOWriteBandwidthMax_1" in directives

    # Verify values are correct
    read_values = {directives["IOReadBandwidthMax_0"], directives["IOReadBandwidthMax_1"]}
    assert "/dev/sda 1048576" in read_values
    assert "/dev/sdb 2097152" in read_values

    write_values = {directives["IOWriteBandwidthMax_0"], directives["IOWriteBandwidthMax_1"]}
    assert "/dev/sda 524288" in write_values
    assert "/dev/sdb 1048576" in write_values


@pytest.mark.integration
@pytest.mark.asyncio
async def test_cgroup_device_limits_in_service_unit(log_dir):
    """Test that service unit file contains all device limits."""
    test_name = create_test_name()
    log_file = (log_dir / f"{test_name}.log").resolve()

    cgroup = CgroupConfig(
        device_read_bps={
            "/dev/sda": 1048576,
            "/dev/sdb": 2097152,
        },
    )

    srv = Service(
        name=test_name,
        start_command=f"bash -c 'echo {test_name} >> {log_file}'",
        cgroup_config=cgroup,
    )
    await srv.create()

    # Read the service file
    service_file = systemd_dir / f"{_SYSTEMD_FILE_PREFIX}{test_name}.service"
    assert service_file.is_file()
    service_content = service_file.read_text()

    # Verify both device limits appear in the service file
    assert "IOReadBandwidthMax=/dev/sda 1048576" in service_content
    assert "IOReadBandwidthMax=/dev/sdb 2097152" in service_content

    await srv.remove()
