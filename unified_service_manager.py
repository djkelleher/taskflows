#!/usr/bin/env python3
"""
Unified Docker and systemd Service Manager

This module provides a unified interface for managing services that can run
either as Docker containers or systemd services, with automatic cgroup
feature switching based on the execution context.
"""

import subprocess
from dataclasses import dataclass
from typing import Optional, Dict, Any, List
from pathlib import Path


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
    block_io_weight: Optional[int] = None  # systemd: 10-1000 (cgroup v1)
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
    
    # Restart and lifecycle
    restart_policy: str = "no"  # no, on-failure, always, unless-stopped
    restart_max_retries: Optional[int] = None
    restart_delay: Optional[int] = None  # seconds
    timeout_start: Optional[int] = None  # start timeout in seconds
    timeout_stop: Optional[int] = None  # stop timeout in seconds
    
    # Environment and execution
    environment: Optional[Dict[str, str]] = None  # environment variables
    user: Optional[str] = None  # run as user
    group: Optional[str] = None  # run as group
    working_dir: Optional[str] = None  # working directory
    
    def to_docker_config(self) -> Dict[str, Any]:
        """Convert to Docker container configuration."""
        config = {}
        
        # CPU configuration
        if self.cpu_quota:
            config["cpu_quota"] = self.cpu_quota
        if self.cpu_period:
            config["cpu_period"] = self.cpu_period
        if self.cpu_shares:
            config["cpu_shares"] = self.cpu_shares
        elif self.cpu_weight:
            # Convert systemd weight (1-10000) to Docker shares (~1024 default)
            config["cpu_shares"] = int((self.cpu_weight / 100) * 1024)
        if self.cpuset_cpus:
            config["cpuset_cpus"] = self.cpuset_cpus
        
        # Memory configuration
        if self.memory_limit:
            config["mem_limit"] = self.memory_limit
        if self.memory_swap_limit:
            config["memswap_limit"] = self.memory_swap_limit
        if self.memory_reservation:
            config["mem_reservation"] = self.memory_reservation
        if self.memory_swappiness:
            config["mem_swappiness"] = self.memory_swappiness
        
        # I/O configuration
        if self.blkio_weight:
            config["blkio_weight"] = self.blkio_weight
        elif self.io_weight:
            # Convert systemd IOWeight (1-10000) to Docker blkio-weight (10-1000)
            config["blkio_weight"] = max(10, min(1000, int(self.io_weight / 10)))
        elif self.block_io_weight:
            config["blkio_weight"] = self.block_io_weight
            
        if self.device_read_bps:
            config["device_read_bps"] = [
                f"{dev}:{bps}" for dev, bps in self.device_read_bps.items()
            ]
        if self.device_write_bps:
            config["device_write_bps"] = [
                f"{dev}:{bps}" for dev, bps in self.device_write_bps.items()
            ]
        if self.device_read_iops:
            config["device_read_iops"] = [
                f"{dev}:{iops}" for dev, iops in self.device_read_iops.items()
            ]
        if self.device_write_iops:
            config["device_write_iops"] = [
                f"{dev}:{iops}" for dev, iops in self.device_write_iops.items()
            ]
        
        # Process limits
        if self.pids_limit:
            config["pids_limit"] = self.pids_limit
        
        # Security and isolation
        if self.oom_score_adj is not None:
            config["oom_score_adj"] = self.oom_score_adj
        if self.read_only_rootfs:
            config["read_only"] = self.read_only_rootfs
        if self.cap_add:
            config["cap_add"] = self.cap_add
        if self.cap_drop:
            config["cap_drop"] = self.cap_drop
        if self.devices:
            config["devices"] = self.devices
        if self.device_cgroup_rules:
            config["device_cgroup_rules"] = self.device_cgroup_rules
        
        # Environment and execution
        if self.environment:
            config["environment"] = self.environment
        if self.user:
            config["user"] = self.user
        if self.group:
            config["group"] = self.group
        if self.working_dir:
            config["working_dir"] = self.working_dir
        
        # Timeouts
        if self.timeout_stop:
            config["stop_timeout"] = self.timeout_stop
        
        # Restart policy
        restart_config = {"Name": self.restart_policy}
        if self.restart_max_retries and self.restart_policy == "on-failure":
            restart_config["MaximumRetryCount"] = self.restart_max_retries
        config["restart_policy"] = restart_config
        
        return config
    
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
        
        # Memory configuration
        if self.memory_limit:
            directives["MemoryMax"] = str(self.memory_limit)
        if self.memory_high:
            directives["MemoryHigh"] = str(self.memory_high)
        elif self.memory_reservation:
            # Use reservation as high water mark
            directives["MemoryHigh"] = str(self.memory_reservation)
        if self.memory_low:
            directives["MemoryLow"] = str(self.memory_low)
        if self.memory_min:
            directives["MemoryMin"] = str(self.memory_min)
        if self.memory_swap_max:
            directives["MemorySwapMax"] = str(self.memory_swap_max)
        elif self.memory_swap_limit and self.memory_limit:
            # Calculate swap allowance
            swap_limit = self.memory_swap_limit - self.memory_limit
            if swap_limit > 0:
                directives["MemorySwapMax"] = str(swap_limit)
        
        # I/O configuration (prefer cgroup v2 directives)
        if self.io_weight:
            directives["IOWeight"] = str(self.io_weight)
        elif self.blkio_weight:
            # Convert Docker blkio-weight (10-1000) to systemd IOWeight (1-10000)
            io_weight = max(1, min(10000, int((self.blkio_weight / 1000) * 10000)))
            directives["IOWeight"] = str(io_weight)
        elif self.block_io_weight:
            directives["BlockIOWeight"] = str(self.block_io_weight)
            
        if self.device_read_bps:
            for dev, bps in self.device_read_bps.items():
                directives[f"IOReadBandwidthMax"] = f"{dev} {bps}"
        if self.device_write_bps:
            for dev, bps in self.device_write_bps.items():
                directives[f"IOWriteBandwidthMax"] = f"{dev} {bps}"
        
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
            remaining_caps = ["CAP_CHOWN", "CAP_DAC_OVERRIDE", "CAP_FOWNER", 
                             "CAP_FSETID", "CAP_KILL", "CAP_SETGID", "CAP_SETUID", 
                             "CAP_SETPCAP", "CAP_NET_BIND_SERVICE", "CAP_NET_RAW", 
                             "CAP_SYS_CHROOT", "CAP_MKNOD", "CAP_AUDIT_WRITE", 
                             "CAP_SETFCAP"]
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
        
        # Restart policy
        restart_map = {
            "no": "no",
            "on-failure": "on-failure", 
            "always": "always",
            "unless-stopped": "always"  # systemd doesn't have unless-stopped
        }
        directives["Restart"] = restart_map.get(self.restart_policy, "no")
        if self.restart_max_retries:
            directives["StartLimitBurst"] = str(self.restart_max_retries)
        if self.restart_delay:
            directives["RestartSec"] = f"{self.restart_delay}s"
        
        return directives


