"""Post-healing verification interfaces and engine."""

from abc import ABC, abstractmethod
from typing import List, Optional

from self_healing.core.models import (
    TargetSpec,
    VerificationResult,
)
from self_healing.verification.engine import VerificationEngine
from self_healing.verification.probes.base import BaseVerificationProbe, ProbeOutcome


class BaseVerificationEngine(ABC):
    """Abstract interface for the post-healing verification engine."""

    @abstractmethod
    def register_probe(self, probe: BaseVerificationProbe) -> None:
        """Register a verification probe."""
        pass

    @abstractmethod
    def verify(self, target: TargetSpec, incident_id: str, **kwargs) -> VerificationResult:
        """Run verification probes on the given target and return aggregate result."""
        pass


__all__ = [
    "BaseVerificationProbe",
    "ProbeOutcome",
    "BaseVerificationEngine",
    "VerificationEngine",
]
