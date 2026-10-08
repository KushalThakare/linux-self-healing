"""FastAPI management and health check application for Linux self-healing."""

from typing import Any, Dict, List, Optional
from fastapi import FastAPI, HTTPException, Query, status
import psutil

from self_healing import __version__
from self_healing.api.schemas import (
    DryRunRequest,
    DryRunResponse,
    FaultStartRequest,
    GuardrailsSummary,
    HealthResponse,
    MonitoringControlRequest,
    MonitoringControlResponse,
    RecoveryHistoryItem,
    SystemStatusResponse,
)
from self_healing.config.settings import AppConfig, get_default_config
from self_healing.core.models import (
    AllowedActionType,
    FaultStatus,
    IncidentRecord,
    IncidentStatus,
    ProcessMetrics,
    ServiceMetrics,
    SystemSnapshot,
    TargetSpec,
    utc_now,
)
from self_healing.fault_injection.manager import FaultManager
from self_healing.incidents import BaseIncidentStore, IncidentRepository
from self_healing.logging.logger import get_logger
from self_healing.monitoring.collector import ProcessMetricsCollector, SystemMetricsCollector
from self_healing.monitoring.service_inspector import ServiceInspector
from self_healing.orchestrator import SelfHealingOrchestrator
from self_healing.targets.registry import (
    FORBIDDEN_DIRECTORY_PREFIXES,
    FORBIDDEN_PROCESS_NAMES,
    TargetRegistry,
)

logger = get_logger("api.app")

FAULT_NAME_NORMALIZE = {
    "cpu": "cpu",
    "high_cpu": "cpu",
    "cpu_runaway": "cpu",
    "memory": "memory",
    "memory_leak": "memory",
    "abnormal_memory": "memory",
    "service": "service",
    "service_failure": "service",
    "process_crash": "service",
    "disk": "disk",
    "disk_exhaustion": "disk",
    "disk_growth": "disk",
    "deadlock": "deadlock",
}


