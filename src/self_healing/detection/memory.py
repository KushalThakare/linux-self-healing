"""Deterministic abnormal memory and leak detector.

Evaluates monotonic RSS memory growth and hard memory budget thresholds
over time to detect leaks and out-of-budget anomalies.
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

logger = get_logger("detection.memory")


class AbnormalMemoryDetector(BaseFaultRule):
    """Detects abnormal memory growth or memory budget exhaustion."""

    def __init__(
        self,
        name: str = "abnormal_memory_rule",
        budget_bytes: int = 150 * 1024 * 1024,  # 150 MB default budget
        min_growth_rate_bytes_sec: float = 2.0 * 1024 * 1024,  # 2 MB/s
        min_samples: int = 3,
        severity: FaultSeverity = FaultSeverity.HIGH,
    ) -> None:
        super().__init__(name=name, fault_type=FaultType.MEMORY_LEAK, severity=severity)
        self.budget_bytes = budget_bytes
        self.min_growth_rate_bytes_sec = min_growth_rate_bytes_sec
        self.min_samples = min_samples

    def _extract_rss_bytes(self, target: TargetSpec, snapshot: MetricSnapshot) -> Optional[int]:
        """Extract process RSS bytes from snapshot."""
        if snapshot.target_id == target.target_id and snapshot.target_rss_bytes is not None:
            return snapshot.target_rss_bytes

        if hasattr(snapshot, "processes") and snapshot.processes:
            for p in snapshot.processes:
                if p.target_id == target.target_id:
                    return p.rss_bytes

        if snapshot.target_rss_bytes is not None:
            return snapshot.target_rss_bytes

        # Fallback to system memory used if target-specific not available
        if snapshot.memory_details:
            return snapshot.memory_details.used_bytes

        return None

    def evaluate(
        self,
        target: TargetSpec,
        window: List[MetricSnapshot],
    ) -> Optional[DetectionEvent]:
        if not window or len(window) < self.min_samples:
            return None

        trailing_samples = window[-self.min_samples:]
        rss_values: List[int] = []

        for snap in trailing_samples:
            val = self._extract_rss_bytes(target, snap)
            if val is None:
                return None
            rss_values.append(val)

        initial_rss = rss_values[0]
        final_rss = rss_values[-1]
        time_span = (trailing_samples[-1].timestamp - trailing_samples[0].timestamp).total_seconds()
        duration_sec = max(time_span, 1.0)

        # Condition A: Budget exceeded
        budget_exceeded = final_rss >= self.budget_bytes

        # Condition B: Monotonic growth over window
        is_monotonic = all(rss_values[i] >= rss_values[i - 1] for i in range(1, len(rss_values)))
        growth_delta = max(0, final_rss - initial_rss)
        growth_rate = growth_delta / duration_sec
        rate_exceeded = is_monotonic and (growth_rate >= self.min_growth_rate_bytes_sec) and (growth_delta > 0)

        if not (budget_exceeded or rate_exceeded):
            return None

        # Build evidence
        final_rss_mb = round(final_rss / (1024 * 1024), 2)
        budget_mb = round(self.budget_bytes / (1024 * 1024), 2)
        growth_delta_mb = round(growth_delta / (1024 * 1024), 2)
        growth_rate_mb_sec = round(growth_rate / (1024 * 1024), 2)

        evidence: Dict[str, Any] = {
            "target_id": target.target_id,
            "rss_bytes_series": rss_values,
            "final_rss_mb": final_rss_mb,
            "budget_mb": budget_mb,
            "budget_exceeded": budget_exceeded,
            "monotonic_growth": is_monotonic,
            "growth_delta_mb": growth_delta_mb,
            "growth_rate_mb_sec": growth_rate_mb_sec,
            "duration_seconds": round(duration_sec, 2),
            "sample_count": len(rss_values),
        }

        reasons = []
        if budget_exceeded:
            reasons.append(f"RSS exceeded configured budget ({final_rss_mb}MB >= {budget_mb}MB)")
        if rate_exceeded:
            reasons.append(f"sustained monotonic growth of {growth_delta_mb}MB ({growth_rate_mb_sec}MB/s)")

        description = (
            f"Deterministic abnormal memory condition detected on target '{target.target_id}': "
            + "; ".join(reasons)
            + f" across {len(rss_values)} samples."
        )

        return DetectionEvent(
            event_id=str(uuid.uuid4()),
            target_id=target.target_id,
            fault_type=self.fault_type,
            severity=self.severity,
            detected_at=utc_now(),
            triggering_value=final_rss_mb,
            threshold_value=budget_mb,
            description=description,
            evidence=evidence,
        )
