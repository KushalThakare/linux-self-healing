"""Isolation Forest model encapsulation, scoring, and persistence."""

from pathlib import Path
from typing import Any, Dict, Optional, Tuple
import joblib
import numpy as np
from sklearn.ensemble import IsolationForest

from self_healing.logging.logger import get_logger

logger = get_logger("anomaly.model")


class IsolationForestModel:
    """Wrapper around scikit-learn's IsolationForest providing normalized anomaly scoring.
    
    Provides fit, normalized scoring [0.0, 1.0], prediction, and safe disk persistence.
    """

    def __init__(
        self,
        n_estimators: int = 100,
        contamination: Any = "auto",
        max_samples: Any = "auto",
        random_state: int = 42,
        threshold: float = 0.50,
    ) -> None:
        self.n_estimators = n_estimators
        self.contamination = contamination
        self.max_samples = max_samples
        self.random_state = random_state
        self.threshold = threshold

        self.model = IsolationForest(
            n_estimators=self.n_estimators,
            contamination=self.contamination,
            max_samples=self.max_samples,
            random_state=self.random_state,
            n_jobs=-1,
        )
        self.is_fitted: bool = False
        self._score_min: float = 0.0
        self._score_max: float = 1.0

    def fit(self, X: np.ndarray) -> "IsolationForestModel":
        """Train Isolation Forest on baseline healthy telemetry samples.
        
        Args:
            X: Scaled feature matrix of shape [n_samples, n_features].
            
        Returns:
            self
        """
        if X.shape[0] < 5:
            raise ValueError(f"Insufficient training samples ({X.shape[0]}). Minimum 5 required.")

        self.model.fit(X)
        self.is_fitted = True

        # Compute empirical calibration bounds from training baseline
        # In scikit-learn, score_samples returns opposite of anomaly score (e.g. -0.4 to -0.6)
        raw_scores = -self.model.score_samples(X)
        self._score_min = float(np.min(raw_scores))
        self._score_max = float(max(np.max(raw_scores), self._score_min + 1e-4))

        logger.info(
            "Isolation Forest trained on %d samples. Baseline raw score range: [%.4f, %.4f]",
            X.shape[0],
            self._score_min,
            self._score_max,
        )
        return self

    def compute_anomaly_scores(self, X: np.ndarray) -> np.ndarray:
        """Compute normalized anomaly scores in range [0.0, 1.0].
        
        Higher values indicate a higher degree of anomaly.
        Scores above ~0.50 represent significant deviation from the baseline.
        
        Args:
            X: Scaled feature matrix.
            
        Returns:
            1D array of normalized float scores in [0.0, 1.0].
        """
        if not self.is_fitted:
            raise RuntimeError("IsolationForestModel must be fitted before scoring samples.")

        dec_func = self.model.decision_function(X)
        scores = 0.50 - (dec_func * 2.0)
        return np.clip(scores, 0.0, 1.0)

    def predict_anomaly(self, X: np.ndarray, threshold: Optional[float] = None) -> Tuple[np.ndarray, np.ndarray]:
        """Predict whether observations are anomalous and return both boolean flags and scores.
        
        Args:
            X: Scaled feature matrix.
            threshold: Anomaly score threshold (defaults to self.threshold).
            
        Returns:
            Tuple of (boolean array is_anomaly, float array anomaly_scores).
        """
        thresh = threshold if threshold is not None else self.threshold
        scores = self.compute_anomaly_scores(X)
        preds = self.model.predict(X)
        is_anomaly = (scores >= thresh) | (preds == -1)
        return is_anomaly, scores

    def save(self, filepath: str) -> None:
        """Persist model and calibration parameters to disk."""
        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "model": self.model,
            "is_fitted": self.is_fitted,
            "threshold": self.threshold,
            "contamination": self.contamination,
            "n_estimators": self.n_estimators,
            "_score_min": self._score_min,
            "_score_max": self._score_max,
        }
        joblib.dump(payload, str(path))
        logger.info("Saved Isolation Forest model to '%s'", path)

    @classmethod
    def load(cls, filepath: str) -> "IsolationForestModel":
        """Load trained model and calibration parameters from disk."""
        path = Path(filepath)
        if not path.is_file():
            raise FileNotFoundError(f"Model file not found: {path}")

        payload = joblib.load(str(path))
        instance = cls(
            n_estimators=payload.get("n_estimators", 100),
            contamination=payload.get("contamination", 0.05),
            threshold=payload.get("threshold", 0.60),
        )
        instance.model = payload["model"]
        instance.is_fitted = payload.get("is_fitted", True)
        instance._score_min = payload.get("_score_min", 0.0)
        instance._score_max = payload.get("_score_max", 1.0)
        logger.info("Loaded Isolation Forest model from '%s'", path)
        return instance
