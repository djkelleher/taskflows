"""Tests for the taskflows.serialization module."""
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from taskflows.serialization import (
    serialize,
    deserialize,
    to_dict,
    from_dict,
    serialize_to_file,
    deserialize_from_file,
    register_type,
    get_registered_type,
)
from taskflows.service import Venv, Service, RestartPolicy
from taskflows.docker import DockerContainer, Volume, Ulimit
from taskflows.schedule import Calendar, Periodic
from taskflows.constraints import CgroupConfig, Memory, CPUPressure


class TestTypeRegistry:
    """Tests for the type registry."""

    def test_get_registered_type(self):
        """Test that registered types can be retrieved."""
        assert get_registered_type("Venv") is Venv
        assert get_registered_type("DockerContainer") is DockerContainer
        assert get_registered_type("Service") is Service

    def test_unregistered_type_returns_none(self):
        """Test that unregistered types return None."""
        assert get_registered_type("NonExistentType") is None


class TestVenvSerialization:
    """Tests for Venv serialization."""

    def test_venv_to_dict(self):
        """Test Venv serialization to dict."""
        venv = Venv(env_name="myenv")
        data = to_dict(venv)

        assert data["type"] == "Venv"
        assert data["env_name"] == "myenv"

    def test_venv_roundtrip_json(self):
        """Test Venv JSON roundtrip."""
        venv = Venv(env_name="myenv", custom_path="/usr/bin/conda")
        json_str = serialize(venv, format="json")
        restored = deserialize(json_str, Venv, format="json")

        assert restored.env_name == venv.env_name
        assert restored.custom_path == venv.custom_path

    def test_venv_to_json(self):
        """Test Venv direct to_json method (if available)."""
        venv = Venv(env_name="testenv")
        data = to_dict(venv)
        json_str = json.dumps(data)

        parsed = json.loads(json_str)
        assert parsed["env_name"] == "testenv"


class TestVolumeSerialization:
    """Tests for Volume serialization."""

    def test_volume_to_dict(self):
        """Test Volume serialization."""
        vol = Volume(host_path="/data", container_path="/app/data", read_only=True)
        data = to_dict(vol)

        assert data["host_path"] == "/data"
        assert data["container_path"] == "/app/data"
        assert data["read_only"] is True

    def test_volume_roundtrip(self):
        """Test Volume roundtrip."""
        vol = Volume(host_path="/tmp/test", container_path="/app", read_only=False)
        json_str = serialize(vol, format="json")
        restored = deserialize(json_str, Volume, format="json")

        assert restored.host_path == vol.host_path
        assert restored.container_path == vol.container_path
        assert restored.read_only == vol.read_only


class TestDockerContainerSerialization:
    """Tests for DockerContainer serialization."""

    def test_simple_container_to_dict(self):
        """Test simple DockerContainer serialization."""
        container = DockerContainer(
            image="python:3.11",
            name="test-container",
            command="python app.py",
        )
        data = to_dict(container)

        assert data["type"] == "DockerContainer"
        assert data["image"] == "python:3.11"
        assert data["name"] == "test-container"

    def test_container_with_volumes(self):
        """Test container with nested volumes."""
        container = DockerContainer(
            image="nginx:latest",
            name="web-server",
            volumes=[
                Volume(host_path="/data", container_path="/usr/share/nginx/html"),
                Volume(host_path="/config", container_path="/etc/nginx", read_only=True),
            ],
        )
        data = to_dict(container)

        assert len(data["volumes"]) == 2
        assert data["volumes"][0]["host_path"] == "/data"
        assert data["volumes"][1]["read_only"] is True

    def test_container_roundtrip(self):
        """Test DockerContainer JSON roundtrip."""
        container = DockerContainer(
            image="redis:latest",
            name="cache",
            network_mode="bridge",
            environment={"REDIS_PASSWORD": "secret"},
        )
        json_str = serialize(container, format="json")
        restored = deserialize(json_str, DockerContainer, format="json")

        assert restored.image == container.image
        assert restored.name == container.name
        assert restored.network_mode == container.network_mode
        assert restored.environment == container.environment

    def test_container_with_cgroup_config(self):
        """Test container with CgroupConfig."""
        cgroup = CgroupConfig(
            memory_limit=1024 * 1024 * 512,  # 512MB
            cpu_shares=512,
            pids_limit=100,
        )
        container = DockerContainer(
            image="worker:latest",
            name="worker",
            cgroup_config=cgroup,
        )
        data = to_dict(container)

        assert "cgroup_config" in data
        assert data["cgroup_config"]["memory_limit"] == 1024 * 1024 * 512


class TestScheduleSerialization:
    """Tests for Schedule serialization."""

    def test_calendar_to_dict(self):
        """Test Calendar serialization."""
        cal = Calendar(schedule="Mon-Fri 09:00", persistent=True, accuracy="1s")
        data = to_dict(cal)

        assert data["type"] == "Calendar"
        assert data["schedule"] == "Mon-Fri 09:00"
        assert data["persistent"] is True

    def test_calendar_roundtrip(self):
        """Test Calendar roundtrip."""
        cal = Calendar(schedule="Sun 12:00 America/New_York")
        json_str = serialize(cal, format="json")
        restored = deserialize(json_str, Calendar, format="json")

        assert restored.schedule == cal.schedule

    def test_periodic_to_dict(self):
        """Test Periodic serialization."""
        periodic = Periodic(start_on="boot", period=300, relative_to="finish")
        data = to_dict(periodic)

        assert data["type"] == "Periodic"
        assert data["start_on"] == "boot"
        assert data["period"] == 300

    def test_periodic_roundtrip(self):
        """Test Periodic roundtrip."""
        periodic = Periodic(start_on="login", period=60, relative_to="start")
        json_str = serialize(periodic, format="json")
        restored = deserialize(json_str, Periodic, format="json")

        assert restored.start_on == periodic.start_on
        assert restored.period == periodic.period
        assert restored.relative_to == periodic.relative_to


