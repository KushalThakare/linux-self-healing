"""Comprehensive automated tests for SQLite IncidentRepository."""

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import pytest

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
    RecoveryAction,
    RecoveryResult,
    RiskLevel,
    TargetSpec,
    VerificationResult,
    VerificationStatus,
    utc_now,
)
from self_healing.incidents import IncidentRepository, SqliteIncidentStore
from self_healing.verification.coordinator import RemediationCoordinator


@pytest.fixture
def memory_repo() -> IncidentRepository:
    """Fixture providing an in-memory IncidentRepository instance."""
    repo = IncidentRepository(db_path=":memory:")
    yield repo
    repo.close()


@pytest.fixture
def file_repo(tmp_path: Path) -> IncidentRepository:
    """Fixture providing a temporary file-backed IncidentRepository."""
    db_file = tmp_path / "sub_dir" / "incidents.db"
    repo = IncidentRepository(db_path=db_file)
    yield repo
    repo.close()


@pytest.fixture
def sample_incident() -> IncidentRecord:
    """Fixture providing a fully populated IncidentRecord."""
    now = utc_now()
    fault = DetectionEvent(
        event_id="evt-101",
        target_id="demo-cpu",
        fault_type=FaultType.HIGH_CPU,
        severity=FaultSeverity.CRITICAL,
        detected_at=now - timedelta(seconds=2),
        triggering_value=96.5,
        threshold_value=85.0,
        description="CPU runaway loop detected",
        evidence={"cpu_percent": 96.5, "detection_latency_ms": 15.2},
    )

    diag = DiagnosisResult(
        diagnosis_id="diag-201",
        event_id="evt-101",
        fault_type=FaultType.HIGH_CPU,
        target_id="demo-cpu",
        evidence={"cpu_percent": 96.5},
        probable_cause="Tight arithmetic spin loop without yield",
        severity=FaultSeverity.CRITICAL,
        confidence=0.98,
        recommended_action=AllowedActionType.TERMINATE_DEMO_PROCESS,
    )

    guardrail = GuardrailDecision(
        decision_id="guard-301",
        action_id="act-401",
        diagnosis_id="diag-201",
        target_id="demo-cpu",
        action_type=AllowedActionType.TERMINATE_DEMO_PROCESS,
        status=GuardrailStatus.APPROVED,
        allowed=True,
    )

    rec = RecoveryResult(
        action_id="act-401",
        target_id="demo-cpu",
        action_type=AllowedActionType.TERMINATE_DEMO_PROCESS,
        success=True,
        execution_latency_ms=42.8,
        output_message="Process terminated gracefully via SIGTERM",
    )

    veri = VerificationResult(
        verification_id="ver-501",
        incident_id="inc-001",
        target_id="demo-cpu",
        status=VerificationStatus.HEALTHY,
        verified=True,
        failed=False,
        evidence={"cpu_after": 2.1, "pid_alive": False},
        verification_duration=0.25,
    )

    return IncidentRecord(
        incident_id="inc-001",
        target_id="demo-cpu",
        started_at=now,
        completed_at=now + timedelta(seconds=1),
        status=IncidentStatus.VERIFIED_SUCCESS,
        fault_event=fault,
        diagnosis=diag,
        policy_decision=guardrail,
        recovery_result=rec,
        verification_result=veri,
    )


def test_repository_initialization_file(file_repo: IncidentRepository):
    """Verify that file-backed repository initializes database and tables."""
    assert Path(file_repo.db_path).exists()
    assert isinstance(file_repo, SqliteIncidentStore)
    assert len(file_repo.list_incidents()) == 0


def test_create_and_get_incident(memory_repo: IncidentRepository, sample_incident: IncidentRecord):
    """Verify create_incident persists record and get_incident returns exact model."""
    created = memory_repo.create_incident(sample_incident)
    assert created.incident_id == sample_incident.incident_id

    retrieved = memory_repo.get_incident("inc-001")
    assert retrieved is not None
    assert retrieved.incident_id == "inc-001"
    assert retrieved.target_id == "demo-cpu"
    assert retrieved.status == IncidentStatus.VERIFIED_SUCCESS
    assert retrieved.fault_event.fault_type == FaultType.HIGH_CPU
    assert retrieved.diagnosis.confidence == 0.98
    assert retrieved.policy_decision.allowed is True
    assert retrieved.recovery_result.success is True
    assert retrieved.verification_result.verified is True


def test_create_incident_duplicate_raises(memory_repo: IncidentRepository, sample_incident: IncidentRecord):
    """Verify creating an incident with existing ID raises ValueError."""
    memory_repo.create_incident(sample_incident)
    with pytest.raises(ValueError, match="already exists"):
        memory_repo.create_incident(sample_incident)


