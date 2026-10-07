"""Policy guardrails and safety gatekeeper interfaces."""

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Dict, List, Optional
import uuid

from self_healing.config.settings import GuardrailsConfig
from self_healing.core.models import (
    ActionType,
    DiagnosisReport,
    PolicyDecision,
    TargetSpec,
    utc_now,
)
from self_healing.logging.logger import get_logger
from self_healing.targets.registry import TargetRegistry

logger = get_logger("guardrails")


class BaseGuardrail(ABC):
    """Abstract interface for policy evaluation."""

    @abstractmethod
    def evaluate_action(
        self,
        target: TargetSpec,
        diagnosis: DiagnosisReport,
        dry_run: bool = True,
    ) -> PolicyDecision:
        """Evaluate whether a proposed remediation action conforms to safety rules."""
        pass


class PolicyGuardrailEngine(BaseGuardrail):
    """Authoritative gatekeeper enforcing safety guardrails and rate limits."""

    def __init__(
        self,
        target_registry: TargetRegistry,
        config: Optional[GuardrailsConfig] = None,
    ) -> None:
        self.target_registry = target_registry
        self.config = config or GuardrailsConfig()
        # Track action timestamps per target for flapping and cooldown enforcement
        self._action_history: Dict[str, List[datetime]] = {}

    def record_action(self, target_id: str, timestamp: Optional[datetime] = None) -> None:
        """Record an approved action execution timestamp for rate limiting."""
        ts = timestamp or utc_now()
        if target_id not in self._action_history:
            self._action_history[target_id] = []
        self._action_history[target_id].append(ts)

    def evaluate_action(
        self,
        target: TargetSpec,
        diagnosis: DiagnosisReport,
        dry_run: bool = True,
    ) -> PolicyDecision:
        decision_id = str(uuid.uuid4())
        action_type = diagnosis.recommended_action

        # 1. Allowlist scope check
        if self.config.enforce_target_allowlist:
            if not self.target_registry.is_allowed(target.target_id):
                rejection = (
                    f"Target '{target.target_id}' is not an active, approved target in TargetRegistry."
                )
                logger.warning("Guardrail rejected action: %s", rejection)
                return PolicyDecision(
                    decision_id=decision_id,
                    diagnosis_id=diagnosis.diagnosis_id,
                    target_id=target.target_id,
                    action_type=action_type,
                    allowed=False,
                    is_dry_run=dry_run,
                    rejection_reason=rejection,
                )

        # 2. Action allowlist check
        if action_type not in ActionType:
            rejection = f"Action '{action_type}' is not a recognized allowlisted ActionType."
            logger.error("Guardrail rejected action: %s", rejection)
            return PolicyDecision(
                decision_id=decision_id,
                diagnosis_id=diagnosis.diagnosis_id,
                target_id=target.target_id,
                action_type=action_type,
                allowed=False,
                is_dry_run=dry_run,
                rejection_reason=rejection,
            )

        # 3. Flapping and rate-limiting check
        now = utc_now()
        history = self._action_history.get(target.target_id, [])
        cutoff_flapping = now.timestamp() - self.config.flapping_window_seconds
        recent_actions = [t for t in history if t.timestamp() >= cutoff_flapping]

        if len(recent_actions) >= self.config.max_actions_per_window:
            rejection = (
                f"Target '{target.target_id}' exceeded max actions "
                f"({len(recent_actions)} >= {self.config.max_actions_per_window}) "
                f"within {self.config.flapping_window_seconds}s window (FLAPPING LOCKOUT)."
            )
            logger.warning("Guardrail flapping lockout triggered: %s", rejection)
            return PolicyDecision(
                decision_id=decision_id,
                diagnosis_id=diagnosis.diagnosis_id,
                target_id=target.target_id,
                action_type=action_type,
                allowed=False,
                is_dry_run=dry_run,
                rejection_reason=rejection,
            )

        # 4. Cooldown check
        if history:
            last_action_ts = history[-1].timestamp()
            cooldown_period = max(self.config.default_cooldown_seconds, target.cooldown_seconds)
            elapsed = now.timestamp() - last_action_ts
            if elapsed < cooldown_period:
                rejection = (
                    f"Target '{target.target_id}' is in cooldown period "
                    f"({elapsed:.1f}s elapsed < {cooldown_period:.1f}s required)."
                )
                logger.info("Guardrail cooldown active: %s", rejection)
                return PolicyDecision(
                    decision_id=decision_id,
                    diagnosis_id=diagnosis.diagnosis_id,
                    target_id=target.target_id,
                    action_type=action_type,
                    allowed=False,
                    is_dry_run=dry_run,
                    rejection_reason=rejection,
                )

        # Passed all guardrails
        logger.info(
            "Guardrail approved action '%s' for target '%s' (dry_run=%s)",
            action_type.value,
            target.target_id,
            dry_run,
        )
        return PolicyDecision(
            decision_id=decision_id,
            diagnosis_id=diagnosis.diagnosis_id,
            target_id=target.target_id,
            action_type=action_type,
            allowed=True,
            is_dry_run=dry_run,
            rejection_reason=None,
        )
