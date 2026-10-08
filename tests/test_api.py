"""Unit tests for FastAPI management endpoints (Phase 11)."""

from datetime import timedelta
from pathlib import Path
from typing import Generator
import pytest
from starlette.testclient import TestClient

from self_healing.api.app import create_app
from self_healing.config.settings import AppConfig, GuardrailsConfig, MonitoringConfig, SystemConfig
from self_healing.core.models import (
    AllowedActionType,
    DetectionEvent,
    DiagnosisResult,
    FaultSeverity,
    FaultStatus,
    FaultType,
    GuardrailDecision,
    GuardrailStatus,
    IncidentRecord,
    IncidentStatus,
    ProcessMetrics,
    ProcessState,
    RecoveryAction,
    RecoveryResult,
    RiskLevel,
    ServiceMetrics,
    TargetSpec,
    VerificationResult,
    VerificationStatus,
    utc_now,
)
from self_healing.fault_injection.manager import FaultManager
from self_healing.incidents import IncidentRepository
from self_healing.orchestrator import SelfHealingOrchestrator
from self_healing.targets.registry import TargetRegistry


@pytest.fixture
def test_targets() -> list[TargetSpec]:
    """Supervised demo targets for testing."""
    return [
        TargetSpec(
            target_id="demo-cpu",
            process_name="python3",
            cmdline_substring="demo_workloads cpu_spin",
            working_dir_prefix="/home/arskage/linux-self-healing",
            max_restarts_per_window=3,
            cooldown_seconds=1.0,
            enabled=True,
        ),
        TargetSpec(
            target_id="demo-service",
            process_name="python3",
            cmdline_substring="demo_workloads service",
            expected_port=8085,
            working_dir_prefix="/home/arskage/linux-self-healing",
            max_restarts_per_window=3,
            cooldown_seconds=1.0,
            enabled=True,
        ),
    ]


@pytest.fixture
def test_config(test_targets: list[TargetSpec]) -> AppConfig:
    """Application config for API testing."""
    return AppConfig(
        system=SystemConfig(mode="development", dry_run=True, log_level="INFO"),
        targets=test_targets,
        monitoring=MonitoringConfig(sample_interval_seconds=0.2, ring_buffer_size=10),
        guardrails=GuardrailsConfig(
            max_actions_per_window=3,
            flapping_window_seconds=30.0,
            default_cooldown_seconds=1.0,
            enforce_target_allowlist=True,
        ),
    )


@pytest.fixture
def test_repo() -> Generator[IncidentRepository, None, None]:
    """In-memory SQLite incident repository populated with test records."""
    repo = IncidentRepository(db_path=":memory:")

    # Seed 1: Verified recovery incident
    inc1 = IncidentRecord(
        incident_id="inc-verified-111",
        target_id="demo-cpu",
        started_at=utc_now() - timedelta(minutes=5),
        completed_at=utc_now() - timedelta(minutes=4),
        status=IncidentStatus.VERIFIED_SUCCESS,
        fault_event=DetectionEvent(
            event_id="ev-111",
            target_id="demo-cpu",
            fault_type=FaultType.HIGH_CPU,
            severity=FaultSeverity.HIGH,
            detected_at=utc_now() - timedelta(minutes=5),
            triggering_value=98.5,
            threshold_value=80.0,
            description="CPU runaway detected",
        ),
        diagnosis=DiagnosisResult(
            diagnosis_id="diag-111",
            event_id="ev-111",
            fault_type=FaultType.HIGH_CPU,
            target_id="demo-cpu",
            evidence={},
            probable_cause="Tight loop calculation",
            severity=FaultSeverity.CRITICAL,
            confidence=0.95,
            recommended_action=AllowedActionType.TERMINATE_DEMO_PROCESS.value,
        ),
        policy_decision=GuardrailDecision(
            decision_id="dec-111",
            action_id="act-111",
            target_id="demo-cpu",
            action_type=AllowedActionType.TERMINATE_DEMO_PROCESS,
            action_params={"pid": 1234},
            allowed=True,
            is_dry_run=True,
            status=GuardrailStatus.APPROVED,
        ),
        recovery_result=RecoveryResult(
            action_id="act-111",
            target_id="demo-cpu",
            action_type=AllowedActionType.TERMINATE_DEMO_PROCESS,
            success=True,
            dry_run=True,
            execution_latency_ms=25.4,
            output_message="Simulated process termination",
        ),
        verification_result=VerificationResult(
            verification_id="ver-111",
            incident_id="inc-verified-111",
            target_id="demo-cpu",
            verified=True,
            status=VerificationStatus.HEALTHY,
            evidence={"cpu": 15.0},
            details="CPU utilization normalized below threshold",
        ),
    )

    # Seed 2: Policy rejected incident
    inc2 = IncidentRecord(
        incident_id="inc-rejected-222",
        target_id="demo-service",
        started_at=utc_now() - timedelta(minutes=2),
        completed_at=utc_now() - timedelta(minutes=1),
        status=IncidentStatus.POLICY_REJECTED,
        fault_event=DetectionEvent(
            event_id="ev-222",
            target_id="demo-service",
            fault_type=FaultType.PROCESS_CRASH,
            severity=FaultSeverity.CRITICAL,
            detected_at=utc_now() - timedelta(minutes=2),
            triggering_value=0.0,
            threshold_value=1.0,
            description="Service crash detected",
        ),
        policy_decision=GuardrailDecision(
            decision_id="dec-222",
            action_id="act-222",
            target_id="demo-service",
            action_type=AllowedActionType.RESTART_DEMO_SERVICE,
            action_params={},
            allowed=False,
            is_dry_run=True,
            status=GuardrailStatus.REJECTED,
            rejection_reason="Check 6 Failed: Cooldown period active",
        ),
    )

    repo.save(inc1)
    repo.save(inc2)
    yield repo
    repo.close()


