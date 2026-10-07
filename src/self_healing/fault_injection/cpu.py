"""Controlled CPU runaway fault injector for isolated demo targets."""

from pathlib import Path
import subprocess
import sys
import time
from typing import Any, Optional
import psutil

from self_healing.core.models import FaultStatus, FaultType, TargetSpec
from self_healing.fault_injection.base import BaseFaultInjector
from self_healing.logging.logger import get_logger

logger = get_logger("fault_injection.cpu")


class CpuRunawayInjector(BaseFaultInjector):
    """Induces high CPU consumption in an isolated demo process."""

    def __init__(self, state_dir: Optional[Path] = None) -> None:
        super().__init__(name="cpu", fault_type=FaultType.HIGH_CPU, state_dir=state_dir)

    def start(self, target: TargetSpec, **kwargs: Any) -> FaultStatus:
        self.validate_target_safety(target)
        proc = self.get_tracked_process(target)
        if proc and proc.is_running():
            return self.status(target)

        # Launch the isolated demo CPU workload
        cmd = [sys.executable, "-m", "self_healing.targets.demo_workloads", "cpu_spin"]
        logger.info("Spawning demo CPU runaway workload for target '%s': %s", target.target_id, cmd)

        p = subprocess.Popen(
            cmd,
            cwd=target.working_dir_prefix,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

        time.sleep(0.3)
        self._save_state(pid=p.pid, target_id=target.target_id)
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
                details=f"Demo CPU runaway target '{target.target_id}' is not running.",
            )

        try:
            cpu_pct = proc.cpu_percent(interval=0.1)
            mem_info = proc.memory_info()
            metrics = {
                "cpu_percent": cpu_pct,
                "rss_bytes": mem_info.rss,
                "vms_bytes": mem_info.vms,
                "num_threads": proc.num_threads(),
                "status": proc.status(),
            }
            return FaultStatus(
                fault_name=self.name,
                target_id=target.target_id,
                is_running=True,
                pid=proc.pid,
                metrics=metrics,
                details=f"Demo CPU runaway active on PID {proc.pid} ({cpu_pct:.1f}% CPU).",
            )
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            self._clear_state()
            return FaultStatus(
                fault_name=self.name,
                target_id=target.target_id,
                is_running=False,
                pid=None,
                metrics={},
                details=f"Demo CPU runaway target '{target.target_id}' is no longer active.",
            )

    def cleanup(self, target: TargetSpec) -> bool:
        self.validate_target_safety(target)
        self.stop_tracked_process(target)
        self._clear_state()
        return True
