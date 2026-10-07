"""Handler for restart_demo_application action.

Restarts demo application workloads by cleanly recycling old processes and
respawning a fresh instance using structured argument lists (shell=False).
"""

import os
from pathlib import Path
import signal
import subprocess
import sys
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
from self_healing.recovery.handlers.base import BaseActionHandler, find_target_pids
from self_healing.targets.registry import is_safe_pid

logger = get_logger("recovery.handlers.restart_app")


class RestartApplicationHandler(BaseActionHandler):
    """Restarts supervised demo applications (e.g. demo-cpu, demo-memory)."""

    def __init__(self) -> None:
        super().__init__(AllowedActionType.RESTART_DEMO_APPLICATION)

    def _determine_workload_args(self, target_spec: TargetSpec, action: RecoveryAction) -> List[str]:
        """Derive safe CLI arguments for the target application."""
        target_id = target_spec.target_id
        cmdline_sub = target_spec.cmdline_substring

        if "cpu" in target_id or "cpu_spin" in cmdline_sub:
            return ["cpu_spin"]
        elif "memory" in target_id or "memory_leak" in cmdline_sub:
            max_mb = action.parameters.get("max_mb", 128)
            return ["memory_leak", "--max-mb", str(max_mb)]
        elif "deadlock" in target_id or "deadlock_hang" in cmdline_sub:
            return ["deadlock_hang"]
        else:
            return ["cpu_spin"]

    def execute(
        self,
        action: RecoveryAction,
        target_spec: TargetSpec,
        dry_run: bool = False,
    ) -> RecoveryResult:
        start_time = time.perf_counter()
        target_id = target_spec.target_id

        existing_pids = find_target_pids(target_spec)

        if dry_run:
            latency_ms = (time.perf_counter() - start_time) * 1000.0
            msg = (
                f"[DRY-RUN] Simulated restart_demo_application for target '{target_id}'. "
                f"Existing PIDs to recycle: {existing_pids or 'None'}."
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
                    "existing_pids": existing_pids,
                    "simulated": True,
                },
            )

        # 1. Terminate existing instances
        stopped_pids: List[int] = []
        for pid in existing_pids:
            if not is_safe_pid(pid):
                continue
            try:
                os.kill(pid, signal.SIGTERM)
                for _ in range(15):
                    if not psutil.pid_exists(pid):
                        break
                    time.sleep(0.1)
                if psutil.pid_exists(pid):
                    os.kill(pid, signal.SIGKILL)
                    time.sleep(0.1)
                stopped_pids.append(pid)
            except (ProcessLookupError, psutil.NoSuchProcess):
                stopped_pids.append(pid)
            except Exception as ex:
                logger.warning("Error stopping process PID %d: %s", pid, ex)

        time.sleep(0.1)

        # 2. Respawn fresh instance using structured argument list (NO shell)
        workspace_dir = str(Path(target_spec.working_dir_prefix).resolve())
        workload_args = self._determine_workload_args(target_spec, action)
        cmd = [
            sys.executable,
            "-m",
            "self_healing.targets.demo_workloads",
            *workload_args,
        ]

        logger.info("Restarting demo application '%s' with command %s", target_id, cmd)
        try:
            proc = subprocess.Popen(
                cmd,
                cwd=workspace_dir,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                shell=False,
                start_new_session=True,
            )
            new_pid = proc.pid
            time.sleep(0.2)

            if proc.poll() is not None:
                raise ActionExecutionError(f"Application exited immediately with returncode {proc.returncode}")

            latency_ms = (time.perf_counter() - start_time) * 1000.0
            msg = (
                f"Successfully restarted demo application '{target_id}'. "
                f"Old PIDs: {stopped_pids}, New PID: {new_pid}."
            )
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
                details={
                    "recycled_pids": stopped_pids,
                    "new_pid": new_pid,
                    "cmd": cmd,
                },
            )
        except Exception as ex:
            latency_ms = (time.perf_counter() - start_time) * 1000.0
            err_msg = f"Failed to restart demo application '{target_id}': {ex}"
            logger.error(err_msg)
            return RecoveryResult(
                action_id=action.action_id,
                target_id=target_id,
                action_type=self.action_type,
                executed_at=utc_now(),
                success=False,
                dry_run=False,
                execution_latency_ms=latency_ms,
                output_message=err_msg,
                error=err_msg,
                details={"recycled_pids": stopped_pids},
            )