@pytest.fixture
def orchestrator(test_config: AppConfig, test_repo: IncidentRepository) -> SelfHealingOrchestrator:
    """SelfHealingOrchestrator configured for API testing."""
    registry = TargetRegistry(test_config.targets)
    return SelfHealingOrchestrator(
        config=test_config,
        target_registry=registry,
        incident_store=test_repo,
        dry_run=True,
    )


@pytest.fixture
def client(
    test_config: AppConfig,
    orchestrator: SelfHealingOrchestrator,
    test_repo: IncidentRepository,
    tmp_path: Path,
) -> Generator[TestClient, None, None]:
    """Configured TestClient for the API application."""
    registry = TargetRegistry(test_config.targets)
    fault_mgr = FaultManager(state_dir=tmp_path / ".fault_state")

    app = create_app(
        config=test_config,
        target_registry=registry,
        orchestrator=orchestrator,
        incident_store=test_repo,
        fault_manager=fault_mgr,
    )
    test_client = TestClient(app)
    yield test_client
    if orchestrator.is_running:
        orchestrator.stop()


# =============================================================================
# 1. GET /health
# =============================================================================
def test_api_health_endpoint(client: TestClient):
    """Verify GET /health returns 200 and healthy status structure."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "version" in data
    assert "timestamp" in data
    assert data["dry_run"] is True
    assert "system" in data
    assert "cpu_percent" in data["system"]
    assert "memory_percent" in data["system"]
    assert data["registered_targets"] == 2


# =============================================================================
# 2. GET /metrics
# =============================================================================
def test_api_metrics_endpoint(client: TestClient):
    """Verify GET /metrics captures and returns full telemetry snapshot."""
    response = client.get("/metrics")
    assert response.status_code == 200
    data = response.json()
    assert "timestamp" in data
    assert "cpu" in data
    assert "percent" in data["cpu"]
    assert "memory" in data
    assert "percent" in data["memory"]
    assert "disks" in data
    assert "uptime_seconds" in data


# =============================================================================
# 3. GET /processes
# =============================================================================
def test_api_processes_endpoints(client: TestClient):
    """Verify GET /processes returns monitored processes or filters by target."""
    response = client.get("/processes")
    assert response.status_code == 200
    assert isinstance(response.json(), list)

    # Filter with existing target
    res_filtered = client.get("/processes?target_id=demo-cpu")
    assert res_filtered.status_code == 200
    assert isinstance(res_filtered.json(), list)

    # Filter with non-existent target returns 404
    res_404 = client.get("/processes?target_id=unknown-target")
    assert res_404.status_code == 404
    assert "not found" in res_404.json()["detail"].lower()


# =============================================================================
# 4. GET /services
# =============================================================================
def test_api_services_endpoint(client: TestClient):
    """Verify GET /services returns service metrics and handles query param."""
    response = client.get("/services")
    assert response.status_code == 200
    services = response.json()
    assert isinstance(services, list)

    # Specific valid service unit
    res_single = client.get("/services?service=cron")
    assert res_single.status_code == 200
    single_list = res_single.json()
    assert len(single_list) == 1
    assert "cron" in single_list[0]["service_name"]

    # Invalid service name rejected by regex
    res_invalid = client.get("/services?service=bad;rm+-rf")
    assert res_invalid.status_code == 400


# =============================================================================
# 5. GET /incidents
# =============================================================================
def test_api_incidents_list_and_filters(client: TestClient):
    """Verify GET /incidents lists records and applies query filters."""
    # List all
    response = client.get("/incidents")
    assert response.status_code == 200
    incidents = response.json()
    assert len(incidents) == 2

    # Filter by fault_type
    res_cpu = client.get("/incidents?fault_type=HIGH_CPU")
    assert res_cpu.status_code == 200
    assert len(res_cpu.json()) == 1
    assert res_cpu.json()[0]["fault_event"]["fault_type"] == "HIGH_CPU"

    # Filter by status
    res_verified = client.get("/incidents?status=VERIFIED_SUCCESS")
    assert res_verified.status_code == 200
    assert len(res_verified.json()) == 1
    assert res_verified.json()[0]["status"] == "VERIFIED_SUCCESS"

    # Filter by target_id
    res_target = client.get("/incidents?target_id=demo-service")
    assert res_target.status_code == 200
    assert len(res_target.json()) == 1
    assert res_target.json()[0]["target_id"] == "demo-service"

    # Limit parameter
    res_limit = client.get("/incidents?limit=1")
    assert res_limit.status_code == 200
    assert len(res_limit.json()) == 1


# =============================================================================
# 6. GET /incidents/{id}
# =============================================================================
def test_api_incident_by_id(client: TestClient):
    """Verify GET /incidents/{id} returns single record or 404."""
    # Existing
    res_found = client.get("/incidents/inc-verified-111")
    assert res_found.status_code == 200
    data = res_found.json()
    assert data["incident_id"] == "inc-verified-111"
    assert data["status"] == "VERIFIED_SUCCESS"
    assert data["policy_decision"]["allowed"] is True

    # Missing
    res_missing = client.get("/incidents/nonexistent-uuid")
    assert res_missing.status_code == 404
    assert "not found" in res_missing.json()["detail"].lower()


# =============================================================================
# 7. GET /system/status
# =============================================================================
def test_api_system_status_endpoint(client: TestClient):
    """Verify GET /system/status returns daemon lifecycle and metrics."""
    response = client.get("/system/status")
    assert response.status_code == 200
    data = response.json()
    assert "version" in data
    assert data["mode"] == "development"
    assert data["dry_run"] is True
    assert data["orchestrator_running"] is False
    assert data["active_targets_count"] == 2
    assert "stats" in data
    assert "ticks_count" in data["stats"]


# =============================================================================
# 8. GET /guardrails
# =============================================================================
def test_api_guardrails_endpoint(client: TestClient):
    """Verify GET /guardrails returns policies, allowlists, and safety limits."""
    response = client.get("/guardrails")
    assert response.status_code == 200
    data = response.json()
    assert data["enforce_target_allowlist"] is True
    assert data["default_cooldown_seconds"] == 1.0
    assert data["max_actions_per_window"] == 3
    assert len(data["allowed_action_types"]) > 0
    assert "terminate_demo_process" in data["allowed_action_types"]
    assert "systemd" in data["forbidden_process_names"]
    assert "/etc" in data["forbidden_directory_prefixes"]


# =============================================================================
# 9. GET /recovery/history
# =============================================================================
def test_api_recovery_history_endpoint(client: TestClient):
    """Verify GET /recovery/history extracts recovery interventions."""
    response = client.get("/recovery/history")
    assert response.status_code == 200
    items = response.json()
    assert len(items) == 2

    # Verify first item (verified recovery)
    item_verified = next(i for i in items if i["incident_id"] == "inc-verified-111")
    assert item_verified["target_id"] == "demo-cpu"
    assert item_verified["allowed_by_guardrails"] is True
    assert item_verified["recovery_success"] is True
    assert item_verified["is_dry_run"] is True
    assert item_verified["action_type"] == "terminate_demo_process"
    assert item_verified["verification_status"] == "HEALTHY"

    # Verify second item (rejected action)
    item_rejected = next(i for i in items if i["incident_id"] == "inc-rejected-222")
    assert item_rejected["target_id"] == "demo-service"
    assert item_rejected["allowed_by_guardrails"] is False
    assert item_rejected["recovery_success"] is False
    assert item_rejected["action_type"] == "restart_demo_service"

    # Filter by target
    res_target = client.get("/recovery/history?target_id=demo-cpu")
    assert res_target.status_code == 200
    assert len(res_target.json()) == 1


# =============================================================================
# 10. POST /faults/{fault_type}/start and stop
# =============================================================================
def test_api_fault_injection_endpoints(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    """Verify POST /faults/{type}/start and stop trigger safe demo fault states."""
    # Mock injector to avoid spawning live external spin workload during unit test
    def mock_start(target, **kwargs):
        return FaultStatus(
            fault_name="cpu",
            target_id=target.target_id,
            is_running=True,
            pid=99999,
            details="Mock fault started",
        )

    def mock_stop(target):
        return FaultStatus(
            fault_name="cpu",
            target_id=target.target_id,
            is_running=False,
            pid=None,
            details="Mock fault stopped",
        )

    fault_mgr: FaultManager = client.app.state.fault_manager
    monkeypatch.setattr(fault_mgr.get_injector("cpu"), "start", mock_start)
    monkeypatch.setattr(fault_mgr.get_injector("cpu"), "stop", mock_stop)

    # Start valid demo fault
    res_start = client.post("/faults/cpu/start", json={"intensity": 75})
    assert res_start.status_code == 200
    start_data = res_start.json()
    assert start_data["fault_name"] == "cpu"
    assert start_data["is_running"] is True
    assert start_data["pid"] == 99999

    # Stop valid demo fault
    res_stop = client.post("/faults/cpu/stop")
    assert res_stop.status_code == 200
    stop_data = res_stop.json()
    assert stop_data["is_running"] is False

    # Unsupported fault type returns 400
    res_bad_start = client.post("/faults/unknown_fault/start")
    assert res_bad_start.status_code == 400
    assert "unsupported" in res_bad_start.json()["detail"].lower()

    res_bad_stop = client.post("/faults/unknown_fault/stop")
    assert res_bad_stop.status_code == 400


# =============================================================================
# 11. POST /system/dry-run
# =============================================================================
def test_api_post_dry_run_toggle(client: TestClient):
    """Verify POST /system/dry-run dynamically toggles dry-run across engines."""
    # Set dry-run to False
    res_off = client.post("/system/dry-run", json={"dry_run": False})
    assert res_off.status_code == 200
    assert res_off.json()["dry_run"] is False

    orch: SelfHealingOrchestrator = client.app.state.orchestrator
    assert orch.dry_run is False
    assert orch.guardrail_engine.default_dry_run is False
    assert orch.recovery_executor.dry_run is False

    # Set dry-run back to True
    res_on = client.post("/system/dry-run", json={"dry_run": True})
    assert res_on.status_code == 200
    assert res_on.json()["dry_run"] is True
    assert orch.dry_run is True


# =============================================================================
# 12. POST /system/monitoring
# =============================================================================
def test_api_post_monitoring_control(client: TestClient):
    """Verify POST /system/monitoring executes tick, starts, and stops daemon."""
    orch: SelfHealingOrchestrator = client.app.state.orchestrator

    # 1. Action: tick
    res_tick = client.post("/system/monitoring", json={"action": "tick"})
    assert res_tick.status_code == 200
    tick_data = res_tick.json()
    assert tick_data["action"] == "tick"
    assert tick_data["ticks_completed"] >= 1
    assert "Tick completed" in tick_data["status"]

    # 2. Action: start
    res_start = client.post("/system/monitoring", json={"action": "start", "interval": 0.5})
    assert res_start.status_code == 200
    start_data = res_start.json()
    assert start_data["action"] == "start"
    assert start_data["is_running"] is True
    assert orch.is_running is True

    # 3. Action: stop
    res_stop = client.post("/system/monitoring", json={"action": "stop"})
    assert res_stop.status_code == 200
    stop_data = res_stop.json()
    assert stop_data["action"] == "stop"
    assert stop_data["is_running"] is False
    assert orch.is_running is False

    # 4. Invalid action returns 422 validation error
    res_invalid = client.post("/system/monitoring", json={"action": "reboot_machine"})
    assert res_invalid.status_code == 422


# =============================================================================
# 13. Safety & Command Injection Protection
# =============================================================================
def test_api_safety_command_injection_rejected(client: TestClient):
    """Verify API rejects any attempts to inject commands or path traversal."""
    # Illegal path characters in fault type
    res_traversal = client.post("/faults/..%2F..%2Fbin%2Fsh/start")
    assert res_traversal.status_code in [400, 404]

    # Command injection payload in service name
    res_cmd = client.get("/services?service=cron;cat+/etc/shadow")
    assert res_cmd.status_code == 400
    assert "Invalid service name" in res_cmd.json()["detail"]
