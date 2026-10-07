"""Controlled disk/log growth fault injector for isolated demo targets."""

import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from typing import Any, Optional
import psutil

from self_healing.core.exceptions import SecurityViolationError
from self_healing.core.models import FaultStatus, FaultType, TargetSpec
from self_healing.fault_injection.base import BaseFaultInjector
from self_healing.logging.logger import get_logger
from self_healing.targets.registry import FORBIDDEN_DIRECTORY_PREFIXES

logger = get_logger("fault_injection.disk")

DEFAULT_DEMO_LOG_DIR = Path("/home/arskage/linux-self-healing/demo_scratch/logs")
MAX_SAFE_DISK_MB = 100


class DiskGrowthInjector(BaseFaultInjector):
    """Induces rapid, bounded log accumulation within an isolated demo scratch path."""

    def __init__(self, state_dir: Optional[Path] = None) -> None:
        super().__init__(name="disk", fault_type=FaultType.DISK_GROWTH, state_dir=state_dir)

    def _validate_output_directory(self, output_dir: Path) -> None:
        """Ensure destination directory is strictly safe and not a system directory."""
        resolved = str(output_dir.resolve())
        if resolved in FORBIDDEN_DIRECTORY_PREFIXES:
            raise SecurityViolationError(
                f"Security violation: cannot use protected system directory '{resolved}' for disk injection."
            )
        # Must be inside workspace
        workspace = Path("/home/arskage/linux-self-healing").resolve()
        if not output_dir.resolve().is_relative_to(workspace):
            raise SecurityViolationError(
                f"Security violation: disk growth directory '{resolved}' must be inside workspace '{workspace}'."
            )

    def start(
        self,
        target: TargetSpec,
        max_mb: int = 50,
        output_dir: Optional[Path] = None,
        **kwargs: Any,
    ) -> FaultStatus:
        self.validate_target_safety(target)
        dest_dir = (output_dir or DEFAULT_DEMO_LOG_DIR).resolve()
        self._validate_output_directory(dest_dir)

        proc = self.get_tracked_process(target)
        if proc and proc.is_running():
            return self.status(target)

        dest_dir.mkdir(parents=True, exist_ok=True)
        effective_max = min(max_mb, MAX_SAFE_DISK_MB)

        cmd = [
            sys.executable,
            "-m",
            "self_healing.targets.demo_workloads",
            "disk_write",
            "--dir",
            str(dest_dir),
            "--max-mb",
            str(effective_max),
            "--interval",
            "0.1",
        ]
        logger.info(
            "Spawning demo disk growth workload for target '%s' (cap: %dMB): %s",
            target.target_id,
            effective_max,
            cmd,
        )

        p = subprocess.Popen(
            cmd,
            cwd=target.working_dir_prefix,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

        time.sleep(0.3)
        self._save_state(
            pid=p.pid,
            target_id=target.target_id,
            metadata={"output_dir": str(dest_dir), "max_mb": effective_max},
        )
        return self.status(target)

    def stop(self, target: TargetSpec) -> FaultStatus:
        self.validate_target_safety(target)
        self.stop_tracked_process(target)
        return self.status(target)

    def status(self, target: TargetSpec) -> FaultStatus:
        self.validate_target_safety(target)
        state = self._load_state() or {}
        dest_dir_str = state.get("metadata", {}).get("output_dir", str(DEFAULT_DEMO_LOG_DIR))
        dest_dir = Path(dest_dir_str)

        # Measure directory size
        total_bytes = 0
        file_count = 0
        if dest_dir.exists() and dest_dir.is_dir():
            for p in dest_dir.glob("**/*"):
                if p.is_file():
                    total_bytes += p.stat().st_size
                    file_count += 1

        total_mb = total_bytes / (1024 * 1024)
        metrics = {
            "output_dir": str(dest_dir),
            "total_bytes": total_bytes,
            "total_mb": round(total_mb, 2),
            "file_count": file_count,
        }

        proc = self.get_tracked_process(target)
        if proc and proc.is_running():
            metrics["writer_pid"] = proc.pid
            metrics["status"] = proc.status()
            return FaultStatus(
                fault_name=self.name,
                target_id=target.target_id,
                is_running=True,
                pid=proc.pid,
                metrics=metrics,
                details=f"Demo disk growth active on PID {proc.pid} ({total_mb:.1f} MB written in {dest_dir}).",
            )

        return FaultStatus(
            fault_name=self.name,
            target_id=target.target_id,
            is_running=False,
            pid=None,
            metrics=metrics,
            details=f"Demo disk growth target '{target.target_id}' is stopped ({total_mb:.1f} MB present in {dest_dir}).",
        )

    def cleanup(self, target: TargetSpec) -> bool:
        self.validate_target_safety(target)
        state = self._load_state() or {}
        dest_dir_str = state.get("metadata", {}).get("output_dir", str(DEFAULT_DEMO_LOG_DIR))
        dest_dir = Path(dest_dir_str).resolve()

        self.stop_tracked_process(target)

        # Remove the target log directory
        if dest_dir.exists() and dest_dir.is_dir():
            self._validate_output_directory(dest_dir)
            try:
                shutil.rmtree(dest_dir)
                logger.info("Removed demo disk directory: %s", dest_dir)
            except OSError as e:
                logger.error("Failed to remove demo disk directory %s: %s", dest_dir, e)

        # Also ensure default scratch log directory is cleaned if present
        default_dir = DEFAULT_DEMO_LOG_DIR.resolve()
        if default_dir.exists() and default_dir.is_dir() and default_dir != dest_dir:
            try:
                shutil.rmtree(default_dir)
            except OSError:
                pass

        self._clear_state()
        return True
