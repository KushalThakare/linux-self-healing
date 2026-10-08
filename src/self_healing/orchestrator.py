"""Autonomous Fault Detection and Self-Healing Orchestrator for Linux.

Executes the closed-loop autonomous reliability pipeline:
MONITOR -> DETECT -> DIAGNOSE -> GUARDRAIL -> RECOVER -> VERIFY -> RECORD
"""

from collections import deque
from datetime import datetime
from pathlib import Path
import signal
import sys
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union
import uuid
from pydantic import BaseModel, Field

from self_healing.config.settings import AppConfig, load_config
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
    SystemSnapshot,
    TargetSpec,
    VerificationResult,
    VerificationStatus,
    utc_now,
)
from self_healing.detection import (
    AbnormalMemoryDetector,
    CpuRunawayDetector,
    DeadlockDetector,
    DiskExhaustionDetector,
    RuleDetectionEngine,
    ServiceFailureDetector,
)
from self_healing.diagnosis.engine import DeterministicDiagnosisEngine
from self_healing.guardrails.engine import SafetyGuardrailEngine
from self_healing.guardrails.registry import AllowedActionRegistry
from self_healing.incidents import IncidentRepository
from self_healing.incidents.store import BaseIncidentStore
from self_healing.logging.logger import get_logger
from self_healing.monitoring.collector import (
    MetricRingBuffer,
    ProcessMetricsCollector,
    SystemMetricsCollector,
)
from self_healing.recovery.executor import RecoveryExecutor
from self_healing.targets.registry import TargetRegistry
from self_healing.verification.coordinator import RemediationCoordinator
from self_healing.verification.engine import VerificationEngine
from self_healing.verification.retry import RetryPolicy

logger = get_logger("orchestrator")


class OrchestratorStats(BaseModel):
    """Runtime metrics and execution statistics for the autonomous orchestrator."""
    ticks_count: int = Field(default=0, description="Total execution ticks evaluated")
    snapshots_collected: int = Field(default=0, description="System snapshots gathered")
    faults_detected: int = Field(default=0, description="Total fault events detected")
    diagnoses_performed: int = Field(default=0, description="Total root cause diagnoses run")
    actions_approved: int = Field(default=0, description="Actions passed through guardrails")
    actions_rejected: int = Field(default=0, description="Actions rejected by safety guardrails")
    remediations_executed: int = Field(default=0, description="Recovery remediations dispatched")
    verifications_passed: int = Field(default=0, description="Post-recovery verifications passed")
    verifications_failed: int = Field(default=0, description="Post-recovery verifications failed")
    incidents_escalated: int = Field(default=0, description="Incidents halted and escalated")
    last_tick_at: Optional[datetime] = Field(default=None, description="Timestamp of most recent tick")


