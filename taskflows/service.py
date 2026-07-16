import os
import stat
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from pprint import pformat
from typing import Literal, Optional, Union

from pydantic.dataclasses import dataclass as pdataclass

# Re-exported for backwards compatibility — these moved to taskflows.common,
# taskflows.docker, and taskflows.systemd but are widely imported from here.
from .common import (
    _SYSTEMD_FILE_PREFIX,
    extract_service_name,  # noqa: F401, E402
    load_service_files,
    logger,
    secure_write_text,
    services_data_dir,
    systemd_dir,
)
from .constraints import (
    CgroupConfig,
    HardwareConstraint,
    SystemLoadConstraint,
    systemd_directive_name,
)
from .docker import (  # noqa: F401, E402
    DockerContainer,
    DockerImage,
    Volume,
    delete_docker_container,
    get_docker_client,
)
from .environments import Venv
from .exec import PickledFunction
from .schedule import Schedule
from .systemd.dbus import (  # noqa: F401, E402
    escape_path,
    reload_unit_files,
    session_dbus,
    systemd_manager,
)
from .systemd.units import (  # noqa: F401, E402
    disable_units,
    enable_units,
    get_schedule_info,
    get_unit_file_states,
    get_unit_files,
    get_units,
    is_start_service,
    remove_units,
    restart_units,
    service_logs,
    start_units,
    stop_units,
)

ServiceT = Union[str, "Service"]
ServicesT = ServiceT | Sequence[ServiceT]


class ServiceRegistry:
    """Thread-safe registry for managing services.

    FIXED: Added RLock to prevent concurrent modification issues when
    multiple threads access or modify the service registry.
    """

    def __init__(self, *services):
        self._services = {s.name: s for s in services}
        self._lock = threading.RLock()  # Reentrant lock for thread safety

    def add(self, *services):
        """Add services to the registry (thread-safe)."""
        with self._lock:
            for s in services:
                self._services[s.name] = s

    @property
    def names(self):
        """Get list of service names (thread-safe)."""
        with self._lock:
            return list(self._services.keys())

    @property
    def services(self):
        """Get list of services (thread-safe)."""
        with self._lock:
            return list(self._services.values())

    async def create(self):
        """Create all services (operations are atomic per service)."""
        # Get snapshot of services to avoid holding lock during long operations
        services_snapshot = self.services
        for s in services_snapshot:
            await s.create()

    async def start(self):
        """Start all services (operations are atomic per service)."""
        services_snapshot = self.services
        for s in services_snapshot:
            await s.start()

    async def stop(self):
        """Stop all services (operations are atomic per service)."""
        services_snapshot = self.services
        for s in services_snapshot:
            await s.stop()

    async def enable(self):
        """Enable all services (operations are atomic per service)."""
        services_snapshot = self.services
        for s in services_snapshot:
            await s.enable()

    async def disable(self):
        """Disable all services (operations are atomic per service)."""
        services_snapshot = self.services
        for s in services_snapshot:
            await s.disable()

    async def restart(self):
        """Restart all services (operations are atomic per service)."""
        services_snapshot = self.services
        for s in services_snapshot:
            await s.restart()

    async def remove(self):
        """Remove all services (operations are atomic per service)."""
        services_snapshot = self.services
        for s in services_snapshot:
            await s.remove()

    def __getitem__(self, name):
        """Get service by name (thread-safe)."""
        with self._lock:
            return self._services[name]

    def __setitem__(self, name, value):
        """Set service by name (thread-safe)."""
        with self._lock:
            self._services[name] = value

    def __contains__(self, name):
        """Check if service exists (thread-safe)."""
        with self._lock:
            return name in self._services

    def __iter__(self):
        """Iterate over services (thread-safe snapshot)."""
        return iter(self.services)

    def __len__(self):
        """Get number of services (thread-safe)."""
        with self._lock:
            return len(self._services)

    def __repr__(self):
        """String representation (thread-safe)."""
        with self._lock:
            return repr(self._services)

    def __str__(self):
        """String representation (thread-safe)."""
        with self._lock:
            return str(self._services)

    def __bool__(self):
        """Check if registry is non-empty (thread-safe)."""
        with self._lock:
            return bool(self._services)

    # Serialization methods
    def to_dict(self, include_none: bool = False) -> dict:
        """Convert registry to a dictionary representation."""
        from taskflows.serialization import to_dict as serialize_to_dict

        with self._lock:
            return {
                "services": [serialize_to_dict(s, include_none) for s in self._services.values()]
            }

    def to_json(self, indent: int = 2, include_none: bool = False) -> str:
        """Serialize registry to JSON string."""
        import json

        data = self.to_dict(include_none)
        # Remove type field from services since we know they're services
        for s in data["services"]:
            s.pop("type", None)
        return json.dumps(data, indent=indent, default=str)

    def to_yaml(self, include_none: bool = False) -> str:
        """Serialize registry to YAML string."""
        import yaml

        data = self.to_dict(include_none)
        # Remove type field from services since we know they're services
        for s in data["services"]:
            s.pop("type", None)
        return yaml.dump(data, default_flow_style=False, allow_unicode=True, sort_keys=False)

    def to_file(
        self,
        path: str | Path,
        format: Literal["json", "yaml"] | None = None,
        include_none: bool = False,
    ) -> None:
        """Save registry to a file."""
        path = Path(path)
        if format is None:
            format = "yaml" if path.suffix in (".yaml", ".yml") else "json"

        if format == "yaml":
            content = self.to_yaml(include_none)
        else:
            content = self.to_json(include_none=include_none)
        secure_write_text(path, content)

    @classmethod
    def from_dict(cls, data: dict) -> "ServiceRegistry":
        """Create registry from a dictionary representation."""
        from taskflows.serialization import from_dict as deserialize_from_dict

        services_data = data.get("services", [])
        services = [deserialize_from_dict(s, Service) for s in services_data]
        return cls(*services)

    @classmethod
    def from_json(cls, data: str) -> "ServiceRegistry":
        """Deserialize registry from JSON string."""
        import json

        return cls.from_dict(json.loads(data))

    @classmethod
    def from_yaml(cls, data: str) -> "ServiceRegistry":
        """Deserialize registry from YAML string."""
        import yaml

        return cls.from_dict(yaml.safe_load(data))

    @classmethod
    def from_file(
        cls, path: str | Path, format: Literal["json", "yaml"] | None = None
    ) -> "ServiceRegistry":
        """Load registry from a file."""
        path = Path(path)
        if format is None:
            format = "yaml" if path.suffix in (".yaml", ".yml") else "json"

        content = path.read_text()
        if format == "yaml":
            return cls.from_yaml(content)
        else:
            return cls.from_json(content)