class TestCgroupConfigSerialization:
    """Tests for CgroupConfig serialization."""

    def test_cgroup_to_dict(self):
        """Test CgroupConfig serialization."""
        cgroup = CgroupConfig(
            cpu_quota=50000,
            cpu_period=100000,
            memory_limit=1024 * 1024 * 1024,  # 1GB
            pids_limit=50,
        )
        data = to_dict(cgroup)

        assert data["type"] == "CgroupConfig"
        assert data["cpu_quota"] == 50000
        assert data["memory_limit"] == 1024 * 1024 * 1024

    def test_cgroup_roundtrip(self):
        """Test CgroupConfig roundtrip."""
        cgroup = CgroupConfig(
            cpu_shares=1024,
            memory_high=512 * 1024 * 1024,
            device_read_bps={"/dev/sda": 10485760},
        )
        json_str = serialize(cgroup, format="json")
        restored = deserialize(json_str, CgroupConfig, format="json")

        assert restored.cpu_shares == cgroup.cpu_shares
        assert restored.memory_high == cgroup.memory_high
        assert restored.device_read_bps == cgroup.device_read_bps


class TestConstraintsSerialization:
    """Tests for constraint types serialization."""

    def test_memory_constraint_roundtrip(self):
        """Test Memory constraint roundtrip."""
        mem = Memory(amount=1024 * 1024 * 1024, constraint=">=", silent=False)
        json_str = serialize(mem, format="json")
        restored = deserialize(json_str, Memory, format="json")

        assert restored.amount == mem.amount
        assert restored.constraint == mem.constraint

    def test_cpu_pressure_roundtrip(self):
        """Test CPUPressure constraint roundtrip."""
        pressure = CPUPressure(max_percent=80, timespan="5min")
        json_str = serialize(pressure, format="json")
        restored = deserialize(json_str, CPUPressure, format="json")

        assert restored.max_percent == pressure.max_percent
        assert restored.timespan == pressure.timespan


class TestServiceSerialization:
    """Tests for Service serialization."""

    def test_simple_service_to_dict(self):
        """Test simple Service serialization."""
        # Note: Service has complex __post_init__ that may modify fields
        service = Service(
            name="test-service",
            start_command="python app.py",
            description="A test service",
        )
        data = service.to_dict()

        assert data["type"] == "Service"
        assert data["name"] == "test-service"
        assert "start_command" in data  # Command may be modified by __post_init__

    def test_service_with_venv(self):
        """Test Service with Venv environment."""
        venv = Venv(env_name="myenv")
        service = Service(
            name="venv-service",
            start_command="python app.py",
            environment=venv,
        )
        data = service.to_dict()

        # Environment may be modified by __post_init__
        assert data["name"] == "venv-service"

    def test_service_with_schedule(self):
        """Test Service with schedule."""
        service = Service(
            name="scheduled-service",
            start_command="python job.py",
            start_schedule=Calendar(schedule="0 * * * *"),
        )
        data = service.to_dict()

        assert "start_schedule" in data

    def test_service_to_json_method(self):
        """Test Service.to_json() method."""
        service = Service(
            name="json-test",
            start_command="echo hello",
        )
        json_str = service.to_json()
        assert isinstance(json_str, str)
        parsed = json.loads(json_str)
        assert parsed["name"] == "json-test"


class TestFileSerialization:
    """Tests for file-based serialization."""

    def test_serialize_to_json_file(self):
        """Test serialization to JSON file."""
        venv = Venv(env_name="test")
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = Path(f.name)

        try:
            serialize_to_file(venv, path)
            restored = deserialize_from_file(path, Venv)
            assert restored.env_name == venv.env_name
        finally:
            path.unlink()

    def test_format_inference_from_extension(self):
        """Test format inference from file extension."""
        vol = Volume(host_path="/a", container_path="/b")

        # Test .json extension
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            json_path = Path(f.name)

        try:
            serialize_to_file(vol, json_path)  # Should use JSON
            content = json_path.read_text()
            assert "{" in content  # JSON uses braces
        finally:
            json_path.unlink()


class TestYAMLSerialization:
    """Tests for YAML serialization."""

    def test_venv_yaml_roundtrip(self):
        """Test Venv YAML roundtrip."""
        venv = Venv(env_name="yaml-test")
        yaml_str = serialize(venv, format="yaml")
        restored = deserialize(yaml_str, Venv, format="yaml")

        assert restored.env_name == venv.env_name

    def test_container_yaml_roundtrip(self):
        """Test DockerContainer YAML roundtrip."""
        container = DockerContainer(
            image="nginx:latest",
            name="web",
            environment={"PORT": "8080"},
        )
        yaml_str = serialize(container, format="yaml")
        restored = deserialize(yaml_str, DockerContainer, format="yaml")

        assert restored.image == container.image
        assert restored.name == container.name

    def test_yaml_file_serialization(self):
        """Test YAML file serialization."""
        vol = Volume(host_path="/data", container_path="/app/data")
        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as f:
            path = Path(f.name)

        try:
            serialize_to_file(vol, path)
            restored = deserialize_from_file(path, Volume)
            assert restored.host_path == vol.host_path
        finally:
            path.unlink()


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_none_values_excluded_by_default(self):
        """Test that None values are excluded by default."""
        vol = Volume(host_path="/a", container_path="/b")  # read_only defaults to False
        data = to_dict(vol, include_none=False)

        # read_only should be included since it has a default value (False)
        assert "read_only" in data

    def test_include_none_values(self):
        """Test including None values explicitly."""
        venv = Venv(env_name="test")  # custom_path is None
        data = to_dict(venv, include_none=True)

        assert "custom_path" in data

    def test_datetime_serialization(self):
        """Test datetime serialization."""
        now = datetime.now(timezone.utc)
        data = {"timestamp": now}

        from taskflows.serialization import _serialize_value, _deserialize_value
        serialized = _serialize_value(data)
        assert serialized["timestamp"]["type"] == "datetime"

        deserialized = _deserialize_value(serialized)
        assert isinstance(deserialized["timestamp"], datetime)

    def test_set_serialization(self):
        """Test set serialization."""
        from taskflows.serialization import _serialize_value, _deserialize_value

        data = {"items": {"a", "b", "c"}}
        serialized = _serialize_value(data)

        assert serialized["items"]["type"] == "set"
        assert set(serialized["items"]["values"]) == {"a", "b", "c"}

        deserialized = _deserialize_value(serialized)
        assert deserialized["items"] == {"a", "b", "c"}

    def test_path_serialization(self):
        """Test Path serialization."""
        from taskflows.serialization import _serialize_value

        data = {"path": Path("/tmp/test")}
        serialized = _serialize_value(data)

        assert serialized["path"] == "/tmp/test"

    def test_invalid_format_raises_error(self):
        """Test that invalid format raises ValueError."""
        venv = Venv(env_name="test")
        with pytest.raises(ValueError, match="Unknown format"):
            serialize(venv, format="xml")


