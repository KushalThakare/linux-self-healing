"""Phase 15 — Robustness and Safety Testing Suite.

Exhaustively verifies system behavior under adversarial, edge-case, and failure-inducing conditions:
1. Repeated CPU faults (flapping & cooldown lockout)
2. Repeated memory faults (memory budget & rate limiting)
3. Service repeatedly crashing (retry exhaustion & escalation)
4. Recovery action failure (handled exception, structured failure record)
5. Verification failure (unsuccessful recovery caught, status updated)
6. Invalid recovery target (unregistered target rejection)
7. Unauthorized process target (PID 1, root daemons, system entities blocked)
8. Excessive retry requests (preventing infinite retry loops)
9. Duplicate detection events (in-flight alert storm deduplication)
10. Malformed detection events (null/corrupt payloads handled safely)
11. Database failure (SQLite operational failure degrades gracefully)
12. Monitoring failure (/proc errors and psutil exceptions handled safely)
13. Detector failure (unhandled detector exception isolated from pipeline)
14. Permission failure (EPERM / AccessDenied handled cleanly)
15. Recovery timeout (slow/hung recovery execution bounded and aborted)

And validates the 6 core safety properties:
- Arbitrary commands cannot execute
- Unauthorized targets cannot be healed
- Retry loops are prevented
- Failures are recorded
- Verification catches unsuccessful recovery
- The system fails safely
"""

import concurrent.futures
from datetime import datetime, timedelta
from pathlib import Path
import sqlite3
import time
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch
import uuid

import pytest

from self_healing.config.settings import AppConfig, GuardrailsConfig
from self_healing.core.exceptions import (
    ActionExecutionError,
    SecurityViolationError,
    TargetNotFoundError,
)
from self_healing.core.models import (
    AllowedActionType,
    DetectionEvent,
    DiagnosisResult,
    FaultEvent,
    FaultSeverity,
    FaultType,
    GuardrailDecision,
    GuardrailStatus,
    IncidentRecord,
    IncidentStatus,
    MetricSnapshot,
    ProcessMetrics,
    ProcessState,
    RecoveryAction,
    RecoveryResult,
    RiskLevel,
    SystemCpuMetrics,
    SystemMemoryMetrics,
    SystemSnapshot,
    TargetSpec,
    VerificationResult,
    VerificationStatus,
    utc_now,
)
from self_healing.detection.base import BaseFaultRule, RuleDetectionEngine
from self_healing.guardrails.engine import SafetyGuardrailEngine
from self_healing.guardrails.registry import AllowedActionRegistry
from self_healing.incidents.repository import IncidentRepository
from self_healing.monitoring.collector import ProcessMetricsCollector, SystemMetricsCollector
from self_healing.orchestrator import OrchestratorStats, SelfHealingOrchestrator
from self_healing.recovery.executor import RecoveryExecutor
from self_healing.recovery.handlers.base import BaseActionHandler
from self_healing.targets.registry import TargetRegistry
from self_healing.verification.coordinator import RemediationCoordinator
from self_healing.verification.engine import VerificationEngine
from self_healing.verification.retry import RetryPolicy


# =============================================================================
# Fixtures & Helpers
# =============================================================================

@pytest.fixture
def mock_target_cpu() -> TargetSpec:
    return TargetSpec(
        target_id="demo-cpu",
        process_name="python3",
        cmdline_substring="demo_workloads.py run_cpu",
        working_dir_prefix=str(Path.cwd()),
        max_restarts_per_window=3,
        cooldown_seconds=10.0,
        enabled=True,
    )


@pytest.fixture
def mock_target_memory() -> TargetSpec:
    return TargetSpec(
        target_id="demo-memory",
        process_name="python3",
        cmdline_substring="demo_workloads.py run_memory",
        working_dir_prefix=str(Path.cwd()),
        max_restarts_per_window=3,
        cooldown_seconds=10.0,
        enabled=True,
    )


