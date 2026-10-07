"""Closed-loop remediation coordinator integrating Guardrails, Recovery, Verification, and Retry Policy."""

from typing import Any, Dict, Optional
import time

from self_healing.core.models import (
    IncidentRecord,
    IncidentStatus,
    RecoveryAction,
    RecoveryResult,
    TargetSpec,
    VerificationResult,
    utc_now,
)
from self_healing.guardrails.engine import SafetyGuardrailEngine
from self_healing.incidents.store import BaseIncidentStore
from self_healing.logging.logger import get_logger
from self_healing.recovery.executor import RecoveryExecutor
from self_healing.targets.registry import TargetRegistry
from self_healing.verification.engine import VerificationEngine
from self_healing.verification.retry import RetryPolicy

logger = get_logger("verification.coordinator")


class RemediationCoordinator:
    """Coordinates the Guardrail -> Recovery -> Verification -> Retry closed loop."""

    def __init__(
        self,
        guardrail_engine: Optional[SafetyGuardrailEngine] = None,
        recovery_executor: Optional[RecoveryExecutor] = None,
        verification_engine: Optional[VerificationEngine] = None,
        retry_policy: Optional[RetryPolicy] = None,
        incident_store: Optional[BaseIncidentStore] = None,
        target_registry: Optional[TargetRegistry] = None,
    ) -> None:
        self.target_registry = target_registry or TargetRegistry()
        self.guardrail_engine = guardrail_engine or SafetyGuardrailEngine(target_registry=self.target_registry)
        self.recovery_executor = recovery_executor or RecoveryExecutor(target_registry=self.target_registry)
        self.retry_policy = retry_policy or RetryPolicy()
        self.verification_engine = verification_engine or VerificationEngine(retry_policy=self.retry_policy)
        self.incident_store = incident_store

    def execute_and_verify(
        self,
        incident: IncidentRecord,
        action: RecoveryAction,
        target_spec: Optional[TargetSpec] = None,
        dry_run: Optional[bool] = None,
        auto_retry: bool = False,
    ) -> IncidentRecord:
        """Execute recovery action through guardrails, verify state, and enforce retry policy.

        Args:
            incident: Active IncidentRecord being remediated.
            action: Proposed RecoveryAction.
            target_spec: TargetSpec under supervision.
            dry_run: Override dry-run mode.
            auto_retry: If True, recursively attempts remediation if retry policy allows.

        Returns:
            Updated IncidentRecord with policy decision, recovery result, and verification result.
        """
        current_action = action
        resolved_target = target_spec or self.target_registry.get(incident.target_id)

        while True:
            # Step 1: Policy & Guardrail Evaluation
            evidence_context = {}
            if incident.diagnosis and hasattr(incident.diagnosis, "evidence"):
                evidence_context = incident.diagnosis.evidence

            decision = self.guardrail_engine.evaluate(
                current_action,
                evidence=evidence_context,
                dry_run=dry_run,
            )
            incident.policy_decision = decision

            if not decision.allowed:
                incident.status = IncidentStatus.ESCALATED if current_action.retry_count > 0 else IncidentStatus.POLICY_REJECTED
                incident.completed_at = utc_now()
                if self.incident_store:
                    self.incident_store.save(incident)
                logger.warning(
                    "Recovery action '%s' rejected by guardrails for incident '%s' (status: %s): %s",
                    current_action.action_id,
                    incident.incident_id,
                    incident.status.value,
                    decision.violations,
                )
                return incident


            incident.status = IncidentStatus.POLICY_APPROVED
            self.guardrail_engine.record_action(resolved_target.target_id)

            # Step 2: Recovery Execution
            recovery_result = self.recovery_executor.execute_guardrail_approved(
                decision=decision,
                action=current_action,
                target_spec=resolved_target,
                dry_run=dry_run,
            )
            incident.recovery_result = recovery_result
            incident.status = IncidentStatus.EXECUTED

            # Step 3: Post-Recovery Verification
            metrics_before = dict(evidence_context)
            verification_result = self.verification_engine.verify(
                target=resolved_target,
                incident_id=incident.incident_id,
                action=current_action,
                recovery_result=recovery_result,
                fault_event=incident.fault_event,
                metrics_before=metrics_before,
            )
            incident.verification_result = verification_result

            # Step 4: Verification Outcome Assessment
            if verification_result.verified:
                incident.status = IncidentStatus.VERIFIED_SUCCESS
                incident.completed_at = utc_now()
                if self.incident_store:
                    self.incident_store.save(incident)
                logger.info(
                    "Incident '%s' successfully remediated and verified for target '%s'.",
                    incident.incident_id,
                    resolved_target.target_id,
                )
                return incident

            # Verification Failed: Mark recovery as unsuccessful
            failure_reason = verification_result.details or "Post-recovery verification checks failed"
            incident.recovery_result = recovery_result.mark_unsuccessful(failure_reason)
            incident.status = IncidentStatus.VERIFICATION_FAILED

            # Step 5: Evaluate Retry Policy
            retry_eval = self.retry_policy.evaluate(current_action, verification_result)

            if retry_eval["should_retry"] and auto_retry:
                delay = retry_eval["delay_seconds"]
                logger.info("Retrying remediation after %.1fs delay (attempt %d)...", delay, retry_eval["retry_count"])
                if delay > 0:
                    time.sleep(min(delay, 2.0))  # Cap sleep in tests/local execution
                current_action = self.retry_policy.next_retry_action(current_action, failure_reason)
                continue
            elif retry_eval["escalate"]:
                incident.status = IncidentStatus.ESCALATED
                incident.completed_at = utc_now()
                logger.warning(
                    "Incident '%s' escalated: retry limit reached (%d/%d). Remediation halted.",
                    incident.incident_id,
                    current_action.retry_count,
                    current_action.max_retries,
                )
                break
            else:
                # Retry permitted but auto_retry=False (or manual review required)
                break

        if self.incident_store:
            self.incident_store.save(incident)

        return incident
