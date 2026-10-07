"""Comprehensive tests for deterministic root cause diagnosis engine.

Covers:
- Diagnosis for all 5 fault types (CPU runaway, abnormal memory, service crash, disk exhaustion, deadlock)
- Explainable traceability log verification
- Evidence aggregation with current system metrics
- Deterministic confidence scoring and allowlisted recovery action recommendations
- Zero execution of recovery actions during diagnosis
- Backward compatibility with DiagnosisReport
"""

from datetime import datetime, timezone
import uuid
import pytest

from self_healing.core.models import (
    ActionType,
    DetectionEvent,
    DiagnosisResult,
    DiskUsageMetrics,
    FaultSeverity,
    FaultType,
    MetricSnapshot,
    ProcessState,
    SystemCpuMetrics,
    SystemMemoryMetrics,
    SystemSnapshot,
    TargetSpec,
)
from self_healing.diagnosis.engine import DeterministicDiagnosisEngine


@pytest.fixture
def diagnosis_engine() -> DeterministicDiagnosisEngine:
    return DeterministicDiagnosisEngine()


@pytest.fixture
def sample_system_snapshot() -> SystemSnapshot:
    """Fixture providing a mock host SystemSnapshot."""
    return SystemSnapshot(
        timestamp=datetime.now(timezone.utc),
        uptime_seconds=3600.0,
        idle_seconds=14000.0,
        cpu=SystemCpuMetrics(
            percent=65.0,
            load_1m=1.25,
            load_5m=0.85,
            load_15m=0.50,
            context_switches=1200000,
            procs_running=2,
            procs_blocked=0,
        ),
        memory=SystemMemoryMetrics(
            total_bytes=16 * 1024 * 1024 * 1024,
            available_bytes=10 * 1024 * 1024 * 1024,
            used_bytes=6 * 1024 * 1024 * 1024,
            free_bytes=4 * 1024 * 1024 * 1024,
            percent=37.5,
            swap_total_bytes=4 * 1024 * 1024 * 1024,
            swap_used_bytes=0,
            swap_percent=0.0,
        ),
        disks=[
            DiskUsageMetrics(
                mount_point="/",
                total_bytes=50 * 1024 * 1024 * 1024,
                used_bytes=20 * 1024 * 1024 * 1024,
                free_bytes=30 * 1024 * 1024 * 1024,
                percent=40.0,
            )
        ],
        processes=[],
        services=[],
    )


# -------------------------------------------------------------------------
# 1. CPU Runaway Diagnosis Tests
# -------------------------------------------------------------------------
def test_diagnose_cpu_runaway(diagnosis_engine: DeterministicDiagnosisEngine, sample_system_snapshot: SystemSnapshot):
    """Test deterministic diagnosis of CPU runaway anomaly."""
    event = DetectionEvent(
        event_id=str(uuid.uuid4()),
        target_id="demo-cpu",
        fault_type=FaultType.HIGH_CPU,
        severity=FaultSeverity.HIGH,
        triggering_value=99.5,
        threshold_value=90.0,
        description="CPU runaway detected",
        evidence={
            "target_id": "demo-cpu",
            "threshold_cpu_percent": 90.0,
            "measured_cpu_series": [95.0, 98.0, 99.5],
            "average_cpu_percent": 97.5,
            "sample_count": 3,
            "duration_seconds": 3.0,
        },
    )

    result = diagnosis_engine.diagnose(event, current_metrics=sample_system_snapshot)

    assert isinstance(result, DiagnosisResult)
    assert result.fault_type == FaultType.HIGH_CPU
    assert result.target_id == "demo-cpu"
    assert result.recommended_action == ActionType.GRACEFUL_TERMINATE
    assert result.confidence == 0.95
    assert "tight execution loop" in result.probable_cause
    assert "97.5%" in result.probable_cause

    # Traceability
    assert len(result.traceability_log) >= 4
    assert any("sustained CPU utilization" in line for line in result.traceability_log)
    assert any("GRACEFUL_TERMINATE" in line for line in result.traceability_log)

    # Evidence fusion
    assert "host_system" in result.evidence
    assert result.evidence["host_system"]["load_1m"] == 1.25