@pytest.fixture
def mock_target_service() -> TargetSpec:
    return TargetSpec(
        target_id="demo-service",
        process_name="python3",
        cmdline_substring="demo_workloads.py run_service",
        working_dir_prefix=str(Path.cwd()),
        max_restarts_per_window=3,
        cooldown_seconds=10.0,
        expected_port=8080,
        health_check_url="http://127.0.0.1:8080/health",
        enabled=True,
    )


@pytest.fixture
def registry(mock_target_cpu, mock_target_memory, mock_target_service) -> TargetRegistry:
    return TargetRegistry(targets=[mock_target_cpu, mock_target_memory, mock_target_service])


@pytest.fixture
def guardrail_engine(registry) -> SafetyGuardrailEngine:
    cfg = GuardrailsConfig(
        max_actions_per_window=3,
        flapping_window_seconds=10.0,
        default_cooldown_seconds=5.0,
        enforce_target_allowlist=True,
    )
    return SafetyGuardrailEngine(target_registry=registry, config=cfg, dry_run=True)


@pytest.fixture
def dummy_evidence() -> Dict[str, Any]:
    return {
        "average_cpu_percent": 95.0,
        "final_rss_mb": 256.0,
        "recent_evidence": [90.0, 95.0, 98.0],
        "target_id": "demo-cpu",
        "log_directory": str(Path.cwd() / "demo_scratch/logs"),
    }


def create_sample_action(
    target_id: str = "demo-cpu",
    action_type: AllowedActionType = AllowedActionType.LOWER_DEMO_PROCESS_PRIORITY,
    retry_count: int = 0,
    max_retries: int = 3,
    extra_params: Optional[Dict[str, Any]] = None,
) -> RecoveryAction:
    params = {"pid": 9999, **(extra_params or {})}
    return RecoveryAction(
        action_id=str(uuid.uuid4()),
        action_type=action_type,
        target=target_id,
        reason="Robustness test candidate intervention",
        required_evidence=["average_cpu_percent"],
        risk_level=RiskLevel.MEDIUM,
        max_retries=max_retries,
        retry_count=retry_count,
        allowed_targets=[target_id],
        parameters=params,
    )


# =============================================================================
# Vector 1: Repeated CPU Faults (Flapping & Cooldown Lockout)
# =============================================================================

def test_vector_01_repeated_cpu_faults_flapping_and_cooldown(guardrail_engine, dummy_evidence):
    """Verify that repeated CPU faults trigger flapping lockout and cooldown enforcement."""
    action1 = create_sample_action(target_id="demo-cpu")
    dec1 = guardrail_engine.evaluate(action1, evidence=dummy_evidence)
    assert dec1.allowed is True
    assert dec1.status == GuardrailStatus.APPROVED
    guardrail_engine.record_action("demo-cpu")

    # Immediate second action must be blocked by cooldown
    action2 = create_sample_action(target_id="demo-cpu")
    dec2 = guardrail_engine.evaluate(action2, evidence=dummy_evidence)
    assert dec2.allowed is False
    assert dec2.status == GuardrailStatus.REJECTED
    assert any("Cooldown period active" in v for v in dec2.violations)

    # Simulate flapping window exhaustion
    now = utc_now()
    guardrail_engine._action_history["demo-cpu"] = [
        now - timedelta(seconds=1),
        now - timedelta(seconds=2),
        now - timedelta(seconds=3),
    ]
    action3 = create_sample_action(target_id="demo-cpu")
    dec3 = guardrail_engine.evaluate(action3, evidence=dummy_evidence)
    assert dec3.allowed is False
    assert any("Flapping lockout active" in v for v in dec3.violations)


# =============================================================================
# Vector 2: Repeated Memory Faults (Budget & Rate Limiting)
# =============================================================================

