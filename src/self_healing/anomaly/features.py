"""Feature extraction and telemetry vectorization for Isolation Forest anomaly detection."""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
import numpy as np

from self_healing.core.models import MetricSnapshot, ProcessState, TargetSpec


FEATURE_NAMES: List[str] = [
    "system_cpu_percent",
    "system_memory_percent",
    "target_cpu_percent",
    "target_rss_mb",
    "target_num_threads",
    "target_num_fds",
    "disk_used_percent",
    "service_state_numeric",
    "cpu_delta",
    "rss_growth_rate_mb",
]


def encode_service_state(state: ProcessState) -> float:
    """Encode process/service operational state into a standardized numeric scalar.
    
    1.0: RUNNING / ACTIVE (nominal healthy state)
    0.5: SLEEPING / IDLE (nominal non-compute state)
    0.0: STOPPED / UNKNOWN
    -0.5: ZOMBIE (abnormal dead child)
    -1.0: DEAD / CRASHED (critical failure state)
    """
    if state in (ProcessState.RUNNING,):
        return 1.0
    elif state in (ProcessState.SLEEPING, ProcessState.IDLE):
        return 0.5
    elif state in (ProcessState.STOPPED, ProcessState.UNKNOWN):
        return 0.0
    elif state in (ProcessState.ZOMBIE,):
        return -0.5
    elif state in (ProcessState.DEAD,):
        return -1.0
    return 0.0


@dataclass
class ExtractedFeatureVector:
    """Strongly-typed representation of an extracted feature vector with metadata."""
    feature_names: List[str]
    values: np.ndarray
    target_id: str
    timestamp_iso: str
    raw_snapshot: MetricSnapshot

    def to_dict(self) -> Dict[str, float]:
        """Convert feature vector to a key-value dictionary."""
        return {name: float(val) for name, val in zip(self.feature_names, self.values)}


class TelemetryFeatureExtractor:
    """Extracts multivariate numerical feature vectors from telemetry snapshots.
    
    Transforms raw system and target process telemetry into standardized
    10-dimensional numerical vectors suitable for unsupervised anomaly detection.
    """

    def __init__(self, feature_names: Optional[List[str]] = None) -> None:
        self.feature_names = feature_names or list(FEATURE_NAMES)

    def extract_vector(
        self,
        current: MetricSnapshot,
        previous: Optional[MetricSnapshot] = None,
    ) -> ExtractedFeatureVector:
        """Extract a single feature vector from current snapshot and optional previous snapshot.
        
        Args:
            current: Current point-in-time metric snapshot.
            previous: Prior snapshot used to compute dynamic rate-of-change deltas.
            
        Returns:
            ExtractedFeatureVector containing the standardized numpy array.
        """
        # 1. Base telemetry values
        sys_cpu = float(current.system_cpu_percent or 0.0)
        sys_mem = float(current.system_memory_percent or 0.0)
        target_cpu = float(current.target_cpu_percent or 0.0)
        target_rss_mb = float(current.target_rss_bytes or 0) / (1024.0 * 1024.0)
        target_threads = float(current.target_num_threads or 1)
        target_fds = float(current.target_num_fds or 0)

        # 2. Disk utilization
        disk_pct = 0.0
        if current.disks:
            # Use max disk utilization across mounts or root mount
            disk_pct = max((float(d.percent) for d in current.disks), default=0.0)

        # 3. Service state numeric
        service_state = encode_service_state(current.target_state)

        # 4. First differences (rate of change)
        cpu_delta = 0.0
        rss_growth_rate_mb = 0.0
        if previous is not None:
            prev_cpu = float(previous.target_cpu_percent or 0.0)
            prev_rss_mb = float(previous.target_rss_bytes or 0) / (1024.0 * 1024.0)
            cpu_delta = target_cpu - prev_cpu
            rss_growth_rate_mb = target_rss_mb - prev_rss_mb

        features = [
            sys_cpu,
            sys_mem,
            target_cpu,
            target_rss_mb,
            target_threads,
            target_fds,
            disk_pct,
            service_state,
            cpu_delta,
            rss_growth_rate_mb,
        ]

        values_arr = np.array(features, dtype=np.float64)

        return ExtractedFeatureVector(
            feature_names=list(self.feature_names),
            values=values_arr,
            target_id=current.target_id,
            timestamp_iso=current.timestamp.isoformat() if hasattr(current.timestamp, "isoformat") else str(current.timestamp),
            raw_snapshot=current,
        )

    def extract_matrix_from_window(
        self,
        window: List[MetricSnapshot],
    ) -> Tuple[np.ndarray, List[ExtractedFeatureVector]]:
        """Extract a 2D matrix (N samples x M features) from a chronological window.
        
        Args:
            window: Ordered list of snapshots (oldest to newest).
            
        Returns:
            Tuple of (numpy 2D array of shape [len(window), num_features], list of feature vectors).
        """
        if not window:
            return np.empty((0, len(self.feature_names)), dtype=np.float64), []

        vectors: List[ExtractedFeatureVector] = []
        rows: List[np.ndarray] = []

        prev: Optional[MetricSnapshot] = None
        for snap in window:
            vec = self.extract_vector(current=snap, previous=prev)
            vectors.append(vec)
            rows.append(vec.values)
            prev = snap

        matrix = np.vstack(rows) if rows else np.empty((0, len(self.feature_names)), dtype=np.float64)
        return matrix, vectors