class UnifiedService:
    """
    Unified service that can run as either a Docker container or systemd service.
    
    When running under systemd, the systemd cgroup settings override Docker's.
    When running standalone via Docker CLI, Docker's cgroup settings apply.
    """
    
    def __init__(self, name: str, image: str, cgroup_config: CgroupConfig):
        self.name = name
        self.image = image
        self.cgroup_config = cgroup_config
        self.slice_name = f"unified-{name}.slice"
        self.service_name = f"unified-{name}.service"
        self.container_name = f"unified_{name}"
    
    def create_systemd_slice(self) -> str:
        """Create systemd slice unit with cgroup configuration."""
        slice_content = [
            "[Unit]",
            f"Description=Unified slice for {self.name}",
            "Before=slices.target",
            "",
            "[Slice]",
        ]
        
        # Add cgroup directives to slice
        directives = self.cgroup_config.to_systemd_directives()
        for key, value in directives.items():
            # Skip restart-related directives (they go in service, not slice)
            if key not in ["Restart", "StartLimitBurst", "RestartSec"]:
                slice_content.append(f"{key}={value}")
        
        slice_path = Path(f"/etc/systemd/system/{self.slice_name}")
        slice_path.write_text("\n".join(slice_content))
        return str(slice_path)
    
    def create_systemd_service(self) -> str:
        """Create systemd service unit that manages the Docker container."""
        service_content = [
            "[Unit]",
            f"Description=Unified service for {self.name}",
            "After=docker.service",
            "Requires=docker.service",
            "",
            "[Service]",
            f"Slice={self.slice_name}",
            "Type=notify",
            "NotifyAccess=all",
            "Delegate=yes",  # Critical: allows Docker to manage cgroup subtree
            "KillMode=none",  # Let Docker handle container shutdown
            "TimeoutStartSec=0",
        ]
        
        # Add restart directives to service
        directives = self.cgroup_config.to_systemd_directives()
        for key in ["Restart", "StartLimitBurst", "RestartSec"]:
            if key in directives:
                service_content.append(f"{key}={directives[key]}")
        
        # Create minimal container config (no resource limits, no restart)
        # These will be overridden by systemd slice when running under systemd
        service_content.extend([
            f"ExecStartPre=-/usr/bin/docker rm -f {self.container_name}",
            f"ExecStart=/usr/bin/docker run --rm --name {self.container_name} "
            f"--cgroup-parent={self.slice_name} "  # Key: attach to systemd slice
            f"--restart=no "  # systemd handles restart
            f"{self.image}",
            f"ExecStop=/usr/bin/docker stop {self.container_name}",
            "",
            "[Install]",
            "WantedBy=multi-user.target"
        ])
        
        service_path = Path(f"/etc/systemd/system/{self.service_name}")
        service_path.write_text("\n".join(service_content))
        return str(service_path)
    
    def create_docker_container(self, under_systemd: bool = False) -> str:
        """
        Create Docker container with appropriate cgroup configuration.
        
        Args:
            under_systemd: If True, create minimal container for systemd management.
                          If False, create full container with all Docker cgroup features.
        """
        docker_config = self.cgroup_config.to_docker_config()
        
        if under_systemd:
            # Minimal configuration - systemd slice will override
            cmd = [
                "docker", "create",
                "--name", self.container_name,
                "--cgroup-parent", self.slice_name,
                # No resource limits - inherited from slice
                # No restart policy - handled by systemd
            ]
        else:
            # Full configuration for standalone Docker usage
            cmd = [
                "docker", "create",
                "--name", self.container_name,
            ]
            
            # CPU configuration
            if "cpu_quota" in docker_config:
                cmd.extend(["--cpu-quota", str(docker_config["cpu_quota"])])
            if "cpu_period" in docker_config:
                cmd.extend(["--cpu-period", str(docker_config["cpu_period"])])
            if "cpu_shares" in docker_config:
                cmd.extend(["--cpu-shares", str(docker_config["cpu_shares"])])
            if "cpuset_cpus" in docker_config:
                cmd.extend(["--cpuset-cpus", docker_config["cpuset_cpus"]])
            
            # Memory configuration
            if "mem_limit" in docker_config:
                cmd.extend(["--memory", str(docker_config["mem_limit"])])
            if "memswap_limit" in docker_config:
                cmd.extend(["--memory-swap", str(docker_config["memswap_limit"])])
            if "mem_reservation" in docker_config:
                cmd.extend(["--memory-reservation", str(docker_config["mem_reservation"])])
            if "mem_swappiness" in docker_config:
                cmd.extend(["--memory-swappiness", str(docker_config["mem_swappiness"])])
            
            # I/O configuration
            if "blkio_weight" in docker_config:
                cmd.extend(["--blkio-weight", str(docker_config["blkio_weight"])])
            if "device_read_bps" in docker_config:
                for device_limit in docker_config["device_read_bps"]:
                    cmd.extend(["--device-read-bps", device_limit])
            if "device_write_bps" in docker_config:
                for device_limit in docker_config["device_write_bps"]:
                    cmd.extend(["--device-write-bps", device_limit])
            if "device_read_iops" in docker_config:
                for device_limit in docker_config["device_read_iops"]:
                    cmd.extend(["--device-read-iops", device_limit])
            if "device_write_iops" in docker_config:
                for device_limit in docker_config["device_write_iops"]:
                    cmd.extend(["--device-write-iops", device_limit])
            
            # Process limits
            if "pids_limit" in docker_config:
                cmd.extend(["--pids-limit", str(docker_config["pids_limit"])])
            
            # Security and isolation
            if "oom_score_adj" in docker_config:
                cmd.extend(["--oom-score-adj", str(docker_config["oom_score_adj"])])
            if "read_only" in docker_config and docker_config["read_only"]:
                cmd.append("--read-only")
            if "cap_add" in docker_config:
                for cap in docker_config["cap_add"]:
                    cmd.extend(["--cap-add", cap])
            if "cap_drop" in docker_config:
                for cap in docker_config["cap_drop"]:
                    cmd.extend(["--cap-drop", cap])
            if "devices" in docker_config:
                for device in docker_config["devices"]:
                    cmd.extend(["--device", device])
            if "device_cgroup_rules" in docker_config:
                for rule in docker_config["device_cgroup_rules"]:
                    cmd.extend(["--device-cgroup-rule", rule])
            
            # Environment and execution
            if "environment" in docker_config:
                for key, value in docker_config["environment"].items():
                    cmd.extend(["--env", f"{key}={value}"])
            if "user" in docker_config:
                cmd.extend(["--user", docker_config["user"]])
            if "group" in docker_config:
                cmd.extend(["--group-add", docker_config["group"]])
            if "working_dir" in docker_config:
                cmd.extend(["--workdir", docker_config["working_dir"]])
            
            # Timeouts
            if "stop_timeout" in docker_config:
                cmd.extend(["--stop-timeout", str(docker_config["stop_timeout"])])
            
            # Restart policy
            restart = docker_config.get("restart_policy", {})
            if restart.get("Name") != "no":
                restart_str = restart["Name"]
                if "MaximumRetryCount" in restart:
                    restart_str += f":{restart['MaximumRetryCount']}"
                cmd.extend(["--restart", restart_str])
        
        cmd.append(self.image)
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"Failed to create container: {result.stderr}")
        
        return result.stdout.strip()
    
    def deploy(self, mode: str = "unified") -> None:
        """
        Deploy the service in the specified mode.
        
        Args:
            mode: "unified" - Both systemd and Docker CLI compatible
                  "systemd" - systemd-only management
                  "docker" - Docker-only management
        """
        if mode == "unified":
            # Create both systemd units and Docker container
            # Container gets full config for Docker CLI usage
            # systemd slice overrides when started via systemd
            
            # 1. Create Docker container with full configuration
            container_id = self.create_docker_container(under_systemd=False)
            print(f"Created Docker container: {container_id}")
            
            # 2. Create systemd slice with override configuration
            slice_path = self.create_systemd_slice()
            print(f"Created systemd slice: {slice_path}")
            
            # 3. Create systemd service that starts existing container
            # Modify service to use existing container instead of creating new one
            service_content = [
                "[Unit]",
                f"Description=Unified service for {self.name}",
                "After=docker.service",
                "Requires=docker.service",
                "",
                "[Service]",
                f"Slice={self.slice_name}",
                "Type=simple",
                "Delegate=yes",
                "KillMode=none",
                "RemainAfterExit=yes",
            ]
            
            # Add restart directives
            directives = self.cgroup_config.to_systemd_directives()
            for key in ["Restart", "StartLimitBurst", "RestartSec"]:
                if key in directives:
                    service_content.append(f"{key}={directives[key]}")
            
            service_content.extend([
                # Start existing container and attach to slice cgroup
                f"ExecStart=/usr/bin/docker start {self.container_name}",
                f"ExecStartPost=/bin/bash -c 'echo $$(docker inspect -f \"{{{{.State.Pid}}}}\" {self.container_name}) > /sys/fs/cgroup/systemd/{self.slice_name}/cgroup.procs'",
                f"ExecStop=/usr/bin/docker stop {self.container_name}",
                "",
                "[Install]",
                "WantedBy=multi-user.target"
            ])
            
            service_path = Path(f"/etc/systemd/system/{self.service_name}")
            service_path.write_text("\n".join(service_content))
            print(f"Created systemd service: {service_path}")
            
            # Reload systemd
            subprocess.run(["systemctl", "daemon-reload"])
            print("Reloaded systemd daemon")
            
            print(f"\nService deployed in unified mode!")
            print(f"  Docker CLI: docker start/stop {self.container_name}")
            print(f"  systemd: systemctl start/stop {self.service_name}")
            
        elif mode == "systemd":
            # systemd-only mode
            self.create_systemd_slice()
            self.create_systemd_service()
            subprocess.run(["systemctl", "daemon-reload"])
            print(f"Service deployed in systemd-only mode")
            
        elif mode == "docker":
            # Docker-only mode
            container_id = self.create_docker_container(under_systemd=False)
            print(f"Service deployed in Docker-only mode: {container_id}")
    
    def get_active_cgroup_path(self) -> Optional[str]:
        """Get the active cgroup path for the running container."""
        try:
            result = subprocess.run(
                ["docker", "inspect", "-f", "{{.State.Pid}}", self.container_name],
                capture_output=True, text=True
            )
            if result.returncode == 0:
                pid = result.stdout.strip()
                if pid and pid != "0":
                    # Check which cgroup the process is in
                    cgroup_file = Path(f"/proc/{pid}/cgroup")
                    if cgroup_file.exists():
                        return cgroup_file.read_text()
        except Exception:
            pass
        return None
    
    def show_cgroup_info(self) -> None:
        """Display current cgroup configuration and hierarchy."""
        cgroup_path = self.get_active_cgroup_path()
        if cgroup_path:
            print(f"Container {self.container_name} cgroup hierarchy:")
            print(cgroup_path)
            
            # Check if running under systemd slice
            if self.slice_name in cgroup_path:
                print(f"\n✓ Running under systemd slice: {self.slice_name}")
                print("  → systemd cgroup limits are active (overriding Docker)")
            else:
                print("\n✓ Running under Docker cgroup")
                print("  → Docker cgroup limits are active")
        else:
            print(f"Container {self.container_name} is not running")


