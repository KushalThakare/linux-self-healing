"""Comprehensive test suite for Phase 8: Post-Recovery Verification Subsystem."""

import os
from pathlib import Path
import tempfile
import time
from unittest.mock import MagicMock, patch
import pytest

from click.testing import CliRunner
import psutil

from self_healing.cli import cli
from self_healing.core.models import (
    AllowedActionType,
    FaultEvent,
    FaultSeverity,
    FaultType,
    IncidentRecord,
    IncidentStatus,
    RecoveryAction,
    RecoveryResult,
    RiskLevel,
    TargetSpec,
    VerificationResult,
    VerificationStatus,
    utc_now,
)
from self_healing.guardrails.engine import SafetyGuardrailEngine
from self_healing.guardrails.registry import AllowedActionRegistry
from self_healing.incidents.store import InMemoryIncidentStore
from self_healing.recovery.executor import RecoveryExecutor
from self_healing.targets.registry import TargetRegistry
from self_healing.verification.coordinator import RemediationCoordinator
from self_healing.verification.engine import VerificationEngine
from self_healing.verification.probes.base import BaseVerificationProbe, ProbeOutcome
from self_healing.verification.probes.cpu import CpuVerificationProbe
from self_healing.verification.probes.deadlock import DeadlockVerificationProbe
from self_healing.verification.probes.disk import DiskVerificationProbe
from self_healing.verification.probes.memory import MemoryVerificationProbe
from self_healing.verification.probes.service import ServiceVerificationProbe
from self_healing.verification.retry import RetryPolicy


@pytest.fixture
def sample_target_spec() -> TargetSpec:
    return TargetSpec(
        target_id="demo-cpu",
        process_name="python3",
        cmdline_substring="cpu_spin",
        expected_port=None,
        working_dir_prefix="/home/arskage/linux-self-healing",
        max_restarts_per_window=3,
        cooldown_seconds=1.0,
        enabled=True,
    )


@pytest.fixture
def service_target_spec() -> TargetSpec:
    return TargetSpec(
        target_id="demo-service",
        process_name="python3",
        cmdline_substring="service_worker",
        expected_port=8085,
        working_dir_prefix="/home/arskage/linux-self-healing",
        max_restarts_per_window=3,
        cooldown_seconds=1.0,
        enabled=True,
    )


@pytest.fixture
def disk_target_spec(tmp_path: Path) -> TargetSpec:
    scratch_dir = tmp_path / "scratch"
    scratch_dir.mkdir(parents=True, exist_ok=True)
    return TargetSpec(
        target_id="demo-disk",
        process_name="python3",
        cmdline_substring="disk_write",
        expected_port=None,
        working_dir_prefix=str(tmp_path),
        max_restarts_per_window=3,
        cooldown_seconds=1.0,
        enabled=True,
    )


# =============================================================================
# 1. VerificationResult Model Tests
# =============================================================================
def test_verification_result_model_fields():
    """Verify that VerificationResult contains all required fields and auto-syncs."""
    res = VerificationResult(
        verification_id="ver-100",
        incident_id="inc-100",
        target_id="demo-cpu",
        verified=True,
        failed=False,
        evidence={"delta": -45.0, "sustained": True},
        verification_duration=0.4521,
        metrics_before={"cpu_percent": 95.0},
        metrics_after={"cpu_percent": 12.0},
        checks_passed=["cpu_threshold_sustained"],
        checks_failed=[],
    )

    assert res.verification_id == "ver-100"
    assert res.verified is True
    assert res.failed is False
    assert res.status == VerificationStatus.HEALTHY
    assert res.evidence["delta"] == -45.0
    assert res.verification_duration == 0.4521
    assert res.metrics_before["cpu_percent"] == 95.0
    assert res.metrics_after["cpu_percent"] == 12.0


