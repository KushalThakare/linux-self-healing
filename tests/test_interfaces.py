"""Unit tests verifying interfaces and separation of concerns across all modules."""

import pytest
from self_healing.core.exceptions import (
    SecurityViolationError,
    TargetNotFoundError,
)
from self_healing.core.models import (
    ActionType,
    FaultSeverity,
    FaultType,
    MetricSnapshot,
    TargetSpec,
)
from self_healing.detection.base import BaseFaultRule, RuleDetectionEngine
from self_healing.diagnosis.base import HeuristicDiagnosisEngine
from self_healing.fault_injection.base import StubFaultInjector
from self_healing.guardrails.base import PolicyGuardrailEngine
from self_healing.incidents.store import InMemoryIncidentStore
from self_healing.monitoring.collector import (
    MetricRingBuffer,
    SystemMetricsCollector,
)
from self_healing.recovery.base import ActionRegistry, StubRecoveryAction
from self_healing.targets.registry import TargetRegistry, is_safe_pid
from self_healing.verification.base import BaseVerificationProbe, VerificationEngine


def test_target_registry_blocks_critical_system_entities():
    """Verify TargetRegistry prevents registering host system processes or root paths."""
    registry = TargetRegistry()

    # Rejection of system directory
    with pytest.raises(SecurityViolationError):
        registry.register(
            TargetSpec(
                target_id="evil-target",
                process_name="python3",
                cmdline_substring="demo.py",
                working_dir_prefix="/",
            )
        )

    # Rejection of protected process names
    with pytest.raises(SecurityViolationError):
        registry.register(
            TargetSpec(
                target_id="systemd-target",
                process_name="systemd",
                cmdline_substring="systemd",
                working_dir_prefix="/home/arskage/linux-self-healing",
            )
        )


def test_is_safe_pid_boundaries():
    """Verify is_safe_pid rejects PID 0, 1, 2, and self."""
    assert is_safe_pid(0) is False
    assert is_safe_pid(1) is False
    assert is_safe_pid(2) is False
    assert is_safe_pid(99999) is True


def test_monitoring_collector_and_ring_buffer(sample_metric: MetricSnapshot):
    """Verify monitoring metrics collection and ring buffer behavior."""
    collector = SystemMetricsCollector()
    sys_metrics = collector.collect_system_metrics()
    assert 0.0 <= sys_metrics.system_cpu_percent <= 100.0
    assert 0.0 <= sys_metrics.system_memory_percent <= 100.0

    buffer = MetricRingBuffer(capacity=5)
    for _ in range(7):
        buffer.append(sample_metric)
    assert len(buffer) == 5
    assert buffer.get_latest() is not None
    buffer.clear()
    assert len(buffer) == 0


def test_detection_engine_contract(sample_target: TargetSpec, sample_metric: MetricSnapshot):
    """Verify detection rule registration and evaluation contract."""
    class DummyHighCpuRule(BaseFaultRule):
        def evaluate(self, target, window):
            if window and window[-1].system_cpu_percent > 10.0:
                from self_healing.core.models import FaultEvent, utc_now
                return FaultEvent(
                    event_id="test-evt",
                    target_id=target.target_id,
                    fault_type=self.fault_type,
                    severity=self.severity,
                    detected_at=utc_now(),
                    triggering_value=window[-1].system_cpu_percent,
                    threshold_value=10.0,
                    description="Dummy trigger",
                )
            return None

    engine = RuleDetectionEngine()
    rule = DummyHighCpuRule("dummy_cpu", FaultType.HIGH_CPU, FaultSeverity.HIGH)
    engine.register_rule(rule)

    events = engine.evaluate(sample_target, [sample_metric])
    assert len(events) == 1
    assert events[0].fault_type == FaultType.HIGH_CPU


def test_diagnosis_engine_contract(
    sample_target: TargetSpec,
    sample_fault_event: FaultEvent,
    sample_metric: MetricSnapshot,
):
    """Verify diagnosis engine outputs strongly typed report."""
    diag_engine = HeuristicDiagnosisEngine()
    report = diag_engine.diagnose(sample_fault_event, [sample_metric], sample_target)

    assert report.event_id == sample_fault_event.event_id
    assert report.target_id == sample_target.target_id
    assert report.confidence > 0.0
    assert report.recommended_action == ActionType.GRACEFUL_TERMINATE


def test_guardrails_flapping_and_cooldown_enforcement(
    sample_target: TargetSpec,
    sample_diagnosis: DiagnosisReport,
    target_registry: TargetRegistry,
):
    """Verify policy engine blocks actions violating flapping or cooldown constraints."""
    from self_healing.config.settings import GuardrailsConfig
    cfg = GuardrailsConfig(
        max_actions_per_window=2,
        flapping_window_seconds=60.0,
        default_cooldown_seconds=10.0,
        enforce_target_allowlist=True,
    )
    policy_engine = PolicyGuardrailEngine(target_registry, cfg)

    # First attempt: allowed
    decision1 = policy_engine.evaluate_action(sample_target, sample_diagnosis, dry_run=True)
    assert decision1.allowed is True
    policy_engine.record_action(sample_target.target_id)

    # Immediate second attempt: rejected by cooldown
    decision2 = policy_engine.evaluate_action(sample_target, sample_diagnosis, dry_run=True)
    assert decision2.allowed is False
    assert "cooldown" in decision2.rejection_reason.lower()


def test_recovery_registry_execution(sample_target: TargetSpec):
    """Verify recovery action registry rejects unallowlisted actions and runs allowlisted stubs."""
    registry = ActionRegistry()
    res = registry.execute_action(ActionType.GRACEFUL_TERMINATE, sample_target, dry_run=True)
    assert res.success is True
    assert res.dry_run is True
    assert res.action_type == ActionType.GRACEFUL_TERMINATE


def test_verification_engine_contract(sample_target: TargetSpec):
    """Verify verification engine runs probes and aggregates status."""
    class DummyProbe(BaseVerificationProbe):
        def probe(self, target: TargetSpec) -> bool:
            return True

    engine = VerificationEngine()
    engine.register_probe(DummyProbe("tcp_health"))
    result = engine.verify(sample_target, incident_id="inc-123")
    assert result.status.value == "HEALTHY"
    assert "tcp_health" in result.checks_passed


def test_incident_store_contract(sample_target: TargetSpec, sample_fault_event: FaultEvent):
    """Verify incident store saves and retrieves IncidentRecord."""
    from self_healing.core.models import IncidentRecord, IncidentStatus
    store = InMemoryIncidentStore()
    record = IncidentRecord(
        incident_id="inc-999",
        target_id=sample_target.target_id,
        status=IncidentStatus.DETECTED,
        fault_event=sample_fault_event,
    )
    store.save(record)
    retrieved = store.get("inc-999")
    assert retrieved is not None
    assert retrieved.incident_id == "inc-999"
    assert len(store.list_incidents()) == 1


def test_fault_injector_safety(sample_target: TargetSpec):
    """Verify fault injector safety checks prevent targeting system processes."""
    injector = StubFaultInjector("cpu_spin", FaultType.HIGH_CPU)
    assert injector.inject(sample_target) is True
    assert injector.restore(sample_target) is True

    unsafe_target = TargetSpec(
        target_id="unsafe",
        process_name="systemd",
        cmdline_substring="systemd",
        working_dir_prefix="/home/arskage/linux-self-healing",
    )
    with pytest.raises(SecurityViolationError):
        injector.inject(unsafe_target)
