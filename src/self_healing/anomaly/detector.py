"""Isolation Forest secondary anomaly detector conforming to detection engine contracts."""

from typing import Any, Dict, List, Optional
import uuid
import numpy as np

from self_healing.anomaly.dataset import generate_healthy_snapshots
from self_healing.anomaly.explainability import AnomalyExplanation, ExplainabilityEngine
from self_healing.anomaly.features import FEATURE_NAMES, TelemetryFeatureExtractor
from self_healing.anomaly.model import IsolationForestModel
from self_healing.anomaly.preprocessor import FeaturePreprocessor
from self_healing.core.models import (
    DetectionEvent,
    FaultSeverity,
    FaultType,
    MetricSnapshot,
    TargetSpec,
    utc_now,
)
from self_healing.detection.base import BaseFaultRule
from self_healing.logging.logger import get_logger

logger = get_logger("anomaly.detector")


class IsolationForestDetector(BaseFaultRule):
    """Secondary multivariate anomaly detector using an unsupervised Isolation Forest.
    
    Operates in parallel with deterministic rules to detect complex degradation,
    simultaneous subtle deviations, or emergent anomalies before hard threshold breaches occur.
    
    Produces explainable feature evidence (Z-score deviations) and never triggers recovery
    actions directly. Output events flow through Diagnosis -> Guardrail -> Recovery -> Verification.
    """

    def __init__(
        self,
        name: str = "IsolationForestDetector",
        threshold: float = 0.50,
        contamination: Any = "auto",
        n_estimators: int = 100,
        model_path: Optional[str] = None,
        auto_fit_baseline: bool = True,
    ) -> None:
        super().__init__(
            name=name,
            fault_type=FaultType.STATISTICAL_ANOMALY,
            severity=FaultSeverity.MEDIUM,
        )
        self.feature_names = list(FEATURE_NAMES)
        self.extractor = TelemetryFeatureExtractor(self.feature_names)
        self.preprocessor = FeaturePreprocessor(self.feature_names)
        self.model = IsolationForestModel(
            n_estimators=n_estimators,
            contamination=contamination,
            threshold=threshold,
        )
        self.explainability = ExplainabilityEngine(self.feature_names)
        self.model_path = model_path

        if model_path:
            try:
                self.load_model(model_path)
            except Exception as e:
                logger.warning("Could not load model from '%s': %s. Re-initializing baseline.", model_path, e)
                if auto_fit_baseline:
                    self._fit_default_baseline()
        elif auto_fit_baseline:
            self._fit_default_baseline()

    def _fit_default_baseline(self) -> None:
        """Fit preprocessor and model on standard synthetic healthy baseline telemetry."""
        logger.info("Initializing IsolationForestDetector with healthy baseline telemetry...")
        baseline_snapshots = generate_healthy_snapshots(n_samples=150)
        matrix, _ = self.extractor.extract_matrix_from_window(baseline_snapshots)
        self.fit_baseline(matrix)

    def fit_baseline(self, raw_matrix: np.ndarray) -> "IsolationForestDetector":
        """Fit preprocessor and Isolation Forest model on healthy telemetry matrix.
        
        Args:
            raw_matrix: 2D array of shape [n_samples, n_features].
        """
        if raw_matrix.shape[0] < 5:
            raise ValueError(f"Insufficient baseline samples ({raw_matrix.shape[0]}). Minimum 5 required.")

        scaled = self.preprocessor.fit_transform(raw_matrix)
        self.model.fit(scaled)
        logger.info("Fitted IsolationForestDetector on %d healthy samples", raw_matrix.shape[0])
        return self

    def fit_baseline_from_snapshots(self, snapshots: List[MetricSnapshot]) -> "IsolationForestDetector":
        """Extract features from snapshots and fit baseline."""
        matrix, _ = self.extractor.extract_matrix_from_window(snapshots)
        return self.fit_baseline(matrix)

    def score_snapshot(
        self,
        current: MetricSnapshot,
        previous: Optional[MetricSnapshot] = None,
    ) -> AnomalyExplanation:
        """Calculate anomaly score and explainable attribution for a single snapshot."""
        vec = self.extractor.extract_vector(current=current, previous=previous)
        raw_matrix = vec.values.reshape(1, -1)
        scaled_matrix = self.preprocessor.transform(raw_matrix)

        _, scores = self.model.predict_anomaly(scaled_matrix)
        score = float(scores[0])

        explanation = self.explainability.explain(
            raw_vector=vec.values,
            anomaly_score=score,
            threshold=self.model.threshold,
            baseline_means=self.preprocessor.baseline_means,
            baseline_stds=self.preprocessor.baseline_stds,
        )
        return explanation

    def evaluate(
        self,
        target: TargetSpec,
        window: List[MetricSnapshot],
    ) -> Optional[DetectionEvent]:
        """Evaluate telemetry window using Isolation Forest.
        
        Args:
            target: The monitored demo target.
            window: Chronological metric snapshots.
            
        Returns:
            DetectionEvent if anomaly score >= threshold; None otherwise.
        """
        if not window:
            return None

        # Filter window to target if needed
        target_snaps = [s for s in window if s.target_id == target.target_id]
        if not target_snaps:
            target_snaps = window

        current = target_snaps[-1]
        previous = target_snaps[-2] if len(target_snaps) >= 2 else None

        explanation = self.score_snapshot(current, previous)

        if not explanation.is_anomaly:
            return None

        severity = FaultSeverity.HIGH if explanation.anomaly_score >= 0.80 else FaultSeverity.MEDIUM

        event = DetectionEvent(
            event_id=f"anomaly-{uuid.uuid4().hex[:8]}",
            target_id=target.target_id,
            fault_type=self.fault_type,
            severity=severity,
            detected_at=utc_now(),
            triggering_value=round(explanation.anomaly_score, 4),
            threshold_value=round(self.model.threshold, 4),
            description=explanation.summary_sentence,
            evidence=explanation.to_evidence_dict(),
        )

        logger.info(
            "[ISOLATION FOREST ANOMALY] Target '%s': %s (Score: %.3f)",
            target.target_id,
            event.description,
            explanation.anomaly_score,
        )
        return event

    def save_model(self, filepath: str) -> None:
        """Persist model state and preprocessor parameters to disk."""
        self.model.save(filepath)

    def load_model(self, filepath: str) -> None:
        """Load model state and preprocessor parameters from disk."""
        self.model = IsolationForestModel.load(filepath)