# Example usage
if __name__ == "__main__":
    # Define comprehensive unified cgroup configuration covering all mappings
    config = CgroupConfig(
        # CPU limits
        cpu_quota=50000,  # 50ms out of 100ms period = 50% CPU
        cpu_period=100000,  # 100ms period
        cpu_shares=512,  # Docker: 0.5 CPU weight
        cpu_weight=50,   # systemd: weight 50 (out of 100 default)
        cpuset_cpus="0,1",  # Pin to CPUs 0 and 1
        
        # Memory limits (comprehensive)
        memory_limit=1024 * 1024 * 1024,  # 1GB hard limit
        memory_high=768 * 1024 * 1024,    # 768MB high water mark (systemd)
        memory_reservation=512 * 1024 * 1024,  # 512MB soft limit (Docker)
        memory_low=256 * 1024 * 1024,     # 256MB preferred memory (systemd)
        memory_swap_limit=2 * 1024 * 1024 * 1024,  # 2GB total (Docker style)
        memory_swap_max=1024 * 1024 * 1024,        # 1GB swap allowance (systemd)
        memory_swappiness=60,  # Moderate swap tendency
        
        # I/O limits (all variants)
        blkio_weight=500,      # Docker: medium I/O weight
        io_weight=5000,        # systemd cgroup v2: medium I/O weight
        block_io_weight=500,   # systemd cgroup v1: medium I/O weight  
        device_read_bps={"/dev/sda": 100 * 1024 * 1024},   # 100MB/s read limit
        device_write_bps={"/dev/sda": 50 * 1024 * 1024},   # 50MB/s write limit
        device_read_iops={"/dev/sda": 1000},  # 1000 read operations/sec
        device_write_iops={"/dev/sda": 500},  # 500 write operations/sec
        
        # Process limits
        pids_limit=100,  # Max 100 processes/threads
        
        # Security and isolation
        oom_score_adj=100,     # Slightly prefer this process for OOM killer
        read_only_rootfs=True, # Make root filesystem read-only
        cap_drop=["NET_RAW", "SYS_ADMIN"],  # Drop dangerous capabilities
        cap_add=["NET_BIND_SERVICE"],       # Add specific capability back
        devices=["/dev/random:/dev/random:r"],  # Allow read access to /dev/random
        
        # Restart and lifecycle
        restart_policy="on-failure",
        restart_max_retries=3,
        restart_delay=10,      # 10 second delay between restarts
        timeout_start=30,      # 30 second start timeout
        timeout_stop=10,       # 10 second stop timeout
        
        # Environment and execution
        environment={
            "LOG_LEVEL": "info",
            "MAX_CONNECTIONS": "100"
        },
        user="nginx",
        working_dir="/usr/share/nginx/html"
    )
    
    # Create unified service
    service = UnifiedService(
        name="comprehensive-example",
        image="nginx:latest",
        cgroup_config=config
    )
    
    print("=== Comprehensive CgroupConfig Coverage Demo ===")
    print("\nThis example demonstrates all parameter mappings between Docker and systemd:")
    print("✓ CPU limits (quota, shares, weight, affinity)")
    print("✓ Memory limits (hard, soft, swap, swappiness)")  
    print("✓ I/O limits (weight, bandwidth, IOPS)")
    print("✓ Process limits (PIDs)")
    print("✓ Security (OOM score, capabilities, devices)")
    print("✓ Lifecycle (restart policies, timeouts)")
    print("✓ Environment (variables, user, working directory)")
    print()
    
    # Show the Docker and systemd configurations that would be generated
    print("Generated Docker configuration:")
    docker_config = config.to_docker_config()
    for key, value in docker_config.items():
        print(f"  {key}: {value}")
    
    print("\nGenerated systemd directives:")
    systemd_config = config.to_systemd_directives()
    for key, value in systemd_config.items():
        print(f"  {key}={value}")
    
    print("\nTo deploy this service:")
    print("  service.deploy(mode='unified')")
    print("  # Then use either:")
    print(f"  # docker start/stop {service.container_name}")
    print(f"  # systemctl start/stop {service.service_name}")
    
    # Uncomment to actually deploy:
    # service.deploy(mode="unified")
    # service.show_cgroup_info()