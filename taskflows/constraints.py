from dataclasses import dataclass
from typing import Dict, List, Literal, Optional, Set

from pydantic import BaseModel


# TODO handle: Failing conditions or asserts will not result in the unit being moved into the "failed" state.
class HardwareConstraint(BaseModel):
    amount: int
    constraint: Literal["<", "<=", "=", "!=", ">=", ">"] = ">="
    # abort without an error message
    silent: bool = False

    @property
    def unit_entries(self) -> Set[str]:
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

    max_percent: int
    timespan: Literal["10sec", "1min", "5min"] = "5min"
    # abort without an error message
    silent: bool = False

    @property
    def unit_entries(self) -> Set[str]:
        action = "Constraint" if self.silent else "Assert"
        return {
            f"{action}{self.__class__.__name__}={self.max_percent}%/{self.timespan}"
        }


class MemoryPressure(SystemLoadConstraint): ...


class CPUPressure(SystemLoadConstraint): ...


class IOPressure(SystemLoadConstraint): ...



@dataclass
class CgroupConfig:
    """Unified cgroup configuration for both Docker and systemd."""

    # CPU limits
    cpu_quota: Optional[int] = None  # microseconds per period
    cpu_period: Optional[int] = 100000  # default 100ms
    cpu_shares: Optional[int] = None  # relative weight (Docker: 1024 = 1 CPU)
    cpu_weight: Optional[int] = None  # systemd weight (1-10000, cgroup v2)
    cpuset_cpus: Optional[str] = None  # CPU affinity (e.g., "0-3,5")

    # Memory limits
    memory_limit: Optional[int] = None  # hard limit in bytes
    memory_high: Optional[int] = None  # soft limit / high-water mark (systemd)
    memory_reservation: Optional[int] = None  # soft limit (Docker)
    memory_low: Optional[int] = None  # preferred memory (systemd)
    memory_min: Optional[int] = None  # guaranteed memory (systemd)
    memory_swap_limit: Optional[int] = None  # bytes (memory + swap)
    memory_swap_max: Optional[int] = None  # swap allowance (systemd cgroup v2)
    memory_swappiness: Optional[int] = None  # 0-100, swap tendency

    # I/O limits
    blkio_weight: Optional[int] = None  # Docker: 10-1000
    io_weight: Optional[int] = None  # systemd: 1-10000 (cgroup v2)
    device_read_bps: Optional[Dict[str, int]] = None  # device -> bytes/sec
    device_write_bps: Optional[Dict[str, int]] = None  # device -> bytes/sec
    device_read_iops: Optional[Dict[str, int]] = None  # device -> operations/sec
    device_write_iops: Optional[Dict[str, int]] = None  # device -> operations/sec

    # Process limits
    pids_limit: Optional[int] = None  # max number of PIDs/tasks

    # Security and isolation
    oom_score_adj: Optional[int] = None  # OOM killer preference (-1000 to 1000)
    read_only_rootfs: Optional[bool] = None  # make root filesystem read-only
    cap_add: Optional[List[str]] = None  # add Linux capabilities
    cap_drop: Optional[List[str]] = None  # drop Linux capabilities
    devices: Optional[List[str]] = None  # device access rules
    device_cgroup_rules: Optional[List[str]] = None  # custom device cgroup rules

    # Timeouts (resource-related)
    timeout_start: Optional[int] = None  # start timeout in seconds
    timeout_stop: Optional[int] = None  # stop timeout in seconds

    # Environment and execution
    environment: Optional[Dict[str, str]] = None  # environment variables
    user: Optional[str] = None  # run as user
    group: Optional[str] = None  # run as group
    working_dir: Optional[str] = None  # working directory

    def to_docker_cli_args(self) -> List[str]:
        """Convert to Docker CLI arguments."""
        args = []

        # CPU configuration - intelligent mapping
        if self.cpu_quota:
            args.extend(["--cpu-quota", str(self.cpu_quota)])
        if self.cpu_period:
            args.extend(["--cpu-period", str(self.cpu_period)])
            
        # CPU weight: prefer cpu_shares, fallback to converted cpu_weight
        if self.cpu_shares:
            args.extend(["--cpu-shares", str(self.cpu_shares)])
        elif self.cpu_weight:
            # Convert systemd weight (1-10000) to Docker shares (~1024 default)
            docker_shares = int((self.cpu_weight / 100) * 1024)
            args.extend(["--cpu-shares", str(docker_shares)])
            
        if self.cpuset_cpus:
            args.extend(["--cpuset-cpus", self.cpuset_cpus])

        # Memory configuration - use intelligent mapping
        effective_memory = self._calculate_effective_memory_limit()
        if effective_memory:
            args.extend(["--memory", str(effective_memory)])
            
        effective_swap = self._calculate_effective_swap_limit()
        if effective_swap:
            args.extend(["--memory-swap", str(effective_swap)])
            
        effective_reservation = self._calculate_effective_memory_reservation()
        if effective_reservation:
            args.extend(["--memory-reservation", str(effective_reservation)])
            
        if self.memory_swappiness is not None:
            args.extend(["--memory-swappiness", str(self.memory_swappiness)])

        # I/O configuration - intelligent mapping
        # I/O weight: prefer blkio_weight, fallback to converted io_weight
        if self.blkio_weight:
            args.extend(["--blkio-weight", str(self.blkio_weight)])
        elif self.io_weight:
            # Convert systemd IOWeight (1-10000) to Docker blkio-weight (10-1000)
            docker_blkio = max(10, min(1000, int(self.io_weight / 10)))
            args.extend(["--blkio-weight", str(docker_blkio)])
            
        # Device bandwidth limits (direct mapping)
        if self.device_read_bps:
            for dev, bps in self.device_read_bps.items():
                args.extend(["--device-read-bps", f"{dev}:{bps}"])
        if self.device_write_bps:
            for dev, bps in self.device_write_bps.items():
                args.extend(["--device-write-bps", f"{dev}:{bps}"])
        if self.device_read_iops:
            for dev, iops in self.device_read_iops.items():
                args.extend(["--device-read-iops", f"{dev}:{iops}"])
        if self.device_write_iops:
            for dev, iops in self.device_write_iops.items():
                args.extend(["--device-write-iops", f"{dev}:{iops}"])

        # Process limits
        if self.pids_limit:
            args.extend(["--pids-limit", str(self.pids_limit)])

        # Security and isolation
        if self.oom_score_adj is not None:
            args.extend(["--oom-score-adj", str(self.oom_score_adj)])
        if self.read_only_rootfs:
            args.append("--read-only")
        if self.cap_add:
            for cap in self.cap_add:
                args.extend(["--cap-add", cap])
        if self.cap_drop:
            for cap in self.cap_drop:
                args.extend(["--cap-drop", cap])
        if self.devices:
            for device in self.devices:
                args.extend(["--device", device])
        if self.device_cgroup_rules:
            for rule in self.device_cgroup_rules:
                args.extend(["--device-cgroup-rule", rule])

        # Environment and execution
        if self.environment:
            for key, value in self.environment.items():
                args.extend(["--env", f"{key}={value}"])
        if self.user:
            args.extend(["--user", self.user])
        if self.group:
            args.extend(["--group-add", self.group])
        if self.working_dir:
            args.extend(["--workdir", self.working_dir])

        # Timeouts
        if self.timeout_stop:
            args.extend(["--stop-timeout", str(self.timeout_stop)])

        return args
    
    def _calculate_effective_memory_limit(self) -> Optional[int]:
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
    
    def _calculate_effective_memory_reservation(self) -> Optional[int]:
        """Calculate the most appropriate memory reservation for Docker from systemd parameters."""
        # Priority: memory_reservation > memory_high > memory_low
        if self.memory_reservation:
            return self.memory_reservation
        if self.memory_high:
            return self.memory_high
        if self.memory_low:
            return self.memory_low
        return None
    
    def _calculate_effective_swap_limit(self) -> Optional[int]:
        """Calculate Docker memory_swap_limit from systemd parameters."""
        if self.memory_swap_limit:
            return self.memory_swap_limit
            
        # systemd: memory_swap_max is swap allowance only
        # Docker: memory_swap_limit is total memory + swap
        if self.memory_swap_max:
            base_memory = self._calculate_effective_memory_limit()
            if base_memory:
                return base_memory + self.memory_swap_max
                
        return None
    
    def _parse_device_bandwidth_limits(self) -> Dict[str, Dict[str, int]]:
        """Parse systemd IOReadBandwidthMax/IOWriteBandwidthMax format."""
        # This would be used if we had systemd directives to parse
        # For now, return empty dict as we're generating, not parsing
        return {}
    
    def _calculate_capability_lists(self) -> tuple[List[str], List[str]]:
        """Calculate cap_add/cap_drop lists from current capabilities."""
        cap_add = list(self.cap_add) if self.cap_add else []
        cap_drop = list(self.cap_drop) if self.cap_drop else []
        
        return cap_add, cap_drop
    
    def to_systemd_directives(self) -> Dict[str, str]:
        """Convert to systemd service directives."""
        directives = {}

        # Enable resource accounting
        directives["CPUAccounting"] = "yes"
        directives["MemoryAccounting"] = "yes"
        directives["IOAccounting"] = "yes"
        directives["TasksAccounting"] = "yes"

        # CPU configuration
        if self.cpu_quota and self.cpu_period:
            # Convert to percentage (systemd uses percentage, Docker uses microseconds)
            cpu_percent = (self.cpu_quota / self.cpu_period) * 100
            directives["CPUQuota"] = f"{cpu_percent:.0f}%"
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
        if self.memory_swap_max:
            directives["MemorySwapMax"] = str(self.memory_swap_max)
        elif self.memory_swap_limit and self.memory_limit:
            # Calculate swap allowance from Docker total limit
            swap_allowance = self.memory_swap_limit - self.memory_limit
            if swap_allowance > 0:
                directives["MemorySwapMax"] = str(swap_allowance)

        # I/O configuration (cgroup v2 preferred)
        if self.io_weight:
            directives["IOWeight"] = str(self.io_weight)
        elif self.blkio_weight:
            # Convert Docker blkio-weight (10-1000) to systemd IOWeight (1-10000)
            io_weight = max(1, min(10000, int((self.blkio_weight / 1000) * 10000)))
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

        # Security and isolation
        if self.oom_score_adj is not None:
            directives["OOMScoreAdjust"] = str(self.oom_score_adj)
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
                cap_name = (
                    cap.upper() if cap.startswith("CAP_") else f"CAP_{cap.upper()}"
                )
                all_caps.add(cap_name)
            directives["CapabilityBoundingSet"] = " ".join(sorted(all_caps))

        # Device restrictions
        if self.devices:
            # Convert Docker device format to systemd DeviceAllow
            for device in self.devices:
                if ":" in device:
                    # Format: /dev/device:rwm or /dev/device:/container/path:rwm
                    parts = device.split(":")
                    dev_path = parts[0]
                    permissions = parts[-1] if len(parts) >= 2 else "rwm"
                    directives["DeviceAllow"] = f"{dev_path} {permissions}"

        # Environment and execution
        if self.environment:
            env_vars = []
            for key, value in self.environment.items():
                env_vars.append(f"{key}={value}")
            directives["Environment"] = " ".join(env_vars)
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
