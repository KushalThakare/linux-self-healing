"""Controlled service crash fault injector for isolated demo targets."""

import http.client
from pathlib import Path
import subprocess
import sys
import time
from typing import Any, Optional
import psutil

from self_healing.core.models import FaultStatus, FaultType, TargetSpec
from self_healing.fault_injection.base import BaseFaultInjector
from self_healing.logging.logger import get_logger

logger = get_logger("fault_injection.service")


class ServiceCrashInjector(BaseFaultInjector):
    """Induces an isolated service crash on the demo HTTP worker target."""

    def __init__(self, state_dir: Optional[Path] = None) -> None:
        super().__init__(name="service", fault_type=FaultType.PROCESS_CRASH, state_dir=state_dir)

    def start(self, target: TargetSpec, auto_crash: bool = True, **kwargs: Any) -> FaultStatus:
        self.validate_target_safety(target)
        port = target.expected_port or 8085

        # Check if process already tracked
        proc = self.get_tracked_process(target)
        if proc and proc.is_running() and not auto_crash:
            return self.status(target)

        # Stop any previous instance
        self.stop_tracked_process(target)

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
        logger.info("Spawning demo service for target '%s': %s", target.target_id, cmd)

        p = subprocess.Popen(
            cmd,
            cwd=target.working_dir_prefix,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

        # Wait for service to bind and verify it is alive
        time.sleep(0.5)
        self._save_state(pid=p.pid, target_id=target.target_id, metadata={"port": port, "crashed": False})

        if auto_crash:
            logger.info("Triggering controlled crash on demo service at 127.0.0.1:%d/crash", port)
            try:
                conn = http.client.HTTPConnection("127.0.0.1", port, timeout=2.0)
                conn.request("GET", "/crash")
                conn.getresponse()
            except Exception:
                # Expected: connection drops when server exits immediately
                pass

            time.sleep(0.3)
            # Re-read state
            exit_code = p.poll()
            logger.info("Service process terminated with exit code: %s", exit_code)
            self._save_state(
                pid=p.pid,
                target_id=target.target_id,
                metadata={"port": port, "crashed": True, "exit_code": exit_code},
            )

        return self.status(target)

    def stop(self, target: TargetSpec) -> FaultStatus:
        self.validate_target_safety(target)
        self.stop_tracked_process(target)
        return self.status(target)

    def status(self, target: TargetSpec) -> FaultStatus:
        self.validate_target_safety(target)
        state = self._load_state()
        port = target.expected_port or 8085

        if not state:
            return FaultStatus(
                fault_name=self.name,
                target_id=target.target_id,
                is_running=False,
                pid=None,
                metrics={"port": port, "port_open": False},
                details=f"Demo service '{target.target_id}' is not deployed.",
            )

        pid = state.get("pid")
        metadata = state.get("metadata", {})
        crashed = metadata.get("crashed", False)

        proc = self.get_tracked_process(target)
        if proc and proc.is_running():
            return FaultStatus(
                fault_name=self.name,
                target_id=target.target_id,
                is_running=True,
                pid=proc.pid,
                metrics={"port": port, "port_open": True, "num_threads": proc.num_threads()},
                details=f"Demo service is running normally on PID {proc.pid} (port {port}).",
            )

        # Process is dead / crashed
        exit_code = metadata.get("exit_code")
        return FaultStatus(
            fault_name=self.name,
            target_id=target.target_id,
            is_running=False,
            pid=pid,
            metrics={"port": port, "port_open": False, "crashed": True, "exit_code": exit_code},
            details=(
                f"Demo service '{target.target_id}' is CRASHED (PID {pid} exited with code {exit_code}). "
                f"Port {port} is inactive."
            ),
        )

    def cleanup(self, target: TargetSpec) -> bool:
        self.validate_target_safety(target)
        self.stop_tracked_process(target)
        self._clear_state()
        return True
