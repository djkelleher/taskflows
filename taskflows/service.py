import os
import re
import subprocess
import threading
from abc import abstractmethod
from dataclasses import dataclass
from datetime import datetime
from functools import cache
from pathlib import Path
from pprint import pformat, pprint
from typing import Callable, Dict, List, Literal, Optional, Sequence, Set, Union

from dbus_next import BusType
from dbus_next.aio import MessageBus
from dbus_next.errors import DBusError
from pydantic.dataclasses import dataclass as pdataclass

from .common import (
    _SYSTEMD_FILE_PREFIX,
    extract_service_name,
    load_service_files,
    logger,
    services_data_dir,
    systemd_dir,
)
from .constraints import (
    CgroupConfig,
    CPUPressure,
    CPUs,
    HardwareConstraint,
    IOPressure,
    Memory,
    MemoryPressure,
    SystemLoadConstraint,
)
from .docker import (
    DockerContainer,
    DockerImage,
    Ulimit,
    Volume,
    delete_docker_container,
    get_docker_client,
)
from .exec import PickledFunction
from .schedule import Calendar, Periodic, Schedule

ServiceT = Union[str, "Service"]
ServicesT = Union[ServiceT, Sequence[ServiceT]]


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
    delay: Optional[int] = None
    # hard ceiling on how many *failed* restarts are allowed within `window` before the task is left in `FAILED` state
    max_attempts: Optional[int] = None
    # sliding time window used to decide whether an attempt counts as “failed”. If the task stays up for the full `window`, the counter resets.
    window: Optional[int] = None

    @property
    def unit_entries(self) -> Set[str]:
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
    def service_entries(self) -> Set[str]:
        entries = {f"Restart={self.condition}"}
        if self.delay:
            entries.add(f"RestartSec={self.delay}")
        return entries


@dataclass
class Venv:
    env_name: str

    @abstractmethod
    def create_env_command(self, command: str) -> str:
        home = Path.home()
        exes = (
            home.joinpath("mambaforge", "bin", "mamba"),
            home.joinpath("miniforge3", "bin", "mamba"),
            home.joinpath("miniconda3", "condabin", "conda"),
        )
        for exe in exes:
            if exe.is_file():
                # Use stdbuf to force line buffering on stdout and stderr and ensure
                # PYTHONUNBUFFERED=1 is set for the executed process (journald streaming)
                # Note: env assignment must precede the command it applies to.
                return f"{exe} run -n {self.env_name} --no-capture-output {command}"
        raise FileNotFoundError(f"Virtualenv not found! Checked: {exes}")


