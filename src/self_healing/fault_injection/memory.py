"""Controlled memory growth fault injector for isolated demo targets."""

from pathlib import Path
import subprocess
import sys
import time
from typing import Any, Optional
import psutil

from self_healing.core.models import FaultStatus, FaultType, TargetSpec
from self_healing.fault_injection.base import BaseFaultInjector
from self_healing.logging.logger import get_logger

logger = get_logger("fault_injection.memory")

# Safety upper bound for demo memory allocation (MB)
MAX_SAFE_MEMORY_MB = 512


class MemoryGrowthInjector(BaseFaultInjector):
    """Induces controlled, bounded memory growth in an isolated demo process."""

    def __init__(self, state_dir: Optional[Path] = None) -> None:
        super().__init__(name="memory", fault_type=FaultType.MEMORY_LEAK, state_dir=state_dir)

    def start(self, target: TargetSpec, max_mb: int = 256, chunk_mb: int = 20, **kwargs: Any) -> FaultStatus:
        self.validate_target_safety(target)
        proc = self.get_tracked_process(target)
        if proc and proc.is_running():
            return self.status(target)

        # Enforce hard safety ceiling
        effective_max = min(max_mb, MAX_SAFE_MEMORY_MB)

        cmd = [
            sys.executable,
            "-m",
            "self_healing.targets.demo_workloads",
            "memory_leak",
            "--max-mb",
            str(effective_max),
            "--chunk-mb",
            str(chunk_mb),
        ]
        logger.info(
            "Spawning demo memory leak workload for target '%s' (cap: %dMB): %s",
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
        self._save_state(pid=p.pid, target_id=target.target_id, metadata={"max_mb": effective_max})
        return self.status(target)

    def stop(self, target: TargetSpec) -> FaultStatus:
        self.validate_target_safety(target)
        self.stop_tracked_process(target)
        return self.status(target)

    def status(self, target: TargetSpec) -> FaultStatus:
        self.validate_target_safety(target)
        proc = self.get_tracked_process(target)
        if not proc:
            return FaultStatus(
                fault_name=self.name,
                target_id=target.target_id,
                is_running=False,
                pid=None,
                metrics={},
                details=f"Demo memory target '{target.target_id}' is not running.",
            )

        try:
            mem_info = proc.memory_info()
            rss_mb = mem_info.rss / (1024 * 1024)
            vms_mb = mem_info.vms / (1024 * 1024)
            metrics = {
                "rss_bytes": mem_info.rss,
                "rss_mb": round(rss_mb, 2),
                "vms_bytes": mem_info.vms,
                "vms_mb": round(vms_mb, 2),
                "memory_percent": round(proc.memory_percent(), 2),
                "status": proc.status(),
            }
            return FaultStatus(
                fault_name=self.name,
                target_id=target.target_id,
                is_running=True,
                pid=proc.pid,
                metrics=metrics,
                details=f"Demo memory growth active on PID {proc.pid} ({rss_mb:.1f} MB RSS).",
            )
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            self._clear_state()
            return FaultStatus(
                fault_name=self.name,
                target_id=target.target_id,
                is_running=False,
                pid=None,
                metrics={},
                details=f"Demo memory target '{target.target_id}' is no longer active.",
            )

    def cleanup(self, target: TargetSpec) -> bool:
        self.validate_target_safety(target)
        self.stop_tracked_process(target)
        self._clear_state()
        return True