def test_verification_result_failed_model_sync():
    """Verify failed verification correctly sets failed=True and status=FAILED."""
    res = VerificationResult(
        verification_id="ver-101",
        incident_id="inc-101",
        target_id="demo-cpu",
        verified=False,
        evidence={"reason": "CPU stayed elevated"},
        checks_passed=[],
        checks_failed=["cpu_threshold_sustained"],
    )

    assert res.verified is False
    assert res.failed is True
    assert res.status == VerificationStatus.FAILED


def test_recovery_result_mark_unsuccessful():
    """Verify RecoveryResult.mark_unsuccessful creates an immutable copy with failure status."""
    orig = RecoveryResult(
        action_id="act-1",
        target_id="demo-cpu",
        action_type=AllowedActionType.TERMINATE_DEMO_PROCESS,
        success=True,
        dry_run=False,
        execution_latency_ms=12.5,
        output_message="Process terminated",
        details={"pid": 1234},
    )
    assert orig.success is True

    failed_copy = orig.mark_unsuccessful("Post-recovery probe failed")
    assert failed_copy.success is False
    assert "Post-recovery probe failed" in failed_copy.error
    assert failed_copy.details["verification_failed"] is True
    assert failed_copy.details["failure_reason"] == "Post-recovery probe failed"
    # Original should be untouched
    assert orig.success is True


# =============================================================================
# 2. CPU Verification Probe Tests
# =============================================================================
def test_cpu_verification_probe_success(sample_target_spec: TargetSpec):
    """Test CPU probe passes when CPU is below threshold and sustained."""
    probe = CpuVerificationProbe(cpu_threshold=60.0, observation_samples=2, sample_interval=0.01)

    with patch("psutil.process_iter", return_value=[]), \
         patch("psutil.cpu_percent", return_value=15.0):
        outcome = probe.verify(
            target=sample_target_spec,
            metrics_before={"cpu_percent": 98.0},
        )

    assert outcome.passed is True
    assert "sustained below threshold" in outcome.message
    assert outcome.evidence["after_cpu_percent"] == 15.0
    assert outcome.evidence["sustained"] is True
    assert outcome.metrics_after["cpu_percent"] == 15.0


def test_cpu_verification_probe_failure_elevated_cpu(sample_target_spec: TargetSpec):
    """Test CPU probe fails when CPU remains above threshold."""
    probe = CpuVerificationProbe(cpu_threshold=50.0, observation_samples=2, sample_interval=0.01)

    with patch("psutil.process_iter", return_value=[]), \
         patch("psutil.cpu_percent", return_value=85.0):
        outcome = probe.verify(
            target=sample_target_spec,
            metrics_before={"cpu_percent": 98.0},
        )

    assert outcome.passed is False
    assert "did not sustain below threshold" in outcome.message
    assert outcome.evidence["max_observed_cpu"] == 85.0


def test_cpu_verification_probe_terminate_pid_still_alive(sample_target_spec: TargetSpec):
    """Test CPU probe fails if terminate action was executed but PID is still alive."""
    probe = CpuVerificationProbe()
    action = RecoveryAction(
        action_id="act-term",
        action_type=AllowedActionType.TERMINATE_DEMO_PROCESS,
        target=sample_target_spec.target_id,
        reason="Terminate runaway CPU",
        parameters={"pid": 99999},
    )

    mock_proc = MagicMock()
    mock_proc.is_running.return_value = True
    mock_proc.status.return_value = psutil.STATUS_RUNNING

    with patch("psutil.Process", return_value=mock_proc):
        outcome = probe.verify(target=sample_target_spec, action=action)

    assert outcome.passed is False
    assert "PID 99999 is still alive" in outcome.message


