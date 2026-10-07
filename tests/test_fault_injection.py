"""Comprehensive automated tests for controlled fault injection subsystem."""

from pathlib import Path
import time
from click.testing import CliRunner
import pytest

from self_healing.cli import cli
from self_healing.core.exceptions import SecurityViolationError
from self_healing.core.models import FaultType, TargetSpec
from self_healing.fault_injection.base import StubFaultInjector
from self_healing.fault_injection.cpu import CpuRunawayInjector
from self_healing.fault_injection.deadlock import DeadlockInjector
from self_healing.fault_injection.disk import DiskGrowthInjector
from self_healing.fault_injection.manager import FaultManager
from self_healing.fault_injection.memory import MemoryGrowthInjector
from self_healing.fault_injection.service import ServiceCrashInjector


@pytest.fixture
def temp_state_dir(tmp_path: Path) -> Path:
    """Fixture providing an isolated temporary state directory for tests."""
    state_dir = tmp_path / "fault_state"
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir


@pytest.fixture
def cpu_target() -> TargetSpec:
    return TargetSpec(
        target_id="demo-cpu",
        process_name="python3",
        cmdline_substring="demo_workloads cpu_spin",
        working_dir_prefix="/home/arskage/linux-self-healing",
    )


@pytest.fixture
def memory_target() -> TargetSpec:
    return TargetSpec(
        target_id="demo-memory",
        process_name="python3",
        cmdline_substring="demo_workloads memory_leak",
        working_dir_prefix="/home/arskage/linux-self-healing",
    )


@pytest.fixture
def service_target() -> TargetSpec:
    return TargetSpec(
        target_id="demo-service",
        process_name="python3",
        cmdline_substring="demo_workloads service_worker",
        expected_port=8085,
        working_dir_prefix="/home/arskage/linux-self-healing",
    )


@pytest.fixture
def disk_target() -> TargetSpec:
    return TargetSpec(
        target_id="demo-disk",
        process_name="python3",
        cmdline_substring="demo_workloads disk_write",
        working_dir_prefix="/home/arskage/linux-self-healing",
    )


@pytest.fixture
def deadlock_target() -> TargetSpec:
    return TargetSpec(
        target_id="demo-deadlock",
        process_name="python3",
        cmdline_substring="demo_workloads deadlock_hang",
        working_dir_prefix="/home/arskage/linux-self-healing",
    )


# -------------------------------------------------------------------------
# 1. Safety and Boundary Tests
# -------------------------------------------------------------------------
def test_safety_boundary_protected_process(temp_state_dir: Path):
    """Ensure fault injector rejects targeting protected system binaries."""
    injector = CpuRunawayInjector(state_dir=temp_state_dir)
    unsafe_spec = TargetSpec(
        target_id="unsafe-systemd",
        process_name="systemd",
        cmdline_substring="systemd",
        working_dir_prefix="/home/arskage/linux-self-healing",
    )
    with pytest.raises(SecurityViolationError):
        injector.start(unsafe_spec)


def test_safety_boundary_protected_root_dir(temp_state_dir: Path):
    """Ensure fault injector rejects root filesystem directories."""
    injector = CpuRunawayInjector(state_dir=temp_state_dir)
    unsafe_spec = TargetSpec(
        target_id="unsafe-dir",
        process_name="python3",
        cmdline_substring="demo_workloads",
        working_dir_prefix="/usr/bin",
    )
    with pytest.raises(SecurityViolationError):
        injector.start(unsafe_spec)


def test_disk_safety_boundary_outside_workspace(temp_state_dir: Path, disk_target: TargetSpec):
    """Ensure disk injector rejects directories outside project workspace."""
    injector = DiskGrowthInjector(state_dir=temp_state_dir)
    with pytest.raises(SecurityViolationError):
        injector.start(disk_target, output_dir=Path("/tmp/outside_test"))


# -------------------------------------------------------------------------
# 2. Lifecycle Tests for All 5 Injectors
# -------------------------------------------------------------------------
def test_cpu_runaway_injector_lifecycle(temp_state_dir: Path, cpu_target: TargetSpec):
    """Test start -> status -> stop -> cleanup for CPU runaway injector."""
    injector = CpuRunawayInjector(state_dir=temp_state_dir)

    # Initial state should be stopped
    init_status = injector.status(cpu_target)
    assert init_status.is_running is False
    assert init_status.pid is None

    # Start fault
    start_status = injector.start(cpu_target)
    assert start_status.is_running is True
    assert start_status.pid is not None
    assert start_status.fault_name == "cpu"

    # Status check
    time.sleep(0.3)
    curr_status = injector.status(cpu_target)
    assert curr_status.is_running is True
    assert curr_status.pid == start_status.pid
    assert "cpu_percent" in curr_status.metrics

    # Stop fault
    stop_status = injector.stop(cpu_target)
    assert stop_status.is_running is False

    # Cleanup
    assert injector.cleanup(cpu_target) is True


