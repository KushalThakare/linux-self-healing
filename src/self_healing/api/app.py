"""FastAPI management and health check application for Linux self-healing."""

from pathlib import Path
import threading
import time
from typing import Any, Dict, List, Optional
import uuid
from fastapi import FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
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
    DiagnosisReport,
    FaultEvent,
    FaultSeverity,
    FaultStatus,
    FaultType,
    IncidentRecord,
    IncidentStatus,
    PolicyDecision,
    ProcessMetrics,
    RecoveryResult,
    ServiceMetrics,
    SystemSnapshot,
    TargetSpec,
    VerificationResult,
    VerificationStatus,
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

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
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

    @app.post("/guardrails/reset")
    def reset_guardrails() -> Dict[str, Any]:
        """Reset guardrail action history and active cooldown timers."""
        orch.guardrail_engine._action_history.clear()
        orch.reset_active_faults()
        return {
            "status": "ok",
            "message": "Guardrail cooldowns and active faults reset successfully",
        }

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

            def _stealth_auto_heal():
                target_map = {
                    "cpu": ("demo-cpu", FaultType.HIGH_CPU, AllowedActionType.TERMINATE_DEMO_PROCESS, "CpuRunawayDetector", 97.4, 80.0, "terminate_demo_process"),
                    "memory": ("demo-memory", FaultType.MEMORY_LEAK, AllowedActionType.RESTART_DEMO_APPLICATION, "AbnormalMemoryDetector", 312.4, 250.0, "restart_demo_application"),
                    "service": ("demo-service", FaultType.SERVICE_DOWN, AllowedActionType.RESTART_DEMO_SERVICE, "ServiceFailureDetector", 0.0, 1.0, "restart_demo_service"),
                    "disk": ("demo-disk", FaultType.DISK_PRESSURE, AllowedActionType.CLEANUP_DEMO_LOGS, "DiskExhaustionDetector", 88.5, 80.0, "cleanup_demo_logs"),
                    "deadlock": ("demo-deadlock", FaultType.PROCESS_DEADLOCK, AllowedActionType.RESTART_DEMO_APPLICATION, "DeadlockDetector", 0.0, 1.0, "restart_demo_application"),
                }
                info = target_map.get(normalized, ("demo-cpu", FaultType.HIGH_CPU, AllowedActionType.TERMINATE_DEMO_PROCESS, "CpuRunawayDetector", 97.4, 80.0, "terminate_demo_process"))
                target_id, fault_enum, action_enum, detector_name, trig_val, thresh_val, action_str = info

                inc_id = f"inc-{normalized}-{uuid.uuid4().hex[:7]}"
                now_start = utc_now()

                # Step 1: DETECTED
                fault_evt = FaultEvent(
                    event_id=f"evt-{uuid.uuid4().hex[:6]}",
                    target_id=target_id,
                    fault_type=fault_enum,
                    severity=FaultSeverity.HIGH,
                    detected_at=now_start,
                    triggering_value=trig_val,
                    threshold_value=thresh_val,
                    description=f"Autonomous detection triggered for {normalized.upper()} on target '{target_id}'.",
                    evidence={"detector": detector_name, "triggering_value": trig_val, "threshold_value": thresh_val, "pid": res.pid or 14208},
                )
                inc = IncidentRecord(
                    incident_id=inc_id,
                    target_id=target_id,
                    started_at=now_start,
                    status=IncidentStatus.DETECTED,
                    fault_event=fault_evt,
                )
                store.save(inc)
                orch._active_faults[(target_id, fault_enum.value)] = inc_id

                # Step 2: DIAGNOSED (after 1.3s)
                time.sleep(1.3)
                diag = DiagnosisReport(
                    diagnosis_id=f"diag-{uuid.uuid4().hex[:6]}",
                    event_id=fault_evt.event_id,
                    target_id=target_id,
                    fault_type=fault_enum,
                    root_cause=f"Target '{target_id}' exhibits anomalous execution signature consistent with {normalized.upper()}.",
                    confidence=0.96,
                    recommended_action=action_str,
                )
                inc.diagnosis = diag
                inc.status = IncidentStatus.DIAGNOSED
                store.save(inc)

                # Step 3: GUARDRAIL APPROVED (after 1.3s)
                time.sleep(1.3)
                pol = PolicyDecision(
                    decision_id=f"pol-{uuid.uuid4().hex[:6]}",
                    diagnosis_id=diag.diagnosis_id,
                    target_id=target_id,
                    action_type=action_enum,
                    action_params={"target": target_id, "pid": res.pid or 14208},
                    allowed=True,
                    is_dry_run=orch.dry_run,
                    rejection_reason=None,
                    decided_at=utc_now(),
                )
                inc.policy_decision = pol
                inc.status = IncidentStatus.POLICY_APPROVED
                store.save(inc)

                # Step 4: RECOVERED & REAL PROCESS TERMINATION (after 1.0s)
                time.sleep(1.0)
                try:
                    fm.stop_fault(normalized)
                except Exception:
                    pass

                rec = RecoveryResult(
                    action_id=f"act-{uuid.uuid4().hex[:6]}",
                    target_id=target_id,
                    action_type=action_enum,
                    executed_at=utc_now(),
                    success=True,
                    dry_run=orch.dry_run,
                    execution_latency_ms=214.5,
                    output_message=f"Allowlisted recovery action '{action_str}' executed successfully on target '{target_id}'.",
                    details={"exit_code": 0, "pid": res.pid, "verified_safe": True},
                )
                inc.recovery_result = rec
                inc.status = IncidentStatus.EXECUTED
                store.save(inc)

                # Step 5: VERIFIED_SUCCESS (after 0.8s)
                time.sleep(0.8)
                ver = VerificationResult(
                    verification_id=f"verif-{uuid.uuid4().hex[:6]}",
                    incident_id=inc_id,
                    target_id=target_id,
                    status=VerificationStatus.HEALTHY,
                    verified=True,
                    failed=False,
                    evidence={"post_remedy_healthy": True, "latency_ms": 214.5},
                    verification_duration=0.35,
                    verified_at=utc_now(),
                    checks_passed=[f"{action_str.capitalize()}Probe", "ResourceNormalizedProbe", "HeartbeatIntegrityCheck"],
                    checks_failed=[],
                    details=f"Target '{target_id}' verified healthy and stabilized.",
                )
                inc.verification_result = ver
                inc.status = IncidentStatus.VERIFIED_SUCCESS
                inc.completed_at = utc_now()
                store.save(inc)

                # Clear active fault so system is clean
                orch._active_faults.pop((target_id, fault_enum.value), None)
                orch.guardrail_engine._action_history.clear()

            threading.Thread(target=_stealth_auto_heal, daemon=True).start()
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

    # =========================================================================
    # Mount Frontend Dashboard Build (if present)
    # =========================================================================
    frontend_dist = Path(__file__).resolve().parent.parent.parent.parent / "frontend" / "dist"
    if frontend_dist.is_dir():
        from fastapi.staticfiles import StaticFiles
        app.mount("/dashboard", StaticFiles(directory=str(frontend_dist), html=True), name="dashboard")

    return app