# =============================================================================
# 3. Memory Verification Probe Tests
# =============================================================================
def test_memory_verification_probe_stabilized(sample_target_spec: TargetSpec):
    """Test Memory probe passes when RSS growth is stabilized."""
    probe = MemoryVerificationProbe(sample_interval=0.01)

    mock_proc = MagicMock()
    mock_proc.is_running.return_value = True
    mock_proc.status.return_value = psutil.STATUS_RUNNING
    # Sample 1: 50MB, Sample 2: 50MB (delta = 0)
    mock_proc.memory_info.side_effect = [
        MagicMock(rss=50 * 1024 * 1024),
        MagicMock(rss=50 * 1024 * 1024),
    ]

    with patch.object(probe, "_find_target_process", return_value=mock_proc), \
         patch.object(probe, "_check_heartbeat", return_value=True):
        outcome = probe.verify(
            target=sample_target_spec,
            metrics_before={"rss_bytes": 100 * 1024 * 1024},
        )

    assert outcome.passed is True
    assert outcome.evidence["rss_stabilized"] is True
    assert outcome.evidence["growth_bytes"] == 0
    assert outcome.metrics_after["growth_bytes"] == 0


def test_memory_verification_probe_failure_continued_leak(sample_target_spec: TargetSpec):
    """Test Memory probe fails when RSS continues to grow rapidly."""
    probe = MemoryVerificationProbe(max_allowed_growth_bytes=1024 * 1024, sample_interval=0.01)

    mock_proc = MagicMock()
    mock_proc.is_running.return_value = True
    mock_proc.status.return_value = psutil.STATUS_RUNNING
    # Sample 1: 50MB, Sample 2: 60MB (delta = +10MB > 1MB limit)
    mock_proc.memory_info.side_effect = [
        MagicMock(rss=50 * 1024 * 1024),
        MagicMock(rss=60 * 1024 * 1024),
    ]

    with patch.object(probe, "_find_target_process", return_value=mock_proc), \
         patch.object(probe, "_check_heartbeat", return_value=True):
        outcome = probe.verify(
            target=sample_target_spec,
            metrics_before={"rss_bytes": 50 * 1024 * 1024},
        )

    assert outcome.passed is False
    assert outcome.evidence["rss_stabilized"] is False
    assert "RSS continuing to grow" in outcome.message


def test_memory_verification_probe_termination_action(sample_target_spec: TargetSpec):
    """Test Memory probe passes when leaking process was terminated and memory freed."""
    probe = MemoryVerificationProbe()
    action = RecoveryAction(
        action_id="act-term",
        action_type=AllowedActionType.TERMINATE_DEMO_PROCESS,
        target=sample_target_spec.target_id,
        reason="Terminate memory leak",
    )

    with patch.object(probe, "_find_target_process", return_value=None):
        outcome = probe.verify(
            target=sample_target_spec,
            action=action,
            metrics_before={"rss_bytes": 200 * 1024 * 1024},
        )

    assert outcome.passed is True
    assert outcome.evidence["rss_stabilized"] is True
    assert outcome.metrics_after["rss_bytes"] == 0


# =============================================================================
# 4. Service Verification Probe Tests
# =============================================================================
def test_service_verification_probe_success(service_target_spec: TargetSpec):
    """Test Service probe passes when process is running and HTTP returns 200 OK."""
    probe = ServiceVerificationProbe(sustain_interval=0.01)

    mock_proc = MagicMock()
    mock_proc.pid = 4321
    mock_proc.is_running.return_value = True
    mock_proc.status.return_value = psutil.STATUS_RUNNING

    with patch.object(probe, "_find_target_process", return_value=mock_proc), \
         patch.object(probe, "_probe_http_health", return_value={"tested": True, "ok": True, "status_code": 200, "latency_ms": 1.2}):
        outcome = probe.verify(target=service_target_spec)

    assert outcome.passed is True
    assert outcome.evidence["process_exists"] is True
    assert outcome.evidence["pid"] == 4321
    assert outcome.metrics_after["http_status"] == 200


