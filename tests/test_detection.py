"""Comprehensive unit tests for deterministic rule-based fault detection.

Covers:
- True Positives (detectors fire accurately when faults occur)
- False Positives (detectors stay silent during transient spikes or normal operations)
- Boundary Conditions (empty windows, single snapshots, exact threshold values, missing fields)
- Evidence Verification (DetectionEvent evidence structure)
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import pytest

from self_healing.core.models import (
    DetectionEvent,
    DiskUsageMetrics,
    FaultSeverity,
    FaultType,
    MetricSnapshot,
    ProcessState,
    ServiceMetrics,
    TargetSpec,
)
from self_healing.detection.cpu import CpuRunawayDetector
from self_healing.detection.deadlock import DeadlockDetector
from self_healing.detection.disk import DiskExhaustionDetector
from self_healing.detection.memory import AbnormalMemoryDetector
from self_healing.detection.service import ServiceFailureDetector


@pytest.fixture
def cpu_target() -> TargetSpec:
    return TargetSpec(
        target_id="demo-cpu",
        process_name="python",
        cmdline_substring="demo_workloads cpu_spin",
        working_dir_prefix="/home/arskage/linux-self-healing",
    )


@pytest.fixture
def memory_target() -> TargetSpec:
    return TargetSpec(
        target_id="demo-memory",
        process_name="python",
        cmdline_substring="demo_workloads memory_leak",
        working_dir_prefix="/home/arskage/linux-self-healing",
    )


@pytest.fixture
def service_target() -> TargetSpec:
    return TargetSpec(
        target_id="demo-service",
        process_name="python",
        cmdline_substring="demo_workloads service_worker",
        expected_port=8085,
        working_dir_prefix="/home/arskage/linux-self-healing",
    )


@pytest.fixture
def disk_target() -> TargetSpec:
    return TargetSpec(
        target_id="demo-disk",
        process_name="python",
        cmdline_substring="demo_workloads disk_write",
        working_dir_prefix="/home/arskage/linux-self-healing",
    )


@pytest.fixture
def deadlock_target() -> TargetSpec:
    return TargetSpec(
        target_id="demo-deadlock",
        process_name="python",
        cmdline_substring="demo_workloads deadlock_hang",
        working_dir_prefix="/home/arskage/linux-self-healing",
    )


def make_snapshot(
    seconds_ago: float = 0.0,
    system_cpu: float = 10.0,
    system_mem: float = 20.0,
    target_id: str = "demo-cpu",
    target_cpu: float = 5.0,
    target_rss: int = 50 * 1024 * 1024,
    target_threads: int = 1,
    target_state: ProcessState = ProcessState.RUNNING,
    disks: list = None,
    services: list = None,
) -> MetricSnapshot:
    """Helper to generate timestamped mock telemetry snapshots."""
    now = datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)
    return MetricSnapshot(
        timestamp=now,
        system_cpu_percent=system_cpu,
        system_memory_percent=system_mem,
        target_id=target_id,
        target_pid=12345,
        target_cpu_percent=target_cpu,
        target_rss_bytes=target_rss,
        target_num_threads=target_threads,
        target_state=target_state,
        disks=disks or [],
        services=services or [],
    )


# -------------------------------------------------------------------------
# 1. CPU Runaway Detector Tests
# -------------------------------------------------------------------------
def test_cpu_runaway_true_positive(cpu_target: TargetSpec):
    """Sustained high CPU over window must fire CpuRunawayDetector."""
    detector = CpuRunawayDetector(cpu_percent_threshold=90.0, min_samples=3)

    # 3 consecutive samples >= 90% CPU
    window = [
        make_snapshot(seconds_ago=3, target_id="demo-cpu", target_cpu=95.0),
        make_snapshot(seconds_ago=2, target_id="demo-cpu", target_cpu=98.0),
        make_snapshot(seconds_ago=1, target_id="demo-cpu", target_cpu=96.5),
    ]

    event = detector.evaluate(cpu_target, window)
    assert event is not None
    assert isinstance(event, DetectionEvent)
    assert event.fault_type == FaultType.HIGH_CPU
    assert event.target_id == "demo-cpu"
    assert event.threshold_value == 90.0
    assert event.triggering_value == 96.5
    assert "measured_cpu_series" in event.evidence
    assert event.evidence["average_cpu_percent"] == 96.5


def test_cpu_runaway_false_positive_transient_spike(cpu_target: TargetSpec):
    """Single transient CPU spike must NOT fire detector."""
    detector = CpuRunawayDetector(cpu_percent_threshold=90.0, min_samples=3)

    # Spike at t=2, but drops immediately back to normal
    window = [
        make_snapshot(seconds_ago=3, target_id="demo-cpu", target_cpu=15.0),
        make_snapshot(seconds_ago=2, target_id="demo-cpu", target_cpu=99.0),
        make_snapshot(seconds_ago=1, target_id="demo-cpu", target_cpu=20.0),
    ]

    event = detector.evaluate(cpu_target, window)
    assert event is None


def test_cpu_runaway_boundary_conditions(cpu_target: TargetSpec):
    """Test boundary conditions: exact threshold equality, empty window, insufficient samples."""
    detector = CpuRunawayDetector(cpu_percent_threshold=90.0, min_samples=3)

    # Boundary: exactly 90.0% should trigger
    window_exact = [
        make_snapshot(seconds_ago=3, target_id="demo-cpu", target_cpu=90.0),
        make_snapshot(seconds_ago=2, target_id="demo-cpu", target_cpu=90.0),
        make_snapshot(seconds_ago=1, target_id="demo-cpu", target_cpu=90.0),
    ]
    assert detector.evaluate(cpu_target, window_exact) is not None

    # Empty window
    assert detector.evaluate(cpu_target, []) is None

    # Insufficient samples (2 < min_samples=3)
    window_insufficient = [
        make_snapshot(seconds_ago=2, target_id="demo-cpu", target_cpu=99.0),
        make_snapshot(seconds_ago=1, target_id="demo-cpu", target_cpu=99.0),
    ]
    assert detector.evaluate(cpu_target, window_insufficient) is None


# -------------------------------------------------------------------------
# 2. Abnormal Memory Detector Tests
# -------------------------------------------------------------------------
def test_abnormal_memory_true_positive_budget(memory_target: TargetSpec):
    """Memory budget violation must fire AbnormalMemoryDetector."""
    budget_100mb = 100 * 1024 * 1024
    detector = AbnormalMemoryDetector(budget_bytes=budget_100mb, min_samples=3)

    window = [
        make_snapshot(seconds_ago=3, target_id="demo-memory", target_rss=80 * 1024 * 1024),
        make_snapshot(seconds_ago=2, target_id="demo-memory", target_rss=95 * 1024 * 1024),
        make_snapshot(seconds_ago=1, target_id="demo-memory", target_rss=120 * 1024 * 1024),
    ]

    event = detector.evaluate(memory_target, window)
    assert event is not None
    assert isinstance(event, DetectionEvent)
    assert event.fault_type == FaultType.MEMORY_LEAK
    assert event.evidence["budget_exceeded"] is True
    assert event.evidence["final_rss_mb"] == 120.0


def test_abnormal_memory_true_positive_growth_rate(memory_target: TargetSpec):
    """Monotonic growth rate above threshold must fire even below budget."""
    detector = AbnormalMemoryDetector(
        budget_bytes=500 * 1024 * 1024,
        min_growth_rate_bytes_sec=10 * 1024 * 1024,  # 10 MB/s
        min_samples=3,
    )

    # Growth of 30MB over 2 seconds = 15 MB/s > 10 MB/s
    window = [
        make_snapshot(seconds_ago=2, target_id="demo-memory", target_rss=20 * 1024 * 1024),
        make_snapshot(seconds_ago=1, target_id="demo-memory", target_rss=35 * 1024 * 1024),
        make_snapshot(seconds_ago=0, target_id="demo-memory", target_rss=50 * 1024 * 1024),
    ]

    event = detector.evaluate(memory_target, window)
    assert event is not None
    assert event.evidence["monotonic_growth"] is True


def test_abnormal_memory_false_positive_fluctuating(memory_target: TargetSpec):
    """Normal fluctuating memory below budget must NOT fire."""
    budget_200mb = 200 * 1024 * 1024
    detector = AbnormalMemoryDetector(budget_bytes=budget_200mb, min_samples=3)

    window = [
        make_snapshot(seconds_ago=3, target_id="demo-memory", target_rss=50 * 1024 * 1024),
        make_snapshot(seconds_ago=2, target_id="demo-memory", target_rss=70 * 1024 * 1024),
        make_snapshot(seconds_ago=1, target_id="demo-memory", target_rss=60 * 1024 * 1024),  # Decreased
    ]

    event = detector.evaluate(memory_target, window)
    assert event is None


def test_abnormal_memory_boundary_conditions(memory_target: TargetSpec):
    """Test boundary conditions for memory detector."""
    budget_50mb = 50 * 1024 * 1024
    detector = AbnormalMemoryDetector(budget_bytes=budget_50mb, min_samples=3)

    # Empty window
    assert detector.evaluate(memory_target, []) is None

    # Single snapshot
    assert detector.evaluate(memory_target, [make_snapshot(target_id="demo-memory")]) is None


# -------------------------------------------------------------------------
# 3. Service Failure Detector Tests
# -------------------------------------------------------------------------
def test_service_failure_true_positive_dead_process(service_target: TargetSpec):
    """Dead process state must fire ServiceFailureDetector."""
    detector = ServiceFailureDetector(expected_active=True, min_failed_samples=1)

    window = [
        make_snapshot(
            seconds_ago=1,
            target_id="demo-service",
            target_state=ProcessState.DEAD,
        )
    ]

    event = detector.evaluate(service_target, window)
    assert event is not None
    assert isinstance(event, DetectionEvent)
    assert event.fault_type == FaultType.PROCESS_CRASH
    assert "target_state" in event.evidence["recent_evidence"]


def test_service_failure_true_positive_systemd_inactive(service_target: TargetSpec):
    """Inactive systemd unit must fire ServiceFailureDetector."""
    detector = ServiceFailureDetector(expected_active=True, min_failed_samples=1)

    failed_svc = ServiceMetrics(
        service_name="demo-service",
        is_active=False,
        active_state="failed",
        sub_state="failed",
    )
    window = [make_snapshot(seconds_ago=1, services=[failed_svc])]

    event = detector.evaluate(service_target, window)
    assert event is not None
    assert event.fault_type == FaultType.PROCESS_CRASH


def test_service_failure_false_positive_healthy_service(service_target: TargetSpec):
    """Active running service must NOT fire detector."""
    detector = ServiceFailureDetector(expected_active=True, min_failed_samples=1)

    active_svc = ServiceMetrics(
        service_name="demo-service",
        is_active=True,
        active_state="active",
        sub_state="running",
    )
    window = [
        make_snapshot(
            seconds_ago=1,
            target_id="demo-service",
            target_state=ProcessState.RUNNING,
            services=[active_svc],
        )
    ]

    event = detector.evaluate(service_target, window)
    assert event is None


def test_service_failure_boundary_conditions(service_target: TargetSpec):
    """Test boundary conditions for service detector."""
    detector = ServiceFailureDetector(min_failed_samples=2)

    # Empty window
    assert detector.evaluate(service_target, []) is None

    # Only 1 failed sample when 2 required
    window_single = [
        make_snapshot(target_id="demo-service", target_state=ProcessState.DEAD)
    ]
    assert detector.evaluate(service_target, window_single) is None


# -------------------------------------------------------------------------
# 4. Disk Exhaustion Detector Tests
# -------------------------------------------------------------------------
def test_disk_exhaustion_true_positive_filesystem_capacity(disk_target: TargetSpec):
    """Filesystem usage exceeding threshold must fire DiskExhaustionDetector."""
    detector = DiskExhaustionDetector(fs_percent_threshold=85.0)

    over_disk = DiskUsageMetrics(
        mount_point="/",
        total_bytes=100_000_000_000,
        used_bytes=90_000_000_000,
        free_bytes=10_000_000_000,
        percent=90.0,
    )
    window = [make_snapshot(seconds_ago=1, disks=[over_disk])]

    event = detector.evaluate(disk_target, window)
    assert event is not None
    assert isinstance(event, DetectionEvent)
    assert event.fault_type == FaultType.DISK_GROWTH
    assert event.evidence["fs_violation"] is True
    assert event.triggering_value == 90.0


def test_disk_exhaustion_true_positive_demo_log_dir(disk_target: TargetSpec, tmp_path: Path):
    """Monitored log directory exceeding byte threshold must fire detector."""
    dummy_log_dir = tmp_path / "logs"
    dummy_log_dir.mkdir()
    # Write 2 MB dummy file
    (dummy_log_dir / "test.log").write_bytes(b"A" * (2 * 1024 * 1024))

    # Threshold set to 1 MB
    detector = DiskExhaustionDetector(
        fs_percent_threshold=99.0,
        log_dir_bytes_threshold=1 * 1024 * 1024,
        log_dir_path=dummy_log_dir,
    )

    under_disk = DiskUsageMetrics(
        mount_point="/",
        total_bytes=100_000_000_000,
        used_bytes=30_000_000_000,
        free_bytes=70_000_000_000,
        percent=30.0,
    )
    window = [make_snapshot(seconds_ago=1, disks=[under_disk])]

    event = detector.evaluate(disk_target, window)
    assert event is not None
    assert event.evidence["log_violation"] is True


def test_disk_exhaustion_false_positive_normal_usage(disk_target: TargetSpec, tmp_path: Path):
    """Normal disk usage and small log dir must NOT fire."""
    empty_log_dir = tmp_path / "empty_logs"
    empty_log_dir.mkdir()

    detector = DiskExhaustionDetector(
        fs_percent_threshold=85.0,
        log_dir_bytes_threshold=10 * 1024 * 1024,
        log_dir_path=empty_log_dir,
    )

    normal_disk = DiskUsageMetrics(
        mount_point="/",
        total_bytes=100_000_000_000,
        used_bytes=40_000_000_000,
        free_bytes=60_000_000_000,
        percent=40.0,
    )
    window = [make_snapshot(seconds_ago=1, disks=[normal_disk])]

    event = detector.evaluate(disk_target, window)
    assert event is None


def test_disk_exhaustion_boundary_conditions(disk_target: TargetSpec):
    """Test boundary conditions for disk detector."""
    detector = DiskExhaustionDetector(fs_percent_threshold=80.0)

    # Empty window
    assert detector.evaluate(disk_target, []) is None

    # Exactly 80.0% should trigger
    exact_disk = DiskUsageMetrics(
        mount_point="/",
        total_bytes=100_000_000_000,
        used_bytes=80_000_000_000,
        free_bytes=20_000_000_000,
        percent=80.0,
    )
    assert detector.evaluate(disk_target, [make_snapshot(disks=[exact_disk])]) is not None


# -------------------------------------------------------------------------
# 5. Deadlock Detector Tests
# -------------------------------------------------------------------------
def test_deadlock_true_positive(deadlock_target: TargetSpec):
    """Multi-threaded process sleeping with 0% CPU must fire DeadlockDetector."""
    detector = DeadlockDetector(min_threads=3, max_cpu_percent=1.0, min_samples=3)

    window = [
        make_snapshot(
            seconds_ago=3,
            target_id="demo-deadlock",
            target_cpu=0.0,
            target_threads=3,
            target_state=ProcessState.SLEEPING,
        ),
        make_snapshot(
            seconds_ago=2,
            target_id="demo-deadlock",
            target_cpu=0.0,
            target_threads=3,
            target_state=ProcessState.SLEEPING,
        ),
        make_snapshot(
            seconds_ago=1,
            target_id="demo-deadlock",
            target_cpu=0.0,
            target_threads=3,
            target_state=ProcessState.SLEEPING,
        ),
    ]

    event = detector.evaluate(deadlock_target, window)
    assert event is not None
    assert isinstance(event, DetectionEvent)
    assert event.fault_type == FaultType.DEADLOCK
    assert event.triggering_value == 3.0
    assert event.evidence["target_id"] == "demo-deadlock"


def test_deadlock_false_positive_single_thread_sleeping(deadlock_target: TargetSpec):
    """Standard single-thread sleeping process (e.g. sleep 10) must NOT fire."""
    detector = DeadlockDetector(min_threads=3, max_cpu_percent=1.0, min_samples=3)

    # 1 thread only (not a circular mutex deadlock)
    window = [
        make_snapshot(
            seconds_ago=3,
            target_id="demo-deadlock",
            target_cpu=0.0,
            target_threads=1,
            target_state=ProcessState.SLEEPING,
        ),
        make_snapshot(
            seconds_ago=2,
            target_id="demo-deadlock",
            target_cpu=0.0,
            target_threads=1,
            target_state=ProcessState.SLEEPING,
        ),
        make_snapshot(
            seconds_ago=1,
            target_id="demo-deadlock",
            target_cpu=0.0,
            target_threads=1,
            target_state=ProcessState.SLEEPING,
        ),
    ]

    event = detector.evaluate(deadlock_target, window)
    assert event is None


def test_deadlock_false_positive_active_multithreaded_worker(deadlock_target: TargetSpec):
    """Multi-threaded process with active CPU utilization must NOT fire."""
    detector = DeadlockDetector(min_threads=3, max_cpu_percent=1.0, min_samples=3)

    # 4 threads, but active CPU (not hung)
    window = [
        make_snapshot(
            seconds_ago=3,
            target_id="demo-deadlock",
            target_cpu=45.0,
            target_threads=4,
            target_state=ProcessState.RUNNING,
        ),
        make_snapshot(
            seconds_ago=2,
            target_id="demo-deadlock",
            target_cpu=50.0,
            target_threads=4,
            target_state=ProcessState.RUNNING,
        ),
        make_snapshot(
            seconds_ago=1,
            target_id="demo-deadlock",
            target_cpu=48.0,
            target_threads=4,
            target_state=ProcessState.RUNNING,
        ),
    ]

    event = detector.evaluate(deadlock_target, window)
    assert event is None


def test_deadlock_boundary_conditions(deadlock_target: TargetSpec):
    """Test boundary conditions for deadlock detector."""
    detector = DeadlockDetector(min_threads=3, min_samples=3)

    # Empty window
    assert detector.evaluate(deadlock_target, []) is None

    # Exactly 3 threads, exactly 1.0% CPU should trigger
    window_exact = [
        make_snapshot(
            seconds_ago=3,
            target_id="demo-deadlock",
            target_cpu=1.0,
            target_threads=3,
            target_state=ProcessState.SLEEPING,
        ),
        make_snapshot(
            seconds_ago=2,
            target_id="demo-deadlock",
            target_cpu=1.0,
            target_threads=3,
            target_state=ProcessState.SLEEPING,
        ),
        make_snapshot(
            seconds_ago=1,
            target_id="demo-deadlock",
            target_cpu=1.0,
            target_threads=3,
            target_state=ProcessState.SLEEPING,
        ),
    ]
    assert detector.evaluate(deadlock_target, window_exact) is not None