def create_app(
    config: Optional[AppConfig] = None,
    target_registry: Optional[TargetRegistry] = None,
    orchestrator: Optional[SelfHealingOrchestrator] = None,
    incident_store: Optional[BaseIncidentStore] = None,
    fault_manager: Optional[FaultManager] = None,
    metrics_collector: Optional[SystemMetricsCollector] = None,
) -> FastAPI:
    """Create and configure the FastAPI management application.
    
    Provides operator telemetry, incident inspection, safety policy queries,
    and controlled demo fault triggering while enforcing strict safety guardrails.
    """
    app_config = config or get_default_config()
    registry = target_registry or TargetRegistry(app_config.targets)

    # Incident store
    store = incident_store
    if store is None:
        if orchestrator is not None:
            store = orchestrator.incident_store
        else:
            store = IncidentRepository(db_path=app_config.storage.db_path)

    # Orchestrator
    orch = orchestrator
    if orch is None:
        orch = SelfHealingOrchestrator(
            config=app_config,
            target_registry=registry,
            incident_store=store,
            dry_run=app_config.system.dry_run,
        )

    # Fault manager
    fm = fault_manager or FaultManager()

    # Collectors & Inspectors
    collector = metrics_collector or orch.collector
    service_inspector = ServiceInspector()
    process_collector = ProcessMetricsCollector()

    app = FastAPI(
        title="Linux Self-Healing Management API",
        version=__version__,
        description="Autonomous Fault Detection and Self-Healing System for Linux - Management & Telemetry API.",
    )

    # Store shared state on app.state
    app.state.config = app_config
    app.state.registry = registry
    app.state.orchestrator = orch
    app.state.incident_store = store
    app.state.fault_manager = fm
    app.state.collector = collector

    # =========================================================================
    # 1. Health Probe
    # =========================================================================
    @app.get("/health", response_model=HealthResponse)
    def get_health() -> HealthResponse:
        """System health and resource availability probe."""
        mem = psutil.virtual_memory()
        cpu = psutil.cpu_percent(interval=None)

        return HealthResponse(
            status="healthy",
            version=__version__,
            timestamp=utc_now(),
            dry_run=orch.dry_run,
            system={
                "cpu_percent": float(cpu),
                "memory_percent": float(mem.percent),
                "memory_available_mb": round(mem.available / (1024 * 1024), 2),
            },
            registered_targets=len(registry.list_targets()),
        )

    # =========================================================================
    # 2. System Metrics Telemetry Snapshot
    # =========================================================================
    @app.get("/metrics", response_model=SystemSnapshot)
    def get_metrics() -> SystemSnapshot:
        """Full system and supervised targets telemetry snapshot."""
        active_targets = [t for t in registry.list_targets() if t.enabled]
        snapshot = collector.collect_system_snapshot(targets=active_targets)
        return snapshot

    # =========================================================================
    # 3. Supervised Process Status
    # =========================================================================
    @app.get("/processes", response_model=List[ProcessMetrics])
    def get_processes(target_id: Optional[str] = Query(default=None)) -> List[ProcessMetrics]:
        """Monitored process table matching registered demo targets."""
        targets = registry.list_targets()
        if target_id:
            targets = [t for t in targets if t.target_id == target_id]
            if not targets:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Target '{target_id}' not found in registry",
                )

        results: List[ProcessMetrics] = []
        for target in targets:
            procs = process_collector.find_target_processes(target)
            results.extend(procs)
        return results

    # =========================================================================
    # 4. Supervised Service Status
    # =========================================================================
    @app.get("/services", response_model=List[ServiceMetrics])
    def get_services(service: Optional[str] = Query(default=None)) -> List[ServiceMetrics]:
        """Status of supervised systemd services."""
        if service:
            try:
                res = service_inspector.inspect_service(service)
                return [res]
            except ValueError as e:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

        # Inspect targets that declare service/expected_port, plus standard baseline services
        services_to_check: List[str] = ["systemd-journald", "cron"]
        for t in registry.list_targets():
            if t.expected_port or "service" in t.target_id or "web" in t.target_id:
                clean_name = t.target_id.replace("demo-", "")
                if clean_name not in services_to_check:
                    services_to_check.append(clean_name)

        out: List[ServiceMetrics] = []
        for s in services_to_check:
            try:
                out.append(service_inspector.inspect_service(s))
            except Exception:
                pass
        return out

    # =========================================================================
    # 5. Incidents List & Query
    # =========================================================================
    @app.get("/incidents", response_model=List[IncidentRecord])
    def list_incidents(
        fault_type: Optional[str] = Query(default=None),
        status_filter: Optional[str] = Query(default=None, alias="status"),
        target_id: Optional[str] = Query(default=None),
        limit: int = Query(default=50, ge=1, le=500),
    ) -> List[IncidentRecord]:
        """List persistent incident records with optional filters."""
        incidents = store.list_incidents(
            fault_type=fault_type,
            status=status_filter,
            limit=limit,
        )
        if target_id:
            incidents = [i for i in incidents if i.target_id == target_id]
        return incidents

    # =========================================================================
    # 6. Incident Details by ID
    # =========================================================================
    @app.get("/incidents/{incident_id}", response_model=IncidentRecord)
    def get_incident(incident_id: str) -> IncidentRecord:
        """Retrieve full details of an incident by its unique ID."""
        incident = store.get_incident(incident_id)
        if not incident:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Incident '{incident_id}' not found",
            )
        return incident

    # =========================================================================
    # 7. System & Orchestrator Daemon Status
    # =========================================================================
    @app.get("/system/status", response_model=SystemStatusResponse)
    def get_system_status() -> SystemStatusResponse:
        """Current operational status and telemetry stats of the self-healing daemon."""
        active_targets = [t for t in registry.list_targets() if t.enabled]
        return SystemStatusResponse(
            version=__version__,
            mode=app_config.system.mode,
            dry_run=orch.dry_run,
            orchestrator_running=orch.is_running,
            poll_interval_seconds=orch.poll_interval_seconds,
            active_targets_count=len(active_targets),
            active_faults_count=len(orch._active_faults),
            stats=orch.stats,
        )

    # =========================================================================
    # 8. Safety Guardrails Configuration & Policies
    # =========================================================================
    @app.get("/guardrails", response_model=GuardrailsSummary)
    def get_guardrails() -> GuardrailsSummary:
        """Active safety guardrail policies, limits, and allowlists."""
        engine = orch.guardrail_engine
        return GuardrailsSummary(
            enforce_target_allowlist=engine.config.enforce_target_allowlist,
            default_cooldown_seconds=engine.config.default_cooldown_seconds,
            flapping_window_seconds=engine.config.flapping_window_seconds,
            max_actions_per_window=engine.config.max_actions_per_window,
            allowed_action_types=[a.value for a in AllowedActionType],
            forbidden_process_names=list(FORBIDDEN_PROCESS_NAMES),
            forbidden_directory_prefixes=list(FORBIDDEN_DIRECTORY_PREFIXES),
            recent_actions_count=sum(len(v) for v in engine._action_history.values()),
        )

    # =========================================================================
    # 9. Recovery Action History
    # =========================================================================
    @app.get("/recovery/history", response_model=List[RecoveryHistoryItem])
    def get_recovery_history(
        target_id: Optional[str] = Query(default=None),
        limit: int = Query(default=50, ge=1, le=500),
    ) -> List[RecoveryHistoryItem]:
        """Historical audit log of recovery actions executed or simulated."""
        incidents = store.list_incidents(limit=limit)
        if target_id:
            incidents = [i for i in incidents if i.target_id == target_id]

        items: List[RecoveryHistoryItem] = []
        for inc in incidents:
            # Include records with policy evaluation or recovery results
            if not inc.policy_decision and not inc.recovery_result:
                continue

            action_type_val = None
            if inc.policy_decision:
                action_type_val = inc.policy_decision.action_type.value
            elif inc.recovery_result:
                action_type_val = inc.recovery_result.action_type.value

            is_dry = True
            if inc.policy_decision:
                is_dry = inc.policy_decision.is_dry_run
            elif inc.recovery_result:
                is_dry = inc.recovery_result.dry_run

            v_status = None
            if inc.verification_result and inc.verification_result.status:
                v_status = inc.verification_result.status.value

            items.append(
                RecoveryHistoryItem(
                    incident_id=inc.incident_id,
                    target_id=inc.target_id,
                    fault_type=inc.fault_event.fault_type.value if inc.fault_event else "UNKNOWN",
                    timestamp=inc.started_at,
                    completed_at=inc.completed_at,
                    action_type=action_type_val,
                    allowed_by_guardrails=bool(inc.policy_decision and inc.policy_decision.allowed),
                    recovery_success=bool(inc.recovery_result and inc.recovery_result.success),
                    verification_status=v_status,
                    duration_ms=inc.recovery_result.execution_latency_ms if inc.recovery_result else None,
                    is_dry_run=is_dry,
                    final_status=inc.status,
                )
            )
        return items

    # =========================================================================
    # 10. Start Controlled Demo Fault
    # =========================================================================
    @app.post("/faults/{fault_type}/start", response_model=FaultStatus)
    def start_fault(fault_type: str, req: Optional[FaultStartRequest] = None) -> FaultStatus:
        """Trigger an isolated demo fault condition strictly on approved demo targets."""
        normalized = FAULT_NAME_NORMALIZE.get(fault_type.lower())
        if not normalized:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported fault type '{fault_type}'. Available: {list(fm._injectors.keys())}",
            )

        kwargs = {}
        if req:
            if req.intensity is not None:
                kwargs["intensity"] = req.intensity
            if req.max_mb is not None:
                kwargs["max_mb"] = req.max_mb
            if req.rate_mb_per_sec is not None:
                kwargs["rate_mb_per_sec"] = req.rate_mb_per_sec

        try:
            res = fm.start_fault(normalized, **kwargs)
            logger.info("Demo fault '%s' started via API: %s", normalized, res)
            return res
        except Exception as e:
            logger.error("Failed to start demo fault '%s': %s", normalized, e)
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))

    # =========================================================================
    # 11. Stop Controlled Demo Fault
    # =========================================================================
    @app.post("/faults/{fault_type}/stop", response_model=FaultStatus)
    def stop_fault(fault_type: str) -> FaultStatus:
        """Stop an active demo fault condition and terminate injected workload."""
        normalized = FAULT_NAME_NORMALIZE.get(fault_type.lower())
        if not normalized:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported fault type '{fault_type}'. Available: {list(fm._injectors.keys())}",
            )

        try:
            res = fm.stop_fault(normalized)
            logger.info("Demo fault '%s' stopped via API: %s", normalized, res)
            return res
        except Exception as e:
            logger.error("Failed to stop demo fault '%s': %s", normalized, e)
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))

    # =========================================================================
    # 12. Toggle or Set Dry-Run Mode
    # =========================================================================
    @app.post("/system/dry-run", response_model=DryRunResponse)
    def set_dry_run(req: DryRunRequest) -> DryRunResponse:
        """Toggle dry-run simulation mode across orchestrator and safety engines."""
        orch.dry_run = req.dry_run
        orch.guardrail_engine.default_dry_run = req.dry_run
        orch.recovery_executor.dry_run = req.dry_run
        app_config.system.dry_run = req.dry_run

        logger.info("Dry-run mode updated via API to: %s", req.dry_run)
        return DryRunResponse(
            dry_run=req.dry_run,
            message=f"Dry-run mode successfully set to {req.dry_run}",
        )

    # =========================================================================
    # 13. Control Orchestrator Monitoring Loop
    # =========================================================================
    @app.post("/system/monitoring", response_model=MonitoringControlResponse)
    def control_monitoring(req: MonitoringControlRequest) -> MonitoringControlResponse:
        """Control the autonomous self-healing loop (start, stop, or tick)."""
        action = req.action.lower()

        if action == "tick":
            handled = orch.tick()
            return MonitoringControlResponse(
                action="tick",
                status=f"Tick completed successfully ({len(handled)} incidents handled)",
                is_running=orch.is_running,
                ticks_completed=orch.stats.ticks_count,
                incidents_handled=len(handled),
            )
        elif action == "start":
            if req.interval and req.interval > 0:
                orch.poll_interval_seconds = req.interval

            if not orch.is_running:
                orch.start()
                return MonitoringControlResponse(
                    action="start",
                    status="Orchestrator autonomous loop started in background",
                    is_running=True,
                    ticks_completed=orch.stats.ticks_count,
                )
            else:
                return MonitoringControlResponse(
                    action="start",
                    status="Orchestrator autonomous loop is already active",
                    is_running=True,
                    ticks_completed=orch.stats.ticks_count,
                )
        elif action == "stop":
            if orch.is_running:
                orch.stop()
                return MonitoringControlResponse(
                    action="stop",
                    status="Orchestrator autonomous loop stopped",
                    is_running=False,
                    ticks_completed=orch.stats.ticks_count,
                )
            else:
                return MonitoringControlResponse(
                    action="stop",
                    status="Orchestrator autonomous loop was not running",
                    is_running=False,
                    ticks_completed=orch.stats.ticks_count,
                )

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown monitoring action '{req.action}'. Allowed: 'start', 'stop', 'tick'",
        )

    # =========================================================================
    # Backward Compatibility Endpoints
    # =========================================================================
    @app.get("/api/v1/status")
    def legacy_system_status() -> Dict[str, Any]:
        """Legacy framework configuration endpoint."""
        return {
            "version": __version__,
            "mode": app_config.system.mode,
            "dry_run": orch.dry_run,
            "log_level": app_config.system.log_level,
            "monitoring_interval_s": orch.poll_interval_seconds,
            "guardrails": {
                "max_actions_per_window": app_config.guardrails.max_actions_per_window,
                "flapping_window_s": app_config.guardrails.flapping_window_seconds,
                "cooldown_s": app_config.guardrails.default_cooldown_seconds,
            },
            "targets_count": len(registry.list_targets()),
        }

    @app.get("/api/v1/targets", response_model=List[TargetSpec])
    def list_targets() -> List[TargetSpec]:
        """List all approved demo targets under supervision."""
        return registry.list_targets()

    @app.get("/api/v1/targets/{target_id}", response_model=TargetSpec)
    def get_target(target_id: str) -> TargetSpec:
        """Get details for a specific registered target."""
        try:
            return registry.get(target_id)
        except Exception:
            raise HTTPException(status_code=404, detail=f"Target '{target_id}' not found")

    return app