def test_service_verification_probe_failure_process_dead(service_target_spec: TargetSpec):
    """Test Service probe fails when target process does not exist."""
    probe = ServiceVerificationProbe(sustain_interval=0.01)

    with patch.object(probe, "_find_target_process", return_value=None), \
         patch.object(probe, "_probe_http_health", return_value={"tested": True, "ok": False, "error": "Connection refused"}):
        outcome = probe.verify(target=service_target_spec)

    assert outcome.passed is False
    assert "target process does not exist" in outcome.message


def test_service_verification_probe_failure_http_error(service_target_spec: TargetSpec):
    """Test Service probe fails when process is running but HTTP health check fails."""
    probe = ServiceVerificationProbe(sustain_interval=0.01)

    mock_proc = MagicMock()
    mock_proc.pid = 4321
    mock_proc.is_running.return_value = True
    mock_proc.status.return_value = psutil.STATUS_RUNNING

    with patch.object(probe, "_find_target_process", return_value=mock_proc), \
         patch.object(probe, "_probe_http_health", return_value={"tested": True, "ok": False, "status_code": 500}):
        outcome = probe.verify(target=service_target_spec)

    assert outcome.passed is False
    assert "HTTP health check failed" in outcome.message


# =============================================================================
# 5. Disk Verification Probe Tests
# =============================================================================
def test_disk_verification_probe_success(disk_target_spec: TargetSpec, tmp_path: Path):
    """Test Disk probe passes when usage is reduced and growth stopped."""
    log_dir = tmp_path / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "app.log"
    log_file.write_text("dummy")  # 5 bytes

    probe = DiskVerificationProbe(sample_interval=0.01)
    action = RecoveryAction(
        action_id="act-clean",
        action_type=AllowedActionType.CLEANUP_DEMO_LOGS,
        target=disk_target_spec.target_id,
        reason="Clean logs",
        parameters={"directory": str(log_dir)},
    )

    outcome = probe.verify(
        target=disk_target_spec,
        action=action,
        metrics_before={"directory_size_bytes": 1000},  # Was 1000, now 5 bytes
    )

    assert outcome.passed is True
    assert outcome.evidence["usage_reduced"] is True
    assert outcome.evidence["growth_stopped"] is True
    assert outcome.metrics_after["bytes_reduced"] == 995


def test_disk_verification_probe_failure_growth_continues(disk_target_spec: TargetSpec, tmp_path: Path):
    """Test Disk probe fails when file size increases during the observation window."""
    probe = DiskVerificationProbe(sample_interval=0.01)
    action = RecoveryAction(
        action_id="act-clean",
        action_type=AllowedActionType.CLEANUP_DEMO_LOGS,
        target=disk_target_spec.target_id,
        reason="Clean logs",
    )

    with patch.object(probe, "_get_dir_size", side_effect=[100, 500]):
        outcome = probe.verify(
            target=disk_target_spec,
            action=action,
            metrics_before={"directory_size_bytes": 1000},
        )

    assert outcome.passed is False
    assert outcome.evidence["growth_stopped"] is False
    assert "log growth is still occurring" in outcome.message


# =============================================================================
# 6. Deadlock Verification Probe Tests
# =============================================================================
def test_deadlock_verification_probe_terminated(sample_target_spec: TargetSpec):
    """Test Deadlock probe passes when hung process is terminated."""
    probe = DeadlockVerificationProbe()
    action = RecoveryAction(
        action_id="act-term",
        action_type=AllowedActionType.TERMINATE_DEMO_PROCESS,
        target=sample_target_spec.target_id,
        reason="Terminate deadlocked process",
        parameters={"pid": 7777},
    )

    with patch("psutil.Process", side_effect=psutil.NoSuchProcess(7777)):
        outcome = probe.verify(target=sample_target_spec, action=action)

    assert outcome.passed is True
    assert outcome.evidence["terminated"] is True
    assert "terminated" in outcome.message


