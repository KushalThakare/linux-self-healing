"""Handler for lower_demo_process_priority action.

Lowers CPU scheduling priority (increases niceness) for runaway demo processes
using native Linux os.setpriority and psutil APIs.
"""

import os
import time
from typing import Any, Dict, List, Optional
import psutil

from self_healing.core.exceptions import ActionExecutionError, SecurityViolationError
from self_healing.core.models import (
    AllowedActionType,
    RecoveryAction,
    RecoveryResult,
    TargetSpec,
    utc_now,
)
from self_healing.logging.logger import get_logger
from self_healing.recovery.handlers.base import BaseActionHandler, find_target_pids, verify_pid_matches_target
from self_healing.targets.registry import is_safe_pid

logger = get_logger("recovery.handlers.priority")


class LowerPriorityHandler(BaseActionHandler):
    """Lower scheduling priority (increase nice value) of demo processes."""

    def __init__(self, default_nice_increment: int = 10) -> None:
        super().__init__(AllowedActionType.LOWER_DEMO_PROCESS_PRIORITY)
        self.default_nice_increment = default_nice_increment

    def execute(
        self,
        action: RecoveryAction,
        target_spec: TargetSpec,
        dry_run: bool = False,
    ) -> RecoveryResult:
        start_time = time.perf_counter()
        target_id = target_spec.target_id
        nice_inc = int(action.parameters.get("nice_increment", self.default_nice_increment))

        explicit_pid = action.parameters.get("pid")
        target_pids: List[int] = []

        if explicit_pid is not None:
            pid_int = int(explicit_pid)
            if not is_safe_pid(pid_int):
                raise SecurityViolationError(f"Target PID {pid_int} is not a safe process to renice.")
            if verify_pid_matches_target(pid_int, target_spec):
                target_pids.append(pid_int)

        if not target_pids:
            target_pids = find_target_pids(target_spec)

        if dry_run:
            latency_ms = (time.perf_counter() - start_time) * 1000.0
            msg = (
                f"[DRY-RUN] Simulated lower_demo_process_priority (+{nice_inc}) for target '{target_id}'. "
                f"Candidate PIDs: {target_pids or 'None'}."
            )
            logger.info(msg)
            return RecoveryResult(
                action_id=action.action_id,
                target_id=target_id,
                action_type=self.action_type,
                executed_at=utc_now(),
                success=True,
                dry_run=True,
                execution_latency_ms=latency_ms,
                output_message=msg,
                details={
                    "candidate_pids": target_pids,
                    "nice_increment": nice_inc,
                    "simulated": True,
                },
            )

        if not target_pids:
            latency_ms = (time.perf_counter() - start_time) * 1000.0
            msg = f"No active processes found matching demo target '{target_id}' to renice."
            logger.info(msg)
            return RecoveryResult(
                action_id=action.action_id,
                target_id=target_id,
                action_type=self.action_type,
                executed_at=utc_now(),
                success=True,
                dry_run=False,
                execution_latency_ms=latency_ms,
                output_message=msg,
                details={"reniced_pids": [], "not_found": True},
            )

        reniced_details: List[Dict[str, Any]] = []
        errors: List[str] = []

        for pid in target_pids:
            if not is_safe_pid(pid):
                continue

            try:
                proc = psutil.Process(pid)
                old_nice = proc.nice()
                # On Linux, nice ranges from -20 to 19. Unprivileged processes can only increase nice up to 19.
                new_nice = min(19, old_nice + nice_inc)

                logger.info(
                    "Lowering priority of target '%s' (PID %d): nice %d -> %d",
                    target_id,
                    pid,
                    old_nice,
                    new_nice,
                )
                # Use native os.setpriority
                os.setpriority(os.PRIO_PROCESS, pid, new_nice)

                # Verify updated priority
                current_nice = os.getpriority(os.PRIO_PROCESS, pid)
                reniced_details.append({
                    "pid": pid,
                    "old_nice": old_nice,
                    "new_nice": current_nice,
                })
            except (ProcessLookupError, psutil.NoSuchProcess):
                errors.append(f"PID {pid} exited before priority could be updated")
            except (PermissionError, psutil.AccessDenied) as pe:
                err_msg = f"Permission denied lowering priority for PID {pid}: {pe}"
                logger.error(err_msg)
                errors.append(err_msg)
            except Exception as ex:
                err_msg = f"Error renicing PID {pid}: {ex}"
                logger.error(err_msg)
                errors.append(err_msg)

        latency_ms = (time.perf_counter() - start_time) * 1000.0
        success = len(errors) == 0 and len(reniced_details) > 0
        output_msg = (
            f"Successfully lowered priority for {len(reniced_details)} process(es) of target '{target_id}'."
            if success
            else f"Failed to lower priority for '{target_id}': {'; '.join(errors)}."
        )

        return RecoveryResult(
            action_id=action.action_id,
            target_id=target_id,
            action_type=self.action_type,
            executed_at=utc_now(),
            success=success,
            dry_run=False,
            execution_latency_ms=latency_ms,
            output_message=output_msg,
            error="; ".join(errors) if errors else None,
            details={
                "reniced_details": reniced_details,
                "nice_increment": nice_inc,
                "errors": errors,
            },
        )