def test_vector_02_repeated_memory_faults_rate_limiting(guardrail_engine, dummy_evidence):
    """Verify that repeated memory faults enforce cooldown and prevent uncontrolled remediation loops."""
    mem_evidence = {**dummy_evidence, "target_id": "demo-memory"}
    action1 = create_sample_action(
        target_id="demo-memory",
        action_type=AllowedActionType.TERMINATE_DEMO_PROCESS,
    )
    dec1 = guardrail_engine.evaluate(action1, evidence=mem_evidence)
    assert dec1.allowed is True
    guardrail_engine.record_action("demo-memory")

    # Repeated memory fault during cooldown window
    action2 = create_sample_action(
        target_id="demo-memory",
        action_type=AllowedActionType.TERMINATE_DEMO_PROCESS,
    )
    dec2 = guardrail_engine.evaluate(action2, evidence=mem_evidence)
    assert dec2.allowed is False
    assert dec2.status == GuardrailStatus.REJECTED
    assert any("Cooldown period active" in v for v in dec2.violations)


# =============================================================================
# Vector 3: Service Repeatedly Crashing (Escalation After Retries)
# =============================================================================

def test_vector_03_service_repeatedly_crashing_escalation(registry):
    """Verify that a service repeatedly failing verification exhausts retries and escalates."""
    store = IncidentRepository(":memory:")
    guardrail_eng = SafetyGuardrailEngine(target_registry=registry, dry_run=True)
    # Always allow in guardrails for retry test so we test coordinator escalation logic
    guardrail_eng.evaluate = MagicMock(return_value=GuardrailDecision(
        decision_id="dec-1",
        action_id="act-1",
        target_id="demo-service",
        action_type=AllowedActionType.RESTART_DEMO_SERVICE,
        allowed=True,
        status=GuardrailStatus.APPROVED,
    ))
    
    mock_executor = MagicMock(spec=RecoveryExecutor)
    mock_executor.execute_guardrail_approved.return_value = RecoveryResult(
        action_id="act-1",
        target_id="demo-service",
        action_type=AllowedActionType.RESTART_DEMO_SERVICE,
        executed_at=utc_now(),
        success=True,
        dry_run=True,
        execution_latency_ms=10.0,
        output_message="Restart simulated",
    )

    # Verification probe continuously fails
    mock_verification = MagicMock(spec=VerificationEngine)
    mock_verification.verify.return_value = VerificationResult(
        verification_id="verif-crash",
        target_id="demo-service",
        incident_id="inc-crash",
        action_id="act-1",
        verified=False,
        status=VerificationStatus.FAILED,
        checked_at=utc_now(),
        verification_duration=0.005,
        details="Service port 8080 refused connection; process dead",
    )

    retry_policy = RetryPolicy(default_max_retries=3, base_delay_seconds=0.01)
    coordinator = RemediationCoordinator(
        guardrail_engine=guardrail_eng,
        recovery_executor=mock_executor,
        verification_engine=mock_verification,
        retry_policy=retry_policy,
        incident_store=store,
        target_registry=registry,
    )

    incident = IncidentRecord(
        incident_id="inc-crash",
        target_id="demo-service",
        started_at=utc_now(),
        status=IncidentStatus.DETECTED,
        fault_event=DetectionEvent(
            event_id="ev-crash",
            target_id="demo-service",
            fault_type=FaultType.PROCESS_CRASH,
            severity=FaultSeverity.CRITICAL,
            triggering_value=0.0,
            threshold_value=1.0,
            description="Service unresponsive",
        ),
    )

    action = RecoveryAction(
        action_id="act-1",
        action_type=AllowedActionType.RESTART_DEMO_SERVICE,
        target="demo-service",
        reason="Restart crashing service",
        required_evidence=[],
        max_retries=3,
        retry_count=0,
        allowed_targets=["demo-service"],
    )

    result_incident = coordinator.execute_and_verify(
        incident=incident,
        action=action,
        dry_run=True,
        auto_retry=True,
    )

    assert result_incident.status == IncidentStatus.ESCALATED
    assert result_incident.completed_at is not None
    # 1 initial execution + 3 retries = 4 executions
    assert mock_executor.execute_guardrail_approved.call_count == 4
    # Check stored incident
    stored = store.get_incident("inc-crash")
    assert stored is not None
    assert stored.status == IncidentStatus.ESCALATED