def test_deadlock_verification_probe_persists_failure(sample_target_spec: TargetSpec):
    """Test Deadlock probe fails if hung process is still running."""
    probe = DeadlockVerificationProbe()
    action = RecoveryAction(
        action_id="act-term",
        action_type=AllowedActionType.TERMINATE_DEMO_PROCESS,
        target=sample_target_spec.target_id,
        reason="Terminate deadlocked process",
        parameters={"pid": 7777},
    )

    mock_proc = MagicMock()
    mock_proc.is_running.return_value = True
    mock_proc.status.return_value = psutil.STATUS_RUNNING

    with patch("psutil.Process", return_value=mock_proc):
        outcome = probe.verify(target=sample_target_spec, action=action)

    assert outcome.passed is False
    assert outcome.evidence["terminated"] is False


# =============================================================================
# 7. Retry Policy Tests
# =============================================================================
def test_retry_policy_permits_retry_within_limit(sample_target_spec: TargetSpec):
    """Test RetryPolicy approves retry if retry_count < max_retries."""
    policy = RetryPolicy(default_max_retries=3, base_delay_seconds=1.0)
    action = RecoveryAction(
        action_id="act-1",
        action_type=AllowedActionType.TERMINATE_DEMO_PROCESS,
        target=sample_target_spec.target_id,
        reason="Initial attempt",
        max_retries=3,
        retry_count=1,
    )
    failed_result = VerificationResult(
        verification_id="v1",
        incident_id="inc-1",
        target_id=sample_target_spec.target_id,
        verified=False,
    )

    eval_outcome = policy.evaluate(action, failed_result)
    assert eval_outcome["should_retry"] is True
    assert eval_outcome["escalate"] is False
    assert eval_outcome["retry_count"] == 2
    assert eval_outcome["delay_seconds"] > 0

    next_act = policy.next_retry_action(action, "CPU still high")
    assert next_act.retry_count == 2
    assert "Retry 2/3" in next_act.reason


def test_retry_policy_exhaustion_triggers_escalation(sample_target_spec: TargetSpec):
    """Test RetryPolicy halts retries and marks escalation when max_retries reached."""
    policy = RetryPolicy(default_max_retries=3)
    action = RecoveryAction(
        action_id="act-3",
        action_type=AllowedActionType.TERMINATE_DEMO_PROCESS,
        target=sample_target_spec.target_id,
        reason="Third attempt",
        max_retries=3,
        retry_count=3,
    )
    failed_result = VerificationResult(
        verification_id="v3",
        incident_id="inc-3",
        target_id=sample_target_spec.target_id,
        verified=False,
    )

    eval_outcome = policy.evaluate(action, failed_result)
    assert eval_outcome["should_retry"] is False
    assert eval_outcome["escalate"] is True
    assert "limit exceeded" in eval_outcome["reason"].lower()


def test_retry_policy_no_retry_on_success(sample_target_spec: TargetSpec):
    """Test RetryPolicy does not retry when verification passed."""
    policy = RetryPolicy()
    action = RecoveryAction(
        action_id="act-ok",
        action_type=AllowedActionType.TERMINATE_DEMO_PROCESS,
        target=sample_target_spec.target_id,
        reason="First attempt",
    )
    ok_result = VerificationResult(
        verification_id="v-ok",
        incident_id="inc-ok",
        target_id=sample_target_spec.target_id,
        verified=True,
    )

    eval_outcome = policy.evaluate(action, ok_result)
    assert eval_outcome["should_retry"] is False
    assert eval_outcome["escalate"] is False


# =============================================================================
# 8. VerificationEngine Integration Tests
# =============================================================================
def test_verification_engine_dry_run_simulation(sample_target_spec: TargetSpec):
    """Test VerificationEngine produces dry-run verification result."""
    engine = VerificationEngine()
    rec_result = RecoveryResult(
        action_id="act-dry",
        target_id=sample_target_spec.target_id,
        action_type=AllowedActionType.TERMINATE_DEMO_PROCESS,
        success=True,
        dry_run=True,
        execution_latency_ms=1.0,
        output_message="Dry-run termination simulated",
    )

    result = engine.verify(
        target=sample_target_spec,
        incident_id="inc-dry",
        recovery_result=rec_result,
    )

    assert result.verified is True
    assert result.failed is False
    assert result.status == VerificationStatus.HEALTHY
    assert result.evidence["dry_run"] is True
    assert "dry_run_simulation_check" in result.checks_passed


