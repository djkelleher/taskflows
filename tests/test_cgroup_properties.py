"""Property-based tests for CgroupConfig using Hypothesis.

Tests conversion accuracy between systemd and Docker cgroup parameters.
"""

import pytest
from hypothesis import given, strategies as st, assume
from taskflows.constraints import CgroupConfig


class TestCPUWeightConversion:
    """Property-based tests for CPU weight conversions."""

    @given(cpu_weight=st.integers(min_value=1, max_value=10000))
    def test_cpu_weight_to_shares_conversion(self, cpu_weight):
        """Test that cpu_weight converts to valid Docker shares."""
        config = CgroupConfig(cpu_weight=cpu_weight)

        # Convert to Docker CLI args
        docker_args = config.to_docker_cli_args()

        # Should contain --cpu-shares
        assert "--cpu-shares" in docker_args

        # Extract the shares value
        shares_idx = docker_args.index("--cpu-shares")
        shares_value = int(docker_args[shares_idx + 1])

        # Docker shares should be positive
        assert shares_value > 0

        # Verify conversion formula: (cpu_weight / 100) * 1024
        expected_shares = int((cpu_weight / 100) * 1024)
        assert shares_value == expected_shares

    @given(cpu_shares=st.integers(min_value=2, max_value=262144))
    def test_cpu_shares_to_weight_conversion(self, cpu_shares):
        """Test that cpu_shares converts to valid systemd weight."""
        config = CgroupConfig(cpu_shares=cpu_shares)

        # Convert to systemd directives
        directives = config.to_systemd_directives()

        # Should contain CPUWeight
        assert "CPUWeight" in directives

        # Extract the weight value
        weight_value = int(directives["CPUWeight"])

        # systemd weight should be in valid range
        assert 1 <= weight_value <= 10000

        # Verify conversion formula: (cpu_shares / 1024) * 100
        expected_weight = max(1, min(10000, int((cpu_shares / 1024) * 100)))
        assert weight_value == expected_weight

    @given(cpu_weight=st.integers(min_value=1, max_value=10000))
    def test_cpu_weight_roundtrip_approximation(self, cpu_weight):
        """Test that cpu_weight -> shares -> weight gives approximate original."""
        # Convert systemd weight to Docker shares
        config1 = CgroupConfig(cpu_weight=cpu_weight)
        docker_args = config1.to_docker_cli_args()
        shares_idx = docker_args.index("--cpu-shares")
        shares_value = int(docker_args[shares_idx + 1])

        # Convert Docker shares back to systemd weight
        config2 = CgroupConfig(cpu_shares=shares_value)
        directives = config2.to_systemd_directives()
        final_weight = int(directives["CPUWeight"])

        # Should be close to original (allow some rounding error)
        # For very low weights, the error might be higher due to integer division
        if cpu_weight >= 100:
            # For reasonable weights, expect <=10% error
            error_percent = abs(final_weight - cpu_weight) / cpu_weight * 100
            assert error_percent <= 10, f"Weight {cpu_weight} -> {shares_value} shares -> {final_weight} weight (error: {error_percent:.1f}%)"


