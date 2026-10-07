"""Controlled demo fault injection interfaces and safe base implementations.

In strict accordance with Rule 6 & 17:
- All dangerous operations must be explicitly restricted to approved demo targets.
- Host processes, kernel operations, or system daemons cannot be targeted.
"""

from abc import ABC, abstractmethod
from pathlib import Path

from self_healing.core.exceptions import SecurityViolationError
from self_healing.core.models import FaultType, TargetSpec
from self_healing.logging.logger import get_logger
from self_healing.targets.registry import FORBIDDEN_DIRECTORY_PREFIXES, FORBIDDEN_PROCESS_NAMES

logger = get_logger("fault_injection")


class BaseFaultInjector(ABC):
    """Abstract base class for safe demo fault injectors."""

    def __init__(self, name: str, fault_type: FaultType) -> None:
        self.name = name
        self.fault_type = fault_type

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

    @abstractmethod
    def inject(self, target: TargetSpec) -> bool:
        """Induce the specific fault in the approved demo target."""
        pass

    @abstractmethod
    def restore(self, target: TargetSpec) -> bool:
        """Revert the injected fault condition if applicable."""
        pass


class StubFaultInjector(BaseFaultInjector):
    """Stub fault injector for skeleton testing."""

    def inject(self, target: TargetSpec) -> bool:
        self.validate_target_safety(target)
        logger.info(
            "[SKELETON] Simulating injection of %s on demo target '%s'",
            self.fault_type.value,
            target.target_id,
        )
        return True

    def restore(self, target: TargetSpec) -> bool:
        self.validate_target_safety(target)
        logger.info(
            "[SKELETON] Simulating restoration of demo target '%s'",
            target.target_id,
        )
        return True
