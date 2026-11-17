"""Statistical calculation and aggregation for evaluation metrics."""

import math
from typing import Dict, List, Optional
from self_healing.evaluation.models import (
    DetectionMode,
    EvaluatedFaultType,
    EvaluationSummary,
    FaultMetricStats,
    ModeSummary,
    TrialResult,
)


def compute_stats(values: List[float]) -> FaultMetricStats:
    """Compute count, mean, median, standard deviation, min, and max."""
    if not values:
        return FaultMetricStats()

    sorted_vals = sorted(values)
    n = len(sorted_vals)
    mean_val = sum(sorted_vals) / n

    if n % 2 == 1:
        median_val = sorted_vals[n // 2]
    else:
        median_val = (sorted_vals[n // 2 - 1] + sorted_vals[n // 2]) / 2.0

    if n > 1:
        variance = sum((x - mean_val) ** 2 for x in sorted_vals) / (n - 1)
        std_val = math.sqrt(variance)
    else:
        std_val = 0.0

    return FaultMetricStats(
        count=n,
        mean=round(mean_val, 3),
        median=round(median_val, 3),
        std_dev=round(std_val, 3),
        min=round(sorted_vals[0], 3),
        max=round(sorted_vals[-1], 3),
    )


def compute_mode_summary(mode: DetectionMode, trials: List[TrialResult]) -> ModeSummary:
    """Aggregate all metrics for a given detection mode."""
    mode_trials = [t for t in trials if t.detection_mode == mode]
    if not mode_trials:
        return ModeSummary(detection_mode=mode)

    total_trials = len(mode_trials)
    nominal_trials = [t for t in mode_trials if t.fault_type == EvaluatedFaultType.NOMINAL]
    fault_trials = [t for t in mode_trials if t.fault_type != EvaluatedFaultType.NOMINAL]

    num_nominal = len(nominal_trials)
    num_faults = len(fault_trials)

    false_positives = sum(1 for t in nominal_trials if t.is_false_positive or t.detected)
    fpr = (false_positives / num_nominal * 100.0) if num_nominal > 0 else 0.0

    detected_count = sum(1 for t in fault_trials if t.detected)
    detection_rate = (detected_count / num_faults * 100.0) if num_faults > 0 else 0.0

    recovery_count = sum(1 for t in fault_trials if t.recovery_success)
    recovery_attempts = sum(1 for t in fault_trials if t.recovery_executed)
    recovery_rate = (recovery_count / recovery_attempts * 100.0) if recovery_attempts > 0 else 0.0

    verification_count = sum(1 for t in fault_trials if t.verification_passed)
    verification_rate = (verification_count / num_faults * 100.0) if num_faults > 0 else 0.0

    guardrail_approvals = sum(1 for t in fault_trials if t.guardrail_approved)
    guardrail_approval_rate = (guardrail_approvals / num_faults * 100.0) if num_faults > 0 else 0.0
    guardrail_rejection_rate = 100.0 - guardrail_approval_rate if num_faults > 0 else 0.0

    duplicate_count = sum(1 for t in fault_trials if t.is_duplicate_suppressed)
    duplicate_rate = (duplicate_count / num_faults * 100.0) if num_faults > 0 else 0.0

    collateral = sum(t.collateral_impact for t in mode_trials)

    # Collect latencies across successful fault trials
    det_latencies = [t.detection_latency_ms for t in fault_trials if t.detection_latency_ms is not None]
    rec_latencies = [t.recovery_latency_ms for t in fault_trials if t.recovery_latency_ms is not None]
    tot_latencies = [t.total_recovery_time_s for t in fault_trials if t.total_recovery_time_s is not None]

    overall_det = compute_stats(det_latencies)
    overall_rec = compute_stats(rec_latencies)
    overall_tot = compute_stats(tot_latencies)

    # Per-fault breakdown
    by_fault_det: Dict[str, FaultMetricStats] = {}
    by_fault_tot: Dict[str, FaultMetricStats] = {}
    by_fault_rec_rate: Dict[str, float] = {}
    by_fault_ver_rate: Dict[str, float] = {}

    fault_categories = {t.fault_type.value for t in fault_trials}
    for f_cat in sorted(fault_categories):
        cat_trials = [t for t in fault_trials if t.fault_type.value == f_cat]
        c_det_l = [t.detection_latency_ms for t in cat_trials if t.detection_latency_ms is not None]
        c_tot_l = [t.total_recovery_time_s for t in cat_trials if t.total_recovery_time_s is not None]
        by_fault_det[f_cat] = compute_stats(c_det_l)
        by_fault_tot[f_cat] = compute_stats(c_tot_l)

        c_rec_ok = sum(1 for t in cat_trials if t.recovery_success)
        c_ver_ok = sum(1 for t in cat_trials if t.verification_passed)
        by_fault_rec_rate[f_cat] = round((c_rec_ok / len(cat_trials)) * 100.0, 1)
        by_fault_ver_rate[f_cat] = round((c_ver_ok / len(cat_trials)) * 100.0, 1)

    return ModeSummary(
        detection_mode=mode,
        total_trials=total_trials,
        fault_trials=num_faults,
        nominal_trials=num_nominal,
        false_positives=false_positives,
        false_positive_rate_percent=round(fpr, 2),
        detection_success_rate_percent=round(detection_rate, 2),
        recovery_success_rate_percent=round(recovery_rate, 2),
        verification_success_rate_percent=round(verification_rate, 2),
        guardrail_approval_rate_percent=round(guardrail_approval_rate, 2),
        guardrail_rejection_rate_percent=round(guardrail_rejection_rate, 2),
        duplicate_suppression_rate_percent=round(duplicate_rate, 2),
        total_collateral_impact=collateral,
        overall_detection_latency_ms=overall_det,
        overall_recovery_latency_ms=overall_rec,
        overall_total_recovery_time_s=overall_tot,
        by_fault_detection_latency_ms=by_fault_det,
        by_fault_total_recovery_time_s=by_fault_tot,
        by_fault_recovery_success_rate=by_fault_rec_rate,
        by_fault_verification_success_rate=by_fault_ver_rate,
    )
