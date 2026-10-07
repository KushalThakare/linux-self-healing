"""Target registry and allowlist validation.

Enforces strict blast-radius containment by ensuring only registered,
safe demo targets can ever be inspected, signaled, or modified.
"""

import os
from pathlib import Path
from typing import Dict, List, Optional
import psutil

from self_healing.core.exceptions import SecurityViolationError, TargetNotFoundError
from self_healing.core.models import TargetSpec
from self_healing.logging.logger import get_logger

logger = get_logger("targets")

FORBIDDEN_PIDS = {0, 1, 2}
FORBIDDEN_PROCESS_NAMES = {
    "systemd", "init", "kthreadd", "sshd", "login", "cron",
    "bash", "zsh", "sh", "sudo", "su", "dockerd", "containerd",
}
FORBIDDEN_DIRECTORY_PREFIXES = {
    "/", "/bin", "/sbin", "/usr/bin", "/usr/sbin", "/etc", "/lib", "/boot",
}


def is_safe_pid(pid: int) -> bool:
    """Verify that a PID is strictly safe to inspect and not a host system process."""
    if pid in FORBIDDEN_PIDS or pid <= 2:
        return False
    if pid == os.getpid():
        # Do not allow targeting self
        return False
    return True


class TargetRegistry:
    """In-memory registry of approved demo targets."""

    def __init__(self, targets: Optional[List[TargetSpec]] = None) -> None:
        self._targets: Dict[str, TargetSpec] = {}
        if targets:
            for t in targets:
                self.register(t)

    def register(self, target: TargetSpec) -> None:
        """Register a new demo target with safety validation."""
        # Validate that working dir is not a root system directory
        normalized_dir = str(Path(target.working_dir_prefix).resolve())
        if normalized_dir in FORBIDDEN_DIRECTORY_PREFIXES:
            raise SecurityViolationError(
                f"Cannot register target '{target.target_id}': "
                f"working directory '{normalized_dir}' is a critical system directory."
            )

        if target.process_name in FORBIDDEN_PROCESS_NAMES:
            raise SecurityViolationError(
                f"Cannot register target '{target.target_id}': "
                f"process name '{target.process_name}' is a protected system process."
            )

        self._targets[target.target_id] = target
        logger.debug("Registered target: %s", target.target_id)

    def get(self, target_id: str) -> TargetSpec:
        """Retrieve target specification by ID."""
        if target_id not in self._targets:
            raise TargetNotFoundError(f"Target '{target_id}' is not registered.")
        return self._targets[target_id]

    def list_targets(self) -> List[TargetSpec]:
        """Return list of all registered targets."""
        return list(self._targets.values())

    def is_allowed(self, target_id: str) -> bool:
        """Check whether a target ID exists and is enabled."""
        target = self._targets.get(target_id)
        return target is not None and target.enabled

    def validate_process_match(self, pid: int, target_spec: TargetSpec) -> bool:
        """Verify whether an active OS process strictly matches the TargetSpec.
        
        Args:
            pid: The process ID to inspect.
            target_spec: The specification to match against.
            
        Returns:
            True if process matches all constraints; False otherwise.
            
        Raises:
            SecurityViolationError: If pid is a protected system PID.
        """
        if not is_safe_pid(pid):
            raise SecurityViolationError(f"PID {pid} is a protected system process.")

        try:
            proc = psutil.Process(pid)
            # Match process name
            if target_spec.process_name not in proc.name():
                return False

            # Match cmdline substring
            cmdline = " ".join(proc.cmdline())
            if target_spec.cmdline_substring not in cmdline:
                return False

            # Match working directory prefix
            cwd = str(Path(proc.cwd()).resolve())
            expected_prefix = str(Path(target_spec.working_dir_prefix).resolve())
            if not cwd.startswith(expected_prefix):
                return False

            return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return False
