import re
from dataclasses import dataclass
from numbers import Real
from typing import Any, Literal

from pydantic import BaseModel, Field

# How each CgroupConfig.to_docker_kwargs() key renders as a docker run flag.
# kinds: value (flag + str), flag (bare flag if truthy), repeat (flag per list
# item), mapping (flag per key=value), nofile (--ulimit nofile=N:N).
_DOCKER_CLI_FLAGS: dict[str, tuple[str, str]] = {
    "cpu_quota": ("--cpu-quota", "value"),
    "cpu_period": ("--cpu-period", "value"),
    "cpu_shares": ("--cpu-shares", "value"),
    "cpuset_cpus": ("--cpuset-cpus", "value"),
    "mem_limit": ("--memory", "value"),
    "memswap_limit": ("--memory-swap", "value"),
    "mem_reservation": ("--memory-reservation", "value"),
    "mem_swappiness": ("--memory-swappiness", "value"),
    "blkio_weight": ("--blkio-weight", "value"),
    "device_read_bps": ("--device-read-bps", "repeat"),
    "device_write_bps": ("--device-write-bps", "repeat"),
    "device_read_iops": ("--device-read-iops", "repeat"),
    "device_write_iops": ("--device-write-iops", "repeat"),
    "pids_limit": ("--pids-limit", "value"),
    "nofile_limit": ("--ulimit", "nofile"),
    "oom_score_adj": ("--oom-score-adj", "value"),
    "read_only": ("--read-only", "flag"),
    "cap_add": ("--cap-add", "repeat"),
    "cap_drop": ("--cap-drop", "repeat"),
    "devices": ("--device", "repeat"),
    "device_cgroup_rules": ("--device-cgroup-rule", "repeat"),
    "environment": ("--env", "mapping"),
    "user": ("--user", "value"),
    "group_add": ("--group-add", "repeat"),
    "working_dir": ("--workdir", "value"),
    "stop_timeout": ("--stop-timeout", "value"),
}

_NUMBERED_DIRECTIVE_RE = re.compile(r"^(?P<name>.+)_\d+$")


def systemd_directive_name(key: str) -> str:
    """Return the systemd directive name for internally numbered keys."""
    match = _NUMBERED_DIRECTIVE_RE.match(key)
    return match.group("name") if match else key


# TODO handle: Failing conditions or asserts will not result in the unit being moved into the "failed" state.
class HardwareConstraint(BaseModel):
    amount: int = Field(ge=0)
    constraint: Literal["<", "<=", "=", "!=", ">=", ">"] = ">="
    # abort without an error message
    silent: bool = False

    @property
    def unit_entries(self) -> set[str]:
        action = "Constraint" if self.silent else "Assert"
        return {f"{action}{self.__class__.__name__}={self.constraint}{self.amount}"}


class Memory(HardwareConstraint):
    """Verify that the specified amount of system memory (in bytes) adheres to the constraint."""

    ...


class CPUs(HardwareConstraint):
    """Verify that the system's CPU count adheres to the provided constraint."""

    ...


class SystemLoadConstraint(BaseModel):
    """
    Verify that the overall system (memory, CPU or IO) pressure is below or equal to a threshold.
    The pressure will be measured as an average over the last `timespan` minutes before the attempt to start the unit is performed.
    """

    max_percent: int = Field(ge=0, le=100)
    timespan: Literal["10sec", "1min", "5min"] = "5min"
    # abort without an error message
    silent: bool = False

    @property
    def unit_entries(self) -> set[str]:
        action = "Constraint" if self.silent else "Assert"
        return {f"{action}{self.__class__.__name__}={self.max_percent}%/{self.timespan}"}


class MemoryPressure(SystemLoadConstraint): ...


class CPUPressure(SystemLoadConstraint): ...


class IOPressure(SystemLoadConstraint): ...


