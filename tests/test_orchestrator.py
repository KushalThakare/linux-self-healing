"""Comprehensive end-to-end tests for the SelfHealingOrchestrator closed loop."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import time
from typing import List
import pytest

from self_healing.config.settings import AppConfig, GuardrailsConfig, MonitoringConfig
from self_healing.core.models import (
    AllowedActionType,
    DetectionEvent,
    DiagnosisResult,
    FaultEvent,
    FaultSeverity,
    FaultType,
    GuardrailStatus,
    IncidentRecord,
    IncidentStatus,
    MetricSnapshot,
    ProcessMetrics,
    ProcessState,
    RecoveryAction,
    SystemSnapshot,
    TargetSpec,
    VerificationResult,
    VerificationStatus,
    utc_now,
)
from self_healing.detection.cpu import CpuRunawayDetector
from self_healing.incidents import IncidentRepository
from self_healing.orchestrator import OrchestratorStats, SelfHealingOrchestrator
from self_healing.targets.registry import TargetRegistry
from self_healing.verification.probes.base import BaseVerificationProbe, ProbeOutcome


@pytest.fixture
def mock_target() -> TargetSpec:
    """Fixture providing an approved supervised demo target."""
    return TargetSpec(
        target_id="demo-cpu",
        process_name="python3",
        cmdline_substring="demo_workloads cpu_spin",
        working_dir_prefix="/home/arskage/linux-self-healing",
        max_restarts_per_window=3,
        cooldown_seconds=5.0,
        enabled=True,
    )


@pytest.fixture
def mock_config(mock_target: TargetSpec) -> AppConfig:
    """Fixture providing customized test AppConfig."""
    cfg = AppConfig(
        targets=[mock_target],
        monitoring=MonitoringConfig(
            sample_interval_seconds=0.1,
            ring_buffer_size=10,
            cpu_percent_threshold=80.0,
        ),
        guardrails=GuardrailsConfig(
            max_actions_per_window=3,
            flapping_window_seconds=30.0,
            default_cooldown_seconds=2.0,
            enforce_target_allowlist=True,
        ),
    )
    return cfg


@pytest.fixture
def memory_repo() -> IncidentRepository:
    """In-memory incident repository fixture."""
    repo = IncidentRepository(db_path=":memory:")
    yield repo
    repo.close()


def test_orchestrator_initialization(mock_config: AppConfig, memory_repo: IncidentRepository):
    """Verify orchestrator initializes with config, registry, detectors, and buffers."""
    orchestrator = SelfHealingOrchestrator(
        config=mock_config,
        incident_store=memory_repo,
        dry_run=True,
    )

    assert orchestrator.dry_run is True
    assert orchestrator.poll_interval_seconds == 0.1
    assert "demo-cpu" in orchestrator.ring_buffers
    assert len(orchestrator.detection_engine._rules) == 5
    assert orchestrator.is_running is False
    assert orchestrator.stats.ticks_count == 0


def test_orchestrator_tick_nominal_load(mock_config: AppConfig, memory_repo: IncidentRepository):
    """Verify tick executes without errors and triggers no incidents under nominal load."""
    orchestrator = SelfHealingOrchestrator(
        config=mock_config,
        incident_store=memory_repo,
        dry_run=True,
    )

    incidents = orchestrator.tick()
    assert len(incidents) == 0
    assert orchestrator.stats.ticks_count == 1
    assert orchestrator.stats.snapshots_collected == 1
    assert orchestrator.stats.faults_detected == 0
    assert orchestrator.latest_snapshot is not None
    assert len(memory_repo.list_incidents()) == 0


def make_high_cpu_system_snapshot(target: TargetSpec, pid: int = 54321, cpu_pct: float = 98.0) -> SystemSnapshot:
    """Helper to generate a SystemSnapshot containing a running high-CPU target process."""
    from self_healing.core.models import SystemCpuMetrics, SystemMemoryMetrics

    proc = ProcessMetrics(
        pid=pid,
        name=target.process_name,
        state=ProcessState.RUNNING,
        cpu_percent=cpu_pct,
        rss_bytes=100 * 1024 * 1024,
        target_id=target.target_id,
    )
    return SystemSnapshot(
        timestamp=utc_now(),
        uptime_seconds=3600.0,
        cpu=SystemCpuMetrics(percent=95.0),
        memory=SystemMemoryMetrics(
            total_bytes=8 * 1024 * 1024 * 1024,
            available_bytes=4 * 1024 * 1024 * 1024,
            used_bytes=4 * 1024 * 1024 * 1024,
            free_bytes=4 * 1024 * 1024 * 1024,
            percent=50.0,
        ),
        processes=[proc],
    )


def test_orchestrator_e2e_closed_loop_happy_path(
    mock_config: AppConfig,
    mock_target: TargetSpec,
    memory_repo: IncidentRepository,
):
    """End-to-End Test: MONITOR -> DETECT -> DIAGNOSE -> GUARDRAIL -> RECOVER -> VERIFY -> RECORD.
    
    Verifies that a detected fault executes through all 7 stages to VERIFIED_SUCCESS.
    """
    orchestrator = SelfHealingOrchestrator(
        config=mock_config,
        incident_store=memory_repo,
        dry_run=True,
    )

    events_emitted = []
    orchestrator.register_listener("incident_created", lambda inc: events_emitted.append(("created", inc)))
    orchestrator.register_listener("incident_resolved", lambda inc: events_emitted.append(("resolved", inc)))

    # Seed the target ring buffer with high CPU snapshots exceeding the 80% threshold
    buffer = orchestrator.ring_buffers[mock_target.target_id]
    base_time = utc_now() - timedelta(seconds=10)
    for i in range(5):
        snap = MetricSnapshot(
            timestamp=base_time + timedelta(seconds=i),
            system_cpu_percent=95.0,
            system_memory_percent=30.0,
            target_id=mock_target.target_id,
            target_pid=54321,
            target_cpu_percent=98.0,
            target_rss_bytes=100 * 1024 * 1024,
            target_state=ProcessState.RUNNING,
        )
        buffer.append(snap)

    # Execute tick with high CPU system snapshot
    sys_snap = make_high_cpu_system_snapshot(mock_target)
    incidents = orchestrator.tick(snapshot=sys_snap)

    assert len(incidents) == 1
    inc = incidents[0]

    # Verify stage progression
    assert inc.status == IncidentStatus.VERIFIED_SUCCESS
    assert inc.fault_event.fault_type == FaultType.HIGH_CPU
    assert inc.diagnosis is not None
    assert inc.diagnosis.confidence > 0.0
    assert inc.policy_decision is not None
    assert inc.policy_decision.allowed is True
    assert inc.policy_decision.is_dry_run is True
    assert inc.recovery_result is not None
    assert inc.recovery_result.success is True
    assert inc.verification_result is not None
    assert inc.verification_result.verified is True

    # Verify persistent recording in SQLite
    persisted = memory_repo.get_incident(inc.incident_id)
    assert persisted is not None
    assert persisted.status == IncidentStatus.VERIFIED_SUCCESS

    # Verify stats updated
    assert orchestrator.stats.faults_detected == 1
    assert orchestrator.stats.diagnoses_performed == 1
    assert orchestrator.stats.actions_approved == 1
    assert orchestrator.stats.remediations_executed == 1
    assert orchestrator.stats.verifications_passed == 1

    # Verify event listeners notified
    assert len(events_emitted) == 2
    assert events_emitted[0][0] == "created"
    assert events_emitted[1][0] == "resolved"


def test_orchestrator_deduplication_ongoing_fault(
    mock_config: AppConfig,
    mock_target: TargetSpec,
    memory_repo: IncidentRepository,
):
    """Verify that multiple consecutive ticks during an ongoing fault do not create duplicate incidents."""
    orchestrator = SelfHealingOrchestrator(
        config=mock_config,
        incident_store=memory_repo,
        dry_run=True,
    )

    # Seed buffer with high CPU snapshots
    buffer = orchestrator.ring_buffers[mock_target.target_id]
    base_time = utc_now() - timedelta(seconds=10)
    for i in range(5):
        snap = MetricSnapshot(
            timestamp=base_time + timedelta(seconds=i),
            system_cpu_percent=95.0,
            system_memory_percent=30.0,
            target_id=mock_target.target_id,
            target_pid=54321,
            target_cpu_percent=98.0,
            target_rss_bytes=100 * 1024 * 1024,
            target_state=ProcessState.RUNNING,
        )
        buffer.append(snap)

    # Mark fault as in-flight / active
    orchestrator._active_faults[(mock_target.target_id, FaultType.HIGH_CPU.value)] = "active-inc-999"

    # Tick: detection finds high CPU, but deduplicator skips duplicate spawn
    sys_snap = make_high_cpu_system_snapshot(mock_target)
    incidents = orchestrator.tick(snapshot=sys_snap)
    assert len(incidents) == 0
    assert orchestrator.stats.faults_detected == 0
    assert len(memory_repo.list_incidents()) == 0


def test_orchestrator_guardrail_rejection_handling(
    mock_config: AppConfig,
    mock_target: TargetSpec,
    memory_repo: IncidentRepository,
):
    """Verify that when guardrails reject an action (e.g. cooldown active), incident is marked POLICY_REJECTED."""
    orchestrator = SelfHealingOrchestrator(
        config=mock_config,
        incident_store=memory_repo,
        dry_run=True,
    )

    # Trigger artificial cooldown on mock_target
    orchestrator.guardrail_engine.record_action(mock_target.target_id)

    # Seed buffer with high CPU snapshots
    buffer = orchestrator.ring_buffers[mock_target.target_id]
    base_time = utc_now() - timedelta(seconds=10)
    for i in range(5):
        snap = MetricSnapshot(
            timestamp=base_time + timedelta(seconds=i),
            system_cpu_percent=95.0,
            system_memory_percent=30.0,
            target_id=mock_target.target_id,
            target_pid=54321,
            target_cpu_percent=98.0,
            target_rss_bytes=100 * 1024 * 1024,
            target_state=ProcessState.RUNNING,
        )
        buffer.append(snap)

    # Tick: guardrail rejects due to cooldown
    sys_snap = make_high_cpu_system_snapshot(mock_target)
    incidents = orchestrator.tick(snapshot=sys_snap)
    assert len(incidents) == 1
    inc = incidents[0]

    assert inc.status == IncidentStatus.POLICY_REJECTED
    assert inc.policy_decision.allowed is False
    assert "Cooldown" in inc.policy_decision.rejection_reason
    assert orchestrator.stats.actions_rejected == 1
    assert orchestrator.stats.remediations_executed == 0


def test_orchestrator_verification_failure_and_escalation(
    mock_config: AppConfig,
    mock_target: TargetSpec,
    memory_repo: IncidentRepository,
):
    """Verify that persistent verification probe failures exhaust retry limits and transition to ESCALATED."""
    orchestrator = SelfHealingOrchestrator(
        config=mock_config,
        incident_store=memory_repo,
        dry_run=False,
    )
    # Configure fast retry backoff for testing
    orchestrator.retry_policy.base_delay_seconds = 0.01

    # Register an intentionally failing custom verification probe
    class AlwaysFailingProbe(BaseVerificationProbe):
        def __init__(self):
            super().__init__(name="failing_probe", fault_type=FaultType.HIGH_CPU, description="Always fails")

        def verify(self, **kwargs) -> ProbeOutcome:
            return ProbeOutcome(
                name=self.name,
                passed=False,
                evidence={"failure": "Mock failure"},
                metrics_after={},
                message="Probe failed intentionally",
            )

    orchestrator.verification_engine.register_probe(AlwaysFailingProbe())

    # Seed high CPU snapshots
    buffer = orchestrator.ring_buffers[mock_target.target_id]
    base_time = utc_now() - timedelta(seconds=10)
    for i in range(5):
        snap = MetricSnapshot(
            timestamp=base_time + timedelta(seconds=i),
            system_cpu_percent=95.0,
            system_memory_percent=30.0,
            target_id=mock_target.target_id,
            target_pid=54321,
            target_cpu_percent=98.0,
            target_rss_bytes=100 * 1024 * 1024,
            target_state=ProcessState.RUNNING,
        )
        buffer.append(snap)

    sys_snap = make_high_cpu_system_snapshot(mock_target)
    incidents = orchestrator.tick(snapshot=sys_snap)
    assert len(incidents) == 1
    inc = incidents[0]

    # After exhausting retries, incident must be escalated
    assert inc.status == IncidentStatus.ESCALATED
    assert orchestrator.stats.incidents_escalated == 1
    assert orchestrator.stats.verifications_failed > 0

    persisted = memory_repo.get_incident(inc.incident_id)
    assert persisted.status == IncidentStatus.ESCALATED


def test_orchestrator_run_bounded_ticks(mock_config: AppConfig, memory_repo: IncidentRepository):
    """Verify run(max_ticks=N) executes the exact number of ticks and terminates."""
    orchestrator = SelfHealingOrchestrator(
        config=mock_config,
        incident_store=memory_repo,
        dry_run=True,
        poll_interval_seconds=0.01,
    )

    orchestrator.run(max_ticks=3)
    assert orchestrator.stats.ticks_count == 3
    assert orchestrator.is_running is False


def test_orchestrator_start_stop_thread(mock_config: AppConfig, memory_repo: IncidentRepository):
    """Verify background threading start and stop lifecycle."""
    orchestrator = SelfHealingOrchestrator(
        config=mock_config,
        incident_store=memory_repo,
        dry_run=True,
        poll_interval_seconds=0.05,
    )

    thread = orchestrator.start()
    assert thread.is_alive()
    assert orchestrator.is_running is True

    time.sleep(0.15)
    orchestrator.stop()

    assert not thread.is_alive()
    assert orchestrator.is_running is False
    assert orchestrator.stats.ticks_count >= 1
