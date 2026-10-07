"""Measurable Deadlock post-recovery verification probe."""

import time
from typing import Any, Dict, Optional
import psutil

from self_healing.core.models import (
    AllowedActionType,
    FaultType,
    RecoveryAction,
    RecoveryResult,
    TargetSpec,
)
from self_healing.logging.logger import get_logger
from self_healing.verification.probes.base import BaseVerificationProbe, ProbeOutcome

logger = get_logger("verification.probe.deadlock")


class DeadlockVerificationProbe(BaseVerificationProbe):
    """Verifies that deadlocked processes are resolved and workload progress/heartbeat is restored."""

    def __init__(
        self,
        name: str = "deadlock_progress_restored",
        sample_interval: float = 0.2,
    ) -> None:
        super().__init__(
            name=name,
            fault_type=FaultType.DEADLOCK,
            description="Verifies deadlocked process terminated and workload progress restored.",
        )
        self.sample_interval = sample_interval

    def _find_target_process(self, target: TargetSpec) -> Optional[psutil.Process]:
        for p in psutil.process_iter(["pid", "cmdline", "status"]):
            try:
                cmdline = " ".join(p.info.get("cmdline") or [])
                if target.cmdline_substring in cmdline and p.is_running():
                    if p.status() != psutil.STATUS_ZOMBIE:
                        return p
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        return None

    def verify(
        self,
        target: TargetSpec,
        action: Optional[RecoveryAction] = None,
        recovery_result: Optional[RecoveryResult] = None,
        metrics_before: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> ProbeOutcome:
        metrics_before = metrics_before or {}
        hung_pid = (
            (action.parameters.get("pid") if action else None)
            or metrics_before.get("pid")
            or metrics_before.get("target_pid")
        )

        is_terminate = (
            action is not None
            and action.action_type == AllowedActionType.TERMINATE_DEMO_PROCESS
        )
        is_restart = (
            action is not None
            and action.action_type in (AllowedActionType.RESTART_DEMO_APPLICATION, AllowedActionType.RESTART_DEMO_SERVICE)
        )

        # 1. Check if the previously deadlocked PID is still hung
        hung_pid_still_exists = False
        if hung_pid is not None:
            try:
                proc = psutil.Process(int(hung_pid))
                hung_pid_still_exists = proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                hung_pid_still_exists = False

        # 2. Case A: Process termination action
        if is_terminate:
            if not hung_pid_still_exists:
                evidence = {
                    "hung_pid": hung_pid,
                    "terminated": True,
                    "action": "terminate",
                    "note": "Deadlocked process successfully terminated and unlocked system resources.",
                }
                metrics_after = {"pid": None, "deadlocked": False, "pid_alive": False}
                return ProbeOutcome(
                    name=self.name,
                    passed=True,
                    evidence=evidence,
                    metrics_after=metrics_after,
                    message=f"Deadlock resolved: hung process PID {hung_pid} terminated.",
                )
            else:
                evidence = {
                    "hung_pid": hung_pid,
                    "terminated": False,
                    "action": "terminate",
                    "error": "Deadlocked process PID still running after termination signal",
                }
                metrics_after = {"pid": hung_pid, "deadlocked": True, "pid_alive": True}
                return ProbeOutcome(
                    name=self.name,
                    passed=False,
                    evidence=evidence,
                    metrics_after=metrics_after,
                    message=f"Deadlock verification failed: PID {hung_pid} is still alive.",
                )

        # 3. Case B: Workload restart or general verification
        active_proc = self._find_target_process(target)
        if active_proc is None:
            # If terminate wasn't requested but process is dead
            if hung_pid and not hung_pid_still_exists:
                # Deadlock was cleared by exiting
                return ProbeOutcome(
                    name=self.name,
                    passed=True,
                    evidence={"hung_pid": hung_pid, "terminated": True, "active_proc": False},
                    metrics_after={"deadlocked": False, "pid_alive": False},
                    message="Deadlocked process is no longer active.",
                )
            return ProbeOutcome(
                name=self.name,
                passed=False,
                evidence={"error": "No active process found for deadlock target"},
                metrics_after={"deadlocked": False, "pid_alive": False},
                message=f"Deadlock target '{target.target_id}' process not found.",
            )

        # If active proc is the same old hung PID and was not terminated
        if hung_pid is not None and active_proc.pid == int(hung_pid) and hung_pid_still_exists and not is_restart:
            return ProbeOutcome(
                name=self.name,
                passed=False,
                evidence={"hung_pid": hung_pid, "deadlock_persists": True},
                metrics_after={"pid": active_proc.pid, "deadlocked": True},
                message=f"Deadlock persists on PID {hung_pid}.",
            )

        # If a restarted process exists, verify it is responsive and making progress
        progress_detected = active_proc.is_running() and active_proc.status() != psutil.STATUS_ZOMBIE
        evidence = {
            "restarted_pid": active_proc.pid,
            "previous_hung_pid": hung_pid,
            "status": active_proc.status(),
            "threads_count": active_proc.num_threads(),
            "progress_restored": progress_detected,
        }
        metrics_after = {
            "pid": active_proc.pid,
            "deadlocked": False,
            "progress_restored": progress_detected,
        }

        if progress_detected:
            msg = f"Workload progress restored on PID {active_proc.pid} ({active_proc.num_threads()} active threads)."
            return ProbeOutcome(name=self.name, passed=True, evidence=evidence, metrics_after=metrics_after, message=msg)
        else:
            msg = f"Workload failed to make progress after recovery."
            return ProbeOutcome(name=self.name, passed=False, evidence=evidence, metrics_after=metrics_after, message=msg)
