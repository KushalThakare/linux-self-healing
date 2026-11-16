"""Explainability engine for multivariate anomaly detection."""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional
import numpy as np


@dataclass
class FeatureContribution:
    """Quantitative attribution metrics for an individual feature."""
    feature_name: str
    observed_value: float
    baseline_mean: float
    baseline_std: float
    z_score: float
    contribution_weight: float

    def to_dict(self) -> Dict[str, Any]:
        """Convert contribution to structured serializable dictionary."""
        return {
            "feature": self.feature_name,
            "observed_value": round(float(self.observed_value), 3),
            "baseline_mean": round(float(self.baseline_mean), 3),
            "baseline_std": round(float(self.baseline_std), 3),
            "z_score": round(float(self.z_score), 2),
            "contribution_weight": round(float(self.contribution_weight), 4),
        }


@dataclass
class AnomalyExplanation:
    """Full forensic explanation of why a telemetry vector was classified as an anomaly."""
    anomaly_score: float
    threshold: float
    is_anomaly: bool
    top_contributors: List[FeatureContribution]
    summary_sentence: str

    def to_evidence_dict(self) -> Dict[str, Any]:
        """Format as detection evidence dictionary suitable for IncidentRecord and DetectionEvent."""
        return {
            "detector": "IsolationForestDetector",
            "anomaly_score": round(self.anomaly_score, 4),
            "threshold": round(self.threshold, 4),
            "is_anomaly": self.is_anomaly,
            "top_contributors": [c.to_dict() for c in self.top_contributors],
            "explanation": self.summary_sentence,
        }


class ExplainabilityEngine:
    """Calculates explainable feature attributions and Z-score deviation metrics.
    
    Identifies which system and process telemetry dimensions contributed most
    heavily to an isolation forest outlier decision.
    """

    def __init__(self, feature_names: List[str]) -> None:
        self.feature_names = feature_names

    def explain(
        self,
        raw_vector: np.ndarray,
        anomaly_score: float,
        threshold: float,
        baseline_means: Dict[str, float],
        baseline_stds: Dict[str, float],
        top_k: int = 3,
    ) -> AnomalyExplanation:
        """Generate explainable forensic report for a feature observation.
        
        Args:
            raw_vector: 1D array of unnormalized observed telemetry values.
            anomaly_score: Normalized anomaly score [0.0, 1.0].
            threshold: Anomaly decision threshold.
            baseline_means: Mean values from healthy training baseline.
            baseline_stds: Standard deviation values from healthy baseline.
            top_k: Number of highest-contributing features to include in the breakdown.
            
        Returns:
            AnomalyExplanation object with top contributing features and direct human summary.
        """
        contributions: List[FeatureContribution] = []
        z_scores: List[float] = []

        for i, name in enumerate(self.feature_names):
            val = float(raw_vector[i])
            mean = baseline_means.get(name, 0.0)
            std = baseline_stds.get(name, 1.0)

            # Standardized absolute Z-score
            z = abs(val - mean) / max(std, 1e-4)
            z_scores.append(z)

            contributions.append(
                FeatureContribution(
                    feature_name=name,
                    observed_value=val,
                    baseline_mean=mean,
                    baseline_std=std,
                    z_score=z,
                    contribution_weight=0.0,  # Computed below
                )
            )

        total_z = sum(z_scores)
        if total_z > 0:
            for c in contributions:
                c.contribution_weight = c.z_score / total_z

        # Rank descending by Z-score deviation
        contributions.sort(key=lambda c: c.z_score, reverse=True)
        top_contributors = contributions[:top_k]

        is_anomaly = anomaly_score >= threshold

        # Construct concise, technical summary
        if is_anomaly and top_contributors:
            main_factors = ", ".join(
                f"{c.feature_name} (val: {round(c.observed_value, 2)}, z: {round(c.z_score, 1)}σ)"
                for c in top_contributors if c.z_score > 1.5
            )
            if not main_factors:
                main_factors = f"{top_contributors[0].feature_name} (val: {round(top_contributors[0].observed_value, 2)})"
            summary = f"Multivariate anomaly detected (score: {round(anomaly_score, 3)} >= {round(threshold, 3)}). Primary deviations: {main_factors}."
        else:
            summary = f"Telemetry consistent with healthy baseline (score: {round(anomaly_score, 3)} < {round(threshold, 3)})."

        return AnomalyExplanation(
            anomaly_score=anomaly_score,
            threshold=threshold,
            is_anomaly=is_anomaly,
            top_contributors=top_contributors,
            summary_sentence=summary,
        )