class TestLoadServicesFromYAML:
    """Tests for load_services_from_yaml function."""

    def test_load_multiple_services(self):
        """Test loading multiple services from YAML."""
        from taskflows.serialization import load_services_from_yaml, save_services_to_yaml

        yaml_content = """
services:
  - name: service-one
    start_command: python one.py
    description: First service

  - name: service-two
    start_command: python two.py
    description: Second service
    enabled: true
"""
        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False, mode="w") as f:
            f.write(yaml_content)
            path = Path(f.name)

        try:
            services = load_services_from_yaml(path)
            assert len(services) == 2
            assert services[0].name == "service-one"
            assert services[1].name == "service-two"
            assert services[1].enabled is True
        finally:
            path.unlink()

    def test_load_services_with_nested_types(self):
        """Test loading services with nested Venv and Schedule."""
        from taskflows.serialization import load_services_from_yaml

        yaml_content = """
services:
  - name: complex-service
    start_command: python app.py
    environment:
      type: Venv
      env_name: myenv
    start_schedule:
      type: Calendar
      schedule: Mon-Fri 09:00
      persistent: true
"""
        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False, mode="w") as f:
            f.write(yaml_content)
            path = Path(f.name)

        try:
            services = load_services_from_yaml(path)
            assert len(services) == 1
            assert services[0].name == "complex-service"
        finally:
            path.unlink()

    def test_save_and_load_roundtrip(self):
        """Test saving and loading services."""
        from taskflows.serialization import load_services_from_yaml, save_services_to_yaml

        services = [
            Service(name="svc-a", start_command="echo a"),
            Service(name="svc-b", start_command="echo b"),
        ]

        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as f:
            path = Path(f.name)

        try:
            save_services_to_yaml(services, path)
            loaded = load_services_from_yaml(path)
            assert len(loaded) == 2
            assert loaded[0].name == "svc-a"
            assert loaded[1].name == "svc-b"
        finally:
            path.unlink()

    def test_missing_services_key_raises_error(self):
        """Test that missing 'services' key raises ValueError."""
        from taskflows.serialization import load_services_from_yaml

        yaml_content = """
other_key:
  - name: something
"""
        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False, mode="w") as f:
            f.write(yaml_content)
            path = Path(f.name)

        try:
            with pytest.raises(ValueError, match="must contain a 'services' key"):
                load_services_from_yaml(path)
        finally:
            path.unlink()


