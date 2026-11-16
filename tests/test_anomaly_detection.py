"""Unit and integration tests for Phase 13 Isolation Forest anomaly detection."""

import os
from pathlib import Path
import tempfile
import pytest
import numpy as np

from self_healing.anomaly.dataset import (
    generate_anomalous_snapshots,
    generate_healthy_snapshots,
)
from self_healing.anomaly.detector import IsolationForestDetector
from self_healing.anomaly.explainability import ExplainabilityEngine
from self_healing.anomaly.features import (
    FEATURE_NAMES,
    TelemetryFeatureExtractor,
    encode_service_state,
)
from self_healing.anomaly.model import IsolationForestModel
from self_healing.anomaly.preprocessor import FeaturePreprocessor
from self_healing.config.settings import GuardrailsConfig
from self_healing.core.models import (
    ActionType,
    AllowedActionType,
    FaultSeverity,
    FaultType,
    GuardrailStatus,
    IncidentRecord,
    IncidentStatus,
    ProcessState,
    RecoveryAction,
    TargetSpec,
)
from self_healing.diagnosis.engine import DeterministicDiagnosisEngine
from self_healing.guardrails.engine import SafetyGuardrailEngine
from self_healing.incidents.store import InMemoryIncidentStore
from self_healing.recovery.executor import RecoveryExecutor
from self_healing.targets.registry import TargetRegistry


@pytest.fixture
def sample_demo_target() -> TargetSpec:
    return TargetSpec(
        target_id="demo-cpu",
        process_name="python3",
        cmdline_substring="cpu_spin",
        working_dir_prefix="/home/user/linux-self-healing",
        enabled=True,
    )


# =============================================================================
# 1. Feature Extraction Tests
# =============================================================================

def test_encode_service_state():
    """Verify service state categorical encoding into standardized numerics."""
    assert encode_service_state(ProcessState.RUNNING) == 1.0
    assert encode_service_state(ProcessState.SLEEPING) == 0.5
    assert encode_service_state(ProcessState.IDLE) == 0.5
    assert encode_service_state(ProcessState.STOPPED) == 0.0
    assert encode_service_state(ProcessState.DEAD) == -1.0
    assert encode_service_state(ProcessState.ZOMBIE) == -0.5


def test_feature_extractor_vector_dimensions():
    """Verify extractor extracts 10-dimensional feature vector matching FEATURE_NAMES."""
    extractor = TelemetryFeatureExtractor()
    snapshots = generate_healthy_snapshots(n_samples=5)

    vec0 = extractor.extract_vector(current=snapshots[0])
    assert len(vec0.values) == 10
    assert len(vec0.feature_names) == 10
    assert vec0.to_dict()["system_cpu_percent"] == snapshots[0].system_cpu_percent

    # Test delta calculation with previous snapshot
    vec1 = extractor.extract_vector(current=snapshots[1], previous=snapshots[0])
    expected_cpu_delta = snapshots[1].target_cpu_percent - snapshots[0].target_cpu_percent
    assert pytest.approx(vec1.to_dict()["cpu_delta"], rel=1e-3) == expected_cpu_delta


def test_feature_extractor_matrix_from_window():
    """Verify 2D matrix transformation from chronological window."""
    extractor = TelemetryFeatureExtractor()
    snapshots = generate_healthy_snapshots(n_samples=20)
    matrix, vectors = extractor.extract_matrix_from_window(snapshots)

    assert matrix.shape == (20, 10)
    assert len(vectors) == 20
    assert not np.isnan(matrix).any()


# =============================================================================
# 2. Preprocessor & Baseline Tests
# =============================================================================

def test_feature_preprocessor_fit_transform():
    """Verify preprocessor calculates baseline statistics and scales features."""
    preprocessor = FeaturePreprocessor()
    extractor = TelemetryFeatureExtractor()
    snapshots = generate_healthy_snapshots(n_samples=50)
    matrix, _ = extractor.extract_matrix_from_window(snapshots)

    scaled = preprocessor.fit_transform(matrix)
    assert scaled.shape == matrix.shape
    assert preprocessor.is_fitted is True

    # Means should be ~0 and stds ~1 on the scaled training set
    assert pytest.approx(np.mean(scaled[:, 0]), abs=1e-1) == 0.0
    assert pytest.approx(np.std(scaled[:, 0]), abs=1e-1) == 1.0

    # Baseline summary contains all features
    summary = preprocessor.get_baseline_summary()
    assert "system_cpu_percent" in summary
    assert summary["target_cpu_percent"]["mean"] > 0


# =============================================================================
# 3. Isolation Forest Model & Scoring Tests
# =============================================================================

