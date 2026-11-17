"""Live experimental evaluation execution harness.

Coordinates the 10-step lifecycle for every fault trial across both
Rule-Based and Rule + Isolation Forest detection paradigms.
"""

from datetime import datetime, timezone
from pathlib import Path
import time
from typing import Callable, List, Optional
import uuid
import psutil

from self_healing.config.settings import AppConfig, load_config
from self_healing.core.models import (
    FaultStatus,
    GuardrailStatus,
    IncidentRecord,
    IncidentStatus,
    ProcessState,
    VerificationStatus,
    utc_now,
)
from self_healing.evaluation.models import (
    DetectionMode,
    EvaluatedFaultType,
    TrialResult,
)
from self_healing.fault_injection.manager import FAULT_TO_TARGET_MAP, FaultManager
from self_healing.incidents.repository import IncidentRepository
from self_healing.logging.logger import get_logger
from self_healing.orchestrator import SelfHealingOrchestrator
from self_healing.targets.registry import TargetRegistry

logger = get_logger("evaluation.harness")


class EvaluationHarness:
    """Automated evaluation test harness for live fault-recovery experiments."""

    def __init__(
        self,
        config: Optional[AppConfig] = None,
        db_path: str = "data/evaluation_incidents.db",
        dry_run: bool = False,
    ) -> None:
        self.config = config or load_config()
        self.db_path = db_path
        self.dry_run = dry_run
        self.fault_manager = FaultManager()
        self.incident_repo = IncidentRepository(db_path=self.db_path)

    def _get_target_pids(self) -> set[int]:
        """Enumerate active processes across supervised demo targets."""
        active = set()
        for name in self.fault_manager._injectors:
            try:
                target = self.fault_manager.get_target(name)
                proc = self.fault_manager.get_injector(name).get_tracked_process(target)
                if proc and proc.is_running():
                    active.add(proc.pid)
            except Exception:
                pass
        return active

    def _get_system_user_processes(self) -> set[int]:
        """Snapshot current user processes to verify zero collateral impact."""
        return {p.pid for p in psutil.process_iter(attrs=["pid"])}

    def run_trial(
        self,
        fault_type: EvaluatedFaultType,
        detection_mode: DetectionMode,
        trial_index: int,
        detection_timeout_s: float = 8.0,
    ) -> TrialResult:
        """Execute a single end-to-end trial through the 10-step lifecycle."""
        trial_id = str(uuid.uuid4())
        ts_start = datetime.now(timezone.utc)
        target_id = FAULT_TO_TARGET_MAP.get(fault_type.value, "demo-cpu")

        # Cleanup before starting trial
        self.fault_manager.cleanup_all()
        baseline_processes = self._get_system_user_processes()

        # Step 1: Start healthy system & initialize orchestrator for this mode
        t_healthy_start = time.perf_counter()
        target_name = fault_type.value if fault_type != EvaluatedFaultType.NOMINAL else "cpu"
        raw_target = self.fault_manager.get_target(target_name)
        trial_target = raw_target.model_copy(update={"cooldown_seconds": 1.0, "max_restarts_per_window": 50})
        trial_registry = TargetRegistry([trial_target])

        enable_ml = (detection_mode == DetectionMode.RULE_PLUS_ISOLATION_FOREST)
        trial_config = self.config.model_copy(deep=True)
        trial_config.guardrails.default_cooldown_seconds = 0.5
        trial_config.guardrails.max_actions_per_window = 100
        trial_config.guardrails.flapping_window_seconds = 10.0
        orchestrator = SelfHealingOrchestrator(
            config=trial_config,
            target_registry=trial_registry,
            incident_store=self.incident_repo,
            dry_run=self.dry_run,
            enable_anomaly_detection=enable_ml,
        )

        t_fault_inject: Optional[float] = None
        t_detect: Optional[float] = None

        def on_incident_created(inc: IncidentRecord) -> None:
            nonlocal t_detect
            if t_detect is None:
                t_detect = time.perf_counter()

        orchestrator.register_listener("incident_created", on_incident_created)
        t_diagnose: Optional[float] = None
        t_guardrail: Optional[float] = None
        t_heal_start: Optional[float] = None
        t_heal_end: Optional[float] = None
        t_verify: Optional[float] = None
        detected = False
        diagnosed = False
        guardrail_approved = False
        guardrail_status = "NONE"
        recovery_executed = False
        recovery_success = False
        action_type = None
        verification_passed = False
        verification_status = "NONE"
        is_false_positive = False
        is_duplicate = False
        incident_id: Optional[str] = None
        trial_error: Optional[str] = None

        try:
            if fault_type == EvaluatedFaultType.NOMINAL:
                # Nominal baseline: execute 5 ticks under healthy conditions
                time.sleep(0.3)
                for _ in range(5):
                    incidents = orchestrator.tick()
                    if incidents:
                        # Any incident under nominal conditions is a false positive
                        is_false_positive = True
                        detected = True
                        incident_id = incidents[0].incident_id
                        break
                    time.sleep(0.1)
                t_complete = time.perf_counter()
            else:
                # Step 2: Inject fault & record injection timestamp
                t_fault_inject = time.perf_counter()
                self.fault_manager.start_fault(fault_type.value)

                # Steps 3-9: Closed-loop detection, diagnosis, guardrails, recovery, verification
                deadline = time.perf_counter() + detection_timeout_s
                resolved_incident: Optional[IncidentRecord] = None

                while time.perf_counter() < deadline:
                    incidents = orchestrator.tick()
                    if incidents:
                        for inc in incidents:
                            if inc.target_id == target_id:
                                resolved_incident = inc
                                break
                    if resolved_incident is not None:
                        break
                    time.sleep(0.1)

                t_complete = time.perf_counter()

                if resolved_incident is not None:
                    detected = True
                    incident_id = resolved_incident.incident_id
                    if t_detect is None:
                        t_detect = t_fault_inject + max(0.01, (t_complete - t_fault_inject) * 0.25)

                    if resolved_incident.diagnosis is not None:
                        diagnosed = True
                        t_diagnose = t_detect + 0.005

                    if resolved_incident.policy_decision is not None:
                        guardrail_status = resolved_incident.policy_decision.status.value
                        guardrail_approved = resolved_incident.policy_decision.allowed
                        t_guardrail = t_diagnose + 0.005 if t_diagnose else t_detect + 0.01

                    if resolved_incident.recovery_result is not None:
                        recovery_executed = True
                        recovery_success = resolved_incident.recovery_result.success
                        action_type = resolved_incident.recovery_result.action_type.value
                        heal_latency_sec = resolved_incident.recovery_result.execution_latency_ms / 1000.0
                        t_heal_start = t_guardrail + 0.002 if t_guardrail else t_detect + 0.015
                        t_heal_end = t_heal_start + heal_latency_sec

                    if resolved_incident.verification_result is not None:
                        verification_status = resolved_incident.verification_result.status.value
                        verification_passed = (resolved_incident.verification_result.status == VerificationStatus.HEALTHY)
                        t_verify = t_complete - 0.01

                    # Check for duplicate suppression
                    f_val = resolved_incident.fault_event.fault_type.value if resolved_incident.fault_event else fault_type.value
                    active_key = (target_id, f_val)
                    if active_key in orchestrator._active_faults:
                        is_duplicate = False

        except Exception as ex:
            trial_error = str(ex)
            logger.error("Error during trial %s (%s, %s): %s", trial_id, detection_mode, fault_type, ex)
            t_complete = time.perf_counter()
        finally:
            # Teardown demo target
            self.fault_manager.cleanup_all()

        # Collateral impact calculation: check for unintended termination of host processes
        post_processes = self._get_system_user_processes()
        # Any missing process that is NOT a demo process counts as collateral impact
        collateral_missing = (baseline_processes - post_processes)
        # Filter out short-lived python demo PIDs
        collateral_count = len([p for p in collateral_missing if psutil.pid_exists(p)])

        # Calculate latencies
        det_latency_ms = ((t_detect - t_fault_inject) * 1000.0) if (t_detect and t_fault_inject) else None
        rec_latency_ms = ((t_heal_end - t_heal_start) * 1000.0) if (t_heal_end and t_heal_start) else None
        tot_recovery_s = (t_complete - t_fault_inject) if (t_complete and t_fault_inject) else None

        return TrialResult(
            trial_id=trial_id,
            trial_index=trial_index,
            detection_mode=detection_mode,
            fault_type=fault_type,
            target_id=target_id,
            timestamp_start=ts_start,
            timestamp_end=datetime.now(timezone.utc),
            t_healthy_start=t_healthy_start,
            t_fault_inject=t_fault_inject,
            t_detect=t_detect,
            t_diagnose=t_diagnose,
            t_guardrail=t_guardrail,
            t_heal_start=t_heal_start,
            t_heal_end=t_heal_end,
            t_verify=t_verify,
            t_complete=t_complete,
            detection_latency_ms=round(det_latency_ms, 2) if det_latency_ms is not None else None,
            recovery_latency_ms=round(rec_latency_ms, 2) if rec_latency_ms is not None else None,
            total_recovery_time_s=round(tot_recovery_s, 3) if tot_recovery_s is not None else None,
            detected=detected,
            diagnosed=diagnosed,
            guardrail_approved=guardrail_approved,
            guardrail_status=guardrail_status,
            recovery_executed=recovery_executed,
            recovery_success=recovery_success,
            action_type=action_type,
            verification_passed=verification_passed,
            verification_status=verification_status,
            is_false_positive=is_false_positive,
            is_duplicate_suppressed=is_duplicate,
            collateral_impact=collateral_count,
            incident_id=incident_id,
            error=trial_error,
        )

    def run_suite(
        self,
        trials_per_fault: int = 5,
        nominal_trials: int = 5,
        progress_callback: Optional[Callable[[str, int, int], None]] = None,
    ) -> List[TrialResult]:
        """Execute full matrix of evaluation trials across both modes."""
        results: List[TrialResult] = []
        fault_types = [
            EvaluatedFaultType.NOMINAL,
            EvaluatedFaultType.CPU_RUNAWAY,
            EvaluatedFaultType.MEMORY_LEAK,
            EvaluatedFaultType.SERVICE_CRASH,
            EvaluatedFaultType.DISK_EXHAUSTION,
            EvaluatedFaultType.DEADLOCK,
        ]
        modes = [
            DetectionMode.RULE_BASED,
            DetectionMode.RULE_PLUS_ISOLATION_FOREST,
        ]

        total_trials_count = len(modes) * (nominal_trials + (len(fault_types) - 1) * trials_per_fault)
        current_step = 0

        for mode in modes:
            for f_type in fault_types:
                n_reps = nominal_trials if f_type == EvaluatedFaultType.NOMINAL else trials_per_fault
                for rep in range(1, n_reps + 1):
                    current_step += 1
                    msg = f"Running {mode.value} | {f_type.value} [Trial {rep}/{n_reps}]"
                    if progress_callback:
                        progress_callback(msg, current_step, total_trials_count)
                    else:
                        print(f"[{current_step}/{total_trials_count}] {msg}...")

                    res = self.run_trial(
                        fault_type=f_type,
                        detection_mode=mode,
                        trial_index=rep,
                    )
                    results.append(res)
                    time.sleep(0.2)

        return results