@pdataclass
class RestartPolicy:
    """Service restart policy."""

    # condition where the service should be restarted.
    condition: Literal[
        "always",
        "on-success",
        "on-failure",
        "on-abnormal",
        "on-abort",
        "on-watchdog",
        "no",
    ]
    # waiting time before each retry (seconds)
    delay: int | None = None
    # hard ceiling on how many *failed* restarts are allowed within `window` before the task is left in `FAILED` state
    max_attempts: int | None = None
    # sliding time window used to decide whether an attempt counts as “failed”. If the task stays up for the full `window`, the counter resets.
    window: int | None = None

    @property
    def unit_entries(self) -> set[str]:
        entries = set()
        # 0 allows unlimited attempts.
        window = self.window or 0
        entries.add(f"StartLimitIntervalSec={window}")
        if self.max_attempts:
            entries.add(f"StartLimitBurst={self.max_attempts}")
        elif window == 0:
            # When window is 0, we need to explicitly set burst to 0 to disable rate limiting
            entries.add("StartLimitBurst=0")
        return entries

    @property
    def service_entries(self) -> set[str]:
        entries = {f"Restart={self.condition}"}
        if self.delay:
            entries.add(f"RestartSec={self.delay}")
        return entries


@pdataclass
class Watchdog:
    """systemd watchdog (hang detection) for a service.

    Emits Type=notify + WatchdogSec=, so the process must send READY=1 on
    startup and WATCHDOG=1 pings at least every `interval_seconds` — use
    taskflows.notify (async_entrypoint arms the pinger automatically). If
    pings stop (hung process), systemd kills the unit; with restart_on_hang
    it is restarted automatically.

    Not supported for DockerContainer environments: NOTIFY_SOCKET does not
    cross the container boundary.
    """

    # systemd kills the service if no ping arrives within this many seconds.
    interval_seconds: int = 30
    # restart the service after a watchdog kill (Restart=on-watchdog).
    restart_on_hang: bool = True
    # allow pings from any process in the cgroup (needed when a runner like
    # `conda run` interposes a parent process between systemd and the app).
    notify_access: Literal["main", "all"] = "all"

    @property
    def service_entries(self) -> set[str]:
        return {
            "Type=notify",
            f"NotifyAccess={self.notify_access}",
            f"WatchdogSec={self.interval_seconds}",
        }