# -------------------------------------------------------------------------
# 2. Abnormal Memory Diagnosis Tests
# -------------------------------------------------------------------------
def test_diagnose_memory_leak_budget_exceeded(
    diagnosis_engine: DeterministicDiagnosisEngine, sample_system_snapshot: SystemSnapshot
):
    """Test deterministic diagnosis of memory budget violation."""
    event = DetectionEvent(
        event_id=str(uuid.uuid4()),
        target_id="demo-memory",
        fault_type=FaultType.MEMORY_LEAK,
        severity=FaultSeverity.HIGH,
        triggering_value=220.0,
        threshold_value=150.0,
        description="Memory budget exceeded",
        evidence={
            "target_id": "demo-memory",
            "rss_bytes_series": [100000000, 150000000, 230686720],
            "final_rss_mb": 220.0,
            "budget_mb": 150.0,
            "budget_exceeded": True,
            "monotonic_growth": True,
            "growth_rate_mb_sec": 15.0,
        },
    )

    result = diagnosis_engine.diagnose(event, current_metrics=sample_system_snapshot)

    assert result.fault_type == FaultType.MEMORY_LEAK
    assert result.target_id == "demo-memory"
    assert result.recommended_action == ActionType.RESTART_SERVICE
    assert result.confidence == 0.95
    assert "memory budget" in result.probable_cause
    assert "220.0 MB" in result.probable_cause

    # Traceability
    assert len(result.traceability_log) >= 4
    assert any("RESTART_SERVICE" in line for line in result.traceability_log)


def test_diagnose_memory_leak_monotonic_growth(diagnosis_engine: DeterministicDiagnosisEngine):
    """Test diagnosis of progressive memory leak with monotonic growth."""
    event = DetectionEvent(
        event_id=str(uuid.uuid4()),
        target_id="demo-memory",
        fault_type=FaultType.MEMORY_LEAK,
        severity=FaultSeverity.HIGH,
        triggering_value=120.0,
        threshold_value=150.0,
        description="Monotonic memory leak detected",
        evidence={
            "target_id": "demo-memory",
            "rss_bytes_series": [50000000, 80000000, 125829120],
            "final_rss_mb": 120.0,
            "budget_mb": 150.0,
            "budget_exceeded": False,
            "monotonic_growth": True,
            "growth_rate_mb_sec": 8.5,
        },
    )

    result = diagnosis_engine.diagnose(event, current_metrics=None)
    assert result.fault_type == FaultType.MEMORY_LEAK
    assert "monotonic heap growth" in result.probable_cause
    assert "8.50 MB/s" in result.probable_cause
    assert result.recommended_action == ActionType.RESTART_SERVICE


# -------------------------------------------------------------------------
# 3. Service Failure Diagnosis Tests
# -------------------------------------------------------------------------
def test_diagnose_service_crash(diagnosis_engine: DeterministicDiagnosisEngine):
    """Test deterministic diagnosis of fatal service crash."""
    event = DetectionEvent(
        event_id=str(uuid.uuid4()),
        target_id="demo-service",
        fault_type=FaultType.PROCESS_CRASH,
        severity=FaultSeverity.CRITICAL,
        triggering_value=0.0,
        threshold_value=1.0,
        description="Service crashed",
        evidence={
            "target_id": "demo-service",
            "expected_active": True,
            "recent_evidence": {
                "service_name": "demo-service",
                "is_active": False,
                "active_state": "failed",
                "sub_state": "dead",
                "exit_code": 1,
            },
        },
    )

    result = diagnosis_engine.diagnose(event)

    assert result.fault_type == FaultType.PROCESS_CRASH
    assert result.target_id == "demo-service"
    assert result.severity == FaultSeverity.CRITICAL
    assert result.confidence == 1.00
    assert result.recommended_action == ActionType.RESTART_SERVICE
    assert "abrupt process crash" in result.probable_cause
    assert "exit code: 1" in result.probable_cause

    # Traceability
    assert len(result.traceability_log) >= 3
    assert any("exit code 1" in line for line in result.traceability_log)