@dataclass
class Service:
    """A service to run a command on a specified schedule."""

    # name used to identify the service.
    name: Optional[str] = None
    # command to execute.
    start_command: Optional[str | Callable[[], None]] = None
    # command to execute to stop the service command.
    stop_command: Optional[str] = None
    # environment where commands should be executed.
    environment: Venv | DockerContainer = None
    # when the service should be started.
    start_schedule: Optional[Schedule | Sequence[Schedule]] = None
    # when the service should be stopped.
    stop_schedule: Optional[Schedule | Sequence[Schedule]] = None
    # when the service should be restarted.
    restart_schedule: Optional[Schedule | Sequence[Schedule]] = None
    # command to execute when the service is restarted.
    restart_command: Optional[str] = None
    # signal used to stop the service.
    kill_signal: str = "SIGTERM"
    restart_policy: Optional[str | RestartPolicy] = "no"
    startup_requirements: Sequence[Union[HardwareConstraint, SystemLoadConstraint]] = (
        None
    )
    # Specifies a timeout (in seconds) that starts running when the queued job is actually started.
    # If limit is reached, the job will be cancelled, the unit however will not change state or even enter the "failed" mode.
    timeout: Optional[int] = None
    # path to a file with environment variables for the service.
    # TODO LoadCredential, LoadCredentialEncrypted, SetCredentialEncrypted
    # TODO forward to docker container.
    env_file: Optional[str] = None
    # environment variables for the service.
    env: Optional[Dict[str, str]] = None
    # working directory for the service.
    working_directory: Optional[str | Path] = None
    # enable the service to start automatically on boot.
    enabled: bool = False
    ## SERVICE RELATIONS ##
    # make sure this service is fully started before begining startup of these services.
    start_before: Optional[ServicesT] = None
    # make sure these services are fully started before begining startup of this service.
    start_after: Optional[ServicesT] = None
    # Units listed in this option will be started simultaneously at the same time as the configuring unit is.
    # If the listed units fail to start, this unit will still be started anyway. Multiple units may be specified.
    wants: Optional[ServicesT] = None
    # Configures dependencies similar to `Wants`, but as long as this unit is up,
    # all units listed in `Upholds` are started whenever found to be inactive or failed, and no job is queued for them.
    # While a Wants= dependency on another unit has a one-time effect when this units started,
    # a `Upholds` dependency on it has a continuous effect, constantly restarting the unit if necessary.
    # This is an alternative to the Restart= setting of service units, to ensure they are kept running whatever happens.
    upholds: Optional[ServicesT] = None
    # Units listed in this option will be started simultaneously at the same time as the configuring unit is.
    # If one of the other units fails to activate, and an ordering dependency `After` on the failing unit is set, this unit will not be started.
    # This unit will be stopped (or restarted) if one of the other units is explicitly stopped (or restarted) via systemctl command (not just normal exit on process finished).
    requires: Optional[ServicesT] = None
    # Units listed in this option will be started simultaneously at the same time as the configuring unit is.
    # If the units listed here are not started already, they will not be started and the starting of this unit will fail immediately.
    # Note: this setting should usually be combined with `After`, to ensure this unit is not started before the other unit.
    requisite: Optional[ServicesT] = None
    # Same as `Requires`, but in order for this unit will be stopped (or restarted), if a listed unit is stopped (or restarted), explicitly or not.
    binds_to: Optional[ServicesT] = None
    # one or more units that are activated when this unit enters the "failed" state.
    # A service unit using Restart= enters the failed state only after the start limits are reached.
    on_failure: Optional[ServicesT] = None
    # one or more units that are activated when this unit enters the "inactive" state.
    on_success: Optional[ServicesT] = None
    # When systemd stops or restarts the units listed here, the action is propagated to this unit.
    # Note that this is a one-way dependency — changes to this unit do not affect the listed units.
    part_of: Optional[ServicesT] = None
    # A space-separated list of one or more units to which stop requests from this unit shall be propagated to,
    # or units from which stop requests shall be propagated to this unit, respectively.
    # Issuing a stop request on a unit will automatically also enqueue stop requests on all units that are linked to it using these two settings.
    propagate_stop_to: Optional[ServicesT] = None
    propagate_stop_from: Optional[ServicesT] = None
    # other units where starting the former will stop the latter and vice versa.
    conflicts: Optional[ServicesT] = None
    # description of this service.
    description: Optional[str] = None
    # cgroup configuration for resource limits
    cgroup_config: Optional['CgroupConfig'] = None

    def __post_init__(self):
        # SECURITY: Validate service name to prevent injection
        from taskflows.security_validation import validate_service_name, validate_env_file_path

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

        self._pkl_funcs = []
        self.env = self.env or {}
        self.env["PYTHONUNBUFFERED"] = "1"

        # Handle named environments (string references)
        if isinstance(self.environment, str):
            from taskflows.admin.environments import get_environment_object

            env_name = self.environment
            env_obj = get_environment_object(env_name)
            if not env_obj:
                raise ValueError(f"Named environment '{env_name}' not found")

            logger.info(f"Loaded named environment '{env_name}' for service {self.name}")
            self.environment = env_obj  # Already a Venv or DockerContainer

        # Handle Docker container environments
        if isinstance(self.environment, DockerContainer):
            """Setup Docker-specific service configuration."""
            container = self.environment

            # Sync names between service and container
            if not container.name and not self.name:
                raise ValueError(
                    "Either service name or container name must be provided"
                )
            elif not container.name:
                container.name = self.name
            elif not self.name:
                self.name = container.name

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

        for attr in ("start_command", "stop_command", "restart_command"):
            if cmd := getattr(self, attr):
                if not isinstance(cmd, str):
                    # create command for deserializing and calling.
                    cmd = PickledFunction(cmd, self.name, attr)
                    self._pkl_funcs.append(cmd)
                if isinstance(self.environment, Venv):
                    cmd = self.environment.create_env_command(cmd)
                setattr(self, attr, cmd)

        def join(args):
            if not isinstance(args, (list, tuple)):
                args = [args]
            return " ".join(args)

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
            self.service_entries.add(f"WorkingDirectory={self.working_directory}")
        if self.timeout:
            self.service_entries.add(f"RuntimeMaxSec={self.timeout}")
        if self.env_file:
            self.service_entries.add(f"EnvironmentFile={self.env_file}")
        if self.env:
            self.service_entries.add(
                "\n".join([f'Environment="{k}={v}"' for k, v in self.env.items()])
            )
        if self.description:
            self.unit_entries.add(f"Description={self.description}")
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
        if self.conflicts:
            self.unit_entries.add(f"Conflicts={join(self.conflicts)}")
        if self.binds_to:
            self.unit_entries.add(f"BindsTo={join(self.binds_to)}")
        if self.propagate_stop_to:
            self.unit_entries.add(f"PropagatesStopTo={join(self.propagate_stop_to)}")
        if self.propagate_stop_from:
            self.unit_entries.add(
                f"StopPropagatedFrom={join(self.propagate_stop_from)}"
            )
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
            
        # Add cgroup configuration directives to systemd service
        if self.cgroup_config:
            cgroup_directives = self.cgroup_config.to_systemd_directives()

            for key, value in cgroup_directives.items():
                # Remove numeric suffix for systemd output
                # IOReadBandwidthMax_0 -> IOReadBandwidthMax
                # This allows multiple device directives to work correctly
                directive_name = key.rsplit('_', 1)[0] if key[-1].isdigit() else key
                self.service_entries.add(f"{directive_name}={value}")

        # Add Docker-specific service entries if using Docker environment
        if isinstance(self.environment, DockerContainer):
            # if self.environment.persisted:
            # Docker start service entries
            if hasattr(self, 'slice'):
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
    def timer_files(self) -> List[str]:
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
    def service_files(self) -> List[str]:
        """Paths to all systemd service unit files for this service."""
        file_stem = self.base_file_stem
        files = [f"{file_stem}.service"]
        if self.stop_schedule:
            files.append(f"stop-{file_stem}.service")
        if self.restart_schedule:
            files.append(f"restart-{file_stem}.service")
        return [os.path.join(systemd_dir, f) for f in files]

    @property
    def unit_files(self) -> List[str]:
        """Get all service and timer files for this service."""
        return self.service_files + self.timer_files

    @property
    def exists(self) -> bool:
        return all(os.path.exists(f) for f in self.unit_files)

    async def start(self):
        """Start this service."""
        await _start_service(self.unit_files)

    async def stop(self, timers: bool = False):
        """Stop this service."""
        await _stop_service(self.unit_files if timers else self.service_files)

    async def restart(self):
        """Restart this service."""
        await _restart_service(self.service_files)

    async def enable(self, timers_only: bool = False):
        """Enable this service."""
        if timers_only:
            await _enable_service(self.timer_files)
        else:
            await _enable_service(self.unit_files)

    async def disable(self):
        """Disable this service."""
        await _disable_service(self.unit_files)

    async def remove(self, preserve_container: bool = False):
        """Remove this service.

        Args:
            preserve_container: If True, don't delete the Docker container (for persisted containers)
        """
        await _remove_service(
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
            isinstance(self.environment, DockerContainer)
            and self.environment.persisted
        )
        await self.remove(preserve_container=preserve_container)
        self._write_timer_units()
        self._write_service_units()

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
                # For run services, no need to do anything here since
                # the docker run command is directly in the systemd service file

            await self.enable(timers_only=not self.enabled)
            # Start timers now
            await _start_service(self.timer_files)
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

    def show_files(self):
        pprint(dict(load_service_files(self.unit_files)))

    def _write_timer_units(self):
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
                f"Description={prefix + ' ' if prefix else ''}timer for {self.name}",
                "[Timer]",
                *timer,
                "[Install]",
                "WantedBy=timers.target",
            ]
            self._write_systemd_file("timer", "\n".join(content), prefix=prefix)

    def _write_service_units(self):
        srv_file = self._write_service_file(
            unit=self.unit_entries, service=self.service_entries
        )
        # TODO ExecCondition, ExecStartPre, ExecStartPost?
        if self.stop_schedule:
            service = [f"ExecStart=systemctl --user stop {os.path.basename(srv_file)}"]
            # Pass unit entries to stop service as well to maintain consistency
            self._write_service_file(
                unit=self.unit_entries, service=service, prefix="stop"
            )
        if self.restart_schedule:
            service = [f"ExecStart=systemctl --user restart {os.path.basename(srv_file)}"]
            # Pass unit entries to restart service as well to maintain consistency
            self._write_service_file(
                unit=self.unit_entries, service=service, prefix="restart"
            )

    @property
    def base_file_stem(self) -> str:
        return f"{_SYSTEMD_FILE_PREFIX}{self.name.replace(' ', '_')}"

    def _write_service_file(
        self,
        unit: Optional[Union[List[str], Set[str]]] = None,
        service: Optional[Union[List[str], Set[str]]] = None,
        prefix: Optional[str] = None,
    ):
        # Always include [Unit] section with description
        content = ["[Unit]"]
        # Add description based on service type
        if prefix:
            description = f"{prefix.capitalize()} service for {self.name}"
        else:
            description = self.description or f"Service for {self.name}"
        content.append(f"Description={description}")

        # Add any additional unit entries
        if unit:
            # Convert set to list if needed
            unit_list = list(unit) if isinstance(unit, set) else unit
            content.extend(unit_list)

        # Convert service set to list if needed
        service_list = list(service) if isinstance(service, set) else service
        content += [
            "[Service]",
            *service_list,
            "[Install]",
            "WantedBy=default.target",
        ]
        return self._write_systemd_file(
            "service", "\n".join(content), prefix=prefix
        )

    def _write_systemd_file(
        self,
        unit_type: Literal["timer", "service"],
        content: str,
        prefix: Optional[str] = None,
    ) -> str:
        systemd_dir.mkdir(parents=True, exist_ok=True)
        file_stem = self.base_file_stem
        if prefix:
            file_stem = f"{prefix}-{file_stem}"
        file = systemd_dir / f"{file_stem}.{unit_type}"
        if file.exists():
            logger.warning(f"Replacing existing unit: {file}")
        else:
            logger.info(f"Creating new unit: {file}")
        file.write_text(content)
        return str(file)

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


