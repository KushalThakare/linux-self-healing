"""Data models for automated experimental evaluation."""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class DetectionMode(str, Enum):
    """Detection engine paradigm under evaluation."""
    RULE_BASED = "RULE_BASED"
    RULE_PLUS_ISOLATION_FOREST = "RULE_PLUS_ISOLATION_FOREST"


class EvaluatedFaultType(str, Enum):
    """Fault conditions evaluated in the test harness."""
    NOMINAL = "nominal"
    CPU_RUNAWAY = "cpu"
    MEMORY_LEAK = "memory"
    SERVICE_CRASH = "service"
    DISK_EXHAUSTION = "disk"
    DEADLOCK = "deadlock"


class TrialResult(BaseModel):
    """Microsecond-precision execution record for a single experimental trial."""
    trial_id: str = Field(description="Unique UUID for this trial run")
    trial_index: int = Field(description="Repetition index (1..N)")
    detection_mode: DetectionMode = Field(description="Detection mode tested")
    fault_type: EvaluatedFaultType = Field(description="Fault condition injected")
    target_id: str = Field(description="Supervised demo target ID")
    timestamp_start: datetime = Field(description="Trial start UTC timestamp")
    timestamp_end: Optional[datetime] = Field(default=None, description="Trial end UTC timestamp")

    # High-resolution monotonic clock timestamps (seconds from time.perf_counter)
    t_healthy_start: float = Field(description="Healthy workload started")
    t_fault_inject: Optional[float] = Field(default=None, description="Fault injected")
    t_detect: Optional[float] = Field(default=None, description="Fault detected by engine")
    t_diagnose: Optional[float] = Field(default=None, description="Diagnosis completed")
    t_guardrail: Optional[float] = Field(default=None, description="Guardrail policy decided")
    t_heal_start: Optional[float] = Field(default=None, description="Recovery action dispatched")
    t_heal_end: Optional[float] = Field(default=None, description="Recovery action completed")
    t_verify: Optional[float] = Field(default=None, description="Verification probe finished")
    t_complete: float = Field(description="Full closed-loop cycle complete")

    # Core measured latencies
    detection_latency_ms: Optional[float] = Field(default=None, description="Time to detect in ms (t_detect - t_fault_inject)")
    recovery_latency_ms: Optional[float] = Field(default=None, description="Recovery action execution latency in ms")
    total_recovery_time_s: Optional[float] = Field(default=None, description="Total recovery time in seconds (t_complete - t_fault_inject)")

    # Lifecycle states & outcomes
    detected: bool = Field(default=False, description="Whether fault was detected")
    diagnosed: bool = Field(default=False, description="Whether root cause was diagnosed")
    guardrail_approved: bool = Field(default=False, description="Whether guardrail approved action")
    guardrail_status: str = Field(default="NONE", description="Guardrail status string")
    recovery_executed: bool = Field(default=False, description="Whether recovery action was executed")
    recovery_success: bool = Field(default=False, description="Whether recovery action succeeded")
    action_type: Optional[str] = Field(default=None, description="Allowlisted action type executed")
    verification_passed: bool = Field(default=False, description="Whether verification passed")
    verification_status: str = Field(default="NONE", description="Post-healing verification status")
    is_false_positive: bool = Field(default=False, description="Whether detection occurred during nominal workload")
    is_duplicate_suppressed: bool = Field(default=False, description="Whether duplicate in-flight fault was suppressed")
    collateral_impact: int = Field(default=0, description="Count of unintended non-target processes affected")
    incident_id: Optional[str] = Field(default=None, description="Persisted SQLite incident ID")
    error: Optional[str] = Field(default=None, description="Error message if trial encountered exception")


class FaultMetricStats(BaseModel):
    """Descriptive statistics for a metric across trials."""
    count: int = Field(default=0)
    mean: float = Field(default=0.0)
    median: float = Field(default=0.0)
    std_dev: float = Field(default=0.0)
    min: float = Field(default=0.0)
    max: float = Field(default=0.0)


class ModeSummary(BaseModel):
    """Aggregated evaluation summary for a specific detection mode."""
    detection_mode: DetectionMode
    total_trials: int = 0
    fault_trials: int = 0
    nominal_trials: int = 0
    false_positives: int = 0
    false_positive_rate_percent: float = 0.0
    detection_success_rate_percent: float = 0.0
    recovery_success_rate_percent: float = 0.0
    verification_success_rate_percent: float = 0.0
    guardrail_approval_rate_percent: float = 0.0
    guardrail_rejection_rate_percent: float = 0.0
    duplicate_suppression_rate_percent: float = 0.0
    total_collateral_impact: int = 0

    # Latency statistics
    overall_detection_latency_ms: FaultMetricStats = Field(default_factory=FaultMetricStats)
    overall_recovery_latency_ms: FaultMetricStats = Field(default_factory=FaultMetricStats)
    overall_total_recovery_time_s: FaultMetricStats = Field(default_factory=FaultMetricStats)

    # Per-fault breakdowns
    by_fault_detection_latency_ms: Dict[str, FaultMetricStats] = Field(default_factory=dict)
    by_fault_total_recovery_time_s: Dict[str, FaultMetricStats] = Field(default_factory=dict)
    by_fault_recovery_success_rate: Dict[str, float] = Field(default_factory=dict)
    by_fault_verification_success_rate: Dict[str, float] = Field(default_factory=dict)


class EvaluationSummary(BaseModel):
    """Comprehensive comparative evaluation summary."""
    started_at: datetime
    completed_at: datetime
    trials_per_fault: int
    rule_based_summary: ModeSummary
    hybrid_summary: ModeSummary
    comparison_notes: List[str] = Field(default_factory=list)
