"""Unit tests for Pydantic domain models and contracts."""

from datetime import datetime
import pytest
from pydantic import ValidationError

from self_healing.core.models import (
    ActionType,
    DiagnosisReport,
    FaultEvent,
    FaultSeverity,
    FaultType,
    IncidentRecord,
    IncidentStatus,
    MetricSnapshot,
    PolicyDecision,
    RecoveryResult,
    TargetSpec,
    VerificationResult,
    VerificationStatus,
    utc_now,
)


def test_metric_snapshot_bounds():
    """Verify bounds validation on MetricSnapshot."""
    # Valid snapshot
    snap = MetricSnapshot(
        system_cpu_percent=50.0,
        system_memory_percent=70.0,
        target_id="demo-web",
        target_pid=5000,
        target_cpu_percent=12.5,
    )
    assert snap.system_cpu_percent == 50.0

    # Invalid system_cpu_percent > 100
    with pytest.raises(ValidationError):
        MetricSnapshot(
            system_cpu_percent=105.0,
            system_memory_percent=50.0,
        )

    # Invalid negative cpu
    with pytest.raises(ValidationError):
        MetricSnapshot(
            system_cpu_percent=-1.0,
            system_memory_percent=50.0,
        )


def test_target_spec_validation():
    """Verify TargetSpec enforces required strings and valid port range."""
    target = TargetSpec(
        target_id="demo-service",
        process_name="python3",
        cmdline_substring="demo.py",
        expected_port=8080,
        working_dir_prefix="/home/user/project",
    )
    assert target.target_id == "demo-service"
    assert target.enabled is True

    # Invalid empty target_id
    with pytest.raises(ValidationError):
        TargetSpec(
            target_id="",
            process_name="python3",
            cmdline_substring="demo.py",
            working_dir_prefix="/tmp",
        )

    # Invalid port > 65535
    with pytest.raises(ValidationError):
        TargetSpec(
            target_id="demo",
            process_name="python3",
            cmdline_substring="demo.py",
            expected_port=70000,
            working_dir_prefix="/tmp",
        )


def test_incident_record_full_lifecycle(
    sample_fault_event: FaultEvent,
    sample_diagnosis: DiagnosisReport,
):
    """Verify assembling a complete IncidentRecord through all phases."""
    policy = PolicyDecision(
        decision_id="pol-1",
        diagnosis_id=sample_diagnosis.diagnosis_id,
        target_id="demo-test-app",
        action_type=ActionType.GRACEFUL_TERMINATE,
        allowed=True,
        is_dry_run=True,
    )
    recovery = RecoveryResult(
        action_id="rec-1",
        target_id="demo-test-app",
        action_type=ActionType.GRACEFUL_TERMINATE,
        success=True,
        dry_run=True,
        execution_latency_ms=1.5,
        output_message="Simulated termination",
    )
    verification = VerificationResult(
        verification_id="ver-1",
        incident_id="inc-1",
        target_id="demo-test-app",
        status=VerificationStatus.HEALTHY,
        checks_passed=["liveness_check"],
    )

    incident = IncidentRecord(
        incident_id="inc-1",
        target_id="demo-test-app",
        status=IncidentStatus.VERIFIED_SUCCESS,
        fault_event=sample_fault_event,
        diagnosis=sample_diagnosis,
        policy_decision=policy,
        recovery_result=recovery,
        verification_result=verification,
        completed_at=utc_now(),
    )

    assert incident.incident_id == "inc-1"
    assert incident.status == IncidentStatus.VERIFIED_SUCCESS
    assert incident.policy_decision.allowed is True
    assert incident.recovery_result.success is True
    assert incident.verification_result.status == VerificationStatus.HEALTHY