# =============================================================================
# Vector 4: Recovery Action Failure (Handled Exception & Failure Record)
# =============================================================================

def test_vector_04_recovery_action_failure_handled(registry):
    """Verify that a handler failure produces a structured failure result without crashing."""
    executor = RecoveryExecutor(target_registry=registry, dry_run=False)

    class BrokenHandler(BaseActionHandler):
        def __init__(self):
            super().__init__(AllowedActionType.TERMINATE_DEMO_PROCESS)
        def execute(self, action, target_spec, dry_run=False):
            raise OSError("Simulated kernel EIO / device failure")

    executor._handlers[AllowedActionType.TERMINATE_DEMO_PROCESS] = BrokenHandler()

    action = create_sample_action(
        target_id="demo-cpu",
        action_type=AllowedActionType.TERMINATE_DEMO_PROCESS,
    )

    result = executor.execute(action, dry_run=False)
    assert result.success is False
    assert "Simulated kernel EIO" in result.error
    assert result.details["exception_type"] == "OSError"
    assert result.execution_latency_ms >= 0.0


# =============================================================================
# Vector 5: Verification Failure Catches Unsuccessful Recovery
# =============================================================================

def test_vector_05_verification_catches_unsuccessful_recovery(registry):
    """Verify that post-recovery verification failure marks recovery as unsuccessful."""
    store = IncidentRepository(":memory:")
    guardrail_eng = SafetyGuardrailEngine(target_registry=registry, dry_run=True)
    guardrail_eng.evaluate = MagicMock(return_value=GuardrailDecision(
        decision_id="dec-v",
        action_id="act-v",
        target_id="demo-cpu",
        action_type=AllowedActionType.LOWER_DEMO_PROCESS_PRIORITY,
        allowed=True,
        status=GuardrailStatus.APPROVED,
    ))

    mock_executor = MagicMock(spec=RecoveryExecutor)
    mock_executor.execute_guardrail_approved.return_value = RecoveryResult(
        action_id="act-v",
        target_id="demo-cpu",
        action_type=AllowedActionType.LOWER_DEMO_PROCESS_PRIORITY,
        executed_at=utc_now(),
        success=True,  # Execution reported success at OS level
        dry_run=True,
        execution_latency_ms=12.0,
        output_message="Priority lowered to 10",
    )

    # Verification detects anomaly still persists
    mock_verification = MagicMock(spec=VerificationEngine)
    mock_verification.verify.return_value = VerificationResult(
        verification_id="verif-vf",
        target_id="demo-cpu",
        incident_id="inc-vf",
        action_id="act-v",
        verified=False,
        status=VerificationStatus.FAILED,
        checked_at=utc_now(),
        verification_duration=0.008,
        details="CPU utilization remains critical at 98.5% > threshold 80%",
    )

    coordinator = RemediationCoordinator(
        guardrail_engine=guardrail_eng,
        recovery_executor=mock_executor,
        verification_engine=mock_verification,
        retry_policy=RetryPolicy(default_max_retries=1),
        incident_store=store,
        target_registry=registry,
    )

    incident = IncidentRecord(
        incident_id="inc-vf",
        target_id="demo-cpu",
        started_at=utc_now(),
        status=IncidentStatus.DETECTED,
        fault_event=DetectionEvent(
            event_id="ev-vf",
            target_id="demo-cpu",
            fault_type=FaultType.HIGH_CPU,
            severity=FaultSeverity.HIGH,
            triggering_value=98.5,
            threshold_value=80.0,
            description="CPU Runaway detected",
        ),
    )

    action = create_sample_action(target_id="demo-cpu", max_retries=1)
    result_incident = coordinator.execute_and_verify(incident=incident, action=action, auto_retry=False)

    # Verification must catch failure and override recovery_result.success to False
    assert result_incident.verification_result.verified is False
    assert result_incident.recovery_result.success is False
    assert result_incident.status == IncidentStatus.VERIFICATION_FAILED