def test_update_incident_lifecycle(memory_repo: IncidentRepository):
    """Verify update_incident properly transitions lifecycle fields."""
    now = utc_now()
    initial_fault = FaultEvent(
        event_id="evt-base",
        target_id="demo-service",
        fault_type=FaultType.PROCESS_CRASH,
        severity=FaultSeverity.HIGH,
        triggering_value=1.0,
        threshold_value=0.0,
        description="Service stopped unexpectedly",
    )
    incident = IncidentRecord(
        incident_id="inc-lifecycle",
        target_id="demo-service",
        started_at=now,
        status=IncidentStatus.DETECTED,
        fault_event=initial_fault,
    )

    memory_repo.create_incident(incident)

    # 1. Update with recovery result
    incident.status = IncidentStatus.EXECUTED
    incident.recovery_result = RecoveryResult(
        action_id="act-restart",
        target_id="demo-service",
        action_type=AllowedActionType.RESTART_DEMO_SERVICE,
        success=True,
        execution_latency_ms=110.0,
        output_message="Service restarted",
    )
    memory_repo.update_incident(incident)

    fetched = memory_repo.get_incident("inc-lifecycle")
    assert fetched.status == IncidentStatus.EXECUTED
    assert fetched.recovery_result.success is True

    # 2. Update with verification result
    incident.status = IncidentStatus.VERIFIED_SUCCESS
    incident.completed_at = utc_now()
    incident.verification_result = VerificationResult(
        verification_id="ver-svc",
        incident_id="inc-lifecycle",
        target_id="demo-service",
        status=VerificationStatus.HEALTHY,
        verified=True,
        failed=False,
    )
    memory_repo.update_incident(incident)

    final_fetched = memory_repo.get_incident("inc-lifecycle")
    assert final_fetched.status == IncidentStatus.VERIFIED_SUCCESS
    assert final_fetched.verification_result.verified is True
    assert final_fetched.completed_at is not None


def test_update_incident_nonexistent_raises(memory_repo: IncidentRepository, sample_incident: IncidentRecord):
    """Verify updating a non-existent incident raises KeyError."""
    with pytest.raises(KeyError, match="does not exist"):
        memory_repo.update_incident(sample_incident)


def test_get_incident_nonexistent(memory_repo: IncidentRepository):
    """Verify get_incident returns None for non-existent IDs."""
    assert memory_repo.get_incident("does-not-exist") is None
    assert memory_repo.get("does-not-exist") is None


def test_save_upsert_behavior(memory_repo: IncidentRepository, sample_incident: IncidentRecord):
    """Verify save() creates on first call and updates on subsequent calls."""
    # First save: create
    memory_repo.save(sample_incident)
    assert memory_repo.get("inc-001") is not None

    # Modify and save again: update
    updated_record = sample_incident.model_copy(update={"status": IncidentStatus.ESCALATED})
    memory_repo.save(updated_record)

    retrieved = memory_repo.get("inc-001")
    assert retrieved.status == IncidentStatus.ESCALATED


def test_stored_relational_columns_fidelity(memory_repo: IncidentRepository, sample_incident: IncidentRecord):
    """Verify all 16 required columns are populated and correctly accessible."""
    memory_repo.create_incident(sample_incident)
    row = memory_repo.get_incident_dict("inc-001")
    assert row is not None

    # Validate all 16 required fields
    assert row["incident_id"] == "inc-001"
    assert row["timestamp"] == sample_incident.started_at.isoformat()
    assert row["fault_type"] == "HIGH_CPU"
    assert row["severity"] == "CRITICAL"
    assert row["affected_target"] == "demo-cpu"
    assert "cpu_percent" in row["detection_evidence"]
    assert "Tight arithmetic spin loop" in row["diagnosis"]
    assert "cpu_detector" in row["detector"] or "high_cpu_detector" in row["detector"]
    assert row["confidence"] == 0.98
    assert row["recovery_action"] == "terminate_demo_process"
    assert "GUARDRAIL APPROVED" in row["guardrail_decision"]
    assert row["recovery_result"] == "SUCCESS"
    assert row["verification_result"] == "HEALTHY"
    assert row["detection_latency"] == 15.2
    assert row["recovery_latency"] == 42.8
    assert row["final_status"] == "VERIFIED_SUCCESS"


