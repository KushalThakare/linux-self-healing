"""Automated Experimental Evaluation Subsystem."""

from self_healing.evaluation.harness import EvaluationHarness
from self_healing.evaluation.metrics import compute_mode_summary
from self_healing.evaluation.models import (
    DetectionMode,
    EvaluatedFaultType,
    EvaluationSummary,
    ModeSummary,
    TrialResult,
)
from self_healing.evaluation.plots import generate_all_plots

__all__ = [
    "EvaluationHarness",
    "compute_mode_summary",
    "DetectionMode",
    "EvaluatedFaultType",
    "EvaluationSummary",
    "ModeSummary",
    "TrialResult",
    "generate_all_plots",
]
