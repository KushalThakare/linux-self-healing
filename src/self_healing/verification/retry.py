"""Retry policy and escalation management for closed-loop remediation."""

from typing import Any, Dict, Optional

from self_healing.core.models import (
    IncidentRecord,
    IncidentStatus,
    RecoveryAction,
    VerificationResult,
)
from self_healing.logging.logger import get_logger

logger = get_logger("verification.retry")


class RetryPolicy:
    """Enforces retry constraints, backoff delays, and halts cascading interventions."""

    def __init__(
        self,
        default_max_retries: int = 3,
        base_delay_seconds: float = 1.0,
        backoff_factor: float = 2.0,
        max_delay_seconds: float = 30.0,
    ) -> None:
        self.default_max_retries = default_max_retries
        self.base_delay_seconds = base_delay_seconds
        self.backoff_factor = backoff_factor
        self.max_delay_seconds = max_delay_seconds

    def get_retry_delay(self, retry_count: int) -> float:
        """Calculate exponential backoff delay for the given attempt count."""
        delay = self.base_delay_seconds * (self.backoff_factor ** max(0, retry_count - 1))
        return min(delay, self.max_delay_seconds)

    def can_retry(self, action: RecoveryAction) -> bool:
        """Check whether action retry budget has not been exhausted."""
        limit = action.max_retries if action.max_retries > 0 else self.default_max_retries
        return action.retry_count < limit

    def next_retry_action(self, action: RecoveryAction, failure_reason: str) -> RecoveryAction:
        """Create the next retry iteration of RecoveryAction with incremented attempt count."""
        next_count = action.retry_count + 1
        updated_reason = f"{action.reason} [Retry {next_count}/{action.max_retries}: {failure_reason}]"
        return action.model_copy(
            update={
                "retry_count": next_count,
                "reason": updated_reason,
            }
        )

    def evaluate(
        self,
        action: RecoveryAction,
        verification_result: VerificationResult,
    ) -> Dict[str, Any]:
        """Evaluate whether to schedule another recovery retry or escalate.

        Args:
            action: The executed RecoveryAction.
            verification_result: Outcome of post-recovery verification.

        Returns:
            Dict containing retry decision, delay, and escalation indicators.
        """
        if verification_result.verified:
            return {
                "should_retry": False,
                "escalate": False,
                "retry_count": action.retry_count,
                "max_retries": action.max_retries,
                "delay_seconds": 0.0,
                "reason": "Verification passed successfully; no retry needed.",
            }

        limit = action.max_retries if action.max_retries > 0 else self.default_max_retries
        next_attempt = action.retry_count + 1

        if next_attempt <= limit:
            delay = self.get_retry_delay(next_attempt)
            logger.info(
                "Verification failed for action '%s' on target '%s'. "
                "Retry policy approves attempt %d/%d after %.1fs delay.",
                action.action_id,
                action.target,
                next_attempt,
                limit,
                delay,
            )
            return {
                "should_retry": True,
                "escalate": False,
                "retry_count": next_attempt,
                "max_retries": limit,
                "delay_seconds": delay,
                "reason": f"Retry permitted ({next_attempt}/{limit}) after {delay:.1f}s delay.",
            }
        else:
            logger.warning(
                "Retry policy limit REACHED for action '%s' on target '%s' (%d/%d attempts exhausted). "
                "Halting automated retries and escalating incident.",
                action.action_id,
                action.target,
                action.retry_count,
                limit,
            )
            return {
                "should_retry": False,
                "escalate": True,
                "retry_count": action.retry_count,
                "max_retries": limit,
                "delay_seconds": 0.0,
                "reason": f"Retry limit exceeded ({action.retry_count}/{limit}). Remediation halted; incident escalated.",
            }