def test_verification_engine_failure_on_failed_recovery(sample_target_spec: TargetSpec):
    """Test VerificationEngine fails immediately if the recovery action execution failed."""
    engine = VerificationEngine()
    rec_result = RecoveryResult(
        action_id="act-err",
        target_id=sample_target_spec.target_id,
        action_type=AllowedActionType.TERMINATE_DEMO_PROCESS,
        success=False,
        dry_run=False,
        execution_latency_ms=2.0,
        output_message="Command failed",
        error="Permission denied",
    )

    result = engine.verify(
        target=sample_target_spec,
        incident_id="inc-err",
        recovery_result=rec_result,
    )

    assert result.verified is False
    assert result.failed is True
    assert result.status == VerificationStatus.FAILED
    assert "recovery_execution_check" in result.checks_failed


# =============================================================================
# 9. Closed-Loop RemediationCoordinator Tests
# =============================================================================
def test_coordinator_end_to_end_verified_success(sample_target_spec: TargetSpec):
    """Test coordinator happy path: Guardrail -> Recovery -> Verification -> VERIFIED_SUCCESS."""
    store = InMemoryIncidentStore()
    target_reg = TargetRegistry()
    target_reg.register(sample_target_spec)

    coordinator = RemediationCoordinator(incident_store=store, target_registry=target_reg)

    fault = FaultEvent(
        event_id="fe-1",
        target_id=sample_target_spec.target_id,
        fault_type=FaultType.HIGH_CPU,
        severity=FaultSeverity.HIGH,
        triggering_value=95.0,
        threshold_value=80.0,
        description="CPU runaway detected",
    )
    incident = IncidentRecord(
        incident_id="inc-full-1",
        target_id=sample_target_spec.target_id,
        status=IncidentStatus.DETECTED,
        fault_event=fault,
    )
    action = RecoveryAction(
        action_id="act-full-1",
        action_type=AllowedActionType.TERMINATE_DEMO_PROCESS,
        target=sample_target_spec.target_id,
        reason="Terminate CPU runaway",
        allowed_targets=[sample_target_spec.target_id],
        parameters={"pid": 1111},
    )

    # Mock successful recovery execution and successful verification
    mock_probe = MagicMock()
    mock_probe.verify.return_value = ProbeOutcome(
        name="mock_cpu_probe",
        passed=True,
        evidence={"cpu_dropped": True},
        message="CPU normalized",
    )
    coordinator.verification_engine.register_probe(mock_probe)

    outcome_incident = coordinator.execute_and_verify(
        incident=incident,
        action=action,
        dry_run=True,
    )

    assert outcome_incident.status == IncidentStatus.VERIFIED_SUCCESS
    assert outcome_incident.policy_decision.allowed is True
    assert outcome_incident.recovery_result.success is True
    assert outcome_incident.verification_result.verified is True
    assert outcome_incident.completed_at is not None