@dataclass
class CgroupConfig:
    """Unified cgroup configuration for both Docker and systemd."""

    # CPU limits
    cpu_quota: int | None = None  # microseconds per period
    cpu_period: int | None = 100000  # default 100ms
    cpu_shares: int | None = None  # relative weight (Docker: 1024 = 1 CPU)
    cpu_weight: int | None = None  # systemd weight (1-10000, cgroup v2)
    cpuset_cpus: str | None = None  # CPU affinity (e.g., "0-3,5")

    # Memory limits
    memory_limit: int | None = None  # hard limit in bytes
    memory_high: int | None = None  # soft limit / high-water mark (systemd)
    memory_reservation: int | None = None  # soft limit (Docker)
    memory_low: int | None = None  # preferred memory (systemd)
    memory_min: int | None = None  # guaranteed memory (systemd)
    memory_swap_limit: int | None = None  # bytes (memory + swap)
    memory_swap_max: int | None = None  # swap allowance (systemd cgroup v2)
    memory_swappiness: int | None = None  # 0-100, swap tendency

    # I/O limits
    blkio_weight: int | None = None  # Docker: 10-1000
    io_weight: int | None = None  # systemd: 1-10000 (cgroup v2)
    device_read_bps: dict[str, int] | None = None  # device -> bytes/sec
    device_write_bps: dict[str, int] | None = None  # device -> bytes/sec
    device_read_iops: dict[str, int] | None = None  # device -> operations/sec
    device_write_iops: dict[str, int] | None = None  # device -> operations/sec

    # Process limits
    pids_limit: int | None = None  # max number of PIDs/tasks
    nofile_limit: int | None = None  # max number of open file descriptors

    # Security and isolation
    oom_score_adj: int | None = None  # OOM killer preference (-1000 to 1000)
    oom_policy: Literal["continue", "stop", "kill"] | None = None
    read_only_rootfs: bool | None = None  # make root filesystem read-only
    cap_add: list[str] | None = None  # add Linux capabilities
    cap_drop: list[str] | None = None  # drop Linux capabilities
    devices: list[str] | None = None  # device access rules
    device_cgroup_rules: list[str] | None = None  # custom device cgroup rules

    # systemd-oomd controls
    managed_oom_swap: Literal["auto", "kill"] | None = None
    managed_oom_memory_pressure: Literal["auto", "kill"] | None = None
    managed_oom_memory_pressure_limit: int | None = None
    managed_oom_preference: Literal["none", "avoid", "omit"] | None = None

    # Timeouts (resource-related)
    timeout_start: int | None = None  # start timeout in seconds
    timeout_stop: int | None = None  # stop timeout in seconds

    # Environment and execution
    environment: dict[str, str] | None = None  # environment variables
    user: str | None = None  # run as user
    group: str | None = None  # run as group
    working_dir: str | None = None  # working directory

    def __post_init__(self) -> None:
        self._normalize_literal("oom_policy")
        self._normalize_literal("managed_oom_swap")
        self._normalize_literal("managed_oom_memory_pressure")
        self._normalize_literal("managed_oom_preference")
        self._normalize_percent("managed_oom_memory_pressure_limit")
        self._validate_positive(
            "cpu_period",
            "cpu_shares",
            "cpu_weight",
            "memory_limit",
            "memory_high",
            "memory_reservation",
            "memory_low",
            "memory_min",
            "memory_swap_limit",
            "pids_limit",
            "nofile_limit",
            "timeout_start",
            "timeout_stop",
        )
        self._validate_non_negative("cpu_quota", "memory_swap_max")
        self._validate_range("cpu_weight", 1, 10000)
        self._validate_range("memory_swappiness", 0, 100)
        self._validate_range("blkio_weight", 10, 1000)
        self._validate_range("io_weight", 1, 10000)
        self._validate_range("oom_score_adj", -1000, 1000)
        self._validate_range("managed_oom_memory_pressure_limit", 0, 100)
        self._validate_literal("oom_policy", {"continue", "stop", "kill"})
        self._validate_literal("managed_oom_swap", {"auto", "kill"})
        self._validate_literal("managed_oom_memory_pressure", {"auto", "kill"})
        self._validate_literal("managed_oom_preference", {"none", "avoid", "omit"})
        self._validate_positive_mapping(
            "device_read_bps",
            "device_write_bps",
            "device_read_iops",
            "device_write_iops",
        )

    def _validate_positive(self, *names: str) -> None:
        for name in names:
            value = getattr(self, name)
            if value is not None and value <= 0:
                raise ValueError(f"{name} must be positive")

    def _validate_non_negative(self, *names: str) -> None:
        for name in names:
            value = getattr(self, name)
            if value is not None and value < 0:
                raise ValueError(f"{name} must be non-negative")

    def _validate_range(self, name: str, minimum: int, maximum: int) -> None:
        value = getattr(self, name)
        if value is None:
            return
        if isinstance(value, bool) or not isinstance(value, Real):
            raise ValueError(f"{name} must be between {minimum} and {maximum}")
        if not minimum <= value <= maximum:
            raise ValueError(f"{name} must be between {minimum} and {maximum}")

    def _normalize_literal(self, name: str) -> None:
        value = getattr(self, name)
        if isinstance(value, str):
            setattr(self, name, value.lower())

    def _normalize_percent(self, name: str) -> None:
        value = getattr(self, name)
        if value is None or isinstance(value, (bool, int)):
            return
        if isinstance(value, float):
            if not value.is_integer():
                raise ValueError(f"{name} must be a whole percent between 0 and 100")
            setattr(self, name, int(value))
            return
        if isinstance(value, str):
            percent = value.strip()
            if percent.endswith("%"):
                percent = percent[:-1].strip()
            if percent.isdigit():
                setattr(self, name, int(percent))
                return
        raise ValueError(f"{name} must be a whole percent between 0 and 100")

    def _validate_literal(self, name: str, allowed: set[str]) -> None:
        value = getattr(self, name)
        if value is not None and value not in allowed:
            allowed_values = ", ".join(sorted(allowed))
            raise ValueError(f"{name} must be one of: {allowed_values}")

    def _validate_positive_mapping(self, *names: str) -> None:
        for name in names:
            values = getattr(self, name)
            if not values:
                continue
            for key, value in values.items():
                if value <= 0:
                    raise ValueError(f"{name}[{key!r}] must be positive")

    def to_docker_kwargs(self) -> dict[str, Any]:
        """Convert to Docker SDK (containers.run) keyword arguments.

        Single source of truth for the cgroup→Docker mapping: the CLI flags
        (to_docker_cli_args) are a mechanical rendering of this dict via
        _DOCKER_CLI_FLAGS, so the two code paths cannot drift.

        The insertion order of keys determines CLI flag order.
        """
        kwargs: dict[str, Any] = {}

        # CPU configuration - intelligent mapping
        if self.cpu_quota:
            kwargs["cpu_quota"] = self.cpu_quota
        if self.cpu_period:
            kwargs["cpu_period"] = self.cpu_period

        # CPU weight: prefer cpu_shares, fallback to converted cpu_weight
        if self.cpu_shares:
            kwargs["cpu_shares"] = self.cpu_shares
        elif self.cpu_weight:
            # Convert systemd weight (1-10000) to Docker shares (~1024 default)
            kwargs["cpu_shares"] = int((self.cpu_weight / 100) * 1024)

        if self.cpuset_cpus:
            kwargs["cpuset_cpus"] = self.cpuset_cpus

        # Memory configuration - use intelligent mapping
        if effective_memory := self._calculate_effective_memory_limit():
            kwargs["mem_limit"] = effective_memory
        if effective_swap := self._calculate_effective_swap_limit():
            kwargs["memswap_limit"] = effective_swap
        if effective_reservation := self._calculate_effective_memory_reservation():
            kwargs["mem_reservation"] = effective_reservation
        if self.memory_swappiness is not None:
            kwargs["mem_swappiness"] = self.memory_swappiness

        # I/O weight: prefer blkio_weight, fallback to converted io_weight
        if self.blkio_weight:
            kwargs["blkio_weight"] = self.blkio_weight
        elif self.io_weight:
            # Convert systemd IOWeight (1-10000) to Docker blkio-weight (10-1000)
            kwargs["blkio_weight"] = max(10, min(1000, int(self.io_weight / 10)))

        # Device bandwidth/IOPS limits (direct mapping)
        for device_field in (
            "device_read_bps",
            "device_write_bps",
            "device_read_iops",
            "device_write_iops",
        ):
            if limits := getattr(self, device_field):
                kwargs[device_field] = [f"{dev}:{value}" for dev, value in limits.items()]

        # Process limits
        if self.pids_limit:
            kwargs["pids_limit"] = self.pids_limit
        if self.nofile_limit:
            # rendered as a nofile ulimit by both the SDK and CLI paths
            kwargs["nofile_limit"] = self.nofile_limit

        # Security and isolation
        if self.oom_score_adj is not None:
            kwargs["oom_score_adj"] = self.oom_score_adj
        if self.read_only_rootfs:
            kwargs["read_only"] = self.read_only_rootfs
        if self.cap_add:
            kwargs["cap_add"] = list(self.cap_add)
        if self.cap_drop:
            kwargs["cap_drop"] = list(self.cap_drop)
        if self.devices:
            kwargs["devices"] = list(self.devices)
        if self.device_cgroup_rules:
            kwargs["device_cgroup_rules"] = list(self.device_cgroup_rules)

        # Environment and execution
        if self.environment:
            kwargs["environment"] = dict(self.environment)
        if self.user:
            kwargs["user"] = self.user
        if self.group:
            kwargs["group_add"] = [self.group]
        if self.working_dir:
            kwargs["working_dir"] = self.working_dir

        # Timeouts
        if self.timeout_stop:
            kwargs["stop_timeout"] = self.timeout_stop

        return kwargs

    def to_docker_cli_args(self) -> list[str]:
        """Convert to Docker CLI arguments (rendered from to_docker_kwargs)."""
        args: list[str] = []
        for key, value in self.to_docker_kwargs().items():
            flag, kind = _DOCKER_CLI_FLAGS[key]
            if kind == "value":
                args.extend([flag, str(value)])
            elif kind == "flag":
                if value:
                    args.append(flag)
            elif kind == "repeat":
                for item in value:
                    args.extend([flag, str(item)])
            elif kind == "mapping":
                for map_key, map_value in value.items():
                    args.extend([flag, f"{map_key}={map_value}"])
            elif kind == "nofile":
                args.extend([flag, f"nofile={value}:{value}"])
        return args

    def _calculate_effective_memory_limit(self) -> int | None:
        """Calculate the most appropriate memory limit for Docker from systemd memory parameters."""
        # Priority: memory_limit > memory_max > memory_high > memory_min
        if self.memory_limit:
            return self.memory_limit

        # For systemd-only configs, use the highest available limit
        candidates = []
        if self.memory_high:
            candidates.append(self.memory_high)
        if self.memory_min:
            # Use min as a baseline, but prefer higher limits
            candidates.append(self.memory_min)

        return max(candidates) if candidates else None

    def _calculate_effective_memory_reservation(self) -> int | None:
        """Calculate the most appropriate memory reservation for Docker from systemd parameters."""
        # Priority: memory_reservation > memory_high > memory_low
        if self.memory_reservation:
            return self.memory_reservation
        if self.memory_high:
            return self.memory_high
        if self.memory_low:
            return self.memory_low
        return None

    def _calculate_effective_swap_limit(self) -> int | None:
        """Calculate Docker memory_swap_limit from systemd parameters."""
        if self.memory_swap_limit:
            return self.memory_swap_limit

        # systemd: memory_swap_max is swap allowance only
        # Docker: memory_swap_limit is total memory + swap
        if self.memory_swap_max is not None:
            base_memory = self._calculate_effective_memory_limit()
            if base_memory:
                return base_memory + self.memory_swap_max

        return None

    def _parse_device_bandwidth_limits(self) -> dict[str, dict[str, int]]:
        """Parse systemd IOReadBandwidthMax/IOWriteBandwidthMax format."""
        # This would be used if we had systemd directives to parse
        # For now, return empty dict as we're generating, not parsing
        return {}

    def _calculate_capability_lists(self) -> tuple[list[str], list[str]]:
        """Calculate cap_add/cap_drop lists from current capabilities."""
        cap_add = list(self.cap_add) if self.cap_add else []
        cap_drop = list(self.cap_drop) if self.cap_drop else []

        return cap_add, cap_drop

    def to_systemd_directives(self) -> dict[str, str]:
        """Convert to systemd service directives."""
        directives = {}

        # Enable resource accounting
        directives["MemoryAccounting"] = "yes"
        directives["IOAccounting"] = "yes"
        directives["TasksAccounting"] = "yes"

        # CPU configuration
        if self.cpu_quota and self.cpu_period:
            # Convert to percentage (systemd uses percentage, Docker uses microseconds)
            cpu_percent = (self.cpu_quota / self.cpu_period) * 100
            directives["CPUQuota"] = f"{cpu_percent:.3f}%"
        if self.cpu_weight:
            directives["CPUWeight"] = str(self.cpu_weight)
        elif self.cpu_shares:
            # Convert Docker shares (1024 default) to systemd weight (1-10000)
            cpu_weight = max(1, min(10000, int((self.cpu_shares / 1024) * 100)))
            directives["CPUWeight"] = str(cpu_weight)
        if self.cpuset_cpus:
            directives["AllowedCPUs"] = self.cpuset_cpus

        # Memory configuration - intelligent mapping
        if self.memory_limit:
            directives["MemoryMax"] = str(self.memory_limit)

        # Memory high: prefer memory_high, fallback to reservation
        if self.memory_high:
            directives["MemoryHigh"] = str(self.memory_high)
        elif self.memory_reservation:
            directives["MemoryHigh"] = str(self.memory_reservation)

        # systemd-specific memory controls
        if self.memory_low:
            directives["MemoryLow"] = str(self.memory_low)
        elif self.memory_reservation:
            # Derive MemoryLow as 75% of reservation for better memory management
            derived_low = int(self.memory_reservation * 0.75)
            directives["MemoryLow"] = str(derived_low)

        if self.memory_min:
            directives["MemoryMin"] = str(self.memory_min)

        # Swap handling: prefer memory_swap_max, fallback to calculated from Docker limits
        if self.memory_swap_max is not None:
            directives["MemorySwapMax"] = str(self.memory_swap_max)
        elif self.memory_swap_limit and self.memory_limit:
            # Calculate swap allowance from Docker total limit
            swap_allowance = self.memory_swap_limit - self.memory_limit
            if swap_allowance > 0:
                directives["MemorySwapMax"] = str(swap_allowance)
        elif self.memory_swappiness:
            directives["MemorySwapMax"] = "infinity"

        # I/O configuration (cgroup v2 preferred)
        if self.io_weight:
            directives["IOWeight"] = str(self.io_weight)
        elif self.blkio_weight:
            # Convert Docker blkio-weight (10-1000) to systemd IOWeight (1-10000)
            io_weight = max(1, min(10000, self.blkio_weight * 10))
            directives["IOWeight"] = str(io_weight)

        # Device bandwidth limits - enhanced mapping
        # Systemd allows multiple IOReadBandwidthMax/IOWriteBandwidthMax directives
        if self.device_read_bps:
            for i, (dev, bps) in enumerate(self.device_read_bps.items()):
                directives[f"IOReadBandwidthMax_{i}"] = f"{dev} {bps}"
        if self.device_write_bps:
            for i, (dev, bps) in enumerate(self.device_write_bps.items()):
                directives[f"IOWriteBandwidthMax_{i}"] = f"{dev} {bps}"

        # Convert IOPS to approximate bandwidth if no bandwidth limits set
        if self.device_read_iops and not self.device_read_bps:
            for i, (dev, iops) in enumerate(self.device_read_iops.items()):
                # Rough approximation: assume 4KB average I/O size
                estimated_bps = iops * 4096
                directives[f"IOReadBandwidthMax_{i}"] = f"{dev} {estimated_bps}"
        if self.device_write_iops and not self.device_write_bps:
            for i, (dev, iops) in enumerate(self.device_write_iops.items()):
                # Rough approximation: assume 4KB average I/O size
                estimated_bps = iops * 4096
                directives[f"IOWriteBandwidthMax_{i}"] = f"{dev} {estimated_bps}"

        # Process limits
        if self.pids_limit:
            directives["TasksMax"] = str(self.pids_limit)
        if self.nofile_limit:
            directives["LimitNOFILE"] = str(self.nofile_limit)

        # Security and isolation
        if self.oom_score_adj is not None:
            directives["OOMScoreAdjust"] = str(self.oom_score_adj)
        if self.oom_policy:
            directives["OOMPolicy"] = self.oom_policy
        if self.managed_oom_swap:
            directives["ManagedOOMSwap"] = self.managed_oom_swap
        if self.managed_oom_memory_pressure:
            directives["ManagedOOMMemoryPressure"] = self.managed_oom_memory_pressure
        if self.managed_oom_memory_pressure_limit is not None:
            directives["ManagedOOMMemoryPressureLimit"] = (
                f"{self.managed_oom_memory_pressure_limit}%"
            )
        if self.managed_oom_preference:
            directives["ManagedOOMPreference"] = self.managed_oom_preference
        if self.read_only_rootfs:
            directives["ProtectSystem"] = "strict"
            directives["ReadOnlyPaths"] = "/"
        if self.cap_drop:
            # Remove capabilities from bounding set
            remaining_caps = [
                "CAP_CHOWN",
                "CAP_DAC_OVERRIDE",
                "CAP_FOWNER",
                "CAP_FSETID",
                "CAP_KILL",
                "CAP_SETGID",
                "CAP_SETUID",
                "CAP_SETPCAP",
                "CAP_NET_BIND_SERVICE",
                "CAP_NET_RAW",
                "CAP_SYS_CHROOT",
                "CAP_MKNOD",
                "CAP_AUDIT_WRITE",
                "CAP_SETFCAP",
            ]
            for cap in self.cap_drop:
                if cap.upper() in remaining_caps:
                    remaining_caps.remove(cap.upper())
                elif f"CAP_{cap.upper()}" in remaining_caps:
                    remaining_caps.remove(f"CAP_{cap.upper()}")
            directives["CapabilityBoundingSet"] = " ".join(remaining_caps)
        if self.cap_add and self.cap_drop:
            # Add back specific capabilities if both add and drop are specified
            all_caps = set(directives.get("CapabilityBoundingSet", "").split())
            for cap in self.cap_add:
                cap_name = cap.upper() if cap.startswith("CAP_") else f"CAP_{cap.upper()}"
                all_caps.add(cap_name)
            directives["CapabilityBoundingSet"] = " ".join(sorted(all_caps))

        # Device restrictions
        if self.devices:
            # Convert Docker device format to systemd DeviceAllow
            for index, device in enumerate(self.devices):
                dev_path = device
                permissions = "rwm"
                if ":" in device:
                    # Format: /dev/device:rwm or /dev/device:/container/path:rwm
                    parts = device.split(":")
                    dev_path = parts[0]
                    permissions = parts[-1] if len(parts) >= 2 else "rwm"
                directives[f"DeviceAllow_{index}"] = f"{dev_path} {permissions}"

        # Environment and execution
        if self.environment:
            from taskflows.security_validation import format_systemd_environment

            for index, (key, value) in enumerate(self.environment.items()):
                directives[f"Environment_{index}"] = format_systemd_environment(key, value)
        if self.user:
            directives["User"] = self.user
        if self.group:
            directives["Group"] = self.group
        if self.working_dir:
            directives["WorkingDirectory"] = self.working_dir

        # Timeouts
        if self.timeout_start:
            directives["TimeoutStartSec"] = f"{self.timeout_start}s"
        if self.timeout_stop:
            directives["TimeoutStopSec"] = f"{self.timeout_stop}s"

        # Note: Restart policy is handled by the Service class, not CgroupConfig

        return directives