def service_logs(service_name: str, n_lines: int = 1000):
    """Get logs command data for a service.

    This function returns the journalctl command that would be used to view logs
    for the specified service.

    Args:
        service_name (str): The name of the service to show logs for.

    Returns:
        dict: Dictionary containing the service name and journalctl command.
    """
    cmd = [
        "journalctl",
        "--user",
        "-u",
        f"{_SYSTEMD_FILE_PREFIX}{service_name}",
        "-n",
        str(n_lines),  # Return only the latest log lines
    ]
    result = subprocess.run(
        cmd,
        capture_output=True,  # capture stdout & stderr
        text=True,  # decode to str instead of bytes
        check=True,  # raise CalledProcessError on non-zero exit
    )
    txt = []
    if result.stderr:
        txt.append(result.stderr)
    if result.stdout:
        txt.append(result.stdout)
    return "\n\n".join(txt).strip()


# DBus connection management with automatic reconnection (async dbus-next)
# Uses asyncio for non-blocking D-Bus operations

import asyncio

# Use a dict to store locks per event loop to avoid "bound to different event loop" errors
_dbus_connection_locks: dict = {}
_dbus_session_bus: Optional[MessageBus] = None
_dbus_manager = None
_dbus_manager_introspection = None
_dbus_last_error_time = 0
_dbus_error_cooldown = 5  # Seconds between reconnection attempts


