"""Root cause diagnosis interfaces and baseline engine."""

from abc import ABC, abstractmethod
from typing import Any, List, Optional, Union
import uuid

from self_healing.core.models import (
    ActionType,
    DetectionEvent,
    DiagnosisReport,
    DiagnosisResult,
    FaultEvent,
    FaultType,
    MetricSnapshot,
    TargetSpec,
)
from self_healing.logging.logger import get_logger

logger = get_logger("diagnosis")

# Baseline deterministic mapping from fault type to default suggested remediation
DEFAULT_ACTION_MAPPING = {
    FaultType.HIGH_CPU: ActionType.GRACEFUL_TERMINATE,
    FaultType.MEMORY_LEAK: ActionType.RESTART_SERVICE,
    FaultType.HUNG_PROCESS: ActionType.RESTART_SERVICE,
    FaultType.PROCESS_CRASH: ActionType.RESTART_SERVICE,
    FaultType.ZOMBIE_PROCESS: ActionType.GRACEFUL_TERMINATE,
    FaultType.FD_EXHAUSTION: ActionType.RESTART_SERVICE,
    FaultType.DISK_GROWTH: ActionType.CLEAN_TEMP_DIR,
    FaultType.DEADLOCK: ActionType.GRACEFUL_TERMINATE,
}


class BaseDiagnosisEngine(ABC):
    """Abstract interface for root cause diagnosis."""

    @abstractmethod
    def diagnose(
        self,
        fault_event: Union[DetectionEvent, FaultEvent],
        metric_history: Optional[List[MetricSnapshot]] = None,
        target: Optional[TargetSpec] = None,
        **kwargs: Any,
    ) -> Union[DiagnosisResult, DiagnosisReport]:
        """Analyze a fault event in context of telemetry history and return a report."""
        pass


class HeuristicDiagnosisEngine(BaseDiagnosisEngine):
    """Rule-based heuristic diagnosis engine skeleton."""

    def diagnose(
        self,
        fault_event: Union[DetectionEvent, FaultEvent],
        metric_history: Optional[List[MetricSnapshot]] = None,
        target: Optional[TargetSpec] = None,
        **kwargs: Any,
    ) -> DiagnosisReport:
        history = list(metric_history or [])
        target_id = target.target_id if target else fault_event.target_id
        recommended_action = DEFAULT_ACTION_MAPPING.get(
            fault_event.fault_type,
            ActionType.GRACEFUL_TERMINATE,
        )

        diagnosis_id = str(uuid.uuid4())
        root_cause = (
            f"Deterministic fault condition '{fault_event.fault_type.value}' detected on target "
            f"'{target_id}'. Triggered at value {fault_event.triggering_value:.2f} "
            f"(threshold: {fault_event.threshold_value:.2f})."
        )

        report = DiagnosisReport(
            diagnosis_id=diagnosis_id,
            event_id=fault_event.event_id,
            target_id=target_id,
            fault_type=fault_event.fault_type,
            root_cause=root_cause,
            confidence=0.95,
            recommended_action=recommended_action,
            telemetry_window=history,
        )

        logger.info(
            "Generated diagnosis %s for event %s (action recommended: %s)",
            diagnosis_id,
            fault_event.event_id,
            recommended_action.value,
        )
        return report
