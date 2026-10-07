"""Handler for restart_demo_service action.

Restarts isolated demo services using structured subprocess arguments (shell=False)
or graceful socket/process recycling without touching host system services.
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

logger = get_logger("recovery.handlers.service")


class RestartServiceHandler(BaseActionHandler):
    """Restarts supervised demo HTTP service or mock user service."""

    def __init__(self, default_port: int = 8085) -> None:
        super().__init__(AllowedActionType.RESTART_DEMO_SERVICE)
        self.default_port = default_port

    def execute(
        self,
        action: RecoveryAction,
        target_spec: TargetSpec,
        dry_run: bool = False,
    ) -> RecoveryResult:
        start_time = time.perf_counter()
        target_id = target_spec.target_id
        port = target_spec.expected_port or self.default_port

        # 1. Discover current running instance
        explicit_pid = action.parameters.get("pid")
        if explicit_pid is not None:
            existing_pids = [int(explicit_pid)]
        else:
            existing_pids = find_target_pids(target_spec)

        if dry_run:
            latency_ms = (time.perf_counter() - start_time) * 1000.0
            msg = (
                f"[DRY-RUN] Simulated restart_demo_service for target '{target_id}' (port {port}). "
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
                    "port": port,
                    "existing_pids": existing_pids,
                    "simulated": True,
                },
            )

        # 2. Terminate existing instances
        stopped_pids: List[int] = []
        for pid in existing_pids:
            if not is_safe_pid(pid):
                continue
            try:
                os.kill(pid, signal.SIGTERM)
                # Wait up to 1.5s for graceful socket release
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
                logger.warning("Error stopping existing service PID %d: %s", pid, ex)

        # Brief pause to ensure TCP port binding is released
        time.sleep(0.2)

        # 3. Respawn the service using structured args array (NO shell)
        workspace_dir = str(Path(target_spec.working_dir_prefix).resolve())
        cmd = [
            sys.executable,
            "-m",
            "self_healing.targets.demo_workloads",
            "service_worker",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ]

        logger.info("Spawning demo service for '%s' with command %s", target_id, cmd)
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
            time.sleep(0.3)

            # Check if process crashed immediately
            if proc.poll() is not None:
                raise ActionExecutionError(f"Service process exited immediately with returncode {proc.returncode}")

            latency_ms = (time.perf_counter() - start_time) * 1000.0
            msg = (
                f"Successfully restarted demo service '{target_id}' on port {port}. "
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
                    "port": port,
                    "recycled_pids": stopped_pids,
                    "new_pid": new_pid,
                },
            )
        except Exception as ex:
            latency_ms = (time.perf_counter() - start_time) * 1000.0
            err_msg = f"Failed to restart demo service '{target_id}': {ex}"
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
                details={"port": port, "recycled_pids": stopped_pids},
            )
