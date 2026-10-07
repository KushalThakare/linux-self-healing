"""Typed allowlisted recovery action registry and interfaces.

In strict compliance with Safety Invariants:
1. No arbitrary shell command execution is permitted.
2. Every action must be an allowlisted Python class.
3. Complex healing operations are deferred until later phases;
   stub and dry-run execution interfaces are defined here.
"""

from abc import ABC, abstractmethod
import time
from typing import Any, Dict, Optional, Type
import uuid

from self_healing.core.exceptions import ActionExecutionError, SecurityViolationError
from self_healing.core.models import (
    ActionType,
    RecoveryResult,
    TargetSpec,
    utc_now,
)
from self_healing.logging.logger import get_logger

logger = get_logger("recovery")


class BaseRecoveryAction(ABC):
    """Abstract base class for all allowlisted recovery actions."""

    def __init__(self, action_type: ActionType) -> None:
        self.action_type = action_type

    @abstractmethod
    def execute(
        self,
        target: TargetSpec,
        params: Optional[Dict[str, Any]] = None,
        dry_run: bool = True,
    ) -> RecoveryResult:
        """Execute or simulate the typed remediation action.
        
        Args:
            target: The approved TargetSpec to remediate.
            params: Optional validated parameters.
            dry_run: When True, simulates action without modifying system state.
            
        Returns:
            RecoveryResult recording latency, status, and message.
        """
        pass


class StubRecoveryAction(BaseRecoveryAction):
    """Skeleton recovery action for architecture testing and dry-run validation."""

    def execute(
        self,
        target: TargetSpec,
        params: Optional[Dict[str, Any]] = None,
        dry_run: bool = True,
    ) -> RecoveryResult:
        start_time = time.perf_counter()
        action_id = str(uuid.uuid4())
        params = params or {}

        if not dry_run:
            logger.warning(
                "Real execution requested on StubRecoveryAction for %s. Operating safely in dry-run mode.",
                target.target_id,
            )

        # In Phase 1 skeleton, healing functionality is intentionally not implemented
        latency_ms = (time.perf_counter() - start_time) * 1000.0
        msg = f"[SKELETON / DRY-RUN] Action '{self.action_type.value}' simulated for target '{target.target_id}'."

        logger.info(msg)
        return RecoveryResult(
            action_id=action_id,
            target_id=target.target_id,
            action_type=self.action_type,
            executed_at=utc_now(),
            success=True,
            dry_run=True,
            execution_latency_ms=latency_ms,
            output_message=msg,
        )


class ActionRegistry:
    """Strictly allowlisted registry of typed recovery action handlers."""

    def __init__(self) -> None:
        self._registry: Dict[ActionType, BaseRecoveryAction] = {}
        # Pre-register stub handlers for all allowlisted action types
        for action_type in ActionType:
            self._registry[action_type] = StubRecoveryAction(action_type)

    def register(self, action: BaseRecoveryAction) -> None:
        """Register a specific recovery action handler."""
        if not isinstance(action.action_type, ActionType):
            raise SecurityViolationError(f"Action type '{action.action_type}' is not allowlisted.")
        self._registry[action.action_type] = action
        logger.debug("Registered recovery action handler for %s", action.action_type.value)

    def get(self, action_type: ActionType) -> BaseRecoveryAction:
        """Retrieve handler for the specified action type."""
        if action_type not in self._registry:
            raise ActionExecutionError(f"No handler registered for action '{action_type.value}'.")
        return self._registry[action_type]

    def execute_action(
        self,
        action_type: ActionType,
        target: TargetSpec,
        params: Optional[Dict[str, Any]] = None,
        dry_run: bool = True,
    ) -> RecoveryResult:
        """Execute an allowlisted recovery action via its registered handler."""
        handler = self.get(action_type)
        return handler.execute(target, params=params, dry_run=dry_run)
