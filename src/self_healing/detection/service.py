"""Deterministic service failure and crash detector.

Evaluates supervised services and processes against expected active state,
triggering on failed, inactive, or abruptly terminated processes.
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

logger = get_logger("detection.service")


class ServiceFailureDetector(BaseFaultRule):
    """Detects service failure or abrupt process termination against expected active state."""

    def __init__(
        self,
        name: str = "service_failure_rule",
        expected_active: bool = True,
        min_failed_samples: int = 1,
        severity: FaultSeverity = FaultSeverity.CRITICAL,
    ) -> None:
        super().__init__(name=name, fault_type=FaultType.PROCESS_CRASH, severity=severity)
        self.expected_active = expected_active
        self.min_failed_samples = min_failed_samples

    def evaluate(
        self,
        target: TargetSpec,
        window: List[MetricSnapshot],
    ) -> Optional[DetectionEvent]:
        # Service detector only evaluates services (targets with expected_port or service/web/daemon in target_id)
        is_service = (
            target.expected_port is not None
            or "service" in target.target_id
            or "web" in target.target_id
            or "daemon" in target.target_id
        )
        if not is_service:
            return None

        if not window or len(window) < self.min_failed_samples:
            return None

        # Inspect recent samples in window
        samples = window[-self.min_failed_samples:]
        failed_evidences: List[Dict[str, Any]] = []

        for snap in samples:
            snap_failure_reasons: List[str] = []
            snap_evidence: Dict[str, Any] = {}

            # 1. Check services list if present
            matching_service = None
            if hasattr(snap, "services") and snap.services:
                for svc in snap.services:
                    if target.target_id in svc.service_name or svc.service_name in target.target_id:
                        matching_service = svc
                        break

            if matching_service:
                snap_evidence["service_name"] = matching_service.service_name
                snap_evidence["is_active"] = matching_service.is_active
                snap_evidence["active_state"] = matching_service.active_state
                snap_evidence["sub_state"] = matching_service.sub_state
                if self.expected_active and not matching_service.is_active:
                    snap_failure_reasons.append(
                        f"systemd unit '{matching_service.service_name}' is {matching_service.active_state}/{matching_service.sub_state}"
                    )

            # 2. Check process state if snapshot represents target
            if snap.target_id == target.target_id:
                snap_evidence["target_state"] = snap.target_state.value if snap.target_state else None
                if snap.target_state in (ProcessState.DEAD, ProcessState.STOPPED):
                    snap_failure_reasons.append(f"process in state {snap.target_state.value}")

            # 3. Check processes list
            if hasattr(snap, "processes") and snap.processes:
                found_proc = any(p.target_id == target.target_id for p in snap.processes)
                if not found_proc and self.expected_active:
                    snap_evidence["process_found"] = False
                    snap_failure_reasons.append("supervised process not found in process table")

            # 4. Check if target has explicit dead / inactive state indicated on snapshot
            if snap.target_pid is None and snap.target_id == target.target_id and self.expected_active:
                snap_evidence["target_pid"] = None
                snap_failure_reasons.append("target process PID is null/missing")

            if snap_failure_reasons:
                snap_evidence["reasons"] = snap_failure_reasons
                failed_evidences.append(snap_evidence)

        # Ensure failure is observed across the required samples
        if len(failed_evidences) < self.min_failed_samples:
            return None

        recent_evidence = failed_evidences[-1]
        reasons_summary = "; ".join(recent_evidence.get("reasons", ["service inactive"]))

        description = (
            f"Deterministic service failure detected on target '{target.target_id}': "
            f"{reasons_summary} (expected active: {self.expected_active})."
        )

        return DetectionEvent(
            event_id=str(uuid.uuid4()),
            target_id=target.target_id,
            fault_type=self.fault_type,
            severity=self.severity,
            detected_at=utc_now(),
            triggering_value=0.0,  # 0 indicates inactive/failed
            threshold_value=1.0 if self.expected_active else 0.0,
            description=description,
            evidence={
                "target_id": target.target_id,
                "expected_active": self.expected_active,
                "consecutive_failed_samples": len(failed_evidences),
                "recent_evidence": recent_evidence,
            },
        )