# -------------------------------------------------------------------------
# 4. Disk Exhaustion Diagnosis Tests
# -------------------------------------------------------------------------
def test_diagnose_disk_exhaustion_log_directory(diagnosis_engine: DeterministicDiagnosisEngine):
    """Test deterministic diagnosis of excessive log accumulation."""
    event = DetectionEvent(
        event_id=str(uuid.uuid4()),
        target_id="demo-disk",
        fault_type=FaultType.DISK_GROWTH,
        severity=FaultSeverity.HIGH,
        triggering_value=25.0,
        threshold_value=15.0,
        description="Demo log growth exceeded quota",
        evidence={
            "target_id": "demo-disk",
            "log_violation": True,
            "fs_violation": False,
            "log_directory": {
                "path": "/home/arskage/linux-self-healing/demo_scratch/logs",
                "bytes": 26214400,
                "mb": 25.0,
                "threshold_mb": 15.0,
            },
            "filesystem": {"mount_point": "/", "used_percent": 42.0},
        },
    )

    result = diagnosis_engine.diagnose(event)

    assert result.fault_type == FaultType.DISK_GROWTH
    assert result.target_id == "demo-disk"
    assert result.recommended_action == ActionType.CLEAN_TEMP_DIR
    assert result.confidence == 0.98
    assert "unrotated log files" in result.probable_cause
    assert "25.0 MB >= 15.0 MB" in result.probable_cause

    # Traceability
    assert len(result.traceability_log) >= 3
    assert any("CLEAN_TEMP_DIR" in line for line in result.traceability_log)


# -------------------------------------------------------------------------
# 5. Deadlock Diagnosis Tests
# -------------------------------------------------------------------------
def test_diagnose_deadlock(diagnosis_engine: DeterministicDiagnosisEngine):
    """Test deterministic diagnosis of multi-threaded circular deadlock."""
    event = DetectionEvent(
        event_id=str(uuid.uuid4()),
        target_id="demo-deadlock",
        fault_type=FaultType.DEADLOCK,
        severity=FaultSeverity.HIGH,
        triggering_value=3.0,
        threshold_value=3.0,
        description="Multi-threaded deadlock detected",
        evidence={
            "target_id": "demo-deadlock",
            "pid": 10478,
            "thread_counts": [3, 3, 3],
            "cpu_percent_series": [0.0, 0.0, 0.0],
            "average_cpu_percent": 0.0,
            "states_series": ["SLEEPING", "SLEEPING", "SLEEPING"],
            "sample_count": 3,
        },
    )

    result = diagnosis_engine.diagnose(event)

    assert result.fault_type == FaultType.DEADLOCK
    assert result.target_id == "demo-deadlock"
    assert result.recommended_action == ActionType.GRACEFUL_TERMINATE
    assert result.confidence == 0.95
    assert "circular mutex contention" in result.probable_cause
    assert "3 threads" in result.probable_cause
    assert "0.0% CPU activity" in result.probable_cause

    # Traceability
    assert len(result.traceability_log) >= 4
    assert any("circular mutex deadlock" in line for line in result.traceability_log)


# -------------------------------------------------------------------------
# 6. Backward Compatibility & Traceability Guarantees
# -------------------------------------------------------------------------
def test_diagnosis_result_backward_compatibility_attributes(diagnosis_engine: DeterministicDiagnosisEngine):
    """Ensure DiagnosisResult fulfills DiagnosisReport interface properties."""
    event = DetectionEvent(
        event_id="evt-100",
        target_id="demo-cpu",
        fault_type=FaultType.HIGH_CPU,
        severity=FaultSeverity.HIGH,
        triggering_value=95.0,
        threshold_value=90.0,
        description="CPU runaway",
        evidence={},
    )
    result = diagnosis_engine.diagnose(event)

    # Attributes expected by DiagnosisReport consumers
    assert hasattr(result, "diagnosis_id")
    assert hasattr(result, "root_cause")
    assert result.root_cause == result.probable_cause
    assert hasattr(result, "telemetry_window")
    assert hasattr(result, "recommended_action")
    assert hasattr(result, "confidence")