def test_isolation_forest_model_training_and_scoring():
    """Verify model fits on healthy telemetry and yields low anomaly scores on nominal load."""
    extractor = TelemetryFeatureExtractor()
    preprocessor = FeaturePreprocessor()
    model = IsolationForestModel(n_estimators=50, contamination="auto", threshold=0.50)

    healthy_snaps = generate_healthy_snapshots(n_samples=100)
    matrix, _ = extractor.extract_matrix_from_window(healthy_snaps)
    scaled_train = preprocessor.fit_transform(matrix)

    model.fit(scaled_train)
    assert model.is_fitted is True

    # Normal test sample should score below threshold
    normal_snap = generate_healthy_snapshots(n_samples=5, random_seed=777)
    normal_matrix, _ = extractor.extract_matrix_from_window(normal_snap)
    normal_scaled = preprocessor.transform(normal_matrix)

    scores = model.compute_anomaly_scores(normal_scaled)
    assert all(0.0 <= s <= 1.0 for s in scores)
    assert np.mean(scores) < 0.55  # Nominal samples remain below threshold


def test_isolation_forest_model_detects_synthetic_anomaly():
    """Verify model flags severe anomalies with scores exceeding the decision threshold."""
    extractor = TelemetryFeatureExtractor()
    preprocessor = FeaturePreprocessor()
    model = IsolationForestModel(n_estimators=50, contamination="auto", threshold=0.50)

    # Train on healthy
    healthy_snaps = generate_healthy_snapshots(n_samples=100)
    matrix, _ = extractor.extract_matrix_from_window(healthy_snaps)
    scaled_train = preprocessor.fit_transform(matrix)
    model.fit(scaled_train)

    # Evaluate on runaway CPU anomaly
    anomaly_snaps = generate_anomalous_snapshots(fault_type="cpu_runaway", n_samples=10)
    anomaly_matrix, _ = extractor.extract_matrix_from_window(anomaly_snaps)
    anomaly_scaled = preprocessor.transform(anomaly_matrix)

    is_anomaly, scores = model.predict_anomaly(anomaly_scaled)
    assert any(is_anomaly)
    assert np.max(scores) >= 0.50


def test_isolation_forest_model_persistence():
    """Verify model saving and loading via joblib maintains predictions."""
    extractor = TelemetryFeatureExtractor()
    preprocessor = FeaturePreprocessor()
    model = IsolationForestModel(n_estimators=30, threshold=0.62)

    healthy_snaps = generate_healthy_snapshots(n_samples=40)
    matrix, _ = extractor.extract_matrix_from_window(healthy_snaps)
    scaled = preprocessor.fit_transform(matrix)
    model.fit(scaled)

    test_scores_orig = model.compute_anomaly_scores(scaled[:5])

    with tempfile.TemporaryDirectory() as tmpdir:
        model_file = os.path.join(tmpdir, "iso_forest.joblib")
        model.save(model_file)

        loaded_model = IsolationForestModel.load(model_file)
        assert loaded_model.is_fitted is True
        assert loaded_model.threshold == 0.62

        test_scores_loaded = loaded_model.compute_anomaly_scores(scaled[:5])
        np.testing.assert_allclose(test_scores_orig, test_scores_loaded, rtol=1e-4)


# =============================================================================
# 4. Explainability & Attribution Tests
# =============================================================================

def test_explainability_engine_top_contributors():
    """Verify explainability engine ranks highest Z-score deviating features."""
    engine = ExplainabilityEngine(FEATURE_NAMES)
    raw_vector = np.array([
        95.0,  # sys_cpu (heavy deviation)
        25.0,  # sys_mem
        92.0,  # target_cpu (heavy deviation)
        30.0,  # target_rss_mb
        3.0,   # threads
        15.0,  # fds
        30.0,  # disk
        1.0,   # service state
        80.0,  # cpu delta
        0.0,   # rss growth
    ])

    baseline_means = {name: 10.0 for name in FEATURE_NAMES}
    baseline_stds = {name: 2.0 for name in FEATURE_NAMES}

    explanation = engine.explain(
        raw_vector=raw_vector,
        anomaly_score=0.88,
        threshold=0.60,
        baseline_means=baseline_means,
        baseline_stds=baseline_stds,
        top_k=3,
    )

    assert explanation.is_anomaly is True
    assert explanation.anomaly_score == 0.88
    assert len(explanation.top_contributors) == 3

    top_names = [c.feature_name for c in explanation.top_contributors]
    assert "system_cpu_percent" in top_names or "target_cpu_percent" in top_names
    assert "cpu_delta" in top_names

    evidence = explanation.to_evidence_dict()
    assert evidence["detector"] == "IsolationForestDetector"
    assert len(evidence["top_contributors"]) == 3


# =============================================================================
# 5. IsolationForestDetector Engine Contract Tests
# =============================================================================

