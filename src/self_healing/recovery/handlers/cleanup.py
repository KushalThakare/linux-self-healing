"""Handler for cleanup_demo_logs action.

Purges simulated log files strictly within authorized demo directories,
enforcing workspace boundary containment and preventing directory traversal.
"""

import os
from pathlib import Path
import time
from typing import Any, Dict, List, Optional

from self_healing.core.exceptions import ActionExecutionError, SecurityViolationError
from self_healing.core.models import (
    AllowedActionType,
    RecoveryAction,
    RecoveryResult,
    TargetSpec,
    utc_now,
)
from self_healing.logging.logger import get_logger
from self_healing.recovery.handlers.base import BaseActionHandler
from self_healing.targets.registry import FORBIDDEN_DIRECTORY_PREFIXES

logger = get_logger("recovery.handlers.cleanup")


class CleanupLogsHandler(BaseActionHandler):
    """Safely cleans up simulated log records within the approved demo directory."""

    def __init__(self, default_log_subdir: str = "demo_scratch/logs") -> None:
        super().__init__(AllowedActionType.CLEANUP_DEMO_LOGS)
        self.default_log_subdir = default_log_subdir

    def _validate_and_resolve_dir(self, action: RecoveryAction, target_spec: TargetSpec) -> Path:
        """Resolve and strictly validate the target log directory."""
        custom_dir = action.parameters.get("directory") or action.parameters.get("log_directory")
        workspace_root = Path(target_spec.working_dir_prefix).resolve()

        if custom_dir:
            candidate = Path(custom_dir).resolve()
        else:
            candidate = (workspace_root / self.default_log_subdir).resolve()

        # Security Check: Ensure resolved directory is strictly inside workspace_root
        try:
            candidate.relative_to(workspace_root)
        except ValueError:
            raise SecurityViolationError(
                f"Security violation: path '{candidate}' is outside authorized workspace '{workspace_root}'."
            )

        # Security Check: Ensure path is not in forbidden system prefixes
        cand_str = str(candidate)
        if cand_str in FORBIDDEN_DIRECTORY_PREFIXES or cand_str.startswith(("/etc", "/var/log", "/usr", "/root")):
            raise SecurityViolationError(
                f"Security violation: target path '{cand_str}' violates filesystem protection boundary."
            )

        return candidate

    def execute(
        self,
        action: RecoveryAction,
        target_spec: TargetSpec,
        dry_run: bool = False,
    ) -> RecoveryResult:
        start_time = time.perf_counter()
        target_id = target_spec.target_id

        log_dir = self._validate_and_resolve_dir(action, target_spec)

        # Find target log files in directory if directory exists
        pattern = action.parameters.get("file_pattern", "*.log")
        log_files = list(log_dir.glob(pattern)) if log_dir.exists() else []
        total_bytes = sum(f.stat().st_size for f in log_files if f.is_file())

        if dry_run:
            latency_ms = (time.perf_counter() - start_time) * 1000.0
            reclaimed_mb = total_bytes / (1024 * 1024)
            msg = (
                f"[DRY-RUN] Simulated cleanup_demo_logs in '{log_dir}'. "
                f"Candidate files: {len(log_files)} ({reclaimed_mb:.2f} MB)."
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
                    "directory": str(log_dir),
                    "candidate_files": [f.name for f in log_files],
                    "candidate_bytes": total_bytes,
                    "simulated": True,
                },
            )

        if not log_dir.exists():
            latency_ms = (time.perf_counter() - start_time) * 1000.0
            msg = f"Target directory '{log_dir}' does not exist. Nothing to clean up."
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
                details={"directory": str(log_dir), "files_removed": [], "reclaimed_bytes": 0},
            )

        removed_files: List[str] = []
        errors: List[str] = []
        reclaimed_bytes = 0

        for f in log_files:
            if not f.is_file():
                continue
            try:
                size = f.stat().st_size
                f.unlink()
                reclaimed_bytes += size
                removed_files.append(f.name)
            except Exception as ex:
                err = f"Failed to unlink '{f.name}': {ex}"
                logger.error(err)
                errors.append(err)

        latency_ms = (time.perf_counter() - start_time) * 1000.0
        success = len(errors) == 0
        reclaimed_mb = reclaimed_bytes / (1024 * 1024)
        output_msg = (
            f"Successfully cleaned {len(removed_files)} log file(s) in '{log_dir}', "
            f"reclaiming {reclaimed_mb:.2f} MB ({reclaimed_bytes} bytes)."
            if success
            else f"Partial cleanup with errors: {'; '.join(errors)}."
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
                "directory": str(log_dir),
                "files_removed": removed_files,
                "reclaimed_bytes": reclaimed_bytes,
                "errors": errors,
            },
        )
