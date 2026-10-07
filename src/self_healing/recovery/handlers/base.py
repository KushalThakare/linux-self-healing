"""Abstract base class and process resolution utilities for recovery handlers.

Ensures all recovery interventions:
- Use strictly typed RecoveryAction inputs.
- Restrict targeting to verified demo workloads.
- Use safe user-space Linux APIs without invoking arbitrary shell commands.
"""

from abc import ABC, abstractmethod
import os
from pathlib import Path
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
from self_healing.targets.registry import FORBIDDEN_PROCESS_NAMES, is_safe_pid

logger = get_logger("recovery.handlers")


def find_target_pids(target_spec: TargetSpec) -> List[int]:
    """Find all running OS PIDs strictly matching the approved demo target specification.

    Args:
        target_spec: The approved TargetSpec under supervision.

    Returns:
        List of matching PIDs validated against safety rules.
    """
    matching_pids: List[int] = []
    
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            pid = proc.info["pid"]
            if not is_safe_pid(pid):
                continue

            name = proc.info.get("name") or ""
            if name in FORBIDDEN_PROCESS_NAMES:
                continue

            cmdline_list = proc.info.get("cmdline") or []
            cmdline_str = " ".join(cmdline_list)

            # Strict substring match against expected demo signature
            if target_spec.cmdline_substring in cmdline_str:
                matching_pids.append(pid)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue

    return matching_pids


def verify_pid_matches_target(pid: int, target_spec: TargetSpec) -> bool:
    """Verify that a specific PID safely matches the target specification."""
    if not is_safe_pid(pid):
        return False

    try:
        proc = psutil.Process(pid)
        name = proc.name()
        if name in FORBIDDEN_PROCESS_NAMES:
            return False

        cmdline_str = " ".join(proc.cmdline())
        return target_spec.cmdline_substring in cmdline_str
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return False


class BaseActionHandler(ABC):
    """Abstract base class for typed recovery action handlers."""

    def __init__(self, action_type: AllowedActionType) -> None:
        self.action_type = action_type

    @abstractmethod
    def execute(
        self,
        action: RecoveryAction,
        target_spec: TargetSpec,
        dry_run: bool = False,
    ) -> RecoveryResult:
        """Execute or simulate the recovery remediation using native Linux APIs.

        Args:
            action: Validated RecoveryAction model.
            target_spec: Approved demo target specification.
            dry_run: If True, simulate without modifying system state.

        Returns:
            RecoveryResult documenting execution latency, output, and details.
        """
        pass