class TestComprehensiveServiceYAML:
    """Tests for loading services with all possible parameters."""

    def test_load_service_with_all_parameters(self):
        """Test loading a service that has EVERY possible parameter set."""
        from taskflows.serialization import load_services_from_yaml

        # This YAML file contains EVERY possible Service parameter
        yaml_content = """
services:
  # Service with ALL possible parameters
  - name: comprehensive-test-service
    start_command: python /app/main.py
    stop_command: pkill -f main.py
    restart_command: python /app/restart.py

    # Environment - using Venv (not specifying custom_path as it requires file to exist)
    environment:
      type: Venv
      env_name: production-env

    # Schedules - using all schedule types
    start_schedule:
      type: Calendar
      schedule: Mon-Fri 09:00
      persistent: true
      accuracy: 1ms

    stop_schedule:
      type: Calendar
      schedule: Mon-Fri 18:00
      persistent: false
      accuracy: 1s

    restart_schedule:
      type: Periodic
      start_on: boot
      period: 3600
      relative_to: finish
      accuracy: 1ms

    # Basic parameters
    kill_signal: SIGINT
    restart_policy: on-failure
    timeout: 300
    env_file: /etc/taskflows/env.conf
    env:
      APP_ENV: production
      DEBUG: "false"
      LOG_LEVEL: INFO
    working_directory: /app
    enabled: true
    description: A comprehensive test service with all parameters

    # Startup requirements
    startup_requirements:
      - type: Memory
        amount: 1073741824
        constraint: ">="
        silent: false
      - type: CPUPressure
        max_percent: 80
        timespan: 5min
        silent: true

    # Service relations - all possible relation types
    start_before:
      - dependent-service-a
      - dependent-service-b
    start_after:
      - dependency-service-a
      - dependency-service-b
    wants:
      - optional-service-a
    upholds:
      - upheld-service-a
    requires:
      - required-service-a
    requisite:
      - prerequisite-service-a
    binds_to:
      - bound-service-a
    on_failure:
      - failure-handler-service
    on_success:
      - success-handler-service
    part_of:
      - parent-service-group
    propagate_stop_to:
      - downstream-service-a
    propagate_stop_from:
      - upstream-service-a
    conflicts:
      - conflicting-service-a

    # Cgroup configuration with all options
    cgroup_config:
      type: CgroupConfig
      # CPU limits
      cpu_quota: 50000
      cpu_period: 100000
      cpu_shares: 1024
      cpu_weight: 100
      cpuset_cpus: "0-3"
      # Memory limits
      memory_limit: 1073741824
      memory_high: 805306368
      memory_reservation: 536870912
      memory_low: 268435456
      memory_min: 134217728
      memory_swap_limit: 2147483648
      memory_swap_max: 1073741824
      memory_swappiness: 60
      # I/O limits
      blkio_weight: 500
      io_weight: 5000
      device_read_bps:
        /dev/sda: 10485760
      device_write_bps:
        /dev/sda: 5242880
      device_read_iops:
        /dev/sda: 100
      device_write_iops:
        /dev/sda: 50
      # Process limits
      pids_limit: 100
      # Security and isolation
      oom_score_adj: -500
      read_only_rootfs: false
      cap_add:
        - NET_ADMIN
        - SYS_TIME
      cap_drop:
        - MKNOD
      devices:
        - /dev/fuse
      device_cgroup_rules:
        - "c 10:200 rwm"
      # Timeouts
      timeout_start: 30
      timeout_stop: 10
      # Environment and execution
      environment:
        CGROUP_VAR: cgroup_value
      user: appuser
      group: appgroup
      working_dir: /app/work

  # Second service with DockerContainer environment
  - name: docker-service
    start_command: python /app/worker.py
    environment:
      type: DockerContainer
      image: python:3.11-slim
      name: worker-container
      network_mode: bridge
      environment:
        CONTAINER_VAR: container_value
      volumes:
        - type: Volume
          host_path: /data
          container_path: /app/data
          read_only: false
        - type: Volume
          host_path: /config
          container_path: /app/config
          read_only: true
    description: Service running in Docker container
    enabled: false
"""
        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False, mode="w") as f:
            f.write(yaml_content)
            path = Path(f.name)

        try:
            services = load_services_from_yaml(path)

            # Verify we loaded 2 services
            assert len(services) == 2

            # === Verify first service (comprehensive) ===
            svc = services[0]

            # Basic properties
            assert svc.name == "comprehensive-test-service"
            # Commands may be wrapped with environment command by __post_init__
            assert "python /app/main.py" in svc.start_command
            assert "pkill -f main.py" in svc.stop_command
            assert "python /app/restart.py" in svc.restart_command
            assert svc.kill_signal == "SIGINT"
            assert svc.restart_policy == "on-failure"
            assert svc.timeout == 300
            assert svc.env_file == "/etc/taskflows/env.conf"
            assert svc.env["APP_ENV"] == "production"
            assert svc.env["DEBUG"] == "false"
            assert svc.env["LOG_LEVEL"] == "INFO"
            assert str(svc.working_directory) == "/app"
            assert svc.enabled is True
            assert svc.description == "A comprehensive test service with all parameters"

            # Environment (Venv)
            assert svc.environment is not None
            assert isinstance(svc.environment, Venv)
            assert svc.environment.env_name == "production-env"

            # Schedules
            assert svc.start_schedule is not None
            from taskflows.schedule import Calendar, Periodic
            assert isinstance(svc.start_schedule, Calendar)
            assert svc.start_schedule.schedule == "Mon-Fri 09:00"
            assert svc.start_schedule.persistent is True

            assert svc.stop_schedule is not None
            assert isinstance(svc.stop_schedule, Calendar)
            assert svc.stop_schedule.schedule == "Mon-Fri 18:00"

            assert svc.restart_schedule is not None
            assert isinstance(svc.restart_schedule, Periodic)
            assert svc.restart_schedule.start_on == "boot"
            assert svc.restart_schedule.period == 3600
            assert svc.restart_schedule.relative_to == "finish"

            # Startup requirements
            assert svc.startup_requirements is not None
            assert len(svc.startup_requirements) == 2

            # Service relations
            assert svc.start_before == ["dependent-service-a", "dependent-service-b"]
            assert svc.start_after == ["dependency-service-a", "dependency-service-b"]
            assert svc.wants == ["optional-service-a"]
            assert svc.upholds == ["upheld-service-a"]
            assert svc.requires == ["required-service-a"]
            assert svc.requisite == ["prerequisite-service-a"]
            assert svc.binds_to == ["bound-service-a"]
            assert svc.on_failure == ["failure-handler-service"]
            assert svc.on_success == ["success-handler-service"]
            assert svc.part_of == ["parent-service-group"]
            assert svc.propagate_stop_to == ["downstream-service-a"]
            assert svc.propagate_stop_from == ["upstream-service-a"]
            assert svc.conflicts == ["conflicting-service-a"]

            # Cgroup config
            cg = svc.cgroup_config
            assert cg is not None
            assert cg.cpu_quota == 50000
            assert cg.cpu_period == 100000
            assert cg.cpu_shares == 1024
            assert cg.cpu_weight == 100
            assert cg.cpuset_cpus == "0-3"
            assert cg.memory_limit == 1073741824
            assert cg.memory_high == 805306368
            assert cg.memory_reservation == 536870912
            assert cg.memory_low == 268435456
            assert cg.memory_min == 134217728
            assert cg.memory_swap_limit == 2147483648
            assert cg.memory_swap_max == 1073741824
            assert cg.memory_swappiness == 60
            assert cg.blkio_weight == 500
            assert cg.io_weight == 5000
            assert cg.device_read_bps == {"/dev/sda": 10485760}
            assert cg.device_write_bps == {"/dev/sda": 5242880}
            assert cg.device_read_iops == {"/dev/sda": 100}
            assert cg.device_write_iops == {"/dev/sda": 50}
            assert cg.pids_limit == 100
            assert cg.oom_score_adj == -500
            assert cg.read_only_rootfs is False
            assert cg.cap_add == ["NET_ADMIN", "SYS_TIME"]
            assert cg.cap_drop == ["MKNOD"]
            assert cg.devices == ["/dev/fuse"]
            assert cg.device_cgroup_rules == ["c 10:200 rwm"]
            assert cg.timeout_start == 30
            assert cg.timeout_stop == 10
            assert cg.environment == {"CGROUP_VAR": "cgroup_value"}
            assert cg.user == "appuser"
            assert cg.group == "appgroup"
            assert cg.working_dir == "/app/work"

            # === Verify second service (Docker) ===
            docker_svc = services[1]
            assert docker_svc.name == "docker-service"
            assert docker_svc.environment is not None
            assert isinstance(docker_svc.environment, DockerContainer)
            assert docker_svc.environment.image == "python:3.11-slim"
            assert docker_svc.environment.name == "worker-container"
            assert docker_svc.environment.network_mode == "bridge"
            # Note: __post_init__ may add additional volumes, so check >= 2
            assert len(docker_svc.environment.volumes) >= 2

        finally:
            path.unlink()

    def test_service_with_multiple_schedules(self):
        """Test loading a service with multiple schedules (list of schedules)."""
        from taskflows.serialization import load_services_from_yaml

        yaml_content = """
services:
  - name: multi-schedule-service
    start_command: python job.py
    start_schedule:
      - type: Calendar
        schedule: Mon 09:00
        persistent: true
      - type: Calendar
        schedule: Wed 09:00
        persistent: true
      - type: Calendar
        schedule: Fri 09:00
        persistent: true
    description: Service with multiple schedules
"""
        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False, mode="w") as f:
            f.write(yaml_content)
            path = Path(f.name)

        try:
            services = load_services_from_yaml(path)
            assert len(services) == 1
            svc = services[0]

            # Multiple schedules should be preserved as a list
            assert svc.start_schedule is not None
            assert isinstance(svc.start_schedule, list)
            assert len(svc.start_schedule) == 3

        finally:
            path.unlink()


