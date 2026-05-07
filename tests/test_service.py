from datetime import datetime, timedelta, timezone
from pathlib import Path
from shutil import rmtree
from time import sleep, time
from unittest.mock import MagicMock, patch

import pytest
from taskflows import constraints
from taskflows.common import _SYSTEMD_FILE_PREFIX
from taskflows.constraints import CgroupConfig
from taskflows.schedule import Calendar, Periodic
from taskflows.service import Service, ServiceRegistry, Venv, service_logs, systemd_dir


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


def test_constraints_reject_invalid_numeric_ranges():
    with pytest.raises(ValueError):
        constraints.Memory(amount=-1)

    with pytest.raises(ValueError):
        constraints.CPUPressure(max_percent=-1)

    with pytest.raises(ValueError):
        constraints.CPUPressure(max_percent=101)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"cpu_period": 0},
        {"cpu_shares": 0},
        {"cpu_weight": 10001},
        {"memory_limit": -1},
        {"memory_swappiness": 101},
        {"blkio_weight": 9},
        {"io_weight": 0},
        {"pids_limit": 0},
        {"nofile_limit": 0},
        {"oom_score_adj": -1001},
        {"timeout_start": -1},
        {"device_read_bps": {"/dev/sda": 0}},
        {"device_write_iops": {"/dev/sda": -1}},
    ],
)
def test_cgroup_config_rejects_invalid_resource_ranges(kwargs):
    with pytest.raises(ValueError):
        CgroupConfig(**kwargs)


def test_calendar_from_datetime_uses_four_digit_year():
    run_time = datetime(2026, 5, 5, 16, 50, 8, tzinfo=timezone.utc)

    calendar = Calendar.from_datetime(run_time)

    assert calendar.schedule == "Tue 2026-05-05 16:50:08 UTC"
    assert "OnCalendar=Tue 2026-05-05 16:50:08 UTC" in calendar.unit_entries


@pytest.mark.parametrize("period", [0, -1])
def test_periodic_rejects_nonpositive_period(period):
    with pytest.raises(ValueError, match="period"):
        Periodic(start_on="boot", period=period, relative_to="start")


@pytest.mark.parametrize(
    "kwargs",
    [
        {"start_on": "shutdown", "period": 1, "relative_to": "start"},
        {"start_on": "boot", "period": 1, "relative_to": "middle"},
    ],
)
def test_periodic_rejects_invalid_options(kwargs):
    with pytest.raises(ValueError):
        Periodic(**kwargs)


@pytest.mark.parametrize(
    "schedule_kwargs",
    [
        {"schedule": "", "accuracy": "1ms"},
        {"schedule": "Mon 12:00", "accuracy": ""},
        {"schedule": "Mon 12:00\nOnBootSec=1", "accuracy": "1ms"},
    ],
)
def test_calendar_rejects_invalid_systemd_values(schedule_kwargs):
    with pytest.raises(ValueError):
        Calendar(**schedule_kwargs)


def test_service_logs_sets_journalctl_timeout(monkeypatch):
    monkeypatch.setenv("TASKFLOWS_JOURNALCTL_TIMEOUT_SECONDS", "7")
    completed = MagicMock(stdout="logs", stderr="")

    with patch(
        "taskflows.service.get_docker_client", side_effect=RuntimeError("no docker")
    ):
        with patch("taskflows.service.subprocess.run", return_value=completed) as run:
            assert service_logs("test-service") == "logs"

    assert run.call_args.kwargs["timeout"] == 7


def test_service_copies_env_before_adding_runtime_defaults():
    env = {"APP_ENV": "test"}

    service = Service(name="env-copy", start_command="python -V", env=env)

    assert env == {"APP_ENV": "test"}
    assert service.env == {"APP_ENV": "test", "PYTHONUNBUFFERED": "1"}


@pytest.mark.parametrize("timeout", [0, -1])
def test_service_rejects_nonpositive_timeout(timeout):
    with pytest.raises(ValueError, match="timeout"):
        Service(name="bad-timeout", start_command="python -V", timeout=timeout)


def test_venv_command_quotes_runner_and_environment_name(tmp_path):
    runner = tmp_path / "conda runner"
    runner.touch()

    command = Venv(env_name="prod env", custom_path=runner).create_env_command(
        "python -V"
    )

    assert command == f"'{runner}' run -n 'prod env' --no-capture-output python -V"


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
        start_schedule=Calendar.from_datetime(
            datetime.now(timezone.utc) + timedelta(seconds=10)
        ),
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
        start_schedule=Calendar.from_datetime(
            datetime.now(timezone.utc) + timedelta(seconds=10)
        ),
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
    read_values = {
        directives["IOReadBandwidthMax_0"],
        directives["IOReadBandwidthMax_1"],
    }
    assert "/dev/sda 1048576" in read_values
    assert "/dev/sdb 2097152" in read_values

    write_values = {
        directives["IOWriteBandwidthMax_0"],
        directives["IOWriteBandwidthMax_1"],
    }
    assert "/dev/sda 524288" in write_values
    assert "/dev/sdb 1048576" in write_values


def test_cgroup_environment_directives_are_escaped():
    cgroup = CgroupConfig(environment={"SAFE_VALUE": 'quoted "value" with spaces'})
    srv = Service(
        name="cgroup-env",
        start_command="echo ok",
        cgroup_config=cgroup,
    )

    assert (
        'Environment="SAFE_VALUE=quoted \\"value\\" with spaces"' in srv.service_entries
    )


def test_cgroup_repeated_device_allow_entries_are_preserved():
    cgroup = CgroupConfig(devices=["/dev/fuse", "/dev/null:r"])
    srv = Service(
        name="cgroup-devices",
        start_command="echo ok",
        cgroup_config=cgroup,
    )

    device_allow_entries = {
        entry for entry in srv.service_entries if entry.startswith("DeviceAllow=")
    }
    assert device_allow_entries == {
        "DeviceAllow=/dev/fuse rwm",
        "DeviceAllow=/dev/null r",
    }


def test_service_relationship_accepts_service_object():
    dependency = Service(name="dependency", start_command="echo dependency")
    srv = Service(
        name="dependent",
        start_command="echo dependent",
        start_after=dependency,
    )

    assert "After=taskflows-dependency.service" in srv.unit_entries


def test_service_env_file_parse_errors_are_fatal(tmp_path):
    env_file = tmp_path / "bad.env"
    env_file.write_text("not-an-env-line")

    with pytest.raises(ValueError, match="Invalid environment line"):
        Service(
            name="bad-env-file",
            start_command="echo bad",
            env_file=str(env_file),
        )


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