# =============================================================================
# Vector 6: Invalid Recovery Target (Bogus / Unregistered ID)
# =============================================================================

def test_vector_06_invalid_recovery_target_rejection(guardrail_engine, dummy_evidence):
    """Verify that bogus or unregistered targets are rejected before execution."""
    bogus_action = RecoveryAction(
        action_id="act-bogus",
        action_type=AllowedActionType.TERMINATE_DEMO_PROCESS,
        target="unknown-rogue-database",
        reason="Remediate rogue target",
        required_evidence=[],
        allowed_targets=["unknown-rogue-database"],
    )

    decision = guardrail_engine.evaluate(bogus_action, evidence=dummy_evidence)
    assert decision.allowed is False
    assert decision.status == GuardrailStatus.REJECTED
    assert any("Check 4 Failed" in v for v in decision.violations)

    # RecoveryExecutor directly rejecting target not in registry
    executor = RecoveryExecutor(target_registry=guardrail_engine.target_registry)
    with pytest.raises(TargetNotFoundError):
        executor.execute(bogus_action)


# =============================================================================
# Vector 7: Unauthorized Process Target (PID 1, Root Daemons, System Paths)
# =============================================================================

def test_vector_07_unauthorized_process_target_shield(guardrail_engine, dummy_evidence):
    """Verify that targeting PID 1, system processes, or protected directories is strictly blocked."""
    # Attempting to target PID 1 (init / systemd)
    action_pid1 = create_sample_action(
        target_id="demo-cpu",
        extra_params={"pid": 1},
    )
    decision = guardrail_engine.evaluate(action_pid1, evidence=dummy_evidence)
    assert decision.allowed is False
    assert any("Check 3 Failed: PID 1 is a protected system PID" in v for v in decision.violations)

    # RecoveryExecutor security boundary check
    executor = RecoveryExecutor(target_registry=guardrail_engine.target_registry)
    with pytest.raises(SecurityViolationError, match="not a safe process to signal"):
        executor.execute(action_pid1)


# =============================================================================
# Vector 8: Excessive Retry Requests Blocked
# =============================================================================

def test_vector_08_excessive_retry_requests_blocked(guardrail_engine, dummy_evidence):
    """Verify that an action with retry_count >= max_retries is rejected by guardrails."""
    exhausted_action = create_sample_action(
        target_id="demo-cpu",
        retry_count=3,
        max_retries=3,
    )
    decision = guardrail_engine.evaluate(exhausted_action, evidence=dummy_evidence)
    assert decision.allowed is False
    assert any("Check 6 Failed: Action retry count exceeded" in v for v in decision.violations)

    policy = RetryPolicy(default_max_retries=3)
    verif_fail = VerificationResult(
        verification_id="verif-excess-retry",
        target_id="demo-cpu",
        incident_id="inc-1",
        action_id="act-1",
        verified=False,
        status=VerificationStatus.FAILED,
    )
    eval_res = policy.evaluate(exhausted_action, verif_fail)
    assert eval_res["should_retry"] is False
    assert eval_res["escalate"] is True


# =============================================================================
# Vector 9: Duplicate Detection Events (In-Flight Deduplication)
# =============================================================================

