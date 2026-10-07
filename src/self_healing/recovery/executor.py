"""Authoritative Recovery Executor subsystem.

Strict Safety Invariants:
1. RecoveryExecutor must NEVER receive arbitrary shell commands.
2. It receives only validated RecoveryAction objects from the guardrail engine.
3. All dangerous actions are restricted to approved demo targets.
4. Every intervention goes through the Pre-Execution, Execution, and Post-Execution lifecycle.
5. Fully supports DRY-RUN mode.
"""

from datetime import datetime
import os
from pathlib import Path
import time
from typing import Any, Dict, List, Optional, Union
import uuid
import psutil

from self_healing.core.exceptions import (
    ActionExecutionError,
    SecurityViolationError,
    TargetNotFoundError,
)
from self_healing.core.models import (
    AllowedActionType,
    GuardrailDecision,
    GuardrailStatus,
    RecoveryAction,
    RecoveryResult,
    TargetSpec,
    utc_now,
)
from self_healing.logging.logger import get_logger
from self_healing.recovery.handlers import (
    BaseActionHandler,
    CleanupLogsHandler,
    LowerPriorityHandler,
    RestartApplicationHandler,
    RestartServiceHandler,
    TerminateProcessHandler,
)
from self_healing.targets.registry import (
    FORBIDDEN_DIRECTORY_PREFIXES,
    FORBIDDEN_PROCESS_NAMES,
    TargetRegistry,
    is_safe_pid,
)

logger = get_logger("recovery.executor")