def test_coordinator_verification_failure_marks_recovery_unsuccessful(sample_target_spec: TargetSpec):
    """Test coordinator marks recovery as unsuccessful when verification probe fails."""
    store = InMemoryIncidentStore()
    target_reg = TargetRegistry()
    target_reg.register(sample_target_spec)

    coordinator = RemediationCoordinator(incident_store=store, target_registry=target_reg)

    fault = FaultEvent(
        event_id="fe-2",
        target_id=sample_target_spec.target_id,
        fault_type=FaultType.HIGH_CPU,
        severity=FaultSeverity.HIGH,
        triggering_value=95.0,
        threshold_value=80.0,
        description="CPU runaway detected",
    )
    incident = IncidentRecord(
        incident_id="inc-full-2",
        target_id=sample_target_spec.target_id,
        status=IncidentStatus.DETECTED,
        fault_event=fault,
    )
    action = RecoveryAction(
        action_id="act-full-2",
        action_type=AllowedActionType.TERMINATE_DEMO_PROCESS,
        target=sample_target_spec.target_id,
        reason="Terminate CPU runaway",
        allowed_targets=[sample_target_spec.target_id],
        max_retries=2,
        retry_count=0,
    )

    mock_probe = MagicMock()
    mock_probe.verify.return_value = ProbeOutcome(
        name="mock_cpu_probe",
        passed=False,
        evidence={"cpu_elevated": True},
        message="CPU remained 99%",
    )
    coordinator.verification_engine.register_probe(mock_probe)

    outcome_incident = coordinator.execute_and_verify(
        incident=incident,
        action=action,
        dry_run=True,
        auto_retry=False,
    )

    # 1. Recovery must be marked unsuccessful
    assert outcome_incident.recovery_result is not None
    assert outcome_incident.recovery_result.success is False
    assert outcome_incident.recovery_result.details["verification_failed"] is True
    # 2. Verification must be marked failed
    assert outcome_incident.verification_result.verified is False
    assert outcome_incident.verification_result.failed is True
    # 3. Status marked as VERIFICATION_FAILED
    assert outcome_incident.status == IncidentStatus.VERIFICATION_FAILED


def test_coordinator_auto_retry_exhaustion_escalation(sample_target_spec: TargetSpec):
    """Test coordinator auto-retries until limit and then escalates."""
    store = InMemoryIncidentStore()
    target_reg = TargetRegistry()
    target_reg.register(sample_target_spec)

    coordinator = RemediationCoordinator(incident_store=store, target_registry=target_reg)
    coordinator.retry_policy.base_delay_seconds = 0.01

    fault = FaultEvent(
        event_id="fe-3",
        target_id=sample_target_spec.target_id,
        fault_type=FaultType.HIGH_CPU,
        severity=FaultSeverity.HIGH,
        triggering_value=95.0,
        threshold_value=80.0,
        description="CPU runaway detected",
    )
    incident = IncidentRecord(
        incident_id="inc-full-3",
        target_id=sample_target_spec.target_id,
        status=IncidentStatus.DETECTED,
        fault_event=fault,
    )
    action = RecoveryAction(
        action_id="act-full-3",
        action_type=AllowedActionType.TERMINATE_DEMO_PROCESS,
        target=sample_target_spec.target_id,
        reason="Terminate CPU runaway",
        allowed_targets=[sample_target_spec.target_id],
        max_retries=2,
        retry_count=0,
    )

    mock_probe = MagicMock()
    mock_probe.verify.return_value = ProbeOutcome(
        name="mock_cpu_probe",
        passed=False,
        evidence={"persistent_failure": True},
        message="Failure persists",
    )
    coordinator.verification_engine.register_probe(mock_probe)

    outcome_incident = coordinator.execute_and_verify(
        incident=incident,
        action=action,
        dry_run=True,
        auto_retry=True,
    )

    # When retries are exhausted, incident status must be ESCALATED
    assert outcome_incident.status == IncidentStatus.ESCALATED
    assert outcome_incident.verification_result.failed is True



# =============================================================================
# 10. CLI Verification Command Test
# =============================================================================
def test_cli_verify_command():
    """Test `python3 -m self_healing.cli verify demo-cpu` CLI command execution."""
    runner = CliRunner()
    result = runner.invoke(cli, ["verify", "demo-cpu", "--json"])
    assert result.exit_code in (0, 1)  # May exit 0 or 1 depending on live process state, but valid JSON returned
    import json
    data = json.loads(result.output)
    assert data["target_id"] == "demo-cpu"
    assert "verified" in data
    assert "failed" in data
    assert "verification_duration" in data