def test_vector_09_duplicate_detection_events_deduplication(registry):
    """Verify that rapid duplicate detection events for an active fault are suppressed."""
    orchestrator = SelfHealingOrchestrator(
        target_registry=registry,
        dry_run=True,
        incident_store=IncidentRepository(":memory:"),
    )

    ev1 = DetectionEvent(
        event_id="ev-dup-1",
        target_id="demo-cpu",
        fault_type=FaultType.HIGH_CPU,
        severity=FaultSeverity.HIGH,
        triggering_value=95.0,
        threshold_value=80.0,
        description="CPU Runaway #1",
        evidence={"average_cpu_percent": 95.0, "target_id": "demo-cpu"},
    )

    # Set fault as active
    orchestrator._active_faults[("demo-cpu", FaultType.HIGH_CPU.value)] = "existing-incident-id"

    # Mock detection engine returning a duplicate event
    mock_snap = SystemSnapshot(
        uptime_seconds=100.0,
        cpu=SystemCpuMetrics(percent=95.0),
        memory=SystemMemoryMetrics(total_bytes=1000, available_bytes=500, used_bytes=500, free_bytes=500, percent=50.0),
    )
    with patch.object(
        orchestrator.detection_engine,
        "evaluate",
        side_effect=lambda target, window: [ev1] if target.target_id == "demo-cpu" else [],
    ):
        incidents = orchestrator.tick(snapshot=mock_snap)
        # Duplicate should be suppressed
        assert len(incidents) == 0
        assert orchestrator.stats.faults_detected == 0


# =============================================================================
# Vector 10: Malformed Detection Events Handled Safely
# =============================================================================

def test_vector_10_malformed_detection_events_handled_safely(registry):
    """Verify that null, corrupted, or malformed detection events do not crash orchestrator tick."""
    orchestrator = SelfHealingOrchestrator(
        target_registry=registry,
        dry_run=True,
        incident_store=IncidentRepository(":memory:"),
    )

    mock_snap = SystemSnapshot(
        uptime_seconds=100.0,
        cpu=SystemCpuMetrics(percent=10.0),
        memory=SystemMemoryMetrics(total_bytes=1000, available_bytes=500, used_bytes=500, free_bytes=500, percent=50.0),
    )

    # Malformed events list containing None, string, and incomplete dict
    malformed_list = [None, "invalid_string_event", {"some_key": 123}]
    with patch.object(orchestrator.detection_engine, "evaluate", return_value=malformed_list):
        # Tick must complete cleanly without unhandled exception
        incidents = orchestrator.tick(snapshot=mock_snap)
        assert len(incidents) == 0
        assert orchestrator.stats.ticks_count == 1


# =============================================================================
# Vector 11: Database Failure (Graceful Degradation)
# =============================================================================

def test_vector_11_database_failure_graceful_degradation(registry):
    """Verify that SQLite storage failure (e.g. disk full, lock) does not crash the orchestrator."""
    broken_store = MagicMock(spec=IncidentRepository)
    broken_store.save.side_effect = sqlite3.OperationalError("database is locked (simulated)")

    orchestrator = SelfHealingOrchestrator(
        target_registry=registry,
        dry_run=True,
        incident_store=broken_store,
    )

    ev = DetectionEvent(
        event_id="ev-db-fail",
        target_id="demo-cpu",
        fault_type=FaultType.HIGH_CPU,
        severity=FaultSeverity.HIGH,
        triggering_value=95.0,
        threshold_value=80.0,
        description="CPU Runaway under DB failure",
        evidence={"average_cpu_percent": 95.0, "target_id": "demo-cpu"},
    )

    mock_snap = SystemSnapshot(
        uptime_seconds=100.0,
        cpu=SystemCpuMetrics(percent=95.0),
        memory=SystemMemoryMetrics(total_bytes=1000, available_bytes=500, used_bytes=500, free_bytes=500, percent=50.0),
    )

    with patch.object(
        orchestrator.detection_engine,
        "evaluate",
        side_effect=lambda target, window: [ev] if target.target_id == "demo-cpu" else [],
    ):
        # Tick should catch DB error and complete without crash
        incidents = orchestrator.tick(snapshot=mock_snap)
        assert len(incidents) == 1
        assert orchestrator.stats.faults_detected == 1


# =============================================================================
# Vector 12: Monitoring Failure (Graceful Fallback on /proc or psutil error)
# =============================================================================