class RecoveryExecutor:
    """Executes validated, allowlisted recovery remediations on approved demo targets."""

    def __init__(
        self,
        target_registry: Optional[TargetRegistry] = None,
        dry_run: bool = False,
    ) -> None:
        self.target_registry = target_registry or TargetRegistry()
        self.default_dry_run = dry_run

        # Allowlisted handler registry
        self._handlers: Dict[AllowedActionType, BaseActionHandler] = {
            AllowedActionType.TERMINATE_DEMO_PROCESS: TerminateProcessHandler(),
            AllowedActionType.LOWER_DEMO_PROCESS_PRIORITY: LowerPriorityHandler(),
            AllowedActionType.CLEANUP_DEMO_LOGS: CleanupLogsHandler(),
            AllowedActionType.RESTART_DEMO_SERVICE: RestartServiceHandler(),
            AllowedActionType.RESTART_DEMO_APPLICATION: RestartApplicationHandler(),
        }

    # -------------------------------------------------------------------------
    # Pre-Execution Validation
    # -------------------------------------------------------------------------
    def _validate_action_object(self, action: Any) -> None:
        """Enforce strict invariant: only RecoveryAction objects permitted."""
        if not isinstance(action, RecoveryAction):
            raise SecurityViolationError(
                f"Security violation: RecoveryExecutor only accepts validated RecoveryAction objects. "
                f"Received type '{type(action).__name__}'. Arbitrary commands and raw strings are strictly forbidden."
            )

        if not isinstance(action.action_type, AllowedActionType):
            raise SecurityViolationError(
                f"Security violation: Action type '{action.action_type}' is not allowlisted."
            )

    def _validate_target(self, action: RecoveryAction, target_spec: Optional[TargetSpec]) -> TargetSpec:
        """Validate target against TargetRegistry and safety boundaries."""
        target_id = action.target
        resolved = target_spec

        if resolved is None:
            try:
                resolved = self.target_registry.get(target_id)
            except TargetNotFoundError:
                raise TargetNotFoundError(
                    f"Target '{target_id}' is not an approved demo target in TargetRegistry."
                )

        if not resolved.enabled:
            raise SecurityViolationError(f"Target '{target_id}' is disabled in TargetRegistry.")

        if resolved.process_name in FORBIDDEN_PROCESS_NAMES:
            raise SecurityViolationError(
                f"Security violation: Target '{target_id}' specifies protected process '{resolved.process_name}'."
            )

        normalized_prefix = str(Path(resolved.working_dir_prefix).resolve())
        if normalized_prefix in FORBIDDEN_DIRECTORY_PREFIXES:
            raise SecurityViolationError(
                f"Security violation: Target '{target_id}' uses protected system path '{normalized_prefix}'."
            )

        if action.allowed_targets and target_id not in action.allowed_targets:
            raise SecurityViolationError(
                f"Target '{target_id}' is not permitted for action '{action.action_type.value}'."
            )

        return resolved

    def _validate_permissions(self, action: RecoveryAction, target_spec: TargetSpec) -> None:
        """Ensure current user process has necessary permissions for the intervention."""
        # 1. Process signaling permissions
        pid_val = action.parameters.get("pid")
        if pid_val is not None:
            pid = int(pid_val)
            if not is_safe_pid(pid):
                raise SecurityViolationError(f"PID {pid} is not a safe process to signal.")
            try:
                # Signal 0 performs error checking without actually sending a signal
                os.kill(pid, 0)
            except ProcessLookupError:
                # Process not running is not a permission error
                pass
            except PermissionError as pe:
                raise ActionExecutionError(
                    f"Permission validation failed: current user lacks permission to signal PID {pid}: {pe}"
                )

        # 2. Filesystem boundary and write permissions for log cleanup
        if action.action_type == AllowedActionType.CLEANUP_DEMO_LOGS:
            custom_dir = action.parameters.get("directory") or action.parameters.get("log_directory")
            workspace_root = Path(target_spec.working_dir_prefix).resolve()
            log_dir = Path(custom_dir).resolve() if custom_dir else (workspace_root / "demo_scratch/logs").resolve()

            # Security boundary check: must reside inside authorized workspace
            try:
                log_dir.relative_to(workspace_root)
            except ValueError:
                raise SecurityViolationError(
                    f"Security violation: path '{log_dir}' is outside authorized workspace '{workspace_root}'."
                )

            cand_str = str(log_dir)
            if cand_str in FORBIDDEN_DIRECTORY_PREFIXES or cand_str.startswith(("/etc", "/var/log", "/usr", "/root")):
                raise SecurityViolationError(
                    f"Security violation: target path '{cand_str}' violates filesystem protection boundary."
                )

            if log_dir.exists() and not os.access(log_dir, os.W_OK):
                raise ActionExecutionError(
                    f"Permission validation failed: directory '{log_dir}' is not writable by current user."
                )

    def _record_intent(self, action: RecoveryAction, target_spec: TargetSpec, dry_run: bool) -> None:
        """Emit structured intent audit log prior to execution."""
        logger.info(
            "[RECOVERY INTENT] action_id='%s' type='%s' target='%s' dry_run=%s reason='%s'",
            action.action_id,
            action.action_type.value,
            target_spec.target_id,
            dry_run,
            action.reason,
        )

    # -------------------------------------------------------------------------
    # Core Execution
    # -------------------------------------------------------------------------
    def execute(
        self,
        action: RecoveryAction,
        target_spec: Optional[TargetSpec] = None,
        dry_run: Optional[bool] = None,
    ) -> RecoveryResult:
        """Execute a validated RecoveryAction following strict pre/during/post lifecycle.

        Args:
            action: Validated RecoveryAction object.
            target_spec: Optional pre-resolved TargetSpec.
            dry_run: Override dry-run mode (defaults to self.default_dry_run).

        Returns:
            RecoveryResult documenting execution latency, output, and details.
        """
        # Step 1: Pre-Execution Validation
        self._validate_action_object(action)
        resolved_target = self._validate_target(action, target_spec)
        self._validate_permissions(action, resolved_target)

        effective_dry_run = self.default_dry_run if dry_run is None else dry_run

        self._record_intent(action, resolved_target, effective_dry_run)

        # Step 2: During Execution
        handler = self._handlers.get(action.action_type)
        if not handler:
            raise ActionExecutionError(f"No handler registered for action '{action.action_type.value}'.")

        start_time = time.perf_counter()
        try:
            result = handler.execute(action, resolved_target, dry_run=effective_dry_run)
            logger.info(
                "[RECOVERY SUCCESS] action_id='%s' target='%s' latency=%.2fms dry_run=%s",
                result.action_id,
                result.target_id,
                result.execution_latency_ms,
                result.dry_run,
            )
            return result
        except Exception as ex:
            latency_ms = (time.perf_counter() - start_time) * 1000.0
            err_msg = f"Recovery execution failed for '{action.action_type.value}': {ex}"
            logger.error("[RECOVERY FAILED] %s", err_msg)
            return RecoveryResult(
                action_id=action.action_id,
                target_id=resolved_target.target_id,
                action_type=action.action_type,
                executed_at=utc_now(),
                success=False,
                dry_run=effective_dry_run,
                execution_latency_ms=latency_ms,
                output_message=err_msg,
                error=str(ex),
                details={"exception_type": type(ex).__name__},
            )

    # -------------------------------------------------------------------------
    # Guardrail-Approved Execution Bridge
    # -------------------------------------------------------------------------
    def execute_guardrail_approved(
        self,
        decision: GuardrailDecision,
        action: RecoveryAction,
        target_spec: Optional[TargetSpec] = None,
        dry_run: Optional[bool] = None,
    ) -> RecoveryResult:
        """Execute only if an explicit GUARDRAIL APPROVED decision is provided.

        Args:
            decision: Policy decision produced by SafetyGuardrailEngine.
            action: RecoveryAction to execute.
            target_spec: Optional TargetSpec.
            dry_run: Override dry-run mode (defaults to decision.is_dry_run).

        Returns:
            RecoveryResult outcome.
        """
        if decision.status != GuardrailStatus.APPROVED or not decision.allowed:
            err_msg = (
                f"Execution rejected: action '{action.action_id}' does not possess a valid "
                f"GUARDRAIL APPROVED decision (Status: {decision.status.value}, Violations: {decision.violations})."
            )
            logger.warning("[EXECUTION BLOCKED] %s", err_msg)
            raise SecurityViolationError(err_msg)

        if decision.action_id != action.action_id:
            raise SecurityViolationError(
                f"Security violation: Decision action_id '{decision.action_id}' does not match "
                f"candidate action_id '{action.action_id}'."
            )

        effective_dry_run = decision.is_dry_run if dry_run is None else dry_run
        return self.execute(action, target_spec=target_spec, dry_run=effective_dry_run)
