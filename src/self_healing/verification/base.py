"""Post-healing verification interfaces and engine."""

from abc import ABC, abstractmethod
from typing import List, Optional
import uuid

from self_healing.core.models import (
    TargetSpec,
    VerificationResult,
    VerificationStatus,
    utc_now,
)
from self_healing.logging.logger import get_logger

logger = get_logger("verification")


class BaseVerificationProbe(ABC):
    """Abstract interface for health verification probes."""

    def __init__(self, name: str) -> None:
        self.name = name

    @abstractmethod
    def probe(self, target: TargetSpec) -> bool:
        """Run verification check on target. Returns True if healthy, False otherwise."""
        pass


class BaseVerificationEngine(ABC):
    """Abstract interface for the post-healing verification engine."""

    @abstractmethod
    def register_probe(self, probe: BaseVerificationProbe) -> None:
        """Register a verification probe."""
        pass

    @abstractmethod
    def verify(self, target: TargetSpec, incident_id: str) -> VerificationResult:
        """Run all verification probes on the given target and return aggregate result."""
        pass


class VerificationEngine(BaseVerificationEngine):
    """Closed-loop verification engine implementation skeleton."""

    def __init__(self) -> None:
        self._probes: List[BaseVerificationProbe] = []

    def register_probe(self, probe: BaseVerificationProbe) -> None:
        self._probes.append(probe)
        logger.debug("Registered verification probe: %s", probe.name)

    def verify(self, target: TargetSpec, incident_id: str) -> VerificationResult:
        passed: List[str] = []
        failed: List[str] = []

        if not self._probes:
            # Baseline skeleton default: assume healthy if no explicit probes configured yet
            passed.append("default_skeleton_probe")

        for probe in self._probes:
            try:
                is_healthy = probe.probe(target)
                if is_healthy:
                    passed.append(probe.name)
                else:
                    failed.append(probe.name)
            except Exception as e:
                logger.error("Probe '%s' failed with error: %s", probe.name, e)
                failed.append(probe.name)

        status = VerificationStatus.HEALTHY if not failed else VerificationStatus.FAILED
        details = (
            f"Verification completed for target '{target.target_id}'. "
            f"Passed: {len(passed)}, Failed: {len(failed)}."
        )

        logger.info(
            "Target '%s' verification status: %s (passed: %s, failed: %s)",
            target.target_id,
            status.value,
            passed,
            failed,
        )

        return VerificationResult(
            verification_id=str(uuid.uuid4()),
            incident_id=incident_id,
            target_id=target.target_id,
            status=status,
            verified_at=utc_now(),
            checks_passed=passed,
            checks_failed=failed,
            details=details,
        )
