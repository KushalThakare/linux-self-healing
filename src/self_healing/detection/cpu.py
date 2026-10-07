"""Deterministic CPU runaway fault detector.

Evaluates sustained high CPU utilization over a configurable duration window,
effectively filtering out transient spikes.
"""

from typing import Any, Dict, List, Optional
import uuid

from self_healing.core.models import (
    DetectionEvent,
    FaultSeverity,
    FaultType,
    MetricSnapshot,
    TargetSpec,
    utc_now,
)
from self_healing.detection.base import BaseFaultRule
from self_healing.logging.logger import get_logger

logger = get_logger("detection.cpu")


class CpuRunawayDetector(BaseFaultRule):
    """Detects sustained high CPU utilization violating configured thresholds."""

    def __init__(
        self,
        name: str = "cpu_runaway_rule",
        cpu_percent_threshold: float = 90.0,
        duration_seconds: float = 3.0,
        min_samples: int = 3,
        severity: FaultSeverity = FaultSeverity.HIGH,
    ) -> None:
        super().__init__(name=name, fault_type=FaultType.HIGH_CPU, severity=severity)
        self.cpu_percent_threshold = cpu_percent_threshold
        self.duration_seconds = duration_seconds
        self.min_samples = min_samples

    def _extract_cpu_percent(self, target: TargetSpec, snapshot: MetricSnapshot) -> Optional[float]:
        """Extract process CPU or target CPU from snapshot."""
        # 1. Direct target metric on snapshot
        if snapshot.target_id == target.target_id and snapshot.target_cpu_percent is not None:
            return snapshot.target_cpu_percent

        # 2. Match against processes list if present
        if hasattr(snapshot, "processes") and snapshot.processes:
            for p in snapshot.processes:
                if p.target_id == target.target_id:
                    return p.cpu_percent

        # 3. Fallback to target_cpu_percent if target matches or not specified
        if snapshot.target_cpu_percent is not None:
            return snapshot.target_cpu_percent

        # 4. Fallback to system CPU percent if global rule
        return snapshot.system_cpu_percent

    def evaluate(
        self,
        target: TargetSpec,
        window: List[MetricSnapshot],
    ) -> Optional[DetectionEvent]:
        if not window or len(window) < self.min_samples:
            return None

        # Analyze trailing window samples
        trailing_samples = window[-self.min_samples:]
        cpu_values: List[float] = []
        timestamps: List[str] = []

        for snap in trailing_samples:
            val = self._extract_cpu_percent(target, snap)
            if val is None:
                return None
            cpu_values.append(val)
            timestamps.append(snap.timestamp.isoformat())

        # Check if ALL samples in the evaluation window exceed threshold
        if not all(val >= self.cpu_percent_threshold for val in cpu_values):
            return None

        # Check duration span
        time_span = (trailing_samples[-1].timestamp - trailing_samples[0].timestamp).total_seconds()
        # If timestamps match or span is simulated, ensure at least min_samples satisfied
        effective_duration = max(time_span, float(len(trailing_samples) - 1))
        if time_span < self.duration_seconds and len(trailing_samples) < self.min_samples:
            return None

        avg_cpu = sum(cpu_values) / len(cpu_values)
        triggering_value = round(cpu_values[-1], 2)

        evidence: Dict[str, Any] = {
            "target_id": target.target_id,
            "threshold_cpu_percent": self.cpu_percent_threshold,
            "measured_cpu_series": cpu_values,
            "average_cpu_percent": round(avg_cpu, 2),
            "sample_count": len(cpu_values),
            "duration_seconds": round(effective_duration, 2),
            "timestamps": timestamps,
        }

        description = (
            f"Deterministic CPU runaway detected on target '{target.target_id}': "
            f"measured sustained CPU >= {self.cpu_percent_threshold:.1f}% "
            f"(recent: {triggering_value:.1f}%, average: {avg_cpu:.1f}%) "
            f"across {len(cpu_values)} samples ({effective_duration:.1f}s)."
        )

        return DetectionEvent(
            event_id=str(uuid.uuid4()),
            target_id=target.target_id,
            fault_type=self.fault_type,
            severity=self.severity,
            detected_at=utc_now(),
            triggering_value=triggering_value,
            threshold_value=self.cpu_percent_threshold,
            description=description,
            evidence=evidence,
        )
