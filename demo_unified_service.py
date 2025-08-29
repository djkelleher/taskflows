#!/usr/bin/env python3
"""
Demo: Unified Docker and systemd Service Management

This script demonstrates how to create a service that works identically
whether started via Docker CLI or systemd, with full cgroup feature parity.
"""

import subprocess
import time
import json
from unified_service_manager import UnifiedService, CgroupConfig


def run_cmd(cmd, check=True):
    """Run command and return output."""
    print(f"→ Running: {' '.join(cmd) if isinstance(cmd, list) else cmd}")
    result = subprocess.run(cmd, shell=isinstance(cmd, str), 
                          capture_output=True, text=True)
    if check and result.returncode != 0:
        print(f"✗ Command failed: {result.stderr}")
        return None
    print(f"  {result.stdout.strip()}")
    return result.stdout.strip()


def demo_cgroup_override():
    """Demonstrate cgroup override behavior."""
    print("=== Unified Docker/systemd Service Demo ===\n")
    
    # Create service with specific resource limits
    config = CgroupConfig(
        cpu_shares=512,  # 0.5 CPU weight
        memory_limit=512 * 1024 * 1024,  # 512MB
        memory_swap_limit=1024 * 1024 * 1024,  # 1GB total (512MB swap)
        restart_policy="on-failure",
        restart_max_retries=3,
        pids_limit=50
    )
    
    service = UnifiedService(
        name="demo-app",
        image="nginx:latest",  # Simple web server for testing
        cgroup_config=config
    )
    
    print("1. Deploying service in unified mode...")
    try:
        service.deploy(mode="unified")
        print("✓ Service deployed successfully!\n")
    except Exception as e:
        print(f"✗ Deployment failed: {e}")
        return
    
    print("2. Testing Docker CLI control...")
    
    # Start via Docker CLI
    print("\n→ Starting container via Docker CLI:")
    run_cmd(["docker", "start", service.container_name])
    
    # Check cgroup info
    print("\n→ Container cgroup status when started via Docker:")
    service.show_cgroup_info()
    
    # Show Docker resource limits
    print("\n→ Docker container resource configuration:")
    inspect_output = run_cmd(["docker", "inspect", service.container_name])
    if inspect_output:
        container_info = json.loads(inspect_output)[0]
        host_config = container_info.get("HostConfig", {})
        
        print(f"  Memory Limit: {host_config.get('Memory', 'unlimited')}")
        print(f"  Memory+Swap: {host_config.get('MemorySwap', 'unlimited')}")
        print(f"  CPU Shares: {host_config.get('CpuShares', 'default')}")
        print(f"  Restart Policy: {host_config.get('RestartPolicy', {}).get('Name', 'no')}")
        print(f"  PidsLimit: {host_config.get('PidsLimit', 'unlimited')}")
    
    # Stop via Docker CLI
    print("\n→ Stopping container via Docker CLI:")
    run_cmd(["docker", "stop", service.container_name])
    
    print("\n3. Testing systemd control...")
    
    # Start via systemd
    print("\n→ Starting service via systemd:")
    run_cmd(["systemctl", "start", service.service_name])
    
    time.sleep(2)  # Allow container to start
    
    # Check cgroup info
    print("\n→ Container cgroup status when started via systemd:")
    service.show_cgroup_info()
    
    # Show systemd slice configuration
    print("\n→ systemd slice resource configuration:")
    slice_status = run_cmd(["systemctl", "show", service.slice_name])
    if slice_status:
        for line in slice_status.split('\n'):
            if any(key in line for key in ['Memory', 'CPU', 'Tasks', 'IOWeight']):
                print(f"  {line}")
    
    # Check actual cgroup values for the running container
    print("\n→ Active cgroup limits (from /sys/fs/cgroup):")
    try:
        # Get container PID
        pid_output = run_cmd(["docker", "inspect", "-f", "{{.State.Pid}}", 
                             service.container_name])
        if pid_output and pid_output != "0":
            pid = pid_output
            
            # Find cgroup path
            with open(f"/proc/{pid}/cgroup", 'r') as f:
                cgroup_info = f.read()
                print(f"  Process cgroup hierarchy:\n{cgroup_info}")
                
            # Check memory limit in cgroup
            cgroup_path = f"/sys/fs/cgroup/systemd/{service.slice_name}"
            try:
                with open(f"{cgroup_path}/memory.max", 'r') as f:
                    memory_max = f.read().strip()
                    print(f"  Active memory.max: {memory_max}")
            except FileNotFoundError:
                print("  Note: cgroup v2 or different path structure")
                
    except Exception as e:
        print(f"  Could not read cgroup info: {e}")
    
    # Stop via systemd
    print("\n→ Stopping service via systemd:")
    run_cmd(["systemctl", "stop", service.service_name])
    
    print("\n4. Demonstrating the difference...")
    print("""
Key Insights:

1. **Docker CLI Mode**: Container uses its own cgroup with Docker-defined limits
   - Memory limit: 512MB (as configured in Docker)
   - CPU shares: 512 (Docker cgroup)
   - Restart policy: handled by Docker daemon

2. **systemd Mode**: Container's cgroup becomes child of systemd slice  
   - Memory limit: 512MB (enforced by systemd slice - overrides Docker)
   - CPU shares: systemd weight conversion (overrides Docker)
   - Restart policy: handled by systemd service manager

3. **cgroup Hierarchy**: 
   - Docker CLI: /docker/container_id/
   - systemd: /systemd/unified-demo-app.slice/docker/container_id/
   
   The systemd slice acts as parent cgroup and its limits take precedence!

This solves your problem: 
- Users can control containers normally via Docker CLI with expected Docker features
- When started via systemd, systemd's more advanced features take over
- Same container, same configuration, different cgroup parent = different behavior
""")
    
    print("\n5. Cleanup...")
    run_cmd(["docker", "rm", "-f", service.container_name], check=False)
    run_cmd(["systemctl", "disable", service.service_name], check=False)
    run_cmd(["rm", "-f", f"/etc/systemd/system/{service.service_name}"], check=False)
    run_cmd(["rm", "-f", f"/etc/systemd/system/{service.slice_name}"], check=False)
    run_cmd(["systemctl", "daemon-reload"])
    
    print("✓ Demo completed and cleaned up!")


if __name__ == "__main__":
    demo_cgroup_override()