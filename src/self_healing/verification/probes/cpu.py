"""Measurable CPU post-recovery verification probe."""

import time
from typing import Any, Dict, List, Optional
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

logger = get_logger("verification.probe.cpu")


class CpuVerificationProbe(BaseVerificationProbe):
    """Verifies that CPU utilization has returned below threshold and sustained."""

    def __init__(
        self,
        name: str = "cpu_threshold_sustained",
        cpu_threshold: float = 60.0,
        observation_samples: int = 2,
        sample_interval: float = 0.2,
    ) -> None:
        super().__init__(
            name=name,
            fault_type=FaultType.HIGH_CPU,
            description="Verifies CPU utilization dropped below threshold and sustained.",
        )
        self.cpu_threshold = cpu_threshold
        self.observation_samples = max(1, observation_samples)
        self.sample_interval = sample_interval

    def verify(
        self,
        target: TargetSpec,
        action: Optional[RecoveryAction] = None,
        recovery_result: Optional[RecoveryResult] = None,
        metrics_before: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> ProbeOutcome:
        metrics_before = metrics_before or {}
        before_cpu = metrics_before.get("cpu_percent") or metrics_before.get("target_cpu_percent", 0.0)

        # 1. Check if recovery action was process termination
        target_pid = (
            (action.parameters.get("pid") if action else None)
            or metrics_before.get("pid")
            or metrics_before.get("target_pid")
        )

        is_terminate_action = (
            action is not None
            and action.action_type == AllowedActionType.TERMINATE_DEMO_PROCESS
        )

        samples: List[float] = []
        pid_alive = False

        if target_pid is not None:
            try:
                proc = psutil.Process(int(target_pid))
                pid_alive = proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pid_alive = False

        # If terminate action was executed, process must no longer be running
        if is_terminate_action:
            if pid_alive:
                evidence = {
                    "action": "terminate",
                    "target_pid": target_pid,
                    "pid_alive": True,
                    "cpu_before": before_cpu,
                    "failure": "Target PID still running after termination action",
                }
                metrics_after = {"pid_alive": True, "target_pid": target_pid}
                return ProbeOutcome(
                    name=self.name,
                    passed=False,
                    evidence=evidence,
                    metrics_after=metrics_after,
                    message=f"CPU verification failed: target PID {target_pid} is still alive.",
                )

        # 2. Sample CPU utilization over observation window
        start_time = time.perf_counter()
        for i in range(self.observation_samples):
            if i > 0 and self.sample_interval > 0:
                time.sleep(self.sample_interval)

            current_pct = 0.0
            if target_pid is not None and pid_alive:
                try:
                    proc = psutil.Process(int(target_pid))
                    current_pct = proc.cpu_percent(interval=0.05)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    current_pct = 0.0
                    pid_alive = False
            else:
                # System-level or target matching substring
                matching_procs = []
                for p in psutil.process_iter(["pid", "cmdline"]):
                    try:
                        cmdline = " ".join(p.info.get("cmdline") or [])
                        if target.cmdline_substring in cmdline:
                            matching_procs.append(p)
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass

                if matching_procs:
                    current_pct = max(p.cpu_percent(interval=0.05) for p in matching_procs)
                else:
                    current_pct = psutil.cpu_percent(interval=0.05)

            samples.append(current_pct)

        observation_duration = time.perf_counter() - start_time
        max_cpu_observed = max(samples) if samples else 0.0
        avg_cpu_observed = sum(samples) / len(samples) if samples else 0.0

        all_below_threshold = all(s <= self.cpu_threshold for s in samples)

        evidence = {
            "before_cpu_percent": before_cpu,
            "after_cpu_percent": avg_cpu_observed,
            "max_observed_cpu": max_cpu_observed,
            "cpu_threshold": self.cpu_threshold,
            "samples_count": len(samples),
            "samples": samples,
            "observation_duration_seconds": round(observation_duration, 4),
            "sustained": all_below_threshold,
            "target_pid": target_pid,
            "pid_alive": pid_alive,
        }

        metrics_after = {
            "cpu_percent": avg_cpu_observed,
            "target_pid": target_pid,
            "pid_alive": pid_alive,
            "sustained_samples": len(samples),
        }

        if all_below_threshold:
            msg = (
                f"CPU utilization sustained below threshold ({avg_cpu_observed:.1f}% <= {self.cpu_threshold:.1f}%) "
                f"over {len(samples)} samples."
            )
            return ProbeOutcome(
                name=self.name,
                passed=True,
                evidence=evidence,
                metrics_after=metrics_after,
                message=msg,
            )
        else:
            msg = (
                f"CPU utilization did not sustain below threshold: max {max_cpu_observed:.1f}% > {self.cpu_threshold:.1f}%."
            )
            return ProbeOutcome(
                name=self.name,
                passed=False,
                evidence=evidence,
                metrics_after=metrics_after,
                message=msg,
            )