class TestTypeInference:
    """Tests for automatic type inference (no explicit 'type' field needed)."""

    def test_infer_venv_from_env_name(self):
        """Test that Venv is inferred from env_name key."""
        from taskflows.serialization import load_services_from_yaml

        yaml_content = """
services:
  - name: venv-service
    start_command: python app.py
    environment:
      env_name: myenv
"""
        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False, mode="w") as f:
            f.write(yaml_content)
            path = Path(f.name)

        try:
            services = load_services_from_yaml(path)
            assert len(services) == 1
            assert isinstance(services[0].environment, Venv)
            assert services[0].environment.env_name == "myenv"
        finally:
            path.unlink()

    def test_infer_docker_from_image(self):
        """Test that DockerContainer is inferred from image key."""
        from taskflows.serialization import load_services_from_yaml

        yaml_content = """
services:
  - name: docker-service
    start_command: python app.py
    environment:
      image: python:3.11
      name: my-container
"""
        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False, mode="w") as f:
            f.write(yaml_content)
            path = Path(f.name)

        try:
            services = load_services_from_yaml(path)
            assert len(services) == 1
            assert isinstance(services[0].environment, DockerContainer)
            assert services[0].environment.image == "python:3.11"
        finally:
            path.unlink()

    def test_infer_calendar_from_schedule(self):
        """Test that Calendar is inferred from schedule key."""
        from taskflows.serialization import load_services_from_yaml
        from taskflows.schedule import Calendar

        yaml_content = """
services:
  - name: scheduled-service
    start_command: python job.py
    start_schedule:
      schedule: Mon-Fri 09:00
      persistent: true
"""
        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False, mode="w") as f:
            f.write(yaml_content)
            path = Path(f.name)

        try:
            services = load_services_from_yaml(path)
            assert len(services) == 1
            assert isinstance(services[0].start_schedule, Calendar)
            assert services[0].start_schedule.schedule == "Mon-Fri 09:00"
        finally:
            path.unlink()

    def test_infer_calendar_from_string(self):
        """Test that a string schedule becomes a Calendar."""
        from taskflows.serialization import load_services_from_yaml
        from taskflows.schedule import Calendar

        yaml_content = """
services:
  - name: simple-scheduled
    start_command: python job.py
    start_schedule: "Mon-Sun 02:00 America/New_York"
"""
        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False, mode="w") as f:
            f.write(yaml_content)
            path = Path(f.name)

        try:
            services = load_services_from_yaml(path)
            assert len(services) == 1
            assert isinstance(services[0].start_schedule, Calendar)
            assert services[0].start_schedule.schedule == "Mon-Sun 02:00 America/New_York"
        finally:
            path.unlink()

    def test_infer_periodic_from_period(self):
        """Test that Periodic is inferred from period key."""
        from taskflows.serialization import load_services_from_yaml
        from taskflows.schedule import Periodic

        yaml_content = """
services:
  - name: periodic-service
    start_command: python job.py
    restart_schedule:
      start_on: boot
      period: 3600
      relative_to: finish
"""
        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False, mode="w") as f:
            f.write(yaml_content)
            path = Path(f.name)

        try:
            services = load_services_from_yaml(path)
            assert len(services) == 1
            assert isinstance(services[0].restart_schedule, Periodic)
            assert services[0].restart_schedule.period == 3600
        finally:
            path.unlink()

    def test_infer_cgroup_config(self):
        """Test that CgroupConfig is inferred from cgroup keys."""
        from taskflows.serialization import load_services_from_yaml

        yaml_content = """
services:
  - name: limited-service
    start_command: python app.py
    cgroup_config:
      memory_limit: 1073741824
      cpu_quota: 50000
      pids_limit: 100
"""
        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False, mode="w") as f:
            f.write(yaml_content)
            path = Path(f.name)

        try:
            services = load_services_from_yaml(path)
            assert len(services) == 1
            cg = services[0].cgroup_config
            assert cg is not None
            assert cg.memory_limit == 1073741824
            assert cg.cpu_quota == 50000
            assert cg.pids_limit == 100
        finally:
            path.unlink()

    def test_infer_volume_in_docker(self):
        """Test that Volume is inferred within DockerContainer volumes."""
        from taskflows.serialization import load_services_from_yaml

        yaml_content = """
services:
  - name: docker-with-volumes
    start_command: python app.py
    environment:
      image: python:3.11
      volumes:
        - host_path: /data
          container_path: /app/data
          read_only: false
        - host_path: /config
          container_path: /app/config
          read_only: true
"""
        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False, mode="w") as f:
            f.write(yaml_content)
            path = Path(f.name)

        try:
            services = load_services_from_yaml(path)
            assert len(services) == 1
            env = services[0].environment
            assert isinstance(env, DockerContainer)
            # Check original volumes (may have additional ones added by __post_init__)
            volume_paths = [(v.host_path, v.container_path) for v in env.volumes]
            assert ("/data", "/app/data") in volume_paths
            assert ("/config", "/app/config") in volume_paths
        finally:
            path.unlink()

    def test_volume_string_format(self):
        """Test that volumes can be specified as strings like '/host:/container'."""
        from taskflows.serialization import load_services_from_yaml
        from taskflows.docker import Volume

        yaml_content = """
services:
  - name: docker-string-volumes
    start_command: python app.py
    environment:
      image: python:3.11
      volumes:
        - /data:/app/data
        - /config:/app/config:ro
        - /logs:/app/logs:rw
"""
        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False, mode="w") as f:
            f.write(yaml_content)
            path = Path(f.name)

        try:
            services = load_services_from_yaml(path)
            assert len(services) == 1
            env = services[0].environment
            assert isinstance(env, DockerContainer)

            # Find our volumes (there may be additional ones from __post_init__)
            volume_map = {(v.host_path, v.container_path): v for v in env.volumes}

            # Check /data:/app/data (default read_only=False)
            assert ("/data", "/app/data") in volume_map
            assert volume_map[("/data", "/app/data")].read_only is False

            # Check /config:/app/config:ro (read_only=True)
            assert ("/config", "/app/config") in volume_map
            assert volume_map[("/config", "/app/config")].read_only is True

            # Check /logs:/app/logs:rw (explicit read_only=False)
            assert ("/logs", "/app/logs") in volume_map
            assert volume_map[("/logs", "/app/logs")].read_only is False
        finally:
            path.unlink()

    def test_mixed_volume_formats(self):
        """Test mixing string and dict volume formats."""
        from taskflows.serialization import load_services_from_yaml

        yaml_content = """
services:
  - name: mixed-volumes
    start_command: python app.py
    environment:
      image: python:3.11
      volumes:
        - /data:/app/data
        - host_path: /config
          container_path: /app/config
          read_only: true
"""
        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False, mode="w") as f:
            f.write(yaml_content)
            path = Path(f.name)

        try:
            services = load_services_from_yaml(path)
            env = services[0].environment
            volume_paths = [(v.host_path, v.container_path) for v in env.volumes]
            assert ("/data", "/app/data") in volume_paths
            assert ("/config", "/app/config") in volume_paths
        finally:
            path.unlink()

    def test_restart_policy_as_string(self):
        """Test that restart_policy as a string works without type field."""
        from taskflows.serialization import load_services_from_yaml

        yaml_content = """
services:
  - name: simple-service
    start_command: python app.py
    restart_policy: on-failure
"""
        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False, mode="w") as f:
            f.write(yaml_content)
            path = Path(f.name)

        try:
            services = load_services_from_yaml(path)
            assert len(services) == 1
            assert services[0].restart_policy == "on-failure"
        finally:
            path.unlink()

    def test_restart_policy_as_dict(self):
        """Test that RestartPolicy is inferred from dict with condition."""
        from taskflows.serialization import load_services_from_yaml
        from taskflows.service import RestartPolicy

        yaml_content = """
services:
  - name: restart-service
    start_command: python app.py
    restart_policy:
      condition: on-failure
      delay: 10
      max_attempts: 5
"""
        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False, mode="w") as f:
            f.write(yaml_content)
            path = Path(f.name)

        try:
            services = load_services_from_yaml(path)
            assert len(services) == 1
            rp = services[0].restart_policy
            assert isinstance(rp, RestartPolicy)
            assert rp.condition == "on-failure"
            assert rp.delay == 10
            assert rp.max_attempts == 5
        finally:
            path.unlink()

    def test_mixed_explicit_and_inferred_types(self):
        """Test mixing explicit type fields with inferred types."""
        from taskflows.serialization import load_services_from_yaml
        from taskflows.schedule import Calendar, Periodic

        yaml_content = """
services:
  - name: mixed-service
    start_command: python app.py
    # Inferred from env_name
    environment:
      env_name: myenv
    # Explicit type
    start_schedule:
      type: Calendar
      schedule: Mon-Fri 09:00
    # Inferred from period
    restart_schedule:
      start_on: boot
      period: 300
      relative_to: finish
"""
        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False, mode="w") as f:
            f.write(yaml_content)
            path = Path(f.name)

        try:
            services = load_services_from_yaml(path)
            assert len(services) == 1
            svc = services[0]
            assert isinstance(svc.environment, Venv)
            assert isinstance(svc.start_schedule, Calendar)
            assert isinstance(svc.restart_schedule, Periodic)
        finally:
            path.unlink()