class SelfHealingOrchestrator:
    """Central autonomous reliability controller for Linux user-space targets."""

    def __init__(
        self,
        config: Optional[AppConfig] = None,
        target_registry: Optional[TargetRegistry] = None,
        incident_store: Optional[BaseIncidentStore] = None,
        dry_run: Optional[bool] = None,
        poll_interval_seconds: Optional[float] = None,
        config_path: Optional[str] = None,
    ) -> None:
        self.config = config or load_config(config_path)
        self.target_registry = target_registry or TargetRegistry(self.config.targets)

        # Dry-run flag: explicit argument takes precedence, then config
        if dry_run is not None:
            self.dry_run = dry_run
        else:
            self.dry_run = self.config.system.dry_run

        # Polling interval
        if poll_interval_seconds is not None:
            self.poll_interval_seconds = poll_interval_seconds
        else:
            self.poll_interval_seconds = self.config.monitoring.sample_interval_seconds

        # Storage
        if incident_store is not None:
            self.incident_store = incident_store
        else:
            self.incident_store = IncidentRepository(db_path=self.config.storage.db_path)

        # Monitoring Subsystem
        self.collector = SystemMetricsCollector()
        self.ring_buffers: Dict[str, MetricRingBuffer] = {}
        for target in self.target_registry.list_targets():
            self.ring_buffers[target.target_id] = MetricRingBuffer(
                capacity=self.config.monitoring.ring_buffer_size
            )

        # Detection Subsystem
        self.detection_engine = RuleDetectionEngine()
        self._register_default_rules()

        # Diagnosis Subsystem
        self.diagnosis_engine = DeterministicDiagnosisEngine()

        # Policy & Guardrails Subsystem
        self.guardrail_engine = SafetyGuardrailEngine(
            target_registry=self.target_registry,
            config=self.config.guardrails,
            dry_run=self.dry_run,
        )

        # Recovery & Verification Subsystem
        self.recovery_executor = RecoveryExecutor(
            target_registry=self.target_registry,
            dry_run=self.dry_run,
        )
        self.retry_policy = RetryPolicy(
            default_max_retries=self.config.guardrails.max_actions_per_window,
            base_delay_seconds=1.0,
        )
        self.verification_engine = VerificationEngine(retry_policy=self.retry_policy)

        # Closed-Loop Remediation Coordinator
        self.coordinator = RemediationCoordinator(
            guardrail_engine=self.guardrail_engine,
            recovery_executor=self.recovery_executor,
            verification_engine=self.verification_engine,
            retry_policy=self.retry_policy,
            incident_store=self.incident_store,
            target_registry=self.target_registry,
        )

        # Active in-flight faults tracker: (target_id, fault_type) -> incident_id
        # Prevents spawning duplicate parallel incidents while a fault is active
        self._active_faults: Dict[Tuple[str, str], str] = {}

        # Runtime State & Telemetry
        self.stats = OrchestratorStats()
        self.latest_snapshot: Optional[SystemSnapshot] = None
        self._running = False
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._listeners: Dict[str, List[Callable[[Any], None]]] = {
            "tick": [],
            "incident_created": [],
            "incident_resolved": [],
            "incident_escalated": [],
        }

    def _register_default_rules(self) -> None:
        """Register the 5 core deterministic fault detection rules."""
        self.detection_engine.register_rule(
            CpuRunawayDetector(
                cpu_percent_threshold=self.config.monitoring.cpu_percent_threshold,
                duration_seconds=2.0,
                min_samples=2,
            )
        )
        budget_bytes = int(self.config.monitoring.memory_rss_mb_threshold * 1024 * 1024)
        self.detection_engine.register_rule(
            AbnormalMemoryDetector(
                budget_bytes=budget_bytes,
                min_samples=2,
            )
        )
        self.detection_engine.register_rule(ServiceFailureDetector())
        self.detection_engine.register_rule(DiskExhaustionDetector())
        self.detection_engine.register_rule(DeadlockDetector())

    # -------------------------------------------------------------------------
    # Event Listeners
    # -------------------------------------------------------------------------
    def register_listener(self, event_name: str, callback: Callable[[Any], None]) -> None:
        """Register a callback listener for orchestrator lifecycle events."""
        if event_name not in self._listeners:
            self._listeners[event_name] = []
        self._listeners[event_name].append(callback)

    def _emit_event(self, event_name: str, payload: Any) -> None:
        """Dispatch event to registered listeners."""
        for cb in self._listeners.get(event_name, []):
            try:
                cb(payload)
            except Exception as ex:
                logger.error("Error in orchestrator event listener '%s': %s", event_name, ex)

    # -------------------------------------------------------------------------
    # Monitoring Helper
    # -------------------------------------------------------------------------
    def _create_target_metric_snapshot(
        self,
        target: TargetSpec,
        system_snap: SystemSnapshot,
        matching_procs: List[ProcessMetrics],
    ) -> MetricSnapshot:
        """Construct normalized MetricSnapshot for a specific monitored target."""
        target_pid: Optional[int] = None
        target_cpu: float = 0.0
        target_rss: int = 0
        target_threads: int = 0
        target_fds: int = 0
        target_state = (
            ProcessState.DEAD
            if (target.expected_port or "service" in target.target_id or "web" in target.target_id)
            else ProcessState.IDLE
        )

        if matching_procs:
            primary_proc = matching_procs[0]
            target_pid = primary_proc.pid
            target_cpu = primary_proc.cpu_percent
            target_rss = primary_proc.rss_bytes
            target_threads = primary_proc.num_threads or 1
            target_fds = primary_proc.num_fds or 0
            target_state = primary_proc.state

        return MetricSnapshot(
            timestamp=system_snap.timestamp,
            system_cpu_percent=system_snap.cpu.percent,
            system_memory_percent=system_snap.memory.percent,
            uptime_seconds=system_snap.uptime_seconds,
            target_id=target.target_id,
            target_pid=target_pid,
            target_cpu_percent=target_cpu,
            target_rss_bytes=target_rss,
            target_num_threads=target_threads,
            target_num_fds=target_fds,
            target_state=target_state,
            cpu_details=system_snap.cpu,
            memory_details=system_snap.memory,
            disks=system_snap.disks,
            services=system_snap.services,
            processes=matching_procs,
        )

    # -------------------------------------------------------------------------
    # Core Pipeline Step: Tick
    # -------------------------------------------------------------------------
    def tick(self, snapshot: Optional[SystemSnapshot] = None) -> List[IncidentRecord]:
        """Execute one complete discrete cycle of the closed-loop recovery pipeline.
        
        Args:
            snapshot: Optional SystemSnapshot override for testing or replay.
        
        Returns:
            List of IncidentRecord objects handled or updated during this tick.
        """
        self.stats.ticks_count += 1
        self.stats.last_tick_at = utc_now()
        handled_incidents: List[IncidentRecord] = []

        active_targets = [t for t in self.target_registry.list_targets() if t.enabled]
        if not active_targets:
            return handled_incidents

        # ---------------------------------------------------------------------
        # 1. MONITOR: Collect telemetry across system and target processes
        # ---------------------------------------------------------------------
        system_snap = snapshot or self.collector.collect_system_snapshot(targets=active_targets)
        self.latest_snapshot = system_snap
        self.stats.snapshots_collected += 1

        # Map processes by target ID
        procs_by_target: Dict[str, List[ProcessMetrics]] = {t.target_id: [] for t in active_targets}
        if system_snap.processes:
            for p in system_snap.processes:
                if p.target_id in procs_by_target:
                    procs_by_target[p.target_id].append(p)

        # Update per-target sliding metric ring buffers
        for target in active_targets:
            tid = target.target_id
            if tid not in self.ring_buffers:
                self.ring_buffers[tid] = MetricRingBuffer(capacity=self.config.monitoring.ring_buffer_size)

            t_procs = procs_by_target.get(tid, [])
            snap = self._create_target_metric_snapshot(target, system_snap, t_procs)
            self.ring_buffers[tid].append(snap)

        # ---------------------------------------------------------------------
        # 2. DETECT: Evaluate deterministic detection rules on metric windows
        # ---------------------------------------------------------------------
        detected_events: List[Tuple[TargetSpec, DetectionEvent]] = []
        for target in active_targets:
            tid = target.target_id
            window = self.ring_buffers[tid].get_window()
            events = self.detection_engine.evaluate(target, window)
            for ev in events:
                if isinstance(ev, DetectionEvent):
                    detected_events.append((target, ev))
                else:
                    # Convert to DetectionEvent
                    det_ev = DetectionEvent(
                        event_id=ev.event_id,
                        target_id=ev.target_id,
                        fault_type=ev.fault_type,
                        severity=ev.severity,
                        detected_at=ev.detected_at,
                        triggering_value=ev.triggering_value,
                        threshold_value=ev.threshold_value,
                        description=ev.description,
                        evidence={"triggering_value": ev.triggering_value},
                    )
                    detected_events.append((target, det_ev))

        # ---------------------------------------------------------------------
        # 3. DEDUPLICATE & DIAGNOSE & REMEDIATE
        # ---------------------------------------------------------------------
        for target, event in detected_events:
            fault_key = (target.target_id, event.fault_type.value)

            # Check if an incident is already actively ongoing for this fault
            if fault_key in self._active_faults:
                active_inc_id = self._active_faults[fault_key]
                logger.debug(
                    "Fault %s on target '%s' is already active in incident '%s'; skipping duplicate spawn.",
                    event.fault_type.value,
                    target.target_id,
                    active_inc_id,
                )
                continue

            self.stats.faults_detected += 1
            logger.info(
                "Orchestrator processing new fault %s on target '%s': %s",
                event.fault_type.value,
                target.target_id,
                event.description,
            )

            # -----------------------------------------------------------------
            # 4. DIAGNOSE: Traceable, deterministic root cause inference
            # -----------------------------------------------------------------
            window = self.ring_buffers[target.target_id].get_window()
            diagnosis = self.diagnosis_engine.diagnose(
                fault_event=event,
                metric_history=window,
                target=target,
                current_metrics=system_snap,
            )
            self.stats.diagnoses_performed += 1

            # Initialize Incident Record
            incident_id = str(uuid.uuid4())
            incident = IncidentRecord(
                incident_id=incident_id,
                target_id=target.target_id,
                started_at=utc_now(),
                status=IncidentStatus.DIAGNOSED,
                fault_event=event,
                diagnosis=diagnosis,
            )

            # Mark fault as active
            self._active_faults[fault_key] = incident_id
            self.incident_store.save(incident)
            self._emit_event("incident_created", incident)

            # -----------------------------------------------------------------
            # 5. GENERATE CANDIDATE ACTION & ENRICH PARAMETERS
            # -----------------------------------------------------------------
            action = AllowedActionRegistry.from_diagnosis(diagnosis)

            # Enrich target PID if known from latest process snapshot
            t_procs = procs_by_target.get(target.target_id, [])
            if t_procs and "pid" not in action.parameters:
                action = action.model_copy(
                    update={"parameters": {**action.parameters, "pid": t_procs[0].pid}}
                )

            # -----------------------------------------------------------------
            # 6. GUARDRAIL -> RECOVER -> VERIFY -> RECORD (via Coordinator)
            # -----------------------------------------------------------------
            logger.info(
                "Remediation coordinator dispatching action '%s' for incident '%s' (dry_run=%s)",
                action.action_type.value,
                incident.incident_id,
                self.dry_run,
            )

            remediated_incident = self.coordinator.execute_and_verify(
                incident=incident,
                action=action,
                target_spec=target,
                dry_run=self.dry_run,
                auto_retry=True,
            )

            # Update stats based on execution outcome
            if remediated_incident.policy_decision:
                if remediated_incident.policy_decision.allowed:
                    self.stats.actions_approved += 1
                else:
                    self.stats.actions_rejected += 1

            if remediated_incident.recovery_result:
                self.stats.remediations_executed += 1

            if remediated_incident.verification_result:
                if remediated_incident.verification_result.verified:
                    self.stats.verifications_passed += 1
                else:
                    self.stats.verifications_failed += 1

            # Handle fault resolution or escalation
            if remediated_incident.status == IncidentStatus.VERIFIED_SUCCESS:
                # Resolved: clear from active faults tracker
                self._active_faults.pop(fault_key, None)
                self._emit_event("incident_resolved", remediated_incident)
                logger.info(
                    "Fault %s on target '%s' successfully remediated and verified (incident: %s)",
                    event.fault_type.value,
                    target.target_id,
                    remediated_incident.incident_id,
                )
            elif remediated_incident.status == IncidentStatus.ESCALATED:
                self.stats.incidents_escalated += 1
                self._emit_event("incident_escalated", remediated_incident)
                logger.warning(
                    "Fault %s on target '%s' ESCALATED: retry limit exhausted (incident: %s)",
                    event.fault_type.value,
                    target.target_id,
                    remediated_incident.incident_id,
                )
            elif remediated_incident.status == IncidentStatus.POLICY_REJECTED:
                logger.warning(
                    "Remediation action rejected by guardrails for incident '%s': %s",
                    remediated_incident.incident_id,
                    remediated_incident.policy_decision.rejection_reason if remediated_incident.policy_decision else "Rejected",
                )

            handled_incidents.append(remediated_incident)

        self._emit_event("tick", self.stats)
        return handled_incidents

    # -------------------------------------------------------------------------
    # Continuous Loop Execution
    # -------------------------------------------------------------------------
    def run(self, max_ticks: Optional[int] = None) -> None:
        """Run the autonomous monitoring and self-healing loop.
        
        Args:
            max_ticks: Optional maximum number of iterations before halting.
        """
        self._running = True
        self._stop_event.clear()

        logger.info(
            "Starting SelfHealingOrchestrator autonomous loop (interval: %.1fs, dry_run: %s)",
            self.poll_interval_seconds,
            self.dry_run,
        )

        ticks_done = 0
        try:
            while not self._stop_event.is_set():
                if max_ticks is not None and ticks_done >= max_ticks:
                    break

                try:
                    self.tick()
                except Exception as ex:
                    logger.error("Exception during orchestrator tick: %s", ex, exc_info=True)

                ticks_done += 1
                self._stop_event.wait(self.poll_interval_seconds)
        finally:
            self._running = False
            logger.info("SelfHealingOrchestrator loop halted after %d ticks.", ticks_done)

    def start(self) -> threading.Thread:
        """Start the orchestrator background thread."""
        if self._running:
            logger.warning("Orchestrator is already running.")
            assert self._thread is not None
            return self._thread

        self._thread = threading.Thread(target=self.run, name="SelfHealingOrchestratorThread", daemon=True)
        self._thread.start()
        return self._thread

    def stop(self) -> None:
        """Signal the orchestrator to stop and wait for loop termination."""
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5.0)
        self._running = False

    @property
    def is_running(self) -> bool:
        """Check if orchestrator loop is currently executing."""
        return self._running

    def get_active_incidents(self) -> List[str]:
        """List active incident IDs currently in flight."""
        return list(self._active_faults.values())

    def reset_active_faults(self) -> None:
        """Clear the active fault deduplication tracker."""
        self._active_faults.clear()
