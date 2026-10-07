"""Safety guardrail engine implementing the policy-first gatekeeper.

Validates all proposed recovery actions across 8 strict security layers before
permitting execution, enforcing rate limits, cooldowns, and dry-run safety.
"""

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
import uuid

from self_healing.config.settings import GuardrailsConfig
from self_healing.core.models import (
    AllowedActionType,
    DiagnosisResult,
    GuardrailDecision,
    GuardrailStatus,
    MetricSnapshot,
    RecoveryAction,
    RiskLevel,
    SystemSnapshot,
    TargetSpec,
    utc_now,
)
from self_healing.guardrails.registry import AllowedActionRegistry
from self_healing.logging.logger import get_logger
from self_healing.targets.registry import (
    FORBIDDEN_DIRECTORY_PREFIXES,
    FORBIDDEN_PIDS,
    FORBIDDEN_PROCESS_NAMES,
    TargetRegistry,
    is_safe_pid,
)

logger = get_logger("guardrails.engine")


class SafetyGuardrailEngine:
    """Authoritative safety gatekeeper validating recovery actions."""

    def __init__(
        self,
        target_registry: Optional[TargetRegistry] = None,
        config: Optional[GuardrailsConfig] = None,
        dry_run: bool = True,
    ) -> None:
        self.target_registry = target_registry or TargetRegistry()
        self.config = config or GuardrailsConfig()
        self.default_dry_run = dry_run
        # History of approved actions per target for flapping and cooldown tracking
        self._action_history: Dict[str, List[datetime]] = {}

    def record_action(self, target_id: str, timestamp: Optional[datetime] = None) -> None:
        """Record an approved action timestamp for flapping and cooldown tracking."""
        ts = timestamp or utc_now()
        if target_id not in self._action_history:
            self._action_history[target_id] = []
        self._action_history[target_id].append(ts)

    def evaluate(
        self,
        action: RecoveryAction,
        evidence: Optional[Dict[str, Any]] = None,
        system_metrics: Optional[Union[MetricSnapshot, SystemSnapshot]] = None,
        dry_run: Optional[bool] = None,
    ) -> GuardrailDecision:
        """Evaluate a proposed RecoveryAction against the 8 mandatory safety layers.

        Args:
            action: The candidate RecoveryAction.
            evidence: Contextual evidence dict from diagnosis.
            system_metrics: Current system telemetry snapshot.
            dry_run: Whether running in dry-run simulation mode (defaults to self.default_dry_run).

        Returns:
            GuardrailDecision with GUARDRAIL APPROVED or GUARDRAIL REJECTED status.
        """
        is_dry_run = self.default_dry_run if dry_run is None else dry_run
        decision_id = str(uuid.uuid4())
        target_id = action.target
        violations: List[str] = []
        reasons: List[str] = []
        checks: Dict[str, bool] = {}
        context_evidence = dict(evidence or {})

        logger.info(
            "Evaluating guardrail policy for action '%s' on target '%s' (dry_run=%s)",
            action.action_type.value,
            target_id,
            is_dry_run,
        )

        # -----------------------------------------------------------------
        # Check 1: Target Existence and Format
        # -----------------------------------------------------------------
        if not target_id or not isinstance(target_id, str) or len(target_id.strip()) == 0:
            violations.append("Check 1 Failed: Target identifier is missing, empty, or invalid format.")
            checks["target_valid"] = False
        else:
            checks["target_valid"] = True

        # -----------------------------------------------------------------
        # Check 2: Action Type Allowlist
        # -----------------------------------------------------------------
        action_val = action.action_type.value if hasattr(action.action_type, "value") else str(action.action_type)
        if not AllowedActionRegistry.is_action_allowed(action_val):
            violations.append(f"Check 2 Failed: Action type '{action_val}' is not in the allowlisted action registry.")
            checks["action_allowlist"] = False
        else:
            checks["action_allowlist"] = True

        # -----------------------------------------------------------------
        # Check 3: Process and Service Identity Safety
        # -----------------------------------------------------------------
        # Check if target maps to protected system identity
        identity_safe = True
        try:
            target_spec = self.target_registry.get(target_id)
            if target_spec.process_name in FORBIDDEN_PROCESS_NAMES:
                violations.append(
                    f"Check 3 Failed: Process name '{target_spec.process_name}' is a protected system process."
                )
                identity_safe = False
            resolved_dir = str(Path(target_spec.working_dir_prefix).resolve())
            if resolved_dir in FORBIDDEN_DIRECTORY_PREFIXES:
                violations.append(
                    f"Check 3 Failed: Working directory '{resolved_dir}' is a critical system directory."
                )
                identity_safe = False
        except Exception:
            # If target not in registry, handled in check 4
            pass

        # Check PID parameter if passed
        pid_param = action.parameters.get("pid")
        if pid_param is not None:
            if not isinstance(pid_param, int) or not is_safe_pid(pid_param):
                violations.append(f"Check 3 Failed: PID {pid_param} is a protected system PID (0, 1, 2, or self).")
                identity_safe = False

        checks["identity_safety"] = identity_safe

        # -----------------------------------------------------------------
        # Check 4: Approved Demo Target Validation
        # -----------------------------------------------------------------
        target_approved = True
        if self.config.enforce_target_allowlist:
            if not self.target_registry.is_allowed(target_id):
                violations.append(
                    f"Check 4 Failed: Target '{target_id}' is not an active approved target in TargetRegistry."
                )
                target_approved = False

        # Validate target is in action's allowed_targets list
        if action.allowed_targets and target_id not in action.allowed_targets:
            violations.append(
                f"Check 4 Failed: Target '{target_id}' is not permitted for action '{action_val}' "
                f"(allowed: {action.allowed_targets})."
            )
            target_approved = False

        checks["approved_demo_target"] = target_approved

        # -----------------------------------------------------------------
        # Check 5: Current System State
        # -----------------------------------------------------------------
        system_safe = True
        if system_metrics:
            if isinstance(system_metrics, SystemSnapshot):
                if system_metrics.cpu.percent > 99.0 and system_metrics.memory.percent > 99.0:
                    violations.append("Check 5 Failed: Host system is in total unrecoverable starvation (>99% CPU & RAM).")
                    system_safe = False
            elif isinstance(system_metrics, MetricSnapshot):
                if system_metrics.system_cpu_percent > 99.0 and system_metrics.system_memory_percent > 99.0:
                    violations.append("Check 5 Failed: Host system resource metrics indicate critical starvation.")
                    system_safe = False
        checks["system_state_safe"] = system_safe

        # -----------------------------------------------------------------
        # Check 6: Retry Count & Flapping / Cooldown
        # -----------------------------------------------------------------
        retry_safe = True
        if action.retry_count >= action.max_retries:
            violations.append(
                f"Check 6 Failed: Action retry count exceeded ({action.retry_count} >= max {action.max_retries})."
            )
            retry_safe = False

        now = utc_now()
        history = self._action_history.get(target_id, [])
        cutoff_flapping = now.timestamp() - self.config.flapping_window_seconds
        recent_actions = [t for t in history if t.timestamp() >= cutoff_flapping]

        if len(recent_actions) >= self.config.max_actions_per_window:
            violations.append(
                f"Check 6 Failed: Flapping lockout active for target '{target_id}' "
                f"({len(recent_actions)} actions in {self.config.flapping_window_seconds}s window)."
            )
            retry_safe = False

        if history:
            last_ts = history[-1].timestamp()
            target_cooldown = self.config.default_cooldown_seconds
            try:
                target_cooldown = max(target_cooldown, self.target_registry.get(target_id).cooldown_seconds)
            except Exception:
                pass
            elapsed = now.timestamp() - last_ts
            if elapsed < target_cooldown:
                violations.append(
                    f"Check 6 Failed: Cooldown period active ({elapsed:.1f}s elapsed < {target_cooldown:.1f}s required)."
                )
                retry_safe = False

        checks["retry_and_rate_limits"] = retry_safe

        # -----------------------------------------------------------------
        # Check 7: Action Risk Evaluation
        # -----------------------------------------------------------------
        risk_safe = True
        if action.risk_level == RiskLevel.CRITICAL and not action.parameters.get("operator_override", False):
            violations.append("Check 7 Failed: CRITICAL risk actions require explicit operator override parameter.")
            risk_safe = False
        checks["action_risk_valid"] = risk_safe

        # -----------------------------------------------------------------
        # Check 8: Required Evidence Verification
        # -----------------------------------------------------------------
        evidence_present = True
        missing_evidence = []
        for req_key in action.required_evidence:
            if req_key not in context_evidence or context_evidence[req_key] is None:
                missing_evidence.append(req_key)

        if missing_evidence:
            violations.append(
                f"Check 8 Failed: Missing required diagnostic evidence keys: {missing_evidence}."
            )
            evidence_present = False
        checks["required_evidence_present"] = evidence_present

        # -----------------------------------------------------------------
        # Formulate Decision Token
        # -----------------------------------------------------------------
        all_passed = all(checks.values())
        if all_passed:
            status = GuardrailStatus.APPROVED
            allowed = True
            reasons.append(f"All 8 guardrail criteria satisfied for target '{target_id}'.")
            if is_dry_run:
                reasons.append("Operating in DRY-RUN mode: OS mutations will be simulated without side-effects.")
            logger.info("[GUARDRAIL APPROVED] Action '%s' approved for target '%s'", action_val, target_id)
        else:
            status = GuardrailStatus.REJECTED
            allowed = False
            reasons.append(f"Action rejected due to {len(violations)} safety violations.")
            logger.warning("[GUARDRAIL REJECTED] Action '%s' rejected for target '%s': %s", action_val, target_id, violations)

        decision = GuardrailDecision(
            decision_id=decision_id,
            action_id=action.action_id,
            target_id=target_id,
            action_type=action.action_type,
            action_params=action.parameters,
            allowed=allowed,
            is_dry_run=is_dry_run,
            status=status,
            violations=violations,
            reasons=reasons,
            validation_details=checks,
            rejection_reason="; ".join(violations) if violations else None,
            decided_at=now,
        )

        return decision