class TestIOWeightConversion:
    """Property-based tests for I/O weight conversions."""

    @given(io_weight=st.integers(min_value=1, max_value=10000))
    def test_io_weight_to_blkio_conversion(self, io_weight):
        """Test that io_weight converts to valid Docker blkio-weight."""
        config = CgroupConfig(io_weight=io_weight)

        # Convert to Docker CLI args
        docker_args = config.to_docker_cli_args()

        # Should contain --blkio-weight
        assert "--blkio-weight" in docker_args

        # Extract the blkio value
        blkio_idx = docker_args.index("--blkio-weight")
        blkio_value = int(docker_args[blkio_idx + 1])

        # Docker blkio-weight must be in range 10-1000
        assert 10 <= blkio_value <= 1000

        # Verify conversion formula: io_weight / 10, clamped to [10, 1000]
        expected_blkio = max(10, min(1000, int(io_weight / 10)))
        assert blkio_value == expected_blkio

    @given(blkio_weight=st.integers(min_value=10, max_value=1000))
    def test_blkio_to_io_weight_conversion(self, blkio_weight):
        """Test that blkio_weight converts to valid systemd IOWeight."""
        config = CgroupConfig(blkio_weight=blkio_weight)

        # Convert to systemd directives
        directives = config.to_systemd_directives()

        # Should contain IOWeight
        assert "IOWeight" in directives

        # Extract the IOWeight value
        io_weight_value = int(directives["IOWeight"])

        # systemd IOWeight should be in valid range
        assert 1 <= io_weight_value <= 10000

        # Verify conversion formula: blkio_weight * 10
        expected_io_weight = max(1, min(10000, blkio_weight * 10))
        assert io_weight_value == expected_io_weight

    @given(io_weight=st.integers(min_value=100, max_value=10000))
    def test_io_weight_roundtrip(self, io_weight):
        """Test that io_weight -> blkio -> io_weight preserves value (when possible)."""
        # Convert systemd IOWeight to Docker blkio-weight
        config1 = CgroupConfig(io_weight=io_weight)
        docker_args = config1.to_docker_cli_args()
        blkio_idx = docker_args.index("--blkio-weight")
        blkio_value = int(docker_args[blkio_idx + 1])

        # Convert Docker blkio-weight back to systemd IOWeight
        config2 = CgroupConfig(blkio_weight=blkio_value)
        directives = config2.to_systemd_directives()
        final_io_weight = int(directives["IOWeight"])

        # For weights that don't get clamped, should be exact roundtrip
        # (io_weight / 10 = blkio, blkio * 10 = io_weight)
        if 100 <= io_weight <= 10000:
            # The conversion is lossy for non-multiples of 10
            expected = (io_weight // 10) * 10  # Round down to nearest 10
            assert final_io_weight == expected, f"IOWeight {io_weight} -> {blkio_value} blkio -> {final_io_weight} IOWeight"


class TestMemoryLimitCalculations:
    """Property-based tests for memory limit calculations."""

    @given(memory_limit=st.integers(min_value=1024, max_value=2**40))
    def test_memory_limit_direct_mapping(self, memory_limit):
        """Test that memory_limit maps directly to Docker --memory."""
        config = CgroupConfig(memory_limit=memory_limit)

        # Convert to Docker CLI args
        docker_args = config.to_docker_cli_args()

        # Should contain --memory
        assert "--memory" in docker_args

        # Extract the memory value
        memory_idx = docker_args.index("--memory")
        memory_value = int(docker_args[memory_idx + 1])

        # Should be exact match
        assert memory_value == memory_limit

        # Also check systemd conversion
        directives = config.to_systemd_directives()
        assert directives["MemoryMax"] == str(memory_limit)

    @given(
        memory_high=st.integers(min_value=1024, max_value=2**39),
        memory_min=st.integers(min_value=512, max_value=2**38)
    )
    def test_memory_high_precedence(self, memory_high, memory_min):
        """Test that memory_high takes precedence over memory_min."""
        assume(memory_high > memory_min)  # Reasonable assumption

        config = CgroupConfig(memory_high=memory_high, memory_min=memory_min)

        # Effective memory should be memory_high (higher limit takes precedence)
        effective = config._calculate_effective_memory_limit()
        assert effective == memory_high

    @given(
        memory_limit=st.integers(min_value=1024 * 1024, max_value=2**39),
        memory_swap_max=st.integers(min_value=1024 * 1024, max_value=2**39)
    )
    def test_swap_limit_calculation(self, memory_limit, memory_swap_max):
        """Test that swap limit is correctly calculated as memory + swap."""
        config = CgroupConfig(memory_limit=memory_limit, memory_swap_max=memory_swap_max)

        # Docker memory_swap_limit should be memory + swap
        effective_swap = config._calculate_effective_swap_limit()
        expected_swap = memory_limit + memory_swap_max

        assert effective_swap == expected_swap

    @given(
        memory_high=st.integers(min_value=1024, max_value=2**39),
        memory_low=st.integers(min_value=512, max_value=2**38)
    )
    def test_memory_reservation_precedence(self, memory_high, memory_low):
        """Test memory reservation calculation precedence."""
        config = CgroupConfig(memory_high=memory_high, memory_low=memory_low)

        # Should prefer memory_high for reservation
        reservation = config._calculate_effective_memory_reservation()
        assert reservation == memory_high


class TestCPUQuotaConversion:
    """Property-based tests for CPU quota conversions."""

    @given(
        cpu_quota=st.integers(min_value=1000, max_value=1000000),
        cpu_period=st.integers(min_value=1000, max_value=1000000)
    )
    def test_cpu_quota_to_systemd_percentage(self, cpu_quota, cpu_period):
        """Test that CPU quota converts to systemd percentage correctly."""
        assume(cpu_quota <= cpu_period * 100)  # Reasonable upper limit

        config = CgroupConfig(cpu_quota=cpu_quota, cpu_period=cpu_period)

        # Convert to systemd directives
        directives = config.to_systemd_directives()

        # Should contain CPUQuota as percentage
        assert "CPUQuota" in directives

        # Extract the percentage value
        quota_str = directives["CPUQuota"]
        assert quota_str.endswith("%")
        quota_percent = float(quota_str[:-1])

        # Verify conversion formula: (quota / period) * 100
        expected_percent = (cpu_quota / cpu_period) * 100

        # Allow small floating point error
        assert abs(quota_percent - expected_percent) < 0.1

    @given(
        cpu_quota=st.integers(min_value=10000, max_value=400000),
    )
    def test_cpu_quota_with_default_period(self, cpu_quota):
        """Test CPU quota with default 100ms period."""
        config = CgroupConfig(cpu_quota=cpu_quota)

        # Default period should be 100000 microseconds (100ms)
        assert config.cpu_period == 100000

        # Docker should get the quota and period
        docker_args = config.to_docker_cli_args()
        assert "--cpu-quota" in docker_args
        assert "--cpu-period" in docker_args

        quota_idx = docker_args.index("--cpu-quota")
        assert int(docker_args[quota_idx + 1]) == cpu_quota

        period_idx = docker_args.index("--cpu-period")
        assert int(docker_args[period_idx + 1]) == 100000


class TestDeviceLimits:
    """Property-based tests for device bandwidth limits."""

    @given(
        bps=st.integers(min_value=1024, max_value=10**9)
    )
    def test_device_read_bps_mapping(self, bps):
        """Test that device read bandwidth limits map correctly."""
        device = "/dev/sda"
        config = CgroupConfig(device_read_bps={device: bps})

        # Convert to Docker CLI args
        docker_args = config.to_docker_cli_args()

        # Should contain --device-read-bps
        assert "--device-read-bps" in docker_args

        # Find the value
        idx = docker_args.index("--device-read-bps")
        value = docker_args[idx + 1]

        # Should be in format "device:bps"
        assert value == f"{device}:{bps}"

    @given(
        iops=st.integers(min_value=10, max_value=100000)
    )
    def test_device_write_iops_mapping(self, iops):
        """Test that device write IOPS limits map correctly."""
        device = "/dev/sdb"
        config = CgroupConfig(device_write_iops={device: iops})

        # Convert to Docker CLI args
        docker_args = config.to_docker_cli_args()

        # Should contain --device-write-iops
        assert "--device-write-iops" in docker_args

        # Find the value
        idx = docker_args.index("--device-write-iops")
        value = docker_args[idx + 1]

        # Should be in format "device:iops"
        assert value == f"{device}:{iops}"


class TestProcessLimits:
    """Property-based tests for process limits."""

    @given(pids_limit=st.integers(min_value=1, max_value=1000000))
    def test_pids_limit_mapping(self, pids_limit):
        """Test that PIDs limit maps correctly to both Docker and systemd."""
        config = CgroupConfig(pids_limit=pids_limit)

        # Docker CLI args
        docker_args = config.to_docker_cli_args()
        assert "--pids-limit" in docker_args
        idx = docker_args.index("--pids-limit")
        assert int(docker_args[idx + 1]) == pids_limit

        # systemd directives
        directives = config.to_systemd_directives()
        assert "TasksMax" in directives
        assert int(directives["TasksMax"]) == pids_limit


class TestOOMScoreAdj:
    """Property-based tests for OOM score adjustment."""

    @given(oom_score=st.integers(min_value=-1000, max_value=1000))
    def test_oom_score_adj_mapping(self, oom_score):
        """Test that OOM score adjustment maps correctly."""
        config = CgroupConfig(oom_score_adj=oom_score)

        # Docker CLI args
        docker_args = config.to_docker_cli_args()
        assert "--oom-score-adj" in docker_args
        idx = docker_args.index("--oom-score-adj")
        assert int(docker_args[idx + 1]) == oom_score

        # systemd directives
        directives = config.to_systemd_directives()
        assert "OOMScoreAdjust" in directives
        assert int(directives["OOMScoreAdjust"]) == oom_score


class TestMemorySwappiness:
    """Property-based tests for memory swappiness."""

    @given(swappiness=st.integers(min_value=0, max_value=100))
    def test_memory_swappiness_mapping(self, swappiness):
        """Test that memory swappiness maps correctly."""
        config = CgroupConfig(memory_swappiness=swappiness)

        # Docker CLI args
        docker_args = config.to_docker_cli_args()
        assert "--memory-swappiness" in docker_args
        idx = docker_args.index("--memory-swappiness")
        assert int(docker_args[idx + 1]) == swappiness

        # systemd directives
        directives = config.to_systemd_directives()
        assert "MemorySwapMax" in directives or swappiness == 0
        # When swappiness is 0, systemd might disable swap