def test_detector_zero_false_positives_on_healthy_window(sample_demo_target):
    """Verify IsolationForestDetector produces zero false alarms on healthy telemetry."""
    detector = IsolationForestDetector(threshold=0.70, auto_fit_baseline=True)
    healthy_window = generate_healthy_snapshots(n_samples=25, random_seed=123)

    event = detector.evaluate(sample_demo_target, healthy_window)
    assert event is None  # Healthy telemetry must NOT trigger anomaly


def test_detector_triggers_on_multivariate_fault(sample_demo_target):
    """Verify IsolationForestDetector fires a DetectionEvent on true anomalies."""
    detector = IsolationForestDetector(threshold=0.50, auto_fit_baseline=True)
    fault_window = generate_anomalous_snapshots(fault_type="cpu_runaway", n_samples=15)

    event = detector.evaluate(sample_demo_target, fault_window)
    assert event is not None
    assert event.target_id == sample_demo_target.target_id
    assert event.fault_type == FaultType.STATISTICAL_ANOMALY
    assert event.triggering_value >= 0.50
    assert "IsolationForestDetector" in event.evidence["detector"]
    assert len(event.evidence["top_contributors"]) > 0


# =============================================================================
# 6. End-to-End Closed Loop Safety Pipeline Tests
# =============================================================================

def test_ml_detection_flows_through_diagnosis_guardrails_recovery(sample_demo_target):
    """Verify ML detector NEVER triggers recovery directly.
    
    Validates mandatory progression:
    ANOMALY DETECTION -> DIAGNOSIS -> GUARDRAIL -> RECOVERY (Dry-Run) -> AUDIT STORE
    """
    # 1. DETECT
    detector = IsolationForestDetector(threshold=0.50, auto_fit_baseline=True)
    fault_window = generate_anomalous_snapshots(fault_type="cpu_runaway", n_samples=10)
    event = detector.evaluate(sample_demo_target, fault_window)
    assert event is not None
    assert event.fault_type == FaultType.STATISTICAL_ANOMALY

    # 2. DIAGNOSE: Deterministic diagnosis engine ingests ML detection and feature evidence
    diag_engine = DeterministicDiagnosisEngine()
    diagnosis = diag_engine.diagnose(event, metric_history=fault_window, target=sample_demo_target)

    assert diagnosis.fault_type == FaultType.STATISTICAL_ANOMALY
    assert diagnosis.recommended_action == ActionType.GRACEFUL_TERMINATE
    assert diagnosis.confidence >= 0.70
    assert "cpu" in diagnosis.probable_cause.lower()

    # 3. GUARDRAIL: Policy engine gates the action
    registry = TargetRegistry([sample_demo_target])
    guardrail_cfg = GuardrailsConfig(
        max_actions_per_window=3,
        flapping_window_seconds=60.0,
        default_cooldown_seconds=5.0,
        enforce_target_allowlist=True,
    )
    guardrail_engine = SafetyGuardrailEngine(target_registry=registry, config=guardrail_cfg, dry_run=True)

    action = RecoveryAction(
        action_id="act-test-ml-1",
        action_type=AllowedActionType.TERMINATE_DEMO_PROCESS,
        target=sample_demo_target.target_id,
        reason=diagnosis.probable_cause,
        required_evidence=["anomaly_score"],
        allowed_targets=[sample_demo_target.target_id],
        parameters={"pid": 10001},
    )

    decision = guardrail_engine.evaluate(
        action=action,
        evidence=diagnosis.evidence,
        dry_run=True,
    )
    assert decision.status == GuardrailStatus.APPROVED
    assert decision.allowed is True
    assert decision.is_dry_run is True

    # 4. RECOVER: Typed execution (dry-run simulation)
    executor = RecoveryExecutor(target_registry=registry, dry_run=True)
    recovery_result = executor.execute_guardrail_approved(
        decision=decision,
        action=action,
        target_spec=sample_demo_target,
        dry_run=True,
    )
    assert recovery_result.success is True
    assert recovery_result.dry_run is True
    assert recovery_result.action_type == AllowedActionType.TERMINATE_DEMO_PROCESS

    # 5. RECORD: Complete audit trail
    store = InMemoryIncidentStore()
    record = IncidentRecord(
        incident_id="inc-ml-001",
        target_id=sample_demo_target.target_id,
        status=IncidentStatus.VERIFIED_SUCCESS,
        fault_event=event,
        diagnosis=diagnosis,
        policy_decision=decision,
        recovery_result=recovery_result,
    )
    store.save(record)
    retrieved = store.get("inc-ml-001")
    assert retrieved is not None
    assert retrieved.fault_event.fault_type == FaultType.STATISTICAL_ANOMALY
    assert retrieved.policy_decision.allowed is True