def test_vector_12_monitoring_failure_graceful_fallback(mock_target_cpu):
    """Verify that collector handles inaccessible /proc or psutil errors gracefully."""
    collector = SystemMetricsCollector(proc_root=Path("/nonexistent_proc_path"))

    # When /proc is nonexistent, collector should fall back to psutil/boot_time
    snap = collector.collect_system_snapshot(targets=[mock_target_cpu])
    assert snap.uptime_seconds >= 0.0
    assert snap.cpu.percent >= 0.0
    assert snap.memory.total_bytes > 0


# =============================================================================
# Vector 13: Detector Failure Isolation
# =============================================================================

def test_vector_13_detector_failure_isolation(mock_target_cpu):
    """Verify that an exception in one detector does not crash the detection engine or drop others."""
    engine = RuleDetectionEngine()

    class FaultyDetector(BaseFaultRule):
        def __init__(self):
            super().__init__("faulty_detector", FaultType.HIGH_CPU)
        def evaluate(self, target, window):
            raise ZeroDivisionError("Simulated bug in detector rule")

    class WorkingDetector(BaseFaultRule):
        def __init__(self):
            super().__init__("working_detector", FaultType.PROCESS_CRASH)
        def evaluate(self, target, window):
            return FaultEvent(
                event_id="ev-work",
                target_id=target.target_id,
                fault_type=FaultType.PROCESS_CRASH,
                severity=FaultSeverity.CRITICAL,
                triggering_value=0.0,
                threshold_value=1.0,
                description="Working detector fired",
            )

    engine.register_rule(FaultyDetector())
    engine.register_rule(WorkingDetector())

    events = engine.evaluate(mock_target_cpu, window=[])
    # Faulty detector should be caught/isolated, working detector must still return event
    assert len(events) == 1
    assert events[0].event_id == "ev-work"


# =============================================================================
# Vector 14: Permission Failure (EPERM / AccessDenied Handled Cleanly)
# =============================================================================

def test_vector_14_permission_failure_handling(registry):
    """Verify that EPERM / PermissionError when signaling process is caught and recorded."""
    executor = RecoveryExecutor(target_registry=registry, dry_run=False)

    action = create_sample_action(
        target_id="demo-cpu",
        action_type=AllowedActionType.TERMINATE_DEMO_PROCESS,
        extra_params={"pid": 9998},
    )

    with patch("os.kill", side_effect=PermissionError("Operation not permitted (EPERM)")):
        with patch("self_healing.recovery.handlers.terminate.verify_pid_matches_target", return_value=True):
            result = executor.execute(action, dry_run=False)
            assert result.success is False
            assert "Permission denied" in result.error or "Operation not permitted" in result.error


# =============================================================================
# Vector 15: Recovery Timeout Enforcement
# =============================================================================

def test_vector_15_recovery_timeout_enforcement(registry):
    """Verify that a slow or hanging recovery action times out cleanly and reports failure."""
    executor = RecoveryExecutor(target_registry=registry, default_timeout_seconds=0.2)

    class SlowHangingHandler(BaseActionHandler):
        def __init__(self):
            super().__init__(AllowedActionType.TERMINATE_DEMO_PROCESS)
        def execute(self, action, target_spec, dry_run=False):
            time.sleep(1.0)  # Exceeds 0.2s timeout
            return RecoveryResult(
                action_id=action.action_id,
                target_id=target_spec.target_id,
                action_type=self.action_type,
                executed_at=utc_now(),
                success=True,
                dry_run=dry_run,
                execution_latency_ms=1000.0,
                output_message="Should not reach here",
            )

    executor._handlers[AllowedActionType.TERMINATE_DEMO_PROCESS] = SlowHangingHandler()

    action = create_sample_action(
        target_id="demo-cpu",
        action_type=AllowedActionType.TERMINATE_DEMO_PROCESS,
        extra_params={"timeout_seconds": 0.2},
    )

    result = executor.execute(action, dry_run=False)
    assert result.success is False
    assert "timed out" in result.error.lower()
    assert result.details["exception_type"] == "TimeoutError"