class TestServiceRegistrySerialization:
    """Tests for ServiceRegistry serialization."""

    def test_registry_to_yaml(self):
        """Test serializing ServiceRegistry to YAML."""
        from taskflows.service import ServiceRegistry

        registry = ServiceRegistry(
            Service(name="svc-a", start_command="echo a"),
            Service(name="svc-b", start_command="echo b"),
        )

        yaml_str = registry.to_yaml()
        assert "services:" in yaml_str
        assert "svc-a" in yaml_str
        assert "svc-b" in yaml_str
        # type field should not be present at service level
        assert "type: Service" not in yaml_str

    def test_registry_to_json(self):
        """Test serializing ServiceRegistry to JSON."""
        import json
        from taskflows.service import ServiceRegistry

        registry = ServiceRegistry(
            Service(name="svc-a", start_command="echo a"),
        )

        json_str = registry.to_json()
        data = json.loads(json_str)
        assert "services" in data
        assert len(data["services"]) == 1
        assert data["services"][0]["name"] == "svc-a"

    def test_registry_roundtrip_yaml(self):
        """Test ServiceRegistry YAML roundtrip."""
        from taskflows.service import ServiceRegistry

        original = ServiceRegistry(
            Service(name="web", start_command="python web.py", description="Web server"),
            Service(name="worker", start_command="python worker.py", enabled=True),
        )

        yaml_str = original.to_yaml()
        restored = ServiceRegistry.from_yaml(yaml_str)

        assert len(restored) == 2
        assert "web" in restored
        assert "worker" in restored
        assert restored["web"].description == "Web server"
        assert restored["worker"].enabled is True

    def test_registry_roundtrip_json(self):
        """Test ServiceRegistry JSON roundtrip."""
        from taskflows.service import ServiceRegistry

        original = ServiceRegistry(
            Service(name="api", start_command="uvicorn app:main"),
        )

        json_str = original.to_json()
        restored = ServiceRegistry.from_json(json_str)

        assert len(restored) == 1
        assert "api" in restored

    def test_registry_to_file_yaml(self):
        """Test saving ServiceRegistry to YAML file."""
        from taskflows.service import ServiceRegistry

        registry = ServiceRegistry(
            Service(name="file-svc", start_command="echo test"),
        )

        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as f:
            path = Path(f.name)

        try:
            registry.to_file(path)
            restored = ServiceRegistry.from_file(path)
            assert len(restored) == 1
            assert "file-svc" in restored
        finally:
            path.unlink()

    def test_registry_to_file_json(self):
        """Test saving ServiceRegistry to JSON file."""
        from taskflows.service import ServiceRegistry

        registry = ServiceRegistry(
            Service(name="json-svc", start_command="echo json"),
        )

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = Path(f.name)

        try:
            registry.to_file(path)
            restored = ServiceRegistry.from_file(path)
            assert len(restored) == 1
            assert "json-svc" in restored
        finally:
            path.unlink()

    def test_registry_with_complex_services(self):
        """Test ServiceRegistry with services that have environments and schedules."""
        from taskflows.service import ServiceRegistry
        from taskflows.schedule import Calendar

        registry = ServiceRegistry(
            Service(
                name="complex-svc",
                start_command="python app.py",
                environment=Venv(env_name="myenv"),
                start_schedule=Calendar(schedule="Mon-Fri 09:00"),
                description="A complex service",
            ),
        )

        yaml_str = registry.to_yaml()
        restored = ServiceRegistry.from_yaml(yaml_str)

        assert len(restored) == 1
        svc = restored["complex-svc"]
        assert svc.description == "A complex service"
        # Environment and schedule should be properly deserialized
        assert isinstance(svc.environment, Venv)
        assert isinstance(svc.start_schedule, Calendar)


