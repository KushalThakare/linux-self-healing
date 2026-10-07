"""Base interfaces and outcome models for verification probes."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from self_healing.core.models import (
    FaultType,
    RecoveryAction,
    RecoveryResult,
    TargetSpec,
)


@dataclass
class ProbeOutcome:
    """Outcome of an individual verification probe evaluation."""

    name: str
    passed: bool
    evidence: Dict[str, Any] = field(default_factory=dict)
    metrics_after: Dict[str, Any] = field(default_factory=dict)
    message: str = ""


class BaseVerificationProbe(ABC):
    """Abstract interface for measurable post-healing verification probes."""

    def __init__(self, name: str, fault_type: Optional[FaultType] = None, description: str = "") -> None:
        self.name = name
        self.fault_type = fault_type
        self.description = description

    def probe(self, target: TargetSpec) -> bool:
        """Legacy lightweight check for backward compatibility. Subclasses may override this."""
        return True

    def verify(
        self,
        target: TargetSpec,
        action: Optional[RecoveryAction] = None,
        recovery_result: Optional[RecoveryResult] = None,
        metrics_before: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> ProbeOutcome:
        """Execute measurable verification check on target.

        Subclasses may override this method for rich telemetry, or override probe()
        for simple boolean health checks.
        """
        passed = self.probe(target)
        return ProbeOutcome(
            name=self.name,
            passed=passed,
            evidence={"legacy_probe": True},
            metrics_after={},
            message=f"Probe '{self.name}' returned {'passed' if passed else 'failed'}.",
        )