@dataclass
class Service:
    """A service to run a command on a specified schedule."""

    # name used to identify the service.
    name: str | None = None
    # command to execute.
    start_command: str | Callable[[], None] | None = None
    # command to execute to stop the service command.
    stop_command: str | None = None
    # environment where commands should be executed.
    environment: Venv | DockerContainer = None
    # when the service should be started.
    start_schedule: Schedule | Sequence[Schedule] | None = None
    # when the service should be stopped.
    stop_schedule: Schedule | Sequence[Schedule] | None = None
    # when the service should be restarted.
    restart_schedule: Schedule | Sequence[Schedule] | None = None
    # command to execute when the service is restarted.
    restart_command: str | None = None
    # signal used to stop the service.
    kill_signal: str = "SIGTERM"
    restart_policy: str | RestartPolicy | None = "no"
    # systemd watchdog (hang detection): the service must send sd_notify pings
    # (see taskflows.notify); systemd restarts it if they stop. Not supported
    # with DockerContainer environments.
    watchdog: Optional["Watchdog"] = None
    startup_requirements: Sequence[HardwareConstraint | SystemLoadConstraint] = None
    # Specifies a timeout (in seconds) that starts running when the queued job is actually started.
    # If limit is reached, the job will be cancelled, the unit however will not change state or even enter the "failed" mode.
    timeout: int | None = None
    # path to a file with environment variables for the service.
    # TODO LoadCredential, LoadCredentialEncrypted, SetCredentialEncrypted
    # TODO forward to docker container.
    env_file: str | None = None
    # environment variables for the service.
    env: dict[str, str] | None = None
    # working directory for the service.
    working_directory: str | Path | None = None
    # enable the service to start automatically on boot.
    enabled: bool = False
    ## SERVICE RELATIONS ##
    # make sure this service is fully started before begining startup of these services.
    start_before: ServicesT | None = None
    # make sure these services are fully started before begining startup of this service.
    start_after: ServicesT | None = None
    # Units listed in this option will be started simultaneously at the same time as the configuring unit is.
    # If the listed units fail to start, this unit will still be started anyway. Multiple units may be specified.
    wants: ServicesT | None = None
    # Configures dependencies similar to `Wants`, but as long as this unit is up,
    # all units listed in `Upholds` are started whenever found to be inactive or failed, and no job is queued for them.
    # While a Wants= dependency on another unit has a one-time effect when this units started,
    # a `Upholds` dependency on it has a continuous effect, constantly restarting the unit if necessary.
    # This is an alternative to the Restart= setting of service units, to ensure they are kept running whatever happens.
    upholds: ServicesT | None = None
    # Units listed in this option will be started simultaneously at the same time as the configuring unit is.
    # If one of the other units fails to activate, and an ordering dependency `After` on the failing unit is set, this unit will not be started.
    # This unit will be stopped (or restarted) if one of the other units is explicitly stopped (or restarted) via systemctl command (not just normal exit on process finished).
    requires: ServicesT | None = None
    # Units listed in this option will be started simultaneously at the same time as the configuring unit is.
    # If the units listed here are not started already, they will not be started and the starting of this unit will fail immediately.
    # Note: this setting should usually be combined with `After`, to ensure this unit is not started before the other unit.
    requisite: ServicesT | None = None
    # Same as `Requires`, but in order for this unit will be stopped (or restarted), if a listed unit is stopped (or restarted), explicitly or not.
    binds_to: ServicesT | None = None
    # one or more units that are activated when this unit enters the "failed" state.
    # A service unit using Restart= enters the failed state only after the start limits are reached.
    on_failure: ServicesT | None = None
    # one or more units that are activated when this unit enters the "inactive" state.
    on_success: ServicesT | None = None
    # When systemd stops or restarts the units listed here, the action is propagated to this unit.
    # Note that this is a one-way dependency — changes to this unit do not affect the listed units.
    part_of: ServicesT | None = None
    # A space-separated list of one or more units to which stop requests from this unit shall be propagated to,
    # or units from which stop requests shall be propagated to this unit, respectively.
    # Issuing a stop request on a unit will automatically also enqueue stop requests on all units that are linked to it using these two settings.
    propagate_stop_to: ServicesT | None = None
    propagate_stop_from: ServicesT | None = None
    # other units where starting the former will stop the latter and vice versa.
    conflicts: ServicesT | None = None
    # description of this service.
    description: str | None = None
    # cgroup configuration for resource limits
    cgroup_config: Optional["CgroupConfig"] = None

    def __post_init__(self):
        from taskflows.security_validation import (
            format_systemd_environment,
            validate_env_file_path,
            validate_service_name,
            validate_systemd_line,
            validate_systemd_value,
        )

        self._pkl_funcs = []
        self.env = dict(self.env or {})
        self.env["PYTHONUNBUFFERED"] = "1"

        # Handle named environments (string references)
        if isinstance(self.environment, str):
            from taskflows.admin.environments import get_environment_object

            env_name = self.environment
            env_obj = get_environment_object(env_name)
            if not env_obj:
                raise ValueError(f"Named environment '{env_name}' not found")

            logger.info(f"Loaded named environment '{env_name}' for service {self.name}")
            self.env["TASKFLOWS_NAMED_ENV"] = env_name
            self.environment = env_obj  # Already a Venv or DockerContainer

        # Handle Docker container environments - sync names before validation
        if isinstance(self.environment, DockerContainer):
            """Setup Docker-specific service configuration."""
            container = self.environment

            # Sync names between service and container
            if not container.name and not self.name:
                raise ValueError("Either service name or container name must be provided")
            elif not container.name:
                container.name = self.name
            elif not self.name:
                self.name = container.name

        # SECURITY: Validate service name to prevent injection
        # This must happen AFTER Docker container name syncing so container name can be used
        try:
            self.name = validate_service_name(self.name)
        except Exception as e:
            logger.error(f"Invalid service name '{self.name}': {e}")
            raise

        # SECURITY: Validate env_file path to prevent directory traversal
        if self.env_file:
            try:
                self.env_file = str(validate_env_file_path(self.env_file, allow_nonexistent=True))
            except Exception as e:
                logger.error(f"Invalid env_file path: {e}")
                raise

        # Continue Docker container setup after validation
        if isinstance(self.environment, DockerContainer):
            container = self.environment

            # Mount the same directory path in container as on host
            # This simplifies the setup and ensures consistency
            services_volume = Volume(
                host_path=services_data_dir,
                container_path=str(services_data_dir),  # Same path in container
                read_only=True,
            )
            # Add to container volumes
            if container.volumes is None:
                container.volumes = [services_volume]
            elif isinstance(container.volumes, Volume):
                container.volumes = [container.volumes, services_volume]
            else:
                container.volumes = list(container.volumes) + [services_volume]

            logger.info(f"Using name '{self.name}' for service and container")

            # Apply cgroup configuration to container if not already set
            if self.cgroup_config and not container.cgroup_config:
                container.cgroup_config = self.cgroup_config

            # Set up slice for systemd resource management
            self.slice = f"{self.name}.slice"

            # Normalize restart policy: systemd doesn't support "unless-stopped"
            # Convert it to "always" for systemd compatibility
            def normalize_restart_policy(policy):
                """Convert Docker restart policies to systemd-compatible values."""
                if policy == "unless-stopped":
                    return "always"
                return policy

            # TODO check for callable start command.
            if container.persisted:
                # Persistent container: started with 'docker start'
                # Handle restart policy migration from container to systemd
                #
                # IMPORTANT: For persisted containers, systemd manages the restart policy,
                # not Docker. We migrate the policy from container to service and set
                # container's policy to "no" to avoid conflicts.
                #
                # NOTE: This modifies the container object's restart_policy attribute.
                if container.restart_policy not in ("no", None):
                    # Migrate and normalize restart policy
                    migrated_policy = normalize_restart_policy(container.restart_policy)

                    # Only override service policy if not already set
                    if self.restart_policy in (None, "no"):
                        self.restart_policy = migrated_policy
                    else:
                        # Service policy takes precedence over container policy
                        self.restart_policy = normalize_restart_policy(self.restart_policy)
                        logger.warning(
                            f"Both service and container have restart policies. "
                            f"Using service policy: {self.restart_policy}, "
                            f"ignoring container policy: {container.restart_policy}"
                        )

                    # Disable Docker's built-in restart to avoid conflicts with systemd
                    container.restart_policy = "no"
                elif self.restart_policy:
                    # Service has restart policy but container doesn't
                    self.restart_policy = normalize_restart_policy(self.restart_policy)

                self.start_command = f"docker start -a {self.name}"
                self.stop_command = f"docker stop -t 30 {self.name}"
                self.restart_command = f"docker restart {self.name}"
            else:
                # Ephemeral container: started with 'docker run'
                # Container is recreated on each service start
                # Normalize restart policy for non-persisted containers too
                if self.restart_policy:
                    self.restart_policy = normalize_restart_policy(self.restart_policy)

                if pkl_func := container.prepare_callable_command():
                    self._pkl_funcs.append(pkl_func)
                self.start_command = container.docker_run_cli_command()
                self.stop_command = f"docker stop {self.name}"
                self.restart_command = f"docker restart {self.name}"

        elif self.restart_policy == "unless-stopped":
            # Normalize restart policy for non-Docker services
            # "unless-stopped" is Docker-specific, convert to systemd-compatible "always"
            self.restart_policy = "always"
        # Validate required fields after setup
        if not self.name:
            raise ValueError("Service name is required")
        if not self.start_command:
            raise ValueError("Service start_command is required")
        if self.timeout is not None and self.timeout <= 0:
            raise ValueError("Service timeout must be greater than 0 seconds")

        for attr in ("start_command", "stop_command", "restart_command"):
            if cmd := getattr(self, attr):
                if not isinstance(cmd, str):
                    # create command for deserializing and calling.
                    cmd = PickledFunction(cmd, self.name, attr)
                    self._pkl_funcs.append(cmd)
                if isinstance(self.environment, Venv):
                    cmd = self.environment.create_env_command(cmd)
                setattr(self, attr, cmd)

        def unit_reference(arg):
            if isinstance(arg, Service):
                return f"{arg.base_file_stem}.service"
            return validate_systemd_value(arg, "systemd unit reference")

        def join(args):
            if not isinstance(args, (list, tuple)):
                args = [args]
            return " ".join(unit_reference(arg) for arg in args)

        self.unit_entries = set()
        self.service_entries = {
            f"ExecStart={self.start_command}",
            f"KillSignal={self.kill_signal}",
            "TimeoutStopSec=120s",
        }
        if self.stop_command:
            self.service_entries.add(f"ExecStop={self.stop_command}")
        if self.restart_command:
            self.service_entries.add(f"ExecReload={self.restart_command}")
        # TODO ExecStopPost?
        if self.working_directory:
            self.service_entries.add(
                f"WorkingDirectory={validate_systemd_value(self.working_directory, 'working_directory')}"
            )
        if self.timeout:
            self.service_entries.add(f"RuntimeMaxSec={self.timeout}")
        if self.env_file:
            # Read env file and parse it ourselves to handle 'export' prefix
            # that systemd's EnvironmentFile doesn't understand
            env_file_vars = self._parse_env_file(self.env_file)
            if env_file_vars:
                self.service_entries.update(
                    format_systemd_environment(k, v) for k, v in env_file_vars.items()
                )
        if self.env:
            self.service_entries.update(
                format_systemd_environment(k, v) for k, v in self.env.items()
            )
        if self.description:
            self.unit_entries.add(
                f"Description={validate_systemd_value(self.description, 'description')}"
            )
        if self.start_after:
            self.unit_entries.add(f"After={join(self.start_after)}")
        if self.start_before:
            self.unit_entries.add(f"Before={join(self.start_before)}")
        if self.conflicts:
            self.unit_entries.add(f"Conflicts={join(self.conflicts)}")
        if self.on_success:
            self.unit_entries.add(f"OnSuccess={join(self.on_success)}")
        if self.on_failure:
            self.unit_entries.add(f"OnFailure={join(self.on_failure)}")
        if self.part_of:
            self.unit_entries.add(f"PartOf={join(self.part_of)}")
        if self.wants:
            self.unit_entries.add(f"Wants={join(self.wants)}")
        if self.upholds:
            self.unit_entries.add(f"Upholds={join(self.upholds)}")
        if self.requires:
            self.unit_entries.add(f"Requires={join(self.requires)}")
        if self.requisite:
            self.unit_entries.add(f"Requisite={join(self.requisite)}")
        if self.binds_to:
            self.unit_entries.add(f"BindsTo={join(self.binds_to)}")
        if self.propagate_stop_to:
            self.unit_entries.add(f"PropagatesStopTo={join(self.propagate_stop_to)}")
        if self.propagate_stop_from:
            self.unit_entries.add(f"StopPropagatedFrom={join(self.propagate_stop_from)}")
        if self.startup_requirements:
            cons = (
                self.startup_requirements
                if isinstance(self.startup_requirements, (list, tuple))
                else [self.startup_requirements]
            )
            for c in cons:
                self.unit_entries.update(c.unit_entries)
        if self.restart_policy not in ("no", None):
            rp = (
                RestartPolicy(condition=self.restart_policy)
                if isinstance(self.restart_policy, str)
                else self.restart_policy
            )
            self.unit_entries.update(rp.unit_entries)
            self.service_entries.update(rp.service_entries)

        if self.watchdog:
            if isinstance(self.environment, DockerContainer):
                raise ValueError(
                    "watchdog is not supported for DockerContainer environments: "
                    "NOTIFY_SOCKET does not cross the container boundary"
                )
            self.service_entries.update(self.watchdog.service_entries)
            if self.watchdog.restart_on_hang and self.restart_policy in ("no", None):
                hang_policy = RestartPolicy(condition="on-watchdog")
                self.unit_entries.update(hang_policy.unit_entries)
                self.service_entries.update(hang_policy.service_entries)

        # Add cgroup configuration directives to systemd service
        if self.cgroup_config:
            cgroup_directives = self.cgroup_config.to_systemd_directives()

            for key, value in cgroup_directives.items():
                directive_name = systemd_directive_name(key)
                if directive_name == "Environment":
                    self.service_entries.add(validate_systemd_line(value))
                else:
                    self.service_entries.add(validate_systemd_line(f"{directive_name}={value}"))

        # Add Docker-specific service entries if using Docker environment
        if isinstance(self.environment, DockerContainer):
            # if self.environment.persisted:
            # Docker start service entries
            if hasattr(self, "slice"):
                self.service_entries.add(f"Slice={self.slice}")
            # Let docker handle the signal
            # TODO change this?
            self.service_entries.add("KillMode=none")
            # Remove SIGTERM since KillMode=none
            self.service_entries.discard("KillSignal=SIGTERM")
            # SIGTERM from docker stop
            self.service_entries.add("SuccessExitStatus=0 143")
            # SIGKILL and docker error code
            self.service_entries.add("RestartForceExitStatus=137 255")
            self.service_entries.add("Delegate=yes")
            # Only set TasksMax=infinity if not already set by cgroup config
            if not any("TasksMax=" in entry for entry in self.service_entries):
                self.service_entries.add("TasksMax=infinity")
            # Drop duplicate log stream in journalctl
            self.service_entries.add("StandardOutput=null")
            self.service_entries.add("StandardError=null")
            # Blocks until fully stopped
            self.service_entries.add(f"ExecStopPost=docker wait {self.name}")
        else:
            # Ensure logs are streamed to journal immediately
            self.service_entries.add("StandardOutput=journal")
            self.service_entries.add("StandardError=journal")

    @property
    def timer_files(self) -> list[str]:
        """Paths to all systemd timer unit files for this service."""
        file_stem = self.base_file_stem
        files = []
        if self.start_schedule:
            files.append(f"{file_stem}.timer")
        if self.stop_schedule:
            files.append(f"stop-{file_stem}.timer")
        if self.restart_schedule:
            files.append(f"restart-{file_stem}.timer")
        return [os.path.join(systemd_dir, f) for f in files]

    @property
    def service_files(self) -> list[str]:
        """Paths to all systemd service unit files for this service."""
        file_stem = self.base_file_stem
        files = [f"{file_stem}.service"]
        if self.stop_schedule:
            files.append(f"stop-{file_stem}.service")
        if self.restart_schedule:
            files.append(f"restart-{file_stem}.service")
        return [os.path.join(systemd_dir, f) for f in files]

    @property
    def unit_files(self) -> list[str]:
        """Get all service and timer files for this service."""
        return self.service_files + self.timer_files

    @property
    def exists(self) -> bool:
        return all(os.path.exists(f) for f in self.unit_files)

    async def start(self):
        """Start this service."""
        await start_units(self.unit_files)

    async def stop(self, timers: bool = False):
        """Stop this service."""
        await stop_units(self.unit_files if timers else self.service_files)

    async def restart(self):
        """Restart this service."""
        await restart_units(self.service_files)

    async def enable(self, timers_only: bool = False):
        """Enable this service."""
        if timers_only:
            await enable_units(self.timer_files)
        else:
            await enable_units(self.unit_files)

    async def disable(self):
        """Disable this service."""
        await disable_units(self.unit_files)

    async def remove(self, preserve_container: bool = False):
        """Remove this service.

        Args:
            preserve_container: If True, don't delete the Docker container (for persisted containers)
        """
        await remove_units(
            service_files=self.service_files,
            timer_files=self.timer_files,
            preserve_container=preserve_container,
        )

    async def create(self, defer_reload: bool = False):
        """Create this service."""
        logger.info(f"Creating service {self}")
        # Remove old version if exists
        # For persisted Docker containers, preserve the container
        preserve_container = (
            isinstance(self.environment, DockerContainer) and self.environment.persisted
        )
        await self.remove(preserve_container=preserve_container)
        self.write_unit_files()

        # Write pickle files and ensure cleanup on error
        for func in self._pkl_funcs:
            func.write()

        try:
            # Handle Docker container creation
            if isinstance(self.environment, DockerContainer):
                # Create Docker container if needed.
                container = self.environment
                if container.persisted:
                    # For persisted containers, only create if it doesn't already exist
                    # This preserves state and avoids unnecessary recreation
                    if not container.exists:
                        logger.info(f"Creating persisted Docker container: {container.name}")
                        container.create(cgroup_parent=self.slice)
                    else:
                        logger.info(f"Persisted Docker container already exists: {container.name}")
                elif isinstance(container.image, DockerImage):
                    container.image.build()
                # For run services, no need to do anything here since
                # the docker run command is directly in the systemd service file

            await self.enable(timers_only=not self.enabled)
            # Start timers now
            await start_units(self.timer_files)
            if not defer_reload:
                await reload_unit_files()
        except Exception as e:
            # Clean up pickle files if service creation fails after they were written
            logger.error(f"Service creation failed, cleaning up pickle files: {e}")
            for func in self._pkl_funcs:
                pickle_file = services_data_dir.joinpath(f"{func.name}#_{func.attr}.pickle")
                try:
                    if pickle_file.exists():
                        pickle_file.unlink()
                        logger.debug(f"Removed pickle file: {pickle_file}")
                except Exception as cleanup_err:
                    logger.warning(f"Failed to clean up pickle file {pickle_file}: {cleanup_err}")
            raise

    def logs(self):
        return service_logs(self.name)

    def show_files(self) -> str:
        return pformat(dict(load_service_files(self.unit_files)))

    def _parse_env_file(self, path: str) -> dict:
        """Parse an env file, stripping 'export' prefixes that systemd doesn't understand.

        Args:
            path: Path to the env file.

        Returns:
            Dictionary of environment variables.
        """
        from pathlib import Path

        env_vars = {}
        path = Path(path)
        if not path.exists():
            logger.warning(f"Env file does not exist yet: {path}")
            return env_vars
        try:
            content = path.read_text()
            for line in content.splitlines():
                line = line.strip()
                # Skip empty lines and comments
                if not line or line.startswith("#"):
                    continue
                # Strip 'export ' prefix if present
                if line.startswith("export "):
                    line = line[7:]  # len('export ') == 7
                # Parse KEY=value
                if "=" in line:
                    key, _, value = line.partition("=")
                    key = key.strip()
                    value = value.strip()
                    # Remove surrounding quotes if present
                    if (value.startswith('"') and value.endswith('"')) or (
                        value.startswith("'") and value.endswith("'")
                    ):
                        value = value[1:-1]
                    if key:
                        env_vars[key] = value
                else:
                    raise ValueError(f"Invalid environment line without '=': {line!r}")
        except Exception as e:
            logger.error(f"Could not parse env file {path}: {e}")
            raise
        return env_vars

    @property
    def base_file_stem(self) -> str:
        return f"{_SYSTEMD_FILE_PREFIX}{self.name.replace(' ', '_')}"

    def _unit_file_name(
        self, unit_type: Literal["timer", "service"], prefix: str | None = None
    ) -> str:
        file_stem = self.base_file_stem
        if prefix:
            file_stem = f"{prefix}-{file_stem}"
        return f"{file_stem}.{unit_type}"

    def render_unit_files(self) -> dict[str, str]:
        """Render all systemd unit files for this service as {filename: content}.

        Pure with respect to the filesystem — nothing is written. Used by
        create()/write_unit_files() and by anything that wants to diff the
        desired state against installed units.
        """
        rendered = self._render_timer_units()
        rendered.update(self._render_service_units())
        return rendered

    def write_unit_files(self) -> list[str]:
        """Write all rendered unit files to the systemd user directory."""
        systemd_dir.mkdir(parents=True, exist_ok=True)
        paths = []
        for filename, content in self.render_unit_files().items():
            file = systemd_dir / filename
            if file.exists():
                logger.warning(f"Replacing existing unit: {file}")
            else:
                logger.info(f"Creating new unit: {file}")
            secure_write_text(file, content, mode=stat.S_IRUSR | stat.S_IWUSR)
            paths.append(str(file))
        return paths

    def _render_timer_units(self) -> dict[str, str]:
        from taskflows.security_validation import (
            validate_systemd_line,
            validate_systemd_value,
        )

        rendered: dict[str, str] = {}
        for prefix, schedule in (
            (None, self.start_schedule),
            ("stop", self.stop_schedule),
            ("restart", self.restart_schedule),
        ):
            if schedule is None:
                continue
            timer = set()
            if isinstance(schedule, (list, tuple)):
                for sched in schedule:
                    timer.update(sched.unit_entries)
            else:
                timer.update(schedule.unit_entries)
            content = [
                "[Unit]",
                "Description="
                f"{validate_systemd_value(prefix + ' ' if prefix else '', 'timer prefix')}"
                f"timer for {self.name}",
                "[Timer]",
                *(validate_systemd_line(line) for line in timer),
                "[Install]",
                "WantedBy=timers.target",
            ]
            rendered[self._unit_file_name("timer", prefix)] = "\n".join(content)
        return rendered

    def _render_service_units(self) -> dict[str, str]:
        main_unit = self._unit_file_name("service")
        rendered = {
            main_unit: self._render_service_file(
                unit=self.unit_entries, service=self.service_entries
            )
        }
        # TODO ExecCondition, ExecStartPre, ExecStartPost?
        if self.stop_schedule:
            # Pass unit entries to stop service as well to maintain consistency
            rendered[self._unit_file_name("service", "stop")] = self._render_service_file(
                unit=self.unit_entries,
                service=[f"ExecStart=systemctl --user stop {main_unit}"],
                prefix="stop",
            )
        if self.restart_schedule:
            # Pass unit entries to restart service as well to maintain consistency
            rendered[self._unit_file_name("service", "restart")] = self._render_service_file(
                unit=self.unit_entries,
                service=[f"ExecStart=systemctl --user restart {main_unit}"],
                prefix="restart",
            )
        return rendered

    def _render_service_file(
        self,
        unit: list[str] | set[str] | None = None,
        service: list[str] | set[str] | None = None,
        prefix: str | None = None,
    ) -> str:
        from taskflows.security_validation import (
            validate_systemd_line,
            validate_systemd_value,
        )

        # Always include [Unit] section with description
        content = ["[Unit]"]
        # Add description based on service type
        if prefix:
            description = f"{prefix.capitalize()} service for {self.name}"
        else:
            description = self.description or f"Service for {self.name}"
        content.append(f"Description={validate_systemd_value(description, 'description')}")

        # Add any additional unit entries
        if unit:
            # Convert set to list if needed
            unit_list = list(unit) if isinstance(unit, set) else unit
            content.extend(validate_systemd_line(line) for line in unit_list)

        # Convert service set to list if needed
        service_list = list(service) if isinstance(service, set) else service
        content += [
            "[Service]",
            *(validate_systemd_line(line) for line in service_list),
            "[Install]",
            "WantedBy=default.target",
        ]
        return "\n".join(content)

    def __repr__(self):
        return str(self)

    def __str__(self):
        meta = {
            "name": self.name,
            "command": self.start_command,
        }
        if self.description:
            meta["description"] = self.description
        if self.start_schedule:
            meta["schedule"] = self.start_schedule
        meta = ", ".join(f"{k}={v}" for k, v in meta.items())
        return f"{self.__class__.__name__}({meta})"

    def to_dict(self, include_none: bool = False) -> dict:
        """Serialize this service to a dictionary.

        Args:
            include_none: Whether to include None values.

        Returns:
            A dictionary representation of the service.
        """
        from taskflows.serialization import to_dict

        return to_dict(self, include_none=include_none)

    def to_json(self, indent: int = 2, include_none: bool = False) -> str:
        """Serialize this service to JSON.

        Args:
            indent: Indentation level for pretty printing.
            include_none: Whether to include None values.

        Returns:
            A JSON string representation of the service.
        """
        from taskflows.serialization import serialize

        return serialize(self, format="json", indent=indent, include_none=include_none)

    def to_yaml(self, include_none: bool = False) -> str:
        """Serialize this service to YAML.

        Args:
            include_none: Whether to include None values.

        Returns:
            A YAML string representation of the service.
        """
        from taskflows.serialization import serialize

        return serialize(self, format="yaml", include_none=include_none)

    @classmethod
    def from_dict(cls, data: dict) -> "Service":
        """Create a Service from a dictionary.

        Args:
            data: The dictionary data.

        Returns:
            A Service instance.
        """
        from taskflows.serialization import from_dict

        return from_dict(data, cls)

    @classmethod
    def from_json(cls, data: str) -> "Service":
        """Create a Service from a JSON string.

        Args:
            data: The JSON string.

        Returns:
            A Service instance.
        """
        from taskflows.serialization import deserialize

        return deserialize(data, cls, format="json")

    @classmethod
    def from_yaml(cls, data: str) -> "Service":
        """Create a Service from a YAML string.

        Args:
            data: The YAML string.

        Returns:
            A Service instance.
        """
        from taskflows.serialization import deserialize

        return deserialize(data, cls, format="yaml")

    def to_file(
        self,
        path: str | Path,
        format: Literal["json", "yaml"] | None = None,
        indent: int = 2,
        include_none: bool = False,
    ) -> None:
        """Serialize this service to a file.

        Args:
            path: The file path.
            format: Output format. If None, inferred from file extension.
            indent: Indentation level for pretty printing.
            include_none: Whether to include None values.
        """
        from taskflows.serialization import serialize_to_file

        serialize_to_file(self, path, format=format, indent=indent, include_none=include_none)

    @classmethod
    def from_file(
        cls, path: str | Path, format: Literal["json", "yaml"] | None = None
    ) -> "Service":
        """Create a Service from a file.

        Args:
            path: The file path.
            format: Input format. If None, inferred from file extension.

        Returns:
            A Service instance.
        """
        from taskflows.serialization import deserialize_from_file

        return deserialize_from_file(path, cls, format=format)


# Backwards-compatible aliases for the pre-decomposition private names
_start_service = start_units
_stop_service = stop_units
_restart_service = restart_units
_enable_service = enable_units
_disable_service = disable_units
_remove_service = remove_units