def test_filtering_and_sorting(memory_repo: IncidentRepository):
    """Verify filtering by fault type, status, and target ID as well as get_recent."""
    base_time = utc_now()

    # Create 3 distinct incidents
    inc1 = IncidentRecord(
        incident_id="inc-cpu",
        target_id="demo-cpu",
        started_at=base_time - timedelta(minutes=10),
        status=IncidentStatus.VERIFIED_SUCCESS,
        fault_event=FaultEvent(
            event_id="e-cpu",
            target_id="demo-cpu",
            fault_type=FaultType.HIGH_CPU,
            severity=FaultSeverity.HIGH,
            triggering_value=90.0,
            threshold_value=80.0,
            description="CPU high",
        ),
    )

    inc2 = IncidentRecord(
        incident_id="inc-mem",
        target_id="demo-memory",
        started_at=base_time - timedelta(minutes=5),
        status=IncidentStatus.VERIFICATION_FAILED,
        fault_event=FaultEvent(
            event_id="e-mem",
            target_id="demo-memory",
            fault_type=FaultType.MEMORY_LEAK,
            severity=FaultSeverity.CRITICAL,
            triggering_value=300.0,
            threshold_value=250.0,
            description="Memory leak",
        ),
    )

    inc3 = IncidentRecord(
        incident_id="inc-disk",
        target_id="demo-disk",
        started_at=base_time - timedelta(minutes=1),
        status=IncidentStatus.ESCALATED,
        fault_event=FaultEvent(
            event_id="e-disk",
            target_id="demo-disk",
            fault_type=FaultType.DISK_GROWTH,
            severity=FaultSeverity.MEDIUM,
            triggering_value=50.0,
            threshold_value=40.0,
            description="Disk full",
        ),
    )

    memory_repo.create_incident(inc1)
    memory_repo.create_incident(inc2)
    memory_repo.create_incident(inc3)

    # 1. Filter by fault type
    cpu_list = memory_repo.filter_by_fault_type(FaultType.HIGH_CPU)
    assert len(cpu_list) == 1
    assert cpu_list[0].incident_id == "inc-cpu"

    mem_list = memory_repo.filter_by_fault_type("MEMORY_LEAK")
    assert len(mem_list) == 1
    assert mem_list[0].incident_id == "inc-mem"

    # 2. Filter by status
    failed_list = memory_repo.filter_by_status(IncidentStatus.VERIFICATION_FAILED)
    assert len(failed_list) == 1
    assert failed_list[0].incident_id == "inc-mem"

    escalated_list = memory_repo.filter_by_status("ESCALATED")
    assert len(escalated_list) == 1
    assert escalated_list[0].incident_id == "inc-disk"

    # 3. Filter by target ID
    disk_target_list = memory_repo.list_incidents(target_id="demo-disk")
    assert len(disk_target_list) == 1
    assert disk_target_list[0].incident_id == "inc-disk"

    # 4. Get recent (ordered by timestamp DESC: inc3 -> inc2 -> inc1)
    recent_2 = memory_repo.get_recent(limit=2)
    assert len(recent_2) == 2
    assert recent_2[0].incident_id == "inc-disk"
    assert recent_2[1].incident_id == "inc-mem"


def test_coordinator_integration_with_sqlite_repository(sample_target: TargetSpec):
    """Verify RemediationCoordinator automatically updates SQLite IncidentRepository."""
    from self_healing.targets.registry import TargetRegistry

    repo = IncidentRepository(db_path=":memory:")
    target_reg = TargetRegistry([sample_target])
    coordinator = RemediationCoordinator(target_registry=target_reg, incident_store=repo)

    incident = IncidentRecord(
        incident_id="coord-sqlite-001",
        target_id=sample_target.target_id,
        fault_event=FaultEvent(
            event_id="e-test",
            target_id=sample_target.target_id,
            fault_type=FaultType.HIGH_CPU,
            severity=FaultSeverity.HIGH,
            triggering_value=90.0,
            threshold_value=80.0,
            description="CPU",
        ),
    )

    action = RecoveryAction(
        action_id="act-test",
        action_type=AllowedActionType.TERMINATE_DEMO_PROCESS,
        target=sample_target.target_id,
        reason="CPU runaway remediation",
        risk_level=RiskLevel.LOW,
        parameters={"pid": 99999},
    )

    # In dry-run mode, guardrails approve, recovery simulates, verification verifies
    result_incident = coordinator.execute_and_verify(
        incident=incident,
        action=action,
        target_spec=sample_target,
        dry_run=True,
    )

    # Assert incident was automatically persisted into SQLite
    persisted = repo.get_incident("coord-sqlite-001")
    assert persisted is not None
    assert persisted.status == IncidentStatus.VERIFIED_SUCCESS
    assert persisted.policy_decision is not None
    assert persisted.recovery_result is not None
    assert persisted.verification_result is not None
    repo.close()


def test_empty_database_queries(memory_repo: IncidentRepository):
    """Verify querying an empty repository returns empty lists and None safely."""
    assert memory_repo.list_incidents() == []
    assert memory_repo.get_recent(5) == []
    assert memory_repo.filter_by_fault_type(FaultType.HIGH_CPU) == []
    assert memory_repo.filter_by_status(IncidentStatus.DETECTED) == []
    assert memory_repo.get_incident_dict("non-existent") is None


def test_concurrent_writes(tmp_path: Path):
    """Verify multiple threads can concurrently insert incidents into file-backed SQLite."""
    import concurrent.futures

    db_path = tmp_path / "concurrent.db"
    repo = IncidentRepository(db_path=db_path)

    def write_worker(idx: int) -> str:
        inc_id = f"inc-concurrent-{idx}"
        inc = IncidentRecord(
            incident_id=inc_id,
            target_id="demo-cpu",
            status=IncidentStatus.DETECTED,
            fault_event=FaultEvent(
                event_id=f"evt-{idx}",
                target_id="demo-cpu",
                fault_type=FaultType.HIGH_CPU,
                severity=FaultSeverity.LOW,
                triggering_value=85.0,
                threshold_value=80.0,
                description=f"Thread {idx}",
            ),
        )
        repo.create_incident(inc)
        return inc_id

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(write_worker, i) for i in range(20)]
        results = [f.result() for f in futures]

    assert len(results) == 20
    assert len(repo.list_incidents(limit=100)) == 20
    repo.close()