def test_memory_growth_injector_lifecycle(temp_state_dir: Path, memory_target: TargetSpec):
    """Test start -> status -> stop -> cleanup for Memory growth injector."""
    injector = MemoryGrowthInjector(state_dir=temp_state_dir)

    # Start with small cap for quick testing
    start_status = injector.start(memory_target, max_mb=60, chunk_mb=20)
    assert start_status.is_running is True
    assert start_status.pid is not None

    time.sleep(0.6)
    curr_status = injector.status(memory_target)
    assert curr_status.is_running is True
    assert "rss_mb" in curr_status.metrics

    # Stop and clean
    stop_status = injector.stop(memory_target)
    assert stop_status.is_running is False
    assert injector.cleanup(memory_target) is True


def test_service_crash_injector_lifecycle(temp_state_dir: Path, service_target: TargetSpec):
    """Test start -> status -> stop -> cleanup for Service crash injector."""
    injector = ServiceCrashInjector(state_dir=temp_state_dir)

    # Start and crash
    start_status = injector.start(service_target, auto_crash=True)
    assert start_status.is_running is False  # Crashed immediately
    assert start_status.metrics.get("crashed") is True
    assert start_status.metrics.get("exit_code") == 1

    # Cleanup
    assert injector.cleanup(service_target) is True


def test_disk_growth_injector_lifecycle(temp_state_dir: Path, disk_target: TargetSpec, tmp_path: Path):
    """Test start -> status -> stop -> cleanup for Disk growth injector."""
    injector = DiskGrowthInjector(state_dir=temp_state_dir)
    test_log_dir = Path("/home/arskage/linux-self-healing/demo_scratch/test_logs")

    start_status = injector.start(disk_target, max_mb=10, output_dir=test_log_dir)
    assert start_status.is_running is True

    time.sleep(0.4)
    curr_status = injector.status(disk_target)
    assert curr_status.metrics.get("total_bytes", 0) > 0

    stop_status = injector.stop(disk_target)
    assert stop_status.is_running is False

    # Cleanup should remove the directory
    assert injector.cleanup(disk_target) is True
    assert not test_log_dir.exists()


def test_deadlock_injector_lifecycle(temp_state_dir: Path, deadlock_target: TargetSpec):
    """Test start -> status -> stop -> cleanup for Deadlock injector."""
    injector = DeadlockInjector(state_dir=temp_state_dir)

    start_status = injector.start(deadlock_target)
    assert start_status.is_running is True
    assert start_status.pid is not None

    time.sleep(0.4)
    curr_status = injector.status(deadlock_target)
    assert curr_status.is_running is True
    assert curr_status.metrics.get("is_hung") is True
    assert curr_status.metrics.get("num_threads", 0) >= 3

    stop_status = injector.stop(deadlock_target)
    assert stop_status.is_running is False
    assert injector.cleanup(deadlock_target) is True


# -------------------------------------------------------------------------
# 3. FaultManager Coordination Tests
# -------------------------------------------------------------------------
def test_fault_manager_targets_and_batch_operations(temp_state_dir: Path):
    """Test FaultManager registry, status query, and cleanup across all injectors."""
    mgr = FaultManager(state_dir=temp_state_dir)

    # Status of all targets
    all_statuses = mgr.status_all()
    assert len(all_statuses) == 5
    fault_names = {s.fault_name for s in all_statuses}
    assert fault_names == {"cpu", "memory", "service", "disk", "deadlock"}

    # Batch cleanup
    cleanup_results = mgr.cleanup_all()
    assert len(cleanup_results) == 5
    assert all(cleanup_results.values())


# -------------------------------------------------------------------------
# 4. CLI Execution Tests
# -------------------------------------------------------------------------
def test_cli_fault_commands():
    """Verify Click CLI commands for fault injection subsystem."""
    runner = CliRunner()

    # Help command
    result = runner.invoke(cli, ["fault", "--help"])
    assert result.exit_code == 0
    assert "cpu" in result.output
    assert "memory" in result.output
    assert "service" in result.output
    assert "disk" in result.output
    assert "deadlock" in result.output

    # Status table
    res_status = runner.invoke(cli, ["fault", "status"])
    assert res_status.exit_code == 0
    assert "DEMO FAULT INJECTION SUBSYSTEM STATUS" in res_status.output

    # Status JSON
    res_json = runner.invoke(cli, ["fault", "status", "--json"])
    assert res_json.exit_code == 0
    assert "demo-cpu" in res_json.output

    # Global cleanup
    res_clean = runner.invoke(cli, ["fault", "cleanup"])
    assert res_clean.exit_code == 0
    assert "DEMO FAULT CLEANUP REPORT" in res_clean.output
