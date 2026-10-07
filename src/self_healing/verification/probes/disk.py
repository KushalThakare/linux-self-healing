"""Measurable Disk / Log Growth post-recovery verification probe."""

import os
from pathlib import Path
import time
from typing import Any, Dict, Optional

from self_healing.core.models import (
    FaultType,
    RecoveryAction,
    RecoveryResult,
    TargetSpec,
)
from self_healing.logging.logger import get_logger
from self_healing.verification.probes.base import BaseVerificationProbe, ProbeOutcome

logger = get_logger("verification.probe.disk")


class DiskVerificationProbe(BaseVerificationProbe):
    """Verifies that disk usage in target log directory is reduced and log growth has stopped."""

    def __init__(
        self,
        name: str = "disk_usage_and_growth_probe",
        sample_interval: float = 0.2,
    ) -> None:
        super().__init__(
            name=name,
            fault_type=FaultType.DISK_GROWTH,
            description="Verifies disk usage reduced and log growth stopped.",
        )
        self.sample_interval = sample_interval

    def _get_dir_size(self, path: Path) -> int:
        """Calculate total bytes occupied by files in directory."""
        if not path.exists():
            return 0
        if path.is_file():
            return path.stat().st_size
        total = 0
        try:
            for entry in path.rglob("*"):
                if entry.is_file():
                    try:
                        total += entry.stat().st_size
                    except (FileNotFoundError, PermissionError):
                        pass
        except (FileNotFoundError, PermissionError):
            pass
        return total

    def _resolve_target_dir(self, target: TargetSpec, action: Optional[RecoveryAction]) -> Path:
        """Resolve supervised log directory path."""
        if action and action.parameters:
            custom_dir = action.parameters.get("directory") or action.parameters.get("log_directory")
            if custom_dir:
                return Path(custom_dir).resolve()
        # Default demo scratch logs path
        return (Path(target.working_dir_prefix) / "demo_scratch/logs").resolve()

    def verify(
        self,
        target: TargetSpec,
        action: Optional[RecoveryAction] = None,
        recovery_result: Optional[RecoveryResult] = None,
        metrics_before: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> ProbeOutcome:
        metrics_before = metrics_before or {}
        before_bytes = metrics_before.get("directory_size_bytes") or metrics_before.get("bytes_used", 0)

        target_dir = self._resolve_target_dir(target, action)

        # 1. Sample directory size at t1
        size_t1 = self._get_dir_size(target_dir)

        # 2. Wait interval and sample at t2 to check if growth stopped
        if self.sample_interval > 0:
            time.sleep(self.sample_interval)
        size_t2 = self._get_dir_size(target_dir)

        growth_delta_bytes = size_t2 - size_t1
        growth_stopped = growth_delta_bytes <= 0

        # Check if disk usage was reduced compared to before recovery
        # If before_bytes was recorded, size_t2 should be strictly less or 0.
        usage_reduced = True
        if before_bytes > 0:
            usage_reduced = size_t2 < before_bytes or size_t2 == 0
        else:
            # If no before_bytes metric was available, size_t2 == 0 or empty directory is considered reduced
            usage_reduced = (size_t2 == 0) or growth_stopped

        bytes_reduced = max(0, before_bytes - size_t2)

        passed = usage_reduced and growth_stopped

        evidence = {
            "target_dir": str(target_dir),
            "before_size_bytes": before_bytes,
            "after_size_t1_bytes": size_t1,
            "after_size_t2_bytes": size_t2,
            "growth_delta_bytes": growth_delta_bytes,
            "bytes_reduced": bytes_reduced,
            "usage_reduced": usage_reduced,
            "growth_stopped": growth_stopped,
        }

        metrics_after = {
            "directory_size_bytes": size_t2,
            "bytes_reduced": bytes_reduced,
            "growth_stopped": growth_stopped,
            "target_dir": str(target_dir),
        }

        if passed:
            msg = (
                f"Disk verification passed for '{target.target_id}': log growth stopped "
                f"(delta: {growth_delta_bytes}B) and disk usage reduced ({bytes_reduced}B reclaimed, "
                f"current size: {size_t2}B)."
            )
            return ProbeOutcome(name=self.name, passed=True, evidence=evidence, metrics_after=metrics_after, message=msg)
        else:
            reasons = []
            if not usage_reduced:
                reasons.append(f"disk usage was not reduced (before: {before_bytes}B, after: {size_t2}B)")
            if not growth_stopped:
                reasons.append(f"log growth is still occurring (+{growth_delta_bytes}B during sample window)")
            msg = f"Disk verification failed: {'; '.join(reasons)}."
            return ProbeOutcome(name=self.name, passed=False, evidence=evidence, metrics_after=metrics_after, message=msg)
