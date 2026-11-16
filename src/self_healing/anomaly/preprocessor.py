"""Feature preprocessor and baseline statistics tracker for anomaly detection."""

from typing import Any, Dict, List, Optional
import numpy as np
from sklearn.preprocessing import StandardScaler

from self_healing.anomaly.features import FEATURE_NAMES


class FeaturePreprocessor:
    """Preprocesses feature vectors, maintains scaling transforms, and tracks healthy baselines.
    
    Provides normalization via StandardScaler and records per-feature mean and standard
    deviation across healthy training distributions to support explainable Z-score attribution.
    """

    def __init__(self, feature_names: Optional[List[str]] = None) -> None:
        self.feature_names = feature_names or list(FEATURE_NAMES)
        self.scaler = StandardScaler()
        self.is_fitted: bool = False
        self.baseline_means: Dict[str, float] = {}
        self.baseline_stds: Dict[str, float] = {}

    def fit(self, X: np.ndarray) -> "FeaturePreprocessor":
        """Fit scaler and baseline statistics on healthy telemetry samples.
        
        Args:
            X: 2D array of shape [n_samples, n_features].
            
        Returns:
            self
        """
        if X.shape[0] == 0:
            raise ValueError("Cannot fit preprocessor on empty dataset.")

        # Replace any NaNs or infinities with finite zero
        X_clean = np.nan_to_num(X, nan=0.0, posinf=100.0, neginf=-100.0)

        self.scaler.fit(X_clean)
        self.is_fitted = True

        # Calculate and cache baseline distribution parameters
        means = np.mean(X_clean, axis=0)
        stds = np.std(X_clean, axis=0)

        for i, name in enumerate(self.feature_names):
            self.baseline_means[name] = float(means[i])
            # Enforce minimum non-zero standard deviation to avoid division by zero
            self.baseline_stds[name] = float(max(stds[i], 1e-4))

        return self

    def transform(self, X: np.ndarray) -> np.ndarray:
        """Standardize feature matrix using fitted parameters.
        
        Args:
            X: 2D array of shape [n_samples, n_features].
            
        Returns:
            Standardized 2D array.
        """
        if not self.is_fitted:
            raise RuntimeError("Preprocessor must be fitted before calling transform.")

        X_clean = np.nan_to_num(X, nan=0.0, posinf=100.0, neginf=-100.0)
        return self.scaler.transform(X_clean)

    def fit_transform(self, X: np.ndarray) -> np.ndarray:
        """Fit and transform feature matrix in one call."""
        return self.fit(X).transform(X)

    def get_baseline_summary(self) -> Dict[str, Dict[str, float]]:
        """Return human-readable summary of the healthy baseline distribution."""
        summary: Dict[str, Dict[str, float]] = {}
        for name in self.feature_names:
            summary[name] = {
                "mean": round(self.baseline_means.get(name, 0.0), 4),
                "std": round(self.baseline_stds.get(name, 1.0), 4),
            }
        return summary

