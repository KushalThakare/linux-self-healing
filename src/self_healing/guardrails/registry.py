"""Allowlisted recovery action registry.

Enforces strict containment by defining approved recovery action templates and
blocking any dynamic, non-allowlisted, or arbitrary shell commands.
"""

from typing import Any, Dict, List, Optional, Set
import uuid

from self_healing.core.exceptions import SecurityViolationError
from self_healing.core.models import (
    ActionType,
    AllowedActionType,
    DiagnosisResult,
    RecoveryAction,
    RiskLevel,
)
from self_healing.logging.logger import get_logger

logger = get_logger("guardrails.registry")

# Immutable allowlist of permitted action types
ALLOWLISTED_ACTION_TYPES: Set[str] = {
    AllowedActionType.RESTART_DEMO_SERVICE.value,
    AllowedActionType.TERMINATE_DEMO_PROCESS.value,
    AllowedActionType.LOWER_DEMO_PROCESS_PRIORITY.value,
    AllowedActionType.CLEANUP_DEMO_LOGS.value,
    AllowedActionType.RESTART_DEMO_APPLICATION.value,
}

# Standard targets allowed per action
ACTION_TARGET_COMPATIBILITY: Dict[AllowedActionType, Set[str]] = {
    AllowedActionType.TERMINATE_DEMO_PROCESS: {"demo-cpu", "demo-deadlock", "demo-worker", "demo-memory"},
    AllowedActionType.RESTART_DEMO_SERVICE: {"demo-service", "demo-web", "demo-memory"},
    AllowedActionType.LOWER_DEMO_PROCESS_PRIORITY: {"demo-cpu", "demo-worker"},
    AllowedActionType.CLEANUP_DEMO_LOGS: {"demo-disk"},
    AllowedActionType.RESTART_DEMO_APPLICATION: {"demo-cpu", "demo-memory", "demo-service", "demo-web", "demo-worker"},
}

# Standard required evidence per action type
ACTION_REQUIRED_EVIDENCE: Dict[AllowedActionType, List[str]] = {
    AllowedActionType.TERMINATE_DEMO_PROCESS: ["target_id"],
    AllowedActionType.RESTART_DEMO_SERVICE: ["target_id"],
    AllowedActionType.LOWER_DEMO_PROCESS_PRIORITY: ["target_id"],
    AllowedActionType.CLEANUP_DEMO_LOGS: ["target_id"],
    AllowedActionType.RESTART_DEMO_APPLICATION: ["target_id"],
}


class AllowedActionRegistry:
    """Registry maintaining approved, typed recovery action templates."""

    @staticmethod
    def is_action_allowed(action_type: str) -> bool:
        """Verify whether an action string is within the strict allowlist."""
        return action_type in ALLOWLISTED_ACTION_TYPES

    @staticmethod
    def validate_action_type(action_type: str) -> None:
        """Validate action type or raise SecurityViolationError."""
        if not AllowedActionRegistry.is_action_allowed(action_type):
            raise SecurityViolationError(
                f"Security violation: action '{action_type}' is not an allowlisted recovery action. "
                f"Allowed actions: {sorted(list(ALLOWLISTED_ACTION_TYPES))}."
            )

    @classmethod
    def create_action(
        cls,
        action_type: AllowedActionType,
        target: str,
        reason: str,
        parameters: Optional[Dict[str, Any]] = None,
        custom_evidence_keys: Optional[List[str]] = None,
        risk_level: Optional[RiskLevel] = None,
        max_retries: int = 3,
    ) -> RecoveryAction:
        """Construct a strongly typed RecoveryAction conforming to safety rules."""
        cls.validate_action_type(action_type.value)

        allowed_targets = sorted(list(ACTION_TARGET_COMPATIBILITY.get(action_type, {target})))
        req_evidence = list(ACTION_REQUIRED_EVIDENCE.get(action_type, ["target_id"]))
        if custom_evidence_keys:
            for k in custom_evidence_keys:
                if k not in req_evidence:
                    req_evidence.append(k)

        # Risk mapping
        if risk_level is None:
            if action_type == AllowedActionType.TERMINATE_DEMO_PROCESS:
                risk_level = RiskLevel.HIGH
            elif action_type in (AllowedActionType.RESTART_DEMO_SERVICE, AllowedActionType.RESTART_DEMO_APPLICATION):
                risk_level = RiskLevel.MEDIUM
            else:
                risk_level = RiskLevel.LOW

        # Preconditions
        preconditions = [
            f"target '{target}' must be registered and enabled in TargetRegistry",
            "target must not be a protected system process or init daemon",
        ]
        if action_type == AllowedActionType.CLEANUP_DEMO_LOGS:
            preconditions.append("monitored log path must reside strictly inside workspace")

        return RecoveryAction(
            action_id=str(uuid.uuid4()),
            action_type=action_type,
            target=target,
            reason=reason,
            required_evidence=req_evidence,
            risk_level=risk_level,
            max_retries=max_retries,
            retry_count=0,
            allowed_targets=allowed_targets,
            preconditions=preconditions,
            parameters=parameters or {},
        )

    @classmethod
    def from_diagnosis(cls, diagnosis: DiagnosisResult) -> RecoveryAction:
        """Bridge DiagnosisResult into an allowlisted RecoveryAction."""
        recommended = diagnosis.recommended_action
        target = diagnosis.target_id
        reason = diagnosis.probable_cause

        # Map ActionType or AllowedActionType to AllowedActionType
        if isinstance(recommended, AllowedActionType):
            act_type = recommended
            req_ev = ["average_cpu_percent"] if diagnosis.fault_type.value == "HIGH_CPU" else ["target_id"]
        elif isinstance(recommended, str) and recommended in {a.value for a in AllowedActionType}:
            act_type = AllowedActionType(recommended)
            req_ev = ["average_cpu_percent"] if diagnosis.fault_type.value == "HIGH_CPU" else ["target_id"]
        elif recommended == ActionType.GRACEFUL_TERMINATE or recommended == "GRACEFUL_TERMINATE":
            act_type = AllowedActionType.TERMINATE_DEMO_PROCESS
            req_ev = ["average_cpu_percent"] if diagnosis.fault_type.value == "HIGH_CPU" else ["thread_counts"]
        elif recommended == ActionType.RESTART_SERVICE or recommended == "RESTART_SERVICE":
            act_type = AllowedActionType.RESTART_DEMO_SERVICE
            req_ev = ["final_rss_mb"] if diagnosis.fault_type.value == "MEMORY_LEAK" else ["recent_evidence"]
        elif recommended == ActionType.CLEAN_TEMP_DIR or recommended == "CLEAN_TEMP_DIR":
            act_type = AllowedActionType.CLEANUP_DEMO_LOGS
            req_ev = ["log_directory"] if "log_directory" in diagnosis.evidence else ["target_id"]
        elif recommended == ActionType.RENICE_PROCESS or recommended == "RENICE_PROCESS":
            act_type = AllowedActionType.LOWER_DEMO_PROCESS_PRIORITY
            req_ev = ["average_cpu_percent"]
        else:
            act_type = AllowedActionType.RESTART_DEMO_APPLICATION
            req_ev = ["target_id"]

        return cls.create_action(
            action_type=act_type,
            target=target,
            reason=reason,
            custom_evidence_keys=req_ev,
        )