class TestHumanReadableParsing:
    """Tests for human-readable memory sizes and time durations."""

    def test_parse_memory_size_integers(self):
        """Test that integers pass through as bytes."""
        from taskflows.serialization import parse_memory_size

        assert parse_memory_size(1024) == 1024
        assert parse_memory_size(0) == 0
        assert parse_memory_size(1073741824) == 1073741824

    def test_parse_memory_size_bytes(self):
        """Test parsing byte values."""
        from taskflows.serialization import parse_memory_size

        assert parse_memory_size("1024") == 1024
        assert parse_memory_size("1024B") == 1024
        assert parse_memory_size("1024b") == 1024

    def test_parse_memory_size_kilobytes(self):
        """Test parsing kilobyte values."""
        from taskflows.serialization import parse_memory_size

        assert parse_memory_size("1K") == 1024
        assert parse_memory_size("1KB") == 1024
        assert parse_memory_size("1kb") == 1024
        assert parse_memory_size("512k") == 512 * 1024

    def test_parse_memory_size_megabytes(self):
        """Test parsing megabyte values."""
        from taskflows.serialization import parse_memory_size

        assert parse_memory_size("1M") == 1024 ** 2
        assert parse_memory_size("1MB") == 1024 ** 2
        assert parse_memory_size("512MB") == 512 * 1024 ** 2
        assert parse_memory_size("512 MB") == 512 * 1024 ** 2

    def test_parse_memory_size_gigabytes(self):
        """Test parsing gigabyte values."""
        from taskflows.serialization import parse_memory_size

        assert parse_memory_size("1G") == 1024 ** 3
        assert parse_memory_size("1GB") == 1024 ** 3
        assert parse_memory_size("2gb") == 2 * 1024 ** 3
        assert parse_memory_size("1.5G") == int(1.5 * 1024 ** 3)

    def test_parse_memory_size_terabytes(self):
        """Test parsing terabyte values."""
        from taskflows.serialization import parse_memory_size

        assert parse_memory_size("1T") == 1024 ** 4
        assert parse_memory_size("1TB") == 1024 ** 4

    def test_parse_memory_size_with_spaces(self):
        """Test parsing with whitespace."""
        from taskflows.serialization import parse_memory_size

        assert parse_memory_size("  1GB  ") == 1024 ** 3
        assert parse_memory_size("512 MB") == 512 * 1024 ** 2

    def test_parse_memory_size_invalid(self):
        """Test that invalid formats raise ValueError."""
        from taskflows.serialization import parse_memory_size

        with pytest.raises(ValueError, match="Unknown memory unit"):
            parse_memory_size("1XB")

        with pytest.raises(ValueError, match="Invalid memory size"):
            parse_memory_size("abc")

        with pytest.raises(ValueError, match="Cannot parse memory size"):
            parse_memory_size([1, 2, 3])

    def test_parse_time_duration_integers(self):
        """Test that integers pass through as seconds."""
        from taskflows.serialization import parse_time_duration

        assert parse_time_duration(300) == 300
        assert parse_time_duration(0) == 0
        assert parse_time_duration(3600) == 3600

    def test_parse_time_duration_seconds(self):
        """Test parsing second values."""
        from taskflows.serialization import parse_time_duration

        assert parse_time_duration("300") == 300
        assert parse_time_duration("30s") == 30
        assert parse_time_duration("30sec") == 30
        assert parse_time_duration("30second") == 30
        assert parse_time_duration("30seconds") == 30

    def test_parse_time_duration_minutes(self):
        """Test parsing minute values."""
        from taskflows.serialization import parse_time_duration

        assert parse_time_duration("5m") == 300
        assert parse_time_duration("5min") == 300
        assert parse_time_duration("5minute") == 300
        assert parse_time_duration("5minutes") == 300
        assert parse_time_duration("1.5m") == 90

    def test_parse_time_duration_hours(self):
        """Test parsing hour values."""
        from taskflows.serialization import parse_time_duration

        assert parse_time_duration("1h") == 3600
        assert parse_time_duration("1hr") == 3600
        assert parse_time_duration("1hour") == 3600
        assert parse_time_duration("2hours") == 7200
        assert parse_time_duration("1.5h") == 5400

    def test_parse_time_duration_days(self):
        """Test parsing day values."""
        from taskflows.serialization import parse_time_duration

        assert parse_time_duration("1d") == 86400
        assert parse_time_duration("1day") == 86400
        assert parse_time_duration("7days") == 604800

    def test_parse_time_duration_weeks(self):
        """Test parsing week values."""
        from taskflows.serialization import parse_time_duration

        assert parse_time_duration("1w") == 604800
        assert parse_time_duration("1week") == 604800
        assert parse_time_duration("2weeks") == 2 * 604800

    def test_parse_time_duration_with_spaces(self):
        """Test parsing with whitespace."""
        from taskflows.serialization import parse_time_duration

        assert parse_time_duration("  5m  ") == 300
        assert parse_time_duration("1 hour") == 3600

    def test_parse_time_duration_invalid(self):
        """Test that invalid formats raise ValueError."""
        from taskflows.serialization import parse_time_duration

        with pytest.raises(ValueError, match="Unknown time unit"):
            parse_time_duration("5x")

        with pytest.raises(ValueError, match="Invalid time duration"):
            parse_time_duration("abc")

        with pytest.raises(ValueError, match="Cannot parse time duration"):
            parse_time_duration([1, 2, 3])

    def test_yaml_with_human_readable_memory(self):
        """Test loading YAML with human-readable memory sizes."""
        from taskflows.serialization import load_services_from_yaml

        yaml_content = """
services:
  - name: memory-test
    start_command: python app.py
    cgroup_config:
      memory_limit: 2GB
      memory_high: 1.5GB
      memory_low: 512MB
"""
        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False, mode="w") as f:
            f.write(yaml_content)
            path = Path(f.name)

        try:
            services = load_services_from_yaml(path)
            assert len(services) == 1
            cg = services[0].cgroup_config
            assert cg is not None
            assert cg.memory_limit == 2 * 1024 ** 3  # 2GB in bytes
            assert cg.memory_high == int(1.5 * 1024 ** 3)  # 1.5GB in bytes
            assert cg.memory_low == 512 * 1024 ** 2  # 512MB in bytes
        finally:
            path.unlink()

    def test_yaml_with_human_readable_time(self):
        """Test loading YAML with human-readable time durations."""
        from taskflows.serialization import load_services_from_yaml
        from taskflows.schedule import Periodic

        yaml_content = """
services:
  - name: time-test
    start_command: python app.py
    timeout: 5m
    restart_schedule:
      period: 1h
      start_on: boot
      relative_to: finish
"""
        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False, mode="w") as f:
            f.write(yaml_content)
            path = Path(f.name)

        try:
            services = load_services_from_yaml(path)
            assert len(services) == 1
            svc = services[0]
            assert svc.timeout == 300  # 5 minutes in seconds
            assert isinstance(svc.restart_schedule, Periodic)
            assert svc.restart_schedule.period == 3600  # 1 hour in seconds
        finally:
            path.unlink()

    def test_yaml_with_restart_policy_delay_and_window(self):
        """Test loading YAML with human-readable delay and window in RestartPolicy."""
        from taskflows.serialization import load_services_from_yaml
        from taskflows.service import RestartPolicy

        yaml_content = """
services:
  - name: restart-test
    start_command: python app.py
    restart_policy:
      condition: on-failure
      delay: 30s
      window: 5m
      max_attempts: 5
"""
        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False, mode="w") as f:
            f.write(yaml_content)
            path = Path(f.name)

        try:
            services = load_services_from_yaml(path)
            assert len(services) == 1
            rp = services[0].restart_policy
            assert isinstance(rp, RestartPolicy)
            assert rp.delay == 30  # 30 seconds
            assert rp.window == 300  # 5 minutes in seconds
        finally:
            path.unlink()

    def test_yaml_mixed_formats(self):
        """Test mixing human-readable and numeric formats."""
        from taskflows.serialization import load_services_from_yaml

        yaml_content = """
services:
  - name: mixed-test
    start_command: python app.py
    timeout: 300
    cgroup_config:
      memory_limit: 1GB
      cpu_quota: 50000
      timeout_start: 30s
      timeout_stop: 10
"""
        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False, mode="w") as f:
            f.write(yaml_content)
            path = Path(f.name)

        try:
            services = load_services_from_yaml(path)
            assert len(services) == 1
            svc = services[0]
            assert svc.timeout == 300  # Already numeric
            cg = svc.cgroup_config
            assert cg.memory_limit == 1024 ** 3  # 1GB
            assert cg.cpu_quota == 50000  # Numeric, not a memory/time field
            assert cg.timeout_start == 30  # 30s parsed
            assert cg.timeout_stop == 10  # Already numeric
        finally:
            path.unlink()

    def test_memory_constraint_with_human_readable(self):
        """Test Memory constraint with human-readable amount."""
        from taskflows.serialization import load_services_from_yaml
        from taskflows.constraints import Memory

        yaml_content = """
services:
  - name: constraint-test
    start_command: python app.py
    startup_requirements:
      - amount: 8GB
        constraint: ">="
"""
        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False, mode="w") as f:
            f.write(yaml_content)
            path = Path(f.name)

        try:
            services = load_services_from_yaml(path)
            assert len(services) == 1
            reqs = services[0].startup_requirements
            assert len(reqs) == 1
            assert isinstance(reqs[0], Memory)
            assert reqs[0].amount == 8 * 1024 ** 3  # 8GB in bytes
        finally:
            path.unlink()
