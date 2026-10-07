"""Deterministic deadlock and hung thread detector.

Detects multi-threaded circular lock contention and hung execution states
where worker threads are permanently blocked without CPU activity.
"""

from typing import Any, Dict, List, Optional
import uuid

from self_healing.core.models import (
    DetectionEvent,
    FaultSeverity,
    FaultType,
    MetricSnapshot,
    ProcessState,
    TargetSpec,
    utc_now,
)
from self_healing.detection.base import BaseFaultRule
from self_healing.logging.logger import get_logger

logger = get_logger("detection.deadlock")


class DeadlockDetector(BaseFaultRule):
    """Detects multi-threaded deadlock state exhibiting zero CPU progress."""

    def __init__(
        self,
        name: str = "deadlock_rule",
        min_threads: int = 3,
        max_cpu_percent: float = 1.0,
        min_samples: int = 3,
        severity: FaultSeverity = FaultSeverity.HIGH,
    ) -> None:
        super().__init__(name=name, fault_type=FaultType.DEADLOCK, severity=severity)
        self.min_threads = min_threads
        self.max_cpu_percent = max_cpu_percent
        self.min_samples = min_samples

    def _extract_process_telemetry(
        self, target: TargetSpec, snapshot: MetricSnapshot
    ) -> Optional[Dict[str, Any]]:
        """Extract process state, thread count, and CPU percent from snapshot."""
        # 1. Check direct target fields on snapshot
        if snapshot.target_id == target.target_id:
            return {
                "pid": snapshot.target_pid,
                "state": snapshot.target_state or ProcessState.UNKNOWN,
                "threads": snapshot.target_num_threads or 0,
                "cpu_percent": snapshot.target_cpu_percent or 0.0,
            }

        # 2. Match within processes list if present
        if hasattr(snapshot, "processes") and snapshot.processes:
            for p in snapshot.processes:
                if p.target_id == target.target_id:
                    return {
                        "pid": p.pid,
                        "state": p.state,
                        "threads": p.num_threads or 0,
                        "cpu_percent": p.cpu_percent,
                    }

        return None

    def evaluate(
        self,
        target: TargetSpec,
        window: List[MetricSnapshot],
    ) -> Optional[DetectionEvent]:
        if not window or len(window) < self.min_samples:
            return None

        samples = window[-self.min_samples:]
        thread_counts: List[int] = []
        cpu_values: List[float] = []
        states: List[str] = []
        pids: List[Optional[int]] = []

        for snap in samples:
            info = self._extract_process_telemetry(target, snap)
            if info is None:
                return None

            threads = info["threads"]
            cpu = info["cpu_percent"]
            state = info["state"]

            thread_counts.append(threads)
            cpu_values.append(cpu)
            states.append(state.value if hasattr(state, "value") else str(state))
            pids.append(info["pid"])

            # Must satisfy deadlock profile: multi-threaded, sleeping/idle, zero CPU
            if threads < self.min_threads:
                return None
            if cpu > self.max_cpu_percent:
                return None
            if state not in (ProcessState.SLEEPING, ProcessState.IDLE):
                return None

        recent_pid = pids[-1]
        recent_threads = thread_counts[-1]
        avg_cpu = sum(cpu_values) / len(cpu_values)

        evidence: Dict[str, Any] = {
            "target_id": target.target_id,
            "pid": recent_pid,
            "thread_counts": thread_counts,
            "cpu_percent_series": cpu_values,
            "average_cpu_percent": round(avg_cpu, 2),
            "states_series": states,
            "sample_count": len(samples),
            "min_threads_threshold": self.min_threads,
            "max_cpu_threshold": self.max_cpu_percent,
        }

        description = (
            f"Deterministic deadlock detected on target '{target.target_id}' (PID {recent_pid}): "
            f"process has {recent_threads} threads hung in SLEEPING state with {avg_cpu:.1f}% CPU "
            f"sustained across {len(samples)} samples."
        )

        return DetectionEvent(
            event_id=str(uuid.uuid4()),
            target_id=target.target_id,
            fault_type=self.fault_type,
            severity=self.severity,
            detected_at=utc_now(),
            triggering_value=float(recent_threads),
            threshold_value=float(self.min_threads),
            description=description,
            evidence=evidence,
        )
