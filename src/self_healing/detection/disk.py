"""Deterministic disk and log exhaustion detector.

Evaluates global filesystem utilization and monitored log directory growth
against configurable thresholds.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional
import uuid

from self_healing.core.models import (
    DetectionEvent,
    DiskUsageMetrics,
    FaultSeverity,
    FaultType,
    MetricSnapshot,
    TargetSpec,
    utc_now,
)
from self_healing.detection.base import BaseFaultRule
from self_healing.logging.logger import get_logger

logger = get_logger("detection.disk")

DEFAULT_LOG_DIR = Path("/home/arskage/linux-self-healing/demo_scratch/logs")


class DiskExhaustionDetector(BaseFaultRule):
    """Detects filesystem exhaustion or excessive log directory accumulation."""

    def __init__(
        self,
        name: str = "disk_exhaustion_rule",
        fs_percent_threshold: float = 85.0,
        log_dir_bytes_threshold: int = 15 * 1024 * 1024,  # 15 MB
        log_dir_path: Optional[Path] = None,
        severity: FaultSeverity = FaultSeverity.HIGH,
    ) -> None:
        super().__init__(name=name, fault_type=FaultType.DISK_GROWTH, severity=severity)
        self.fs_percent_threshold = fs_percent_threshold
        self.log_dir_bytes_threshold = log_dir_bytes_threshold
        self.log_dir_path = log_dir_path or DEFAULT_LOG_DIR

    def _get_log_dir_size(self) -> int:
        """Measure current size of monitored demo log directory if present."""
        if not self.log_dir_path.exists() or not self.log_dir_path.is_dir():
            return 0
        total = 0
        for p in self.log_dir_path.glob("**/*"):
            if p.is_file():
                try:
                    total += p.stat().st_size
                except OSError:
                    pass
        return total

    def evaluate(
        self,
        target: TargetSpec,
        window: List[MetricSnapshot],
    ) -> Optional[DetectionEvent]:
        if not window:
            return None

        latest_snap = window[-1]

        # 1. Check global filesystem utilization in latest snapshot
        fs_violation = False
        fs_evidence: Dict[str, Any] = {}
        triggering_fs_pct = 0.0

        if latest_snap.disks:
            for d in latest_snap.disks:
                if d.percent >= self.fs_percent_threshold:
                    fs_violation = True
                    triggering_fs_pct = d.percent
                    fs_evidence = {
                        "mount_point": d.mount_point,
                        "used_percent": d.percent,
                        "total_bytes": d.total_bytes,
                        "used_bytes": d.used_bytes,
                        "free_bytes": d.free_bytes,
                    }
                    break

        # 2. Check demo log directory accumulation
        log_dir_size = self._get_log_dir_size()
        log_violation = log_dir_size >= self.log_dir_bytes_threshold

        if not (fs_violation or log_violation):
            return None

        # Build evidence
        evidence: Dict[str, Any] = {
            "target_id": target.target_id,
            "fs_violation": fs_violation,
            "log_violation": log_violation,
        }

        reasons = []
        if fs_violation:
            evidence["filesystem"] = fs_evidence
            reasons.append(
                f"Filesystem '{fs_evidence.get('mount_point', '/')}' utilization reached "
                f"{triggering_fs_pct:.1f}% (threshold: {self.fs_percent_threshold:.1f}%)"
            )
        if log_violation:
            log_mb = round(log_dir_size / (1024 * 1024), 2)
            thresh_mb = round(self.log_dir_bytes_threshold / (1024 * 1024), 2)
            evidence["log_directory"] = {
                "path": str(self.log_dir_path),
                "bytes": log_dir_size,
                "mb": log_mb,
                "threshold_mb": thresh_mb,
            }
            reasons.append(
                f"Monitored log directory '{self.log_dir_path}' accumulated {log_mb} MB "
                f"(threshold: {thresh_mb} MB)"
            )

        triggering_value = (
            triggering_fs_pct if fs_violation else round(log_dir_size / (1024 * 1024), 2)
        )
        threshold_value = (
            self.fs_percent_threshold
            if fs_violation
            else round(self.log_dir_bytes_threshold / (1024 * 1024), 2)
        )

        description = (
            f"Deterministic disk exhaustion condition detected on target '{target.target_id}': "
            + "; ".join(reasons)
            + "."
        )

        return DetectionEvent(
            event_id=str(uuid.uuid4()),
            target_id=target.target_id,
            fault_type=self.fault_type,
            severity=self.severity,
            detected_at=utc_now(),
            triggering_value=triggering_value,
            threshold_value=threshold_value,
            description=description,
            evidence=evidence,
        )