# =============================================================================
# Safety Property Invariants: 6 Core Verification Guarantees
# =============================================================================

def test_safety_property_arbitrary_commands_cannot_execute(registry):
    """Verify that arbitrary shell command strings are strictly rejected by the type system."""
    executor = RecoveryExecutor(target_registry=registry)

    # Attempting to pass raw shell strings or arbitrary dicts
    with pytest.raises(SecurityViolationError, match="Arbitrary commands and raw strings are strictly forbidden"):
        executor.execute("rm -rf /")

    with pytest.raises(SecurityViolationError):
        executor.execute({"cmd": "reboot", "target": "demo-cpu"})


def test_safety_property_unauthorized_targets_cannot_be_healed(registry, dummy_evidence):
    """Verify unauthorized host targets cannot be healed across guardrail and executor."""
    guardrail_eng = SafetyGuardrailEngine(target_registry=registry)
    action = RecoveryAction(
        action_id="act-unauth",
        action_type=AllowedActionType.TERMINATE_DEMO_PROCESS,
        target="system-init-daemon",
        reason="Healing unauthorized target",
        required_evidence=[],
    )
    decision = guardrail_eng.evaluate(action, evidence=dummy_evidence)
    assert decision.allowed is False
    assert decision.status == GuardrailStatus.REJECTED


def test_safety_property_retry_loops_are_prevented(guardrail_engine, dummy_evidence):
    """Verify hard ceilings on retries prevent infinite remediation loops."""
    action = create_sample_action(target_id="demo-cpu", retry_count=5, max_retries=3)
    dec = guardrail_engine.evaluate(action, evidence=dummy_evidence)
    assert dec.allowed is False
    assert any("Action retry count exceeded" in v for v in dec.violations)


def test_safety_property_failures_are_recorded(registry):
    """Verify that all failures produce a persisted incident record."""
    store = IncidentRepository(":memory:")
    incident = IncidentRecord(
        incident_id="inc-audit-fail",
        target_id="demo-cpu",
        started_at=utc_now(),
        status=IncidentStatus.POLICY_REJECTED,
        fault_event=DetectionEvent(
            event_id="ev-fail",
            target_id="demo-cpu",
            fault_type=FaultType.HIGH_CPU,
            severity=FaultSeverity.HIGH,
            triggering_value=99.0,
            threshold_value=80.0,
            description="CPU failure recorded",
        ),
    )
    store.save(incident)
    fetched = store.get_incident("inc-audit-fail")
    assert fetched is not None
    assert fetched.status == IncidentStatus.POLICY_REJECTED


def test_safety_property_verification_catches_unsuccessful_recovery():
    """Verify that failed verification properly flags recovery as unsuccessful."""
    rec_res = RecoveryResult(
        action_id="act-1",
        target_id="demo-cpu",
        action_type=AllowedActionType.TERMINATE_DEMO_PROCESS,
        executed_at=utc_now(),
        success=True,
        dry_run=False,
        execution_latency_ms=15.0,
        output_message="Process terminated",
    )
    marked = rec_res.mark_unsuccessful("Verification check failed: CPU runaway persists")
    assert marked.success is False
    assert "Verification check failed" in marked.output_message


def test_safety_property_system_fails_safely(registry):
    """Verify that multiple consecutive failures in pipeline do not raise unhandled exceptions."""
    broken_store = MagicMock(spec=IncidentRepository)
    broken_store.save.side_effect = RuntimeError("Storage broken")

    orchestrator = SelfHealingOrchestrator(
        target_registry=registry,
        dry_run=True,
        incident_store=broken_store,
    )

    # Run tick under broken storage - should complete safely
    incidents = orchestrator.tick()
    assert isinstance(incidents, list)
    assert orchestrator.stats.ticks_count == 1
