"""Handler for terminate_demo_process action.

Terminates runaway demo processes using graceful SIGTERM followed by SIGKILL
escalation, adhering strictly to safe PID boundaries.
"""

import os
from pathlib import Path
import signal
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

logger = get_logger("recovery.handlers.terminate")


def is_pid_dead(pid: int) -> bool:
    """Check if process has terminated (no such process or zombie)."""
    try:
        proc = psutil.Process(pid)
        return proc.status() == psutil.STATUS_ZOMBIE
    except (psutil.NoSuchProcess, ProcessLookupError):
        return True


class TerminateProcessHandler(BaseActionHandler):
    """Graceful termination and SIGKILL escalation for demo processes."""

    def __init__(self, default_grace_period: float = 2.0) -> None:
        super().__init__(AllowedActionType.TERMINATE_DEMO_PROCESS)
        self.default_grace_period = default_grace_period

    def execute(
        self,
        action: RecoveryAction,
        target_spec: TargetSpec,
        dry_run: bool = False,
    ) -> RecoveryResult:
        start_time = time.perf_counter()
        target_id = target_spec.target_id
        grace_period = float(action.parameters.get("grace_period_seconds", self.default_grace_period))

        # Check if an explicit PID was passed in action parameters
        explicit_pid = action.parameters.get("pid")
        target_pids: List[int] = []

        if explicit_pid is not None:
            pid_int = int(explicit_pid)
            if not is_safe_pid(pid_int):
                raise SecurityViolationError(f"Target PID {pid_int} is not a safe process to signal.")
            if verify_pid_matches_target(pid_int, target_spec):
                target_pids.append(pid_int)
            else:
                logger.warning(
                    "Explicit PID %d did not match signature for target '%s'. Falling back to discovery.",
                    pid_int,
                    target_id,
                )

        if not target_pids:
            target_pids = find_target_pids(target_spec)

        if dry_run:
            latency_ms = (time.perf_counter() - start_time) * 1000.0
            msg = (
                f"[DRY-RUN] Simulated terminate_demo_process for target '{target_id}'. "
                f"Matching PIDs identified: {target_pids or 'None'}."
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
                    "grace_period_seconds": grace_period,
                    "simulated": True,
                },
            )

        if not target_pids:
            latency_ms = (time.perf_counter() - start_time) * 1000.0
            msg = f"No active processes found matching demo target '{target_id}' (process already dead)."
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
                details={"terminated_pids": [], "already_stopped": True},
            )

        terminated: List[int] = []
        errors: List[str] = []

        for pid in target_pids:
            if not is_safe_pid(pid):
                continue

            try:
                # Stage 1: Send SIGTERM for graceful exit
                logger.info("Sending SIGTERM to target '%s' (PID %d)", target_id, pid)
                os.kill(pid, signal.SIGTERM)

                # Wait up to grace_period for exit
                deadline = time.time() + grace_period
                exited = False
                while time.time() < deadline:
                    if is_pid_dead(pid):
                        exited = True
                        break
                    time.sleep(0.05)

                # Stage 2: Escalate to SIGKILL if still running
                if not exited and not is_pid_dead(pid):
                    logger.warning("PID %d did not exit after %.1fs. Sending SIGKILL.", pid, grace_period)
                    os.kill(pid, signal.SIGKILL)
                    time.sleep(0.1)

                terminated.append(pid)
            except ProcessLookupError:
                # Process already terminated
                terminated.append(pid)
            except PermissionError as pe:
                err_msg = f"Permission denied signaling PID {pid}: {pe}"
                logger.error(err_msg)
                errors.append(err_msg)
            except Exception as ex:
                err_msg = f"Error terminating PID {pid}: {ex}"
                logger.error(err_msg)
                errors.append(err_msg)

        latency_ms = (time.perf_counter() - start_time) * 1000.0
        success = len(errors) == 0 and len(terminated) > 0
        output_msg = (
            f"Successfully terminated {len(terminated)} process(es) for target '{target_id}': {terminated}."
            if success
            else f"Failed to terminate all targets for '{target_id}': {'; '.join(errors)}."
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
                "terminated_pids": terminated,
                "grace_period_seconds": grace_period,
                "errors": errors,
            },
        )