def _get_dbus_lock() -> asyncio.Lock:
    """Get the asyncio lock for the current event loop.

    This handles the case where tests run with different event loops.
    Each event loop gets its own lock.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    loop_id = id(loop) if loop else 0
    if loop_id not in _dbus_connection_locks:
        _dbus_connection_locks[loop_id] = asyncio.Lock()
    return _dbus_connection_locks[loop_id]


async def _reset_dbus_connections():
    """Reset DBus connections (called when connection becomes stale)."""
    global _dbus_session_bus, _dbus_manager, _dbus_manager_introspection
    if _dbus_session_bus is not None:
        try:
            _dbus_session_bus.disconnect()
        except Exception:
            pass
    _dbus_session_bus = None
    _dbus_manager = None
    _dbus_manager_introspection = None
    logger.info("DBus connections reset for reconnection")


async def _session_dbus_unlocked() -> MessageBus:
    """Internal: Get or create the D-Bus session bus connection without acquiring lock.

    MUST be called with _get_dbus_lock() already held.
    """
    global _dbus_session_bus, _dbus_last_error_time
    import time

    # Try to use existing connection
    if _dbus_session_bus is not None and _dbus_session_bus.connected:
        return _dbus_session_bus

    if _dbus_session_bus is not None:
        logger.warning("DBus session bus disconnected, reconnecting...")
        _dbus_session_bus = None

    # Apply cooldown to avoid tight reconnection loops
    current_time = time.time()
    if current_time - _dbus_last_error_time < _dbus_error_cooldown:
        await asyncio.sleep(0.5)  # Brief delay

    # Create new connection
    try:
        logger.info("Creating new DBus session bus connection")
        _dbus_session_bus = await MessageBus(bus_type=BusType.SESSION).connect()
        logger.info("DBus session bus connection established successfully")
        return _dbus_session_bus
    except Exception as e:
        _dbus_last_error_time = current_time
        logger.error(f"Failed to create DBus session bus: {e}", exc_info=True)
        raise


async def session_dbus() -> MessageBus:
    """Get or create the D-Bus session bus connection.

    Implements automatic reconnection on connection failure.
    Handles systemd restarts gracefully.

    Returns:
        MessageBus instance

    Raises:
        DBusError: If connection cannot be established
    """
    async with _get_dbus_lock():
        return await _session_dbus_unlocked()


async def systemd_manager():
    """Get or create the systemd D-Bus manager interface.

    Implements automatic reconnection on connection failure.
    Handles systemd restarts gracefully.

    Returns:
        Proxy interface to systemd manager

    Raises:
        DBusError: If manager cannot be accessed
    """
    global _dbus_manager, _dbus_manager_introspection

    async with _get_dbus_lock():
        # Get bus (will reconnect if needed) - use unlocked version since we already hold the lock
        bus = await _session_dbus_unlocked()

        # Try to use existing manager if bus is still the same
        if _dbus_manager is not None:
            try:
                # Health check: try a simple property access
                version = await _dbus_manager.get_version()
                return _dbus_manager
            except (DBusError, Exception) as e:
                logger.warning(f"DBus manager health check failed: {e}")
                await _reset_dbus_connections()
                bus = await _session_dbus_unlocked()

        # Create new manager interface
        try:
            logger.info("Creating new systemd D-Bus manager interface")
            _dbus_manager_introspection = await bus.introspect(
                "org.freedesktop.systemd1", "/org/freedesktop/systemd1"
            )
            proxy = bus.get_proxy_object(
                "org.freedesktop.systemd1",
                "/org/freedesktop/systemd1",
                _dbus_manager_introspection,
            )
            _dbus_manager = proxy.get_interface("org.freedesktop.systemd1.Manager")
            # Verify manager works
            version = await _dbus_manager.get_version()
            logger.info(f"Systemd D-Bus manager connected (version: {version})")
            return _dbus_manager
        except Exception as e:
            logger.error(f"Failed to create systemd manager: {e}", exc_info=True)
            await _reset_dbus_connections()
            raise


async def _dbus_operation_with_retry(operation, operation_name, max_retries=2):
    """Execute a D-Bus operation with automatic retry on connection failure.

    Args:
        operation: Async callable that performs the D-Bus operation
        operation_name: Human-readable name for logging
        max_retries: Maximum number of retry attempts

    Returns:
        Result of the operation

    Raises:
        DBusError: If all retries fail
    """
    for attempt in range(max_retries + 1):
        try:
            return await operation()
        except DBusError as e:
            error_str = str(e).lower()

            # Check if this is a connection-related error
            is_connection_error = any(
                keyword in error_str
                for keyword in ["connection", "disconnected", "not available", "no reply"]
            )

            if is_connection_error and attempt < max_retries:
                logger.warning(
                    f"DBus operation '{operation_name}' failed with connection error "
                    f"(attempt {attempt + 1}/{max_retries + 1}): {e}"
                )
                # Reset connections and retry
                await _reset_dbus_connections()
                await asyncio.sleep(0.5 * (attempt + 1))  # Exponential backoff
                continue
            else:
                # Non-connection error or final attempt - propagate
                if attempt == max_retries:
                    logger.error(
                        f"DBus operation '{operation_name}' failed after {max_retries + 1} attempts: {e}"
                    )
                raise
        except Exception as e:
            # Unexpected error - always propagate
            logger.error(f"Unexpected error in DBus operation '{operation_name}': {e}", exc_info=True)
            raise


async def reload_unit_files():
    """Reload systemd unit files with automatic retry on connection failure."""
    async def _reload():
        mgr = await systemd_manager()
        await mgr.call_reload()
    await _dbus_operation_with_retry(_reload, "reload_unit_files")


async def escape_path(path) -> str:
    """Escape a path so that it can be used in a systemd file."""
    mgr = await systemd_manager()
    return await mgr.call_escape_path(path)


async def _get_unit_proxy(bus: MessageBus, unit_path: str):
    """Get a proxy object for a unit at the given path."""
    introspection = await bus.introspect("org.freedesktop.systemd1", unit_path)
    return bus.get_proxy_object("org.freedesktop.systemd1", unit_path, introspection)


async def get_schedule_info(unit: str):
    """Get the schedule information for a unit."""
    unit_stem = Path(unit).stem
    if not unit_stem.startswith(_SYSTEMD_FILE_PREFIX):
        unit_stem = f"{_SYSTEMD_FILE_PREFIX}{unit_stem}"
    manager = await systemd_manager()
    bus = await session_dbus()

    # Load service unit
    service_path = await manager.call_load_unit(f"{unit_stem}.service")
    service_proxy = await _get_unit_proxy(bus, service_path)
    service_props = service_proxy.get_interface("org.freedesktop.DBus.Properties")

    schedule = {
        # timestamp of the last time a unit entered the active state.
        "Last Start": await service_props.call_get(
            "org.freedesktop.systemd1.Unit", "ActiveEnterTimestamp"
        ),
        # timestamp of the last time a unit exited the active state.
        "Last Finish": await service_props.call_get(
            "org.freedesktop.systemd1.Unit", "ActiveExitTimestamp"
        ),
    }

    # Load timer unit
    timer_path = await manager.call_load_unit(f"{unit_stem}.timer")
    timer_proxy = await _get_unit_proxy(bus, timer_path)
    timer_props = timer_proxy.get_interface("org.freedesktop.DBus.Properties")

    schedule["Next Start"] = await timer_props.call_get(
        "org.freedesktop.systemd1.Timer", "NextElapseUSecRealtime"
    )

    missing_dt = datetime(1970, 1, 1, 0, 0, 0)

    def timestamp_to_dt(timestamp):
        try:
            # Handle Variant type from dbus-next
            if hasattr(timestamp, "value"):
                timestamp = timestamp.value
            dt = datetime.fromtimestamp(timestamp / 1_000_000)
            if dt == missing_dt:
                return None
            return dt
        except (ValueError, TypeError):
            # "year 586524 is out of range" or type error
            return None

    schedule = {field: timestamp_to_dt(val) for field, val in schedule.items()}

    # TimersCalendar
    timers_cal = []
    timers_calendar_raw = await timer_props.call_get(
        "org.freedesktop.systemd1.Timer", "TimersCalendar"
    )
    # Handle Variant type
    if hasattr(timers_calendar_raw, "value"):
        timers_calendar_raw = timers_calendar_raw.value
    for timer in timers_calendar_raw:
        base, spec, next_start = timer
        timers_cal.append(
            {
                "base": base,
                "spec": spec,
                "next_start": timestamp_to_dt(next_start),
            }
        )
    schedule["Timers Calendar"] = timers_cal
    if (not schedule["Next Start"]) and (
        next_start := [t["next_start"] for t in timers_cal if t["next_start"]]
    ):
        schedule["Next Start"] = min(next_start)

    # TimersMonotonic
    timers_mono = []
    timers_monotonic_raw = await timer_props.call_get(
        "org.freedesktop.systemd1.Timer", "TimersMonotonic"
    )
    # Handle Variant type
    if hasattr(timers_monotonic_raw, "value"):
        timers_monotonic_raw = timers_monotonic_raw.value
    for timer in timers_monotonic_raw:
        base, offset, next_start = timer
        timers_mono.append(
            {
                "base": base,
                "offset": offset,
                "next_start": timestamp_to_dt(next_start),
            }
        )
    schedule["Timers Monotonic"] = timers_mono
    return schedule


async def get_unit_files(
    unit_type: Optional[Literal["service", "timer"]] = None,
    match: Optional[str] = None,
    states: Optional[str | Sequence[str]] = None,
) -> List[str]:
    """Get a list of paths of taskflows unit files."""
    file_states = await get_unit_file_states(unit_type=unit_type, match=match, states=states)
    return list(file_states.keys())


async def get_unit_file_states(
    unit_type: Optional[Literal["service", "timer"]] = None,
    match: Optional[str] = None,
    states: Optional[str | Sequence[str]] = None,
) -> Dict[str, str]:
    """Map taskflows unit file path to unit state."""
    states = states or []
    pattern = _make_unit_match_pattern(unit_type=unit_type, match=match)
    mgr = await systemd_manager()
    files = await mgr.call_list_unit_files_by_patterns(states, [pattern])
    logger.debug(f"Found {len(files)} units matching: {pattern}")
    if not files:
        logger.error(f"No taskflows unit files found matching: {pattern}")
    return {str(file): str(state) for file, state in files}


async def get_units(
    unit_type: Optional[Literal["service", "timer"]] = None,
    match: Optional[str] = None,
    states: Optional[str | Sequence[str]] = None,
) -> List[Dict[str, str]]:
    """Get metadata for taskflows units."""
    states = states or []
    pattern = _make_unit_match_pattern(unit_type=unit_type, match=match)
    mgr = await systemd_manager()
    files = await mgr.call_list_units_by_patterns(states, [pattern])
    fields = [
        "unit_name",
        "description",
        "load_state",
        "active_state",
        "sub_state",
        "followed",
        "unit_path",
        "job_id",
        "job_type",
        "job_path",
    ]
    units = [{k: str(v) for k, v in zip(fields, f)} for f in files]
    logger.debug(f"Found {len(units)} units matching: {pattern}")
    return units


def _make_unit_match_pattern(
    unit_type: Optional[Literal["service", "timer"]] = None, match: Optional[str] = None
) -> str:
    pattern = match or "*"
    if unit_type and not pattern.endswith(f".{unit_type}"):
        pattern += f".{unit_type}"
    else:
        pattern += ".*"
    if _SYSTEMD_FILE_PREFIX not in pattern:
        pattern = f"*{_SYSTEMD_FILE_PREFIX}{pattern}"
    return re.sub(r"\*{2,}", "*", pattern)


def is_start_service(unit_file: str) -> bool:
    """Check if a unit file is a main start service (not an auxiliary stop/restart service).

    Args:
        unit_file: Unit file path or filename

    Returns:
        True if the unit is the main service (doesn't start with "stop-" or "restart-")
    """
    filename = os.path.basename(unit_file) if os.path.sep in unit_file else unit_file
    return not (filename.startswith("stop-") or filename.startswith("restart-"))


async def _start_service(files: Sequence[str]):
    from taskflows.metrics import service_state

    mgr = await systemd_manager()
    for sf in files:
        sf = os.path.basename(sf)
        if is_start_service(sf):
            service_name = extract_service_name(sf)
            logger.info(f"Running: {sf}")
            await mgr.call_start_unit(sf, "replace")
            # Track service state change
            service_state.labels(service_name=service_name, state="active").set(1)
            service_state.labels(service_name=service_name, state="inactive").set(0)


async def _stop_service(files: Sequence[str]):
    from taskflows.metrics import service_state

    mgr = await systemd_manager()
    for sf in files:
        sf = os.path.basename(sf)
        service_name = extract_service_name(sf)
        logger.info(f"Stopping: {sf}")
        try:
            await mgr.call_stop_unit(sf, "replace")
            # Track service state change
            service_state.labels(service_name=service_name, state="inactive").set(1)
            service_state.labels(service_name=service_name, state="active").set(0)
        except DBusError as err:
            logger.warning(f"Could not stop {sf}: ({type(err)}) {err}")

        # remove any failed status caused by stopping service.
        # await mgr.call_reset_failed_unit(sf)


async def _restart_service(files: Sequence[str]):
    from taskflows.metrics import service_restarts

    units = [os.path.basename(f) for f in files]
    # only restart main service units
    units = [u for u in units if is_start_service(u)]
    mgr = await systemd_manager()
    for sf in units:
        service_name = extract_service_name(sf)
        logger.info(f"Restarting: {sf}")
        try:
            await mgr.call_restart_unit(sf, "replace")
            # Track restart
            service_restarts.labels(service_name=service_name, reason="manual").inc()
        except DBusError as err:
            logger.warning(f"Could not restart {sf}: ({type(err)}) {err}")


async def _enable_service(files: Sequence[str]):
    mgr = await systemd_manager()
    logger.info(f"Enabling: {pformat(files)}")

    async def enable_files(files, is_retry=False):
        try:
            # the first bool controls whether the unit shall be enabled for runtime only (true, /run), or persistently (false, /etc).
            # The second one controls whether symlinks pointing to other units shall be replaced if necessary.
            await mgr.call_enable_unit_files(files, False, True)
        except DBusError as err:
            logger.warning(f"Could not enable {files}: ({type(err)}) {err}")
            if not is_retry and len(files) > 1:
                for file in files:
                    await enable_files([file], is_retry=True)

    await enable_files(files)


async def _disable_service(files: Sequence[str]):
    mgr = await systemd_manager()
    files = [os.path.basename(f) for f in files]
    logger.info(f"Disabling: {pformat(files)}")

    async def disable_files(files, is_retry=False):
        try:
            # the first bool controls whether the unit shall be enabled for runtime only (true, /run), or persistently (false, /etc).
            # The second one controls whether symlinks pointing to other units shall be replaced if necessary.
            result = await mgr.call_disable_unit_files(files, False)
            for meta in result:
                # meta has: the type of the change (one of symlink or unlink), the file name of the symlink and the destination of the symlink.
                logger.info(f"{meta[0]} {meta[1]} {meta[2]}")
        except DBusError as err:
            logger.warning(f"Could not disable {files}: ({type(err)}) {err}")
            if not is_retry and len(files) > 1:
                for file in files:
                    await disable_files([file], is_retry=True)

    await disable_files(files)


async def _remove_service(service_files: Sequence[str], timer_files: Sequence[str], preserve_container: bool = False):
    def valid_file_paths(files):
        files = [Path(f) for f in files]
        return [f for f in files if f.is_file()]

    service_files = valid_file_paths(service_files)
    timer_files = valid_file_paths(timer_files)
    logger.info(
        f"Removing {len(service_files)} services and {len(timer_files)} timers"
    )
    files = service_files + timer_files
    await _stop_service(files)
    await _disable_service(files)
    container_names = set()
    mgr = await systemd_manager()
    for srv_file in service_files:
        logger.info(f"Cleaning cache and runtime directories: {srv_file}.")
        try:
            # the possible values are "configuration", "state", "logs", "cache", "runtime", "fdstore", and "all".
            await mgr.call_clean_unit(srv_file.name, ["all"])
        except DBusError as err:
            logger.warning(f"Could not clean {srv_file}: ({type(err)}) {err}")
        container_name = re.search(
            r"docker (?:start|stop) ([\w-]+)", srv_file.read_text()
        )
        if container_name:
            container_names.add(container_name.group(1))
    if not preserve_container:
        for cname in container_names:
            delete_docker_container(cname)
    else:
        logger.info(f"Preserving Docker containers: {container_names}")
    for srv in service_files:
        files.extend(services_data_dir.glob(f"{extract_service_name(srv)}#*.pickle"))
    for file in files:
        logger.info(f"Deleting {file}")
        file.unlink()
    logger.info(
        f"Finished removing {len(service_files)} services and {len(timer_files)} timers"
    )
    await reload_unit_files()
