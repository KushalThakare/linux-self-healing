"""Automated tests for Phase 14 Evaluation Framework."""

from datetime import datetime, timezone
from pathlib import Path
import pytest

from self_healing.evaluation.harness import EvaluationHarness
from self_healing.evaluation.metrics import compute_mode_summary, compute_stats
from self_healing.evaluation.models import (
    DetectionMode,
    EvaluatedFaultType,
    TrialResult,
)
from self_healing.evaluation.plots import generate_all_plots


def test_trial_result_model_validation():
    """Verify TrialResult model validation and serialization."""
    now = datetime.now(timezone.utc)
    t = TrialResult(
        trial_id="test-trial-1",
        trial_index=1,
        detection_mode=DetectionMode.RULE_BASED,
        fault_type=EvaluatedFaultType.CPU_RUNAWAY,
        target_id="demo-cpu",
        timestamp_start=now,
        t_healthy_start=0.0,
        t_fault_inject=1.0,
        t_detect=1.5,
        t_diagnose=1.51,
        t_guardrail=1.52,
        t_heal_start=1.53,
        t_heal_end=1.55,
        t_verify=1.60,
        t_complete=1.65,
        detection_latency_ms=500.0,
        recovery_latency_ms=20.0,
        total_recovery_time_s=0.65,
        detected=True,
        diagnosed=True,
        guardrail_approved=True,
        recovery_success=True,
        verification_passed=True,
    )
    assert t.detection_latency_ms == 500.0
    assert t.recovery_latency_ms == 20.0
    assert t.total_recovery_time_s == 0.65
    assert t.detected is True

    data = t.model_dump()
    assert data["trial_id"] == "test-trial-1"
    assert data["detection_mode"] == "RULE_BASED"


def test_compute_stats():
    """Verify descriptive statistics computation."""
    empty_stats = compute_stats([])
    assert empty_stats.count == 0
    assert empty_stats.mean == 0.0

    values = [10.0, 20.0, 30.0, 40.0, 50.0]
    stats = compute_stats(values)
    assert stats.count == 5
    assert stats.mean == 30.0
    assert stats.median == 30.0
    assert stats.min == 10.0
    assert stats.max == 50.0
    assert stats.std_dev > 0.0


def test_compute_mode_summary():
    """Verify metric rates aggregation in ModeSummary."""
    now = datetime.now(timezone.utc)
    trials = [
        # Nominal trial (no false alarm)
        TrialResult(
            trial_id="t0",
            trial_index=1,
            detection_mode=DetectionMode.RULE_BASED,
            fault_type=EvaluatedFaultType.NOMINAL,
            target_id="demo-cpu",
            timestamp_start=now,
            t_healthy_start=0.0,
            t_complete=1.0,
            detected=False,
            is_false_positive=False,
        ),
        # Successful fault trial
        TrialResult(
            trial_id="t1",
            trial_index=1,
            detection_mode=DetectionMode.RULE_BASED,
            fault_type=EvaluatedFaultType.CPU_RUNAWAY,
            target_id="demo-cpu",
            timestamp_start=now,
            t_healthy_start=0.0,
            t_fault_inject=1.0,
            t_detect=1.4,
            t_complete=2.0,
            detection_latency_ms=400.0,
            recovery_latency_ms=15.0,
            total_recovery_time_s=1.0,
            detected=True,
            diagnosed=True,
            guardrail_approved=True,
            recovery_executed=True,
            recovery_success=True,
            verification_passed=True,
        ),
    ]

    summary = compute_mode_summary(DetectionMode.RULE_BASED, trials)
    assert summary.total_trials == 2
    assert summary.nominal_trials == 1
    assert summary.fault_trials == 1
    assert summary.false_positive_rate_percent == 0.0
    assert summary.detection_success_rate_percent == 100.0
    assert summary.recovery_success_rate_percent == 100.0
    assert summary.verification_success_rate_percent == 100.0
    assert summary.guardrail_approval_rate_percent == 100.0
    assert summary.overall_detection_latency_ms.mean == 400.0


def test_generate_all_plots(tmp_path: Path):
    """Verify all report plots are generated without error."""
    now = datetime.now(timezone.utc)
    dummy_trial = TrialResult(
        trial_id="t1",
        trial_index=1,
        detection_mode=DetectionMode.RULE_BASED,
        fault_type=EvaluatedFaultType.CPU_RUNAWAY,
        target_id="demo-cpu",
        timestamp_start=now,
        t_healthy_start=0.0,
        t_fault_inject=1.0,
        t_detect=1.5,
        t_complete=2.5,
        detection_latency_ms=500.0,
        recovery_latency_ms=10.0,
        total_recovery_time_s=1.5,
        detected=True,
        diagnosed=True,
        guardrail_approved=True,
        recovery_executed=True,
        recovery_success=True,
        action_type="terminate_demo_process",
        verification_passed=True,
    )
    r_summary = compute_mode_summary(DetectionMode.RULE_BASED, [dummy_trial])
    h_summary = compute_mode_summary(DetectionMode.RULE_PLUS_ISOLATION_FOREST, [dummy_trial])

    plots = generate_all_plots(r_summary, h_summary, [dummy_trial], tmp_path)
    assert len(plots) >= 3
    for p in plots:
        assert p.exists()
        assert p.stat().st_size > 0
