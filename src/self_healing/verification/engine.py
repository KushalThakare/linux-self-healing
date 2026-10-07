"""Authoritative Verification Engine for post-healing health validation."""

import time
from typing import Any, Dict, List, Optional, Union
import uuid

from self_healing.core.models import (
    AllowedActionType,
    FaultEvent,
    FaultType,
    RecoveryAction,
    RecoveryResult,
    TargetSpec,
    VerificationResult,
    VerificationStatus,
    utc_now,
)
from self_healing.logging.logger import get_logger
from self_healing.verification.probes.base import BaseVerificationProbe, ProbeOutcome
from self_healing.verification.probes.cpu import CpuVerificationProbe
from self_healing.verification.probes.deadlock import DeadlockVerificationProbe
from self_healing.verification.probes.disk import DiskVerificationProbe
from self_healing.verification.probes.memory import MemoryVerificationProbe
from self_healing.verification.probes.service import ServiceVerificationProbe
from self_healing.verification.retry import RetryPolicy

logger = get_logger("verification.engine")


class VerificationEngine:
    """Closed-loop verification engine executing measurable health checks."""

    def __init__(self, retry_policy: Optional[RetryPolicy] = None) -> None:
        self._custom_probes: List[BaseVerificationProbe] = []
        self._default_probes: Dict[FaultType, BaseVerificationProbe] = {
            FaultType.HIGH_CPU: CpuVerificationProbe(),
            FaultType.MEMORY_LEAK: MemoryVerificationProbe(),
            FaultType.PROCESS_CRASH: ServiceVerificationProbe(),
            FaultType.DISK_GROWTH: DiskVerificationProbe(),
            FaultType.DEADLOCK: DeadlockVerificationProbe(),
        }
        self.retry_policy = retry_policy or RetryPolicy()

    def register_probe(self, probe: BaseVerificationProbe) -> None:
        """Register a custom verification probe."""
        self._custom_probes.append(probe)
        logger.debug("Registered verification probe: %s", probe.name)

    def _select_probes(
        self,
        target: TargetSpec,
        action: Optional[RecoveryAction],
        fault_event: Optional[Union[FaultEvent, Any]],
    ) -> List[BaseVerificationProbe]:
        """Select relevant probes based on target, fault type, or recovery action."""
        if self._custom_probes:
            return list(self._custom_probes)

        selected: List[BaseVerificationProbe] = []

        # 1. Selection by FaultType
        if fault_event is not None and hasattr(fault_event, "fault_type"):
            ft = fault_event.fault_type
            if ft in self._default_probes:
                selected.append(self._default_probes[ft])

        # 2. Selection by RecoveryAction
        if action is not None:
            if action.action_type == AllowedActionType.CLEANUP_DEMO_LOGS:
                if self._default_probes[FaultType.DISK_GROWTH] not in selected:
                    selected.append(self._default_probes[FaultType.DISK_GROWTH])
            elif action.action_type in (AllowedActionType.RESTART_DEMO_SERVICE, AllowedActionType.RESTART_DEMO_APPLICATION):
                if target.target_id == "demo-memory" and self._default_probes[FaultType.MEMORY_LEAK] not in selected:
                    selected.append(self._default_probes[FaultType.MEMORY_LEAK])
                elif self._default_probes[FaultType.PROCESS_CRASH] not in selected:
                    selected.append(self._default_probes[FaultType.PROCESS_CRASH])
            elif action.action_type in (AllowedActionType.TERMINATE_DEMO_PROCESS, AllowedActionType.LOWER_DEMO_PROCESS_PRIORITY):
                if "deadlock" in target.target_id:
                    if self._default_probes[FaultType.DEADLOCK] not in selected:
                        selected.append(self._default_probes[FaultType.DEADLOCK])
                elif "memory" in target.target_id:
                    if self._default_probes[FaultType.MEMORY_LEAK] not in selected:
                        selected.append(self._default_probes[FaultType.MEMORY_LEAK])
                elif self._default_probes[FaultType.HIGH_CPU] not in selected:
                    selected.append(self._default_probes[FaultType.HIGH_CPU])

        # 3. Fallback: by target naming convention
        if not selected:
            if "cpu" in target.target_id:
                selected.append(self._default_probes[FaultType.HIGH_CPU])
            elif "memory" in target.target_id:
                selected.append(self._default_probes[FaultType.MEMORY_LEAK])
            elif "service" in target.target_id or "web" in target.target_id:
                selected.append(self._default_probes[FaultType.PROCESS_CRASH])
            elif "disk" in target.target_id:
                selected.append(self._default_probes[FaultType.DISK_GROWTH])
            elif "deadlock" in target.target_id:
                selected.append(self._default_probes[FaultType.DEADLOCK])
            else:
                # Default generic service health check
                selected.append(self._default_probes[FaultType.PROCESS_CRASH])

        return selected

    def verify(
        self,
        target: TargetSpec,
        incident_id: str,
        action: Optional[RecoveryAction] = None,
        recovery_result: Optional[RecoveryResult] = None,
        fault_event: Optional[Union[FaultEvent, Any]] = None,
        metrics_before: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> VerificationResult:
        """Execute measurable verification checks on the remediated target.

        Args:
            target: The TargetSpec under supervision.
            incident_id: Associated incident identifier.
            action: The executed RecoveryAction if applicable.
            recovery_result: The executed RecoveryResult if applicable.
            fault_event: Triggering FaultEvent if applicable.
            metrics_before: Pre-recovery metric snapshot.

        Returns:
            VerificationResult documenting verified, failed, evidence, duration, and metrics.
        """
        start_time = time.perf_counter()
        passed_checks: List[str] = []
        failed_checks: List[str] = []
        aggregate_evidence: Dict[str, Any] = {}
        aggregate_metrics_after: Dict[str, Any] = {}

        metrics_before = dict(metrics_before or {})

        # Handle Dry-Run Mode (when no custom probes explicitly registered)
        is_dry_run = recovery_result.dry_run if recovery_result is not None else False
        if is_dry_run and not self._custom_probes:
            duration = time.perf_counter() - start_time
            passed_checks.append("dry_run_simulation_check")
            aggregate_evidence["dry_run"] = True
            aggregate_evidence["note"] = "Recovery ran in DRY-RUN mode; execution simulated without host mutations."
            if recovery_result:
                aggregate_evidence["action_id"] = recovery_result.action_id
                aggregate_evidence["action_type"] = (
                    recovery_result.action_type.value
                    if hasattr(recovery_result.action_type, "value")
                    else str(recovery_result.action_type)
                )

            return VerificationResult(
                verification_id=str(uuid.uuid4()),
                incident_id=incident_id,
                target_id=target.target_id,
                status=VerificationStatus.HEALTHY,
                verified=True,
                failed=False,
                evidence=aggregate_evidence,
                verification_duration=round(duration, 4),
                metrics_before=metrics_before,
                metrics_after=metrics_before,
                verified_at=utc_now(),
                checks_passed=passed_checks,
                checks_failed=failed_checks,
                details=f"Dry-run simulation verification succeeded for target '{target.target_id}'.",
                retry_recommended=False,
                retry_count=action.retry_count if action else 0,
            )

        # Handle initial recovery failure: if recovery execution itself failed
        if recovery_result is not None and not recovery_result.success:
            duration = time.perf_counter() - start_time
            failed_checks.append("recovery_execution_check")
            aggregate_evidence["recovery_error"] = recovery_result.error or recovery_result.output_message
            details = f"Verification failed immediately: recovery execution failed ({recovery_result.error})."

            retry_rec = False
            if action:
                eval_retry = self.retry_policy.evaluate(
                    action,
                    VerificationResult(
                        verification_id="temp",
                        incident_id=incident_id,
                        target_id=target.target_id,
                        status=VerificationStatus.FAILED,
                        verified=False,
                        failed=True,
                        verification_duration=duration,
                        checks_failed=failed_checks,
                    ),
                )
                retry_rec = eval_retry["should_retry"]

            return VerificationResult(
                verification_id=str(uuid.uuid4()),
                incident_id=incident_id,
                target_id=target.target_id,
                status=VerificationStatus.FAILED,
                verified=False,
                failed=True,
                evidence=aggregate_evidence,
                verification_duration=round(duration, 4),
                metrics_before=metrics_before,
                metrics_after={},
                verified_at=utc_now(),
                checks_passed=passed_checks,
                checks_failed=failed_checks,
                details=details,
                retry_recommended=retry_rec,
                retry_count=action.retry_count if action else 0,
            )

        # Select and run probes
        probes = self._select_probes(target, action, fault_event)

        for p in probes:
            try:
                if hasattr(p, "verify"):
                    outcome: ProbeOutcome = p.verify(
                        target=target,
                        action=action,
                        recovery_result=recovery_result,
                        metrics_before=metrics_before,
                        **kwargs,
                    )
                    if outcome.passed:
                        passed_checks.append(outcome.name)
                    else:
                        failed_checks.append(outcome.name)
                    aggregate_evidence[outcome.name] = outcome.evidence
                    aggregate_metrics_after.update(outcome.metrics_after)
                else:
                    # Legacy probe interface
                    is_healthy = p.probe(target)
                    if is_healthy:
                        passed_checks.append(p.name)
                    else:
                        failed_checks.append(p.name)
            except Exception as ex:
                logger.error("Verification probe '%s' raised exception: %s", p.name, ex)
                failed_checks.append(p.name)
                aggregate_evidence[p.name] = {"exception": str(ex)}

        duration = time.perf_counter() - start_time
        verified = (len(failed_checks) == 0) and (len(passed_checks) > 0)
        failed = not verified

        status = VerificationStatus.HEALTHY if verified else VerificationStatus.FAILED
        details = (
            f"Verification completed for target '{target.target_id}' in {duration:.3f}s. "
            f"Passed: {len(passed_checks)} ({passed_checks}), Failed: {len(failed_checks)} ({failed_checks})."
        )

        logger.info(
            "Target '%s' verification result: verified=%s, status=%s, duration=%.3fs",
            target.target_id,
            verified,
            status.value,
            duration,
        )

        # Evaluate retry recommendations
        retry_rec = False
        if failed and action:
            eval_retry = self.retry_policy.evaluate(
                action,
                VerificationResult(
                    verification_id="temp",
                    incident_id=incident_id,
                    target_id=target.target_id,
                    status=status,
                    verified=verified,
                    failed=failed,
                    verification_duration=duration,
                    checks_failed=failed_checks,
                ),
            )
            retry_rec = eval_retry["should_retry"]

        return VerificationResult(
            verification_id=str(uuid.uuid4()),
            incident_id=incident_id,
            target_id=target.target_id,
            status=status,
            verified=verified,
            failed=failed,
            evidence=aggregate_evidence,
            verification_duration=round(duration, 4),
            metrics_before=metrics_before,
            metrics_after=aggregate_metrics_after,
            verified_at=utc_now(),
            checks_passed=passed_checks,
            checks_failed=failed_checks,
            details=details,
            retry_recommended=retry_rec,
            retry_count=action.retry_count if action else 0,
        )
