"""Deterministic rule-based detection engine interfaces."""

from abc import ABC, abstractmethod
from typing import List, Optional

from self_healing.core.models import (
    DetectionEvent,
    FaultEvent,
    FaultSeverity,
    FaultType,
    MetricSnapshot,
    TargetSpec,
)
from self_healing.logging.logger import get_logger

logger = get_logger("detection")


class BaseFaultRule(ABC):
    """Abstract interface for deterministic detection rules."""

    def __init__(
        self,
        name: str,
        fault_type: FaultType,
        severity: FaultSeverity = FaultSeverity.HIGH,
    ) -> None:
        self.name = name
        self.fault_type = fault_type
        self.severity = severity

    @abstractmethod
    def evaluate(
        self,
        target: TargetSpec,
        window: List[MetricSnapshot],
    ) -> Optional[FaultEvent]:
        """Evaluate a time-series metric window for rule violations.
        
        Args:
            target: The monitored target specification.
            window: Chronological metric snapshots.
            
        Returns:
            FaultEvent if rule criteria are satisfied; None otherwise.
        """
        pass


class BaseDetectionEngine(ABC):
    """Abstract interface for the detection engine."""

    @abstractmethod
    def register_rule(self, rule: BaseFaultRule) -> None:
        """Register a detection rule."""
        pass

    @abstractmethod
    def evaluate(
        self,
        target: TargetSpec,
        window: List[MetricSnapshot],
    ) -> List[FaultEvent]:
        """Evaluate all registered rules against current telemetry window."""
        pass


class RuleDetectionEngine(BaseDetectionEngine):
    """Deterministic rule-based detection engine implementation skeleton."""

    def __init__(self) -> None:
        self._rules: List[BaseFaultRule] = []

    def register_rule(self, rule: BaseFaultRule) -> None:
        self._rules.append(rule)
        logger.debug("Registered detection rule: %s (%s)", rule.name, rule.fault_type.value)

    def evaluate(
        self,
        target: TargetSpec,
        window: List[MetricSnapshot],
    ) -> List[FaultEvent]:
        events: List[FaultEvent] = []
        for rule in self._rules:
            event = rule.evaluate(target, window)
            if event is not None:
                events.append(event)
                logger.info(
                    "Fault detected by rule '%s' for target '%s': %s",
                    rule.name,
                    target.target_id,
                    event.description,
                )
        return events
