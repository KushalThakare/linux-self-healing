"""Central fault injection coordinator and registry.

Coordinates execution across all isolated demo targets while strictly
enforcing safety constraints and allowlists.
"""

from pathlib import Path
from typing import Dict, List, Optional

from self_healing.config.settings import load_config
from self_healing.core.exceptions import TargetNotFoundError
from self_healing.core.models import FaultStatus, TargetSpec
from self_healing.fault_injection.base import BaseFaultInjector, DEFAULT_STATE_DIR
from self_healing.fault_injection.cpu import CpuRunawayInjector
from self_healing.fault_injection.deadlock import DeadlockInjector
from self_healing.fault_injection.disk import DiskGrowthInjector
from self_healing.fault_injection.memory import MemoryGrowthInjector
from self_healing.fault_injection.service import ServiceCrashInjector
from self_healing.logging.logger import get_logger
from self_healing.targets.registry import TargetRegistry

logger = get_logger("fault_injection.manager")

# Mapping from CLI fault names to target IDs
FAULT_TO_TARGET_MAP = {
    "cpu": "demo-cpu",
    "memory": "demo-memory",
    "service": "demo-service",
    "disk": "demo-disk",
    "deadlock": "demo-deadlock",
}


class FaultManager:
    """Manages lifecycle and coordination for all demo fault injectors."""

    def __init__(self, state_dir: Optional[Path] = None, config_path: Optional[str] = None) -> None:
        self.state_dir = state_dir or DEFAULT_STATE_DIR
        self.config = load_config(config_path)
        self.registry = TargetRegistry(self.config.targets)

        # Initialize injectors
        self._injectors: Dict[str, BaseFaultInjector] = {
            "cpu": CpuRunawayInjector(state_dir=self.state_dir),
            "memory": MemoryGrowthInjector(state_dir=self.state_dir),
            "service": ServiceCrashInjector(state_dir=self.state_dir),
            "disk": DiskGrowthInjector(state_dir=self.state_dir),
            "deadlock": DeadlockInjector(state_dir=self.state_dir),
        }

    def get_injector(self, name: str) -> BaseFaultInjector:
        """Get fault injector instance by name."""
        name = name.lower()
        if name not in self._injectors:
            raise ValueError(f"Unknown fault injector '{name}'. Available: {list(self._injectors.keys())}")
        return self._injectors[name]

    def get_target(self, name: str) -> TargetSpec:
        """Resolve approved TargetSpec for a specific fault type."""
        name = name.lower()
        target_id = FAULT_TO_TARGET_MAP.get(name)
        if not target_id:
            raise ValueError(f"No registered target mapping for fault '{name}'.")
        try:
            return self.registry.get(target_id)
        except TargetNotFoundError:
            raise TargetNotFoundError(
                f"Target '{target_id}' mapped to fault '{name}' is not configured in targets allowlist."
            )

    def start_fault(self, name: str, **kwargs) -> FaultStatus:
        """Start a specific demo fault condition."""
        injector = self.get_injector(name)
        target = self.get_target(name)
        return injector.start(target, **kwargs)

    def stop_fault(self, name: str) -> FaultStatus:
        """Stop a specific demo fault condition."""
        injector = self.get_injector(name)
        target = self.get_target(name)
        return injector.stop(target)

    def status_fault(self, name: str) -> FaultStatus:
        """Query status of a specific demo fault."""
        injector = self.get_injector(name)
        target = self.get_target(name)
        return injector.status(target)

    def cleanup_fault(self, name: str) -> bool:
        """Clean up artifacts and stop demo processes for a specific fault."""
        injector = self.get_injector(name)
        target = self.get_target(name)
        return injector.cleanup(target)

    def status_all(self) -> List[FaultStatus]:
        """Query status of all registered demo faults."""
        statuses = []
        for name in self._injectors:
            try:
                target = self.get_target(name)
                statuses.append(self._injectors[name].status(target))
            except Exception as e:
                logger.error("Failed to query status for fault '%s': %s", name, e)
        return statuses

    def cleanup_all(self) -> Dict[str, bool]:
        """Perform comprehensive cleanup across all demo fault injectors."""
        results = {}
        for name, injector in self._injectors.items():
            try:
                target = self.get_target(name)
                results[name] = injector.cleanup(target)
            except Exception as e:
                logger.error("Failed to clean up fault '%s': %s", name, e)
                results[name] = False
        return results
