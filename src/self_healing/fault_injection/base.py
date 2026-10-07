"""Controlled demo fault injection interfaces and safe base implementations.

In strict accordance with Rules 1, 2, 6 & 17:
- All dangerous operations must be explicitly restricted to approved demo targets.
- Host processes, kernel operations, or system daemons cannot be targeted.
- Every injector supports start, stop, status, and cleanup lifecycles.
"""

from abc import ABC, abstractmethod
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional
import psutil

from self_healing.core.exceptions import SecurityViolationError
from self_healing.core.models import FaultStatus, FaultType, TargetSpec
from self_healing.logging.logger import get_logger
from self_healing.targets.registry import (
    FORBIDDEN_DIRECTORY_PREFIXES,
    FORBIDDEN_PIDS,
    FORBIDDEN_PROCESS_NAMES,
    is_safe_pid,
)

logger = get_logger("fault_injection")

DEFAULT_STATE_DIR = Path("/home/arskage/linux-self-healing/.fault_state")


class BaseFaultInjector(ABC):
    """Abstract base class for safe demo fault injectors."""

    def __init__(self, name: str, fault_type: FaultType, state_dir: Optional[Path] = None) -> None:
        self.name = name
        self.fault_type = fault_type
        self.state_dir = state_dir or DEFAULT_STATE_DIR
        self.state_file = self.state_dir / f"{self.name}.json"
        self._ensure_state_dir()

    def _ensure_state_dir(self) -> None:
        """Create state directory if it does not exist."""
        try:
            self.state_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            logger.warning("Could not create fault state directory %s: %s", self.state_dir, e)

    def validate_target_safety(self, target: TargetSpec) -> None:
        """Enforce strict blast-radius safety boundary before any injection."""
        if target.process_name in FORBIDDEN_PROCESS_NAMES:
            raise SecurityViolationError(
                f"Safety violation: cannot inject fault into protected system process '{target.process_name}'."
            )
        resolved_dir = str(Path(target.working_dir_prefix).resolve())
        if resolved_dir in FORBIDDEN_DIRECTORY_PREFIXES:
            raise SecurityViolationError(
                f"Safety violation: target working directory '{resolved_dir}' is a critical system directory."
            )

    def _save_state(self, pid: int, target_id: str, metadata: Optional[Dict[str, Any]] = None) -> None:
        """Persist runtime fault state to disk."""
        data = {
            "fault_name": self.name,
            "fault_type": self.fault_type.value,
            "target_id": target_id,
            "pid": pid,
            "started_at": time.time(),
            "metadata": metadata or {},
        }
        self.state_file.write_text(json.dumps(data, indent=2))

    def _load_state(self) -> Optional[Dict[str, Any]]:
        """Load persisted runtime fault state from disk."""
        if not self.state_file.exists():
            return None
        try:
            return json.loads(self.state_file.read_text())
        except (json.JSONDecodeError, OSError):
            return None

    def _clear_state(self) -> None:
        """Remove state file."""
        if self.state_file.exists():
            try:
                self.state_file.unlink()
            except OSError:
                pass

    def get_tracked_process(self, target: TargetSpec) -> Optional[psutil.Process]:
        """Retrieve and validate the tracked demo process against TargetSpec."""
        state = self._load_state()
        if not state:
            return None

        pid = state.get("pid")
        if not pid or not isinstance(pid, int):
            return None

        if not is_safe_pid(pid):
            logger.error("Tracked PID %d is not a safe PID.", pid)
            return None

        if not psutil.pid_exists(pid):
            return None

        try:
            proc = psutil.Process(pid)
            # Re-verify process matches the target specification
            cmdline = " ".join(proc.cmdline())
            if target.cmdline_substring not in cmdline:
                logger.warning("PID %d cmdline does not match target '%s'.", pid, target.target_id)
                return None
            return proc
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return None

    def stop_tracked_process(self, target: TargetSpec, timeout: float = 3.0) -> bool:
        """Safely terminate the tracked demo process."""
        proc = self.get_tracked_process(target)
        if not proc:
            state = self._load_state()
            if state:
                state["pid"] = None
                state["stopped"] = True
                try:
                    self.state_file.write_text(json.dumps(state, indent=2))
                except OSError:
                    pass
            return True

        pid = proc.pid
        logger.info("Stopping demo process PID %d for target '%s'", pid, target.target_id)
        try:
            proc.terminate()
            proc.wait(timeout=timeout)
        except psutil.TimeoutExpired:
            logger.warning("Process PID %d did not terminate gracefully; escalating to SIGKILL", pid)
            try:
                proc.kill()
                proc.wait(timeout=2.0)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

        state = self._load_state()
        if state:
            state["pid"] = None
            state["stopped"] = True
            try:
                self.state_file.write_text(json.dumps(state, indent=2))
            except OSError:
                pass

        return not psutil.pid_exists(pid)

    @abstractmethod
    def start(self, target: TargetSpec, **kwargs: Any) -> FaultStatus:
        """Start or induce the fault condition on the demo target."""
        pass

    @abstractmethod
    def stop(self, target: TargetSpec) -> FaultStatus:
        """Stop the fault condition on the demo target."""
        pass

    @abstractmethod
    def status(self, target: TargetSpec) -> FaultStatus:
        """Inspect the current state and metrics of the fault target."""
        pass

    @abstractmethod
    def cleanup(self, target: TargetSpec) -> bool:
        """Restore environment, clean artifacts, and reset state."""
        pass

    def inject(self, target: TargetSpec) -> bool:
        """Backward-compatible wrapper for start()."""
        self.validate_target_safety(target)
        res = self.start(target)
        return res.is_running

    def restore(self, target: TargetSpec) -> bool:
        """Backward-compatible wrapper for cleanup()."""
        self.validate_target_safety(target)
        return self.cleanup(target)


class StubFaultInjector(BaseFaultInjector):
    """Stub fault injector for testing and skeleton baseline."""

    def __init__(self, name: str = "stub", fault_type: FaultType = FaultType.HIGH_CPU) -> None:
        super().__init__(name=name, fault_type=fault_type)
        self._simulated_running = False

    def start(self, target: TargetSpec, **kwargs: Any) -> FaultStatus:
        self.validate_target_safety(target)
        self._simulated_running = True
        return FaultStatus(
            fault_name=self.name,
            target_id=target.target_id,
            is_running=True,
            pid=99999,
            metrics={"simulated": True},
            details=f"Stub fault {self.name} started on {target.target_id}",
        )

    def stop(self, target: TargetSpec) -> FaultStatus:
        self.validate_target_safety(target)
        self._simulated_running = False
        return FaultStatus(
            fault_name=self.name,
            target_id=target.target_id,
            is_running=False,
            pid=None,
            metrics={},
            details=f"Stub fault {self.name} stopped on {target.target_id}",
        )

    def status(self, target: TargetSpec) -> FaultStatus:
        self.validate_target_safety(target)
        return FaultStatus(
            fault_name=self.name,
            target_id=target.target_id,
            is_running=self._simulated_running,
            pid=99999 if self._simulated_running else None,
            metrics={},
            details=f"Stub fault {self.name} status",
        )

    def cleanup(self, target: TargetSpec) -> bool:
        self.validate_target_safety(target)
        self._simulated_running = False
        self._clear_state()
        return True
