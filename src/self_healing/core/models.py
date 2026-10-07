"""Core domain models and data contracts for the self-healing system.

All models are strictly typed using Pydantic v2 to ensure schema consistency
across the entire detection, diagnosis, policy, recovery, and verification loop.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, ConfigDict, Field


def utc_now() -> datetime:
    """Return current timestamp with UTC timezone."""
    return datetime.now(timezone.utc)


class FaultSeverity(str, Enum):
    """Severity levels for detected system or process faults."""
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class FaultType(str, Enum):
    """Deterministic fault categories detected by the system."""
    HIGH_CPU = "HIGH_CPU"
    MEMORY_LEAK = "MEMORY_LEAK"
    HUNG_PROCESS = "HUNG_PROCESS"
    PROCESS_CRASH = "PROCESS_CRASH"
    ZOMBIE_PROCESS = "ZOMBIE_PROCESS"
    FD_EXHAUSTION = "FD_EXHAUSTION"
    DISK_GROWTH = "DISK_GROWTH"
    DEADLOCK = "DEADLOCK"


class ActionType(str, Enum):
    """Allowlisted typed recovery actions supported by the system."""
    GRACEFUL_TERMINATE = "GRACEFUL_TERMINATE"
    FORCED_KILL = "FORCED_KILL"
    RESTART_SERVICE = "RESTART_SERVICE"
    RENICE_PROCESS = "RENICE_PROCESS"
    CLEAN_TEMP_DIR = "CLEAN_TEMP_DIR"


class VerificationStatus(str, Enum):
    """Outcomes of post-healing verification probes."""
    HEALTHY = "HEALTHY"
    FAILED = "FAILED"
    FLAPPING = "FLAPPING"
    TIMEOUT = "TIMEOUT"


class IncidentStatus(str, Enum):
    """Lifecycle status of an incident record."""
    DETECTED = "DETECTED"
    DIAGNOSED = "DIAGNOSED"
    POLICY_APPROVED = "POLICY_APPROVED"
    POLICY_REJECTED = "POLICY_REJECTED"
    EXECUTED = "EXECUTED"
    VERIFIED_SUCCESS = "VERIFIED_SUCCESS"
    VERIFICATION_FAILED = "VERIFICATION_FAILED"
    ESCALATED = "ESCALATED"


class ProcessState(str, Enum):
    """Canonical Linux process states."""
    RUNNING = "RUNNING"
    SLEEPING = "SLEEPING"
    DISK_SLEEP = "DISK_SLEEP"
    STOPPED = "STOPPED"
    ZOMBIE = "ZOMBIE"
    DEAD = "DEAD"
    IDLE = "IDLE"
    UNKNOWN = "UNKNOWN"


class SystemCpuMetrics(BaseModel):
    """Normalized global CPU utilization and scheduler metrics."""
    model_config = ConfigDict(frozen=True)

    percent: float = Field(..., ge=0.0, le=100.0, description="Overall CPU usage percentage")
    per_cpu_percent: List[float] = Field(default_factory=list, description="Per-core CPU usage percentages")
    load_1m: Optional[float] = Field(default=None, ge=0.0, description="1-minute load average from /proc/loadavg")
    load_5m: Optional[float] = Field(default=None, ge=0.0, description="5-minute load average from /proc/loadavg")
    load_15m: Optional[float] = Field(default=None, ge=0.0, description="15-minute load average from /proc/loadavg")
    context_switches: Optional[int] = Field(default=None, ge=0, description="Total context switches from /proc/stat")
    procs_running: Optional[int] = Field(default=None, ge=0, description="Runnable processes count from /proc/stat")
    procs_blocked: Optional[int] = Field(default=None, ge=0, description="Blocked/waiting processes from /proc/stat")


class SystemMemoryMetrics(BaseModel):
    """Normalized physical RAM and swap memory metrics."""
    model_config = ConfigDict(frozen=True)

    total_bytes: int = Field(..., ge=0, description="Total physical memory in bytes")
    available_bytes: int = Field(..., ge=0, description="Available memory for allocation without swapping")
    used_bytes: int = Field(..., ge=0, description="Used memory in bytes")
    free_bytes: int = Field(..., ge=0, description="Completely unallocated memory in bytes")
    percent: float = Field(..., ge=0.0, le=100.0, description="RAM utilization percentage")
    buffers_bytes: Optional[int] = Field(default=None, ge=0, description="Kernel buffer cache in bytes from /proc/meminfo")
    cached_bytes: Optional[int] = Field(default=None, ge=0, description="Page cache memory in bytes from /proc/meminfo")
    swap_total_bytes: Optional[int] = Field(default=None, ge=0, description="Total swap space in bytes")
    swap_used_bytes: Optional[int] = Field(default=None, ge=0, description="Used swap space in bytes")
    swap_percent: Optional[float] = Field(default=None, ge=0.0, le=100.0, description="Swap utilization percentage")


class DiskUsageMetrics(BaseModel):
    """Normalized filesystem storage metrics."""
    model_config = ConfigDict(frozen=True)

    mount_point: str = Field(..., description="Filesystem mount path (e.g. '/')")
    total_bytes: int = Field(..., ge=0, description="Total capacity in bytes")
    used_bytes: int = Field(..., ge=0, description="Used space in bytes")
    free_bytes: int = Field(..., ge=0, description="Free available space in bytes")
    percent: float = Field(..., ge=0.0, le=100.0, description="Filesystem usage percentage")


class ProcessMetrics(BaseModel):
    """Normalized process-level telemetry snapshot."""
    model_config = ConfigDict(frozen=True)

    pid: int = Field(..., gt=0, description="Process ID")
    name: str = Field(..., description="Process binary or task name")
    state: ProcessState = Field(default=ProcessState.UNKNOWN, description="Canonical process execution state")
    ppid: Optional[int] = Field(default=None, ge=0, description="Parent Process ID")
    cpu_percent: float = Field(default=0.0, ge=0.0, description="Process CPU usage percentage")
    rss_bytes: int = Field(default=0, ge=0, description="Resident Set Size memory in bytes")
    vms_bytes: Optional[int] = Field(default=None, ge=0, description="Virtual Memory Size in bytes")
    memory_percent: Optional[float] = Field(default=None, ge=0.0, le=100.0, description="Process memory percentage of host RAM")
    num_threads: Optional[int] = Field(default=None, ge=0, description="Thread count")
    num_fds: Optional[int] = Field(default=None, ge=0, description="Open file descriptors count")
    cmdline: List[str] = Field(default_factory=list, description="Process command line arguments")
    create_time: Optional[float] = Field(default=None, ge=0.0, description="Epoch timestamp of process creation")
    target_id: Optional[str] = Field(default=None, description="Associated TargetSpec ID if supervised")


class ServiceMetrics(BaseModel):
    """Normalized systemd service status."""
    model_config = ConfigDict(frozen=True)

    service_name: str = Field(..., description="Systemd unit name (e.g. 'nginx.service' or 'cron')")
    is_active: bool = Field(..., description="True if unit is in active state")
    active_state: str = Field(..., description="Active state string (e.g. 'active', 'inactive', 'failed')")
    sub_state: str = Field(..., description="Sub-state string (e.g. 'running', 'dead', 'exited')")
    is_enabled: Optional[bool] = Field(default=None, description="True if unit is enabled to start on boot")
    checked_at: datetime = Field(default_factory=utc_now, description="Timestamp of status inspection")


class SystemSnapshot(BaseModel):
    """Comprehensive point-in-time normalized system telemetry snapshot."""
    model_config = ConfigDict(frozen=True)

    timestamp: datetime = Field(default_factory=utc_now, description="Snapshot capture timestamp (UTC)")
    uptime_seconds: float = Field(..., ge=0.0, description="System uptime in seconds from /proc/uptime")
    idle_seconds: Optional[float] = Field(default=None, ge=0.0, description="Cumulative CPU idle seconds from /proc/uptime")
    cpu: SystemCpuMetrics = Field(..., description="Global CPU metrics")
    memory: SystemMemoryMetrics = Field(..., description="Global memory metrics")
    disks: List[DiskUsageMetrics] = Field(default_factory=list, description="Filesystem disk usage list")
    processes: List[ProcessMetrics] = Field(default_factory=list, description="Monitored processes list")
    services: List[ServiceMetrics] = Field(default_factory=list, description="Inspected systemd services list")


class MetricSnapshot(BaseModel):
    """Point-in-time telemetry snapshot of system and target metrics."""
    model_config = ConfigDict(frozen=True)

    timestamp: datetime = Field(default_factory=utc_now, description="Snapshot capture timestamp (UTC)")
    system_cpu_percent: float = Field(..., ge=0.0, le=100.0, description="Global CPU usage percentage")
    system_memory_percent: float = Field(..., ge=0.0, le=100.0, description="Global RAM usage percentage")
    uptime_seconds: Optional[float] = Field(default=None, ge=0.0, description="System uptime in seconds")
    target_id: Optional[str] = Field(default=None, description="Identifier of supervised target if applicable")
    target_pid: Optional[int] = Field(default=None, description="Operating system PID of target")
    target_cpu_percent: Optional[float] = Field(default=None, ge=0.0, description="Per-process CPU usage percentage")
    target_rss_bytes: Optional[int] = Field(default=None, ge=0, description="Per-process Resident Set Size (bytes)")
    target_num_threads: Optional[int] = Field(default=None, ge=0, description="Number of active process threads")
    target_num_fds: Optional[int] = Field(default=None, ge=0, description="Number of open file descriptors")
    target_state: Optional[ProcessState] = Field(default=None, description="Process execution state")
    cpu_details: Optional[SystemCpuMetrics] = Field(default=None, description="Detailed CPU telemetry")
    memory_details: Optional[SystemMemoryMetrics] = Field(default=None, description="Detailed memory telemetry")
    disks: List[DiskUsageMetrics] = Field(default_factory=list, description="Disk usage breakdown")
    services: List[ServiceMetrics] = Field(default_factory=list, description="Monitored service states")


class TargetSpec(BaseModel):
    """Specification of an approved demo process or service under supervision.
    
    Hard invariant: Only processes strictly conforming to an approved TargetSpec
    are allowed to be inspected or modified by the recovery system.
    """
    model_config = ConfigDict(frozen=True)

    target_id: str = Field(..., min_length=1, description="Unique target identifier (e.g., 'demo-web')")
    process_name: str = Field(..., min_length=1, description="Binary or executable name (e.g., 'python3')")
    cmdline_substring: str = Field(..., min_length=1, description="Must be present in /proc/[pid]/cmdline")
    expected_port: Optional[int] = Field(default=None, ge=1, le=65535, description="Expected listening TCP port")
    working_dir_prefix: str = Field(..., min_length=1, description="Approved workspace prefix where process runs")
    max_restarts_per_window: int = Field(default=3, ge=1, description="Max allowed recoveries before flapping lockout")
    cooldown_seconds: float = Field(default=30.0, ge=0.0, description="Mandatory quiet period between interventions")
    health_check_url: Optional[str] = Field(default=None, description="HTTP endpoint for active health probing")
    enabled: bool = Field(default=True, description="Whether this target is currently supervised")


class FaultEvent(BaseModel):
    """Event emitted when a deterministic detection rule triggers."""
    model_config = ConfigDict(frozen=True)

    event_id: str = Field(..., description="Unique event identifier (UUID)")
    target_id: str = Field(..., description="Affected target identifier")
    fault_type: FaultType = Field(..., description="Categorized fault type")
    severity: FaultSeverity = Field(..., description="Fault severity rating")
    detected_at: datetime = Field(default_factory=utc_now, description="Timestamp of fault detection")
    triggering_value: float = Field(..., description="Measured telemetry value that tripped threshold")
    threshold_value: float = Field(..., description="Configured threshold limit")
    description: str = Field(..., description="Human-readable description of the anomaly")


class DetectionEvent(FaultEvent):
    """Standardized event emitted by deterministic fault detectors with concrete evidence."""
    model_config = ConfigDict(frozen=True)

    evidence: Dict[str, Any] = Field(
        default_factory=dict,
        description="Structured telemetry evidence explaining why the detector fired",
    )


class DiagnosisReport(BaseModel):
    """Structured report produced by the root cause diagnosis engine."""
    model_config = ConfigDict(frozen=True)

    diagnosis_id: str = Field(..., description="Unique diagnosis identifier (UUID)")
    event_id: str = Field(..., description="Associated fault event ID")
    target_id: str = Field(..., description="Target evaluated")
    fault_type: FaultType = Field(..., description="Fault type analyzed")
    root_cause: str = Field(..., description="Inferred root cause explanation")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Diagnostic confidence score (0.0 - 1.0)")
    recommended_action: Union[ActionType, AllowedActionType, str] = Field(..., description="Proposed recovery action from typed registry")
    telemetry_window: List[MetricSnapshot] = Field(default_factory=list, description="Historical metric context")


class DiagnosisResult(BaseModel):
    """Deterministic, explainable diagnosis outcome based on forensic evidence."""
    model_config = ConfigDict(frozen=True)

    diagnosis_id: str = Field(..., description="Unique diagnosis identifier (UUID)")
    event_id: str = Field(..., description="Associated detection event ID")
    fault_type: FaultType = Field(..., description="Categorized fault type")
    target_id: str = Field(..., description="Affected demo target ID")
    evidence: Dict[str, Any] = Field(default_factory=dict, description="Recorded evidence from detection event and system metrics")
    probable_cause: str = Field(..., description="Deterministic, explainable root cause explanation")
    severity: FaultSeverity = Field(..., description="Severity level of the diagnosed fault")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Deterministic confidence score (0.0 to 1.0)")
    recommended_action: Union[ActionType, AllowedActionType, str] = Field(..., description="Recommended typed recovery action from allowlisted registry")
    traceability_log: List[str] = Field(default_factory=list, description="Step-by-step reasoning trail explaining how conclusion was derived")
    root_cause: Optional[str] = Field(default=None, description="Alias for probable_cause for backward compatibility")
    telemetry_window: List[MetricSnapshot] = Field(default_factory=list, description="Historical metric context")


class RiskLevel(str, Enum):
    """Risk rating for recovery interventions."""
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class AllowedActionType(str, Enum):
    """Explicit allowlist of permitted recovery actions."""
    RESTART_DEMO_SERVICE = "restart_demo_service"
    TERMINATE_DEMO_PROCESS = "terminate_demo_process"
    LOWER_DEMO_PROCESS_PRIORITY = "lower_demo_process_priority"
    CLEANUP_DEMO_LOGS = "cleanup_demo_logs"
    RESTART_DEMO_APPLICATION = "restart_demo_application"


class GuardrailStatus(str, Enum):
    """Explicit guardrail evaluation decision status."""
    APPROVED = "GUARDRAIL APPROVED"
    REJECTED = "GUARDRAIL REJECTED"


class RecoveryAction(BaseModel):
    """Typed specification for a proposed recovery remediation."""
    model_config = ConfigDict(frozen=True)

    action_id: str = Field(..., description="Unique action identifier (UUID)")
    action_type: AllowedActionType = Field(..., description="Allowlisted action type")
    target: str = Field(..., min_length=1, description="Target identifier (e.g. 'demo-cpu')")
    reason: str = Field(..., min_length=1, description="Diagnostic reason justifying this action")
    required_evidence: List[str] = Field(default_factory=list, description="List of required evidence keys that must be present")
    risk_level: RiskLevel = Field(default=RiskLevel.MEDIUM, description="Action operational risk rating")
    max_retries: int = Field(default=3, ge=1, description="Maximum permitted execution retry attempts")
    retry_count: int = Field(default=0, ge=0, description="Current retry attempt count")
    allowed_targets: List[str] = Field(default_factory=list, description="Approved target IDs permitted for this specific action")
    preconditions: List[str] = Field(default_factory=list, description="Prerequisite conditions required before execution")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Typed parameters for the recovery executor")


class PolicyDecision(BaseModel):
    """Gatekeeper evaluation token produced by the guardrail policy engine."""
    model_config = ConfigDict(frozen=True)

    decision_id: str = Field(..., description="Unique policy decision ID (UUID)")
    diagnosis_id: Optional[str] = Field(default=None, description="Associated diagnosis report ID")
    target_id: str = Field(..., description="Evaluated target ID")
    action_type: Union[ActionType, AllowedActionType] = Field(..., description="Evaluated action type")
    action_params: Dict[str, Any] = Field(default_factory=dict, description="Validated typed action parameters")
    allowed: bool = Field(..., description="Whether action is permitted to proceed")
    is_dry_run: bool = Field(default=False, description="Whether action will run in dry-run mode (simulation only)")
    rejection_reason: Optional[str] = Field(default=None, description="Explanation if action was rejected by guardrail")
    decided_at: datetime = Field(default_factory=utc_now, description="Timestamp of policy evaluation")


class GuardrailDecision(PolicyDecision):
    """Comprehensive policy gatekeeper decision outcome."""
    model_config = ConfigDict(frozen=True)

    status: GuardrailStatus = Field(..., description="Explicit decision status: GUARDRAIL APPROVED or GUARDRAIL REJECTED")
    action_id: str = Field(..., description="Associated RecoveryAction ID")
    violations: List[str] = Field(default_factory=list, description="List of security or policy violations detected")
    reasons: List[str] = Field(default_factory=list, description="Detailed explanatory reasons for decision")
    validation_details: Dict[str, bool] = Field(default_factory=dict, description="Detailed check breakdown across all 8 guardrail criteria")


class RecoveryResult(BaseModel):
    """Outcome of an allowlisted recovery action execution."""
    model_config = ConfigDict(frozen=True)

    action_id: str = Field(..., description="Unique recovery action identifier (UUID)")
    target_id: str = Field(..., description="Remediated target ID")
    action_type: Union[ActionType, AllowedActionType, str] = Field(..., description="Executed action type")
    executed_at: datetime = Field(default_factory=utc_now, description="Timestamp of execution")
    success: bool = Field(..., description="Whether the recovery action completed without error")
    dry_run: bool = Field(default=False, description="True if action was simulated without altering OS state")
    execution_latency_ms: float = Field(..., ge=0.0, description="Execution duration in milliseconds")
    output_message: str = Field(..., description="Execution summary or details")
    error: Optional[str] = Field(default=None, description="Error message if execution failed")
    details: Dict[str, Any] = Field(default_factory=dict, description="Detailed execution telemetry or metadata")


class VerificationResult(BaseModel):
    """Outcome of closed-loop verification probes following remediation."""
    model_config = ConfigDict(frozen=True)

    verification_id: str = Field(..., description="Unique verification identifier (UUID)")
    incident_id: str = Field(..., description="Associated incident ID")
    target_id: str = Field(..., description="Target verified")
    status: VerificationStatus = Field(..., description="Overall verification outcome")
    verified_at: datetime = Field(default_factory=utc_now, description="Timestamp of verification")
    checks_passed: List[str] = Field(default_factory=list, description="List of successful health check names")
    checks_failed: List[str] = Field(default_factory=list, description="List of failed health check names")
    details: str = Field(default="", description="Detailed probe diagnostic summary")


class IncidentRecord(BaseModel):
    """Immutable audit record tracing the entire closed-loop lifecycle."""
    incident_id: str = Field(..., description="Unique incident identifier (UUID)")
    target_id: str = Field(..., description="Affected target ID")
    started_at: datetime = Field(default_factory=utc_now, description="Incident start timestamp")
    completed_at: Optional[datetime] = Field(default=None, description="Incident completion timestamp")
    status: IncidentStatus = Field(default=IncidentStatus.DETECTED, description="Current incident lifecycle status")
    fault_event: FaultEvent = Field(..., description="Initial triggering fault event")
    diagnosis: Optional[Union[DiagnosisResult, DiagnosisReport]] = Field(default=None, description="Diagnostic report or result")
    policy_decision: Optional[PolicyDecision] = Field(default=None, description="Guardrail evaluation decision")
    recovery_result: Optional[RecoveryResult] = Field(default=None, description="Recovery execution record")
    verification_result: Optional[VerificationResult] = Field(default=None, description="Post-healing verification")


class FaultStatus(BaseModel):
    """Standardized runtime status of a fault injection demo."""
    model_config = ConfigDict(frozen=True)

    fault_name: str = Field(..., description="Name of the fault (e.g. 'cpu', 'memory')")
    target_id: str = Field(..., description="Target identifier (e.g. 'demo-cpu')")
    is_running: bool = Field(..., description="Whether demo fault workload process is actively running")
    pid: Optional[int] = Field(default=None, description="Operating system PID of demo target process")
    metrics: Dict[str, Any] = Field(default_factory=dict, description="Live telemetry metrics for the target")
    details: str = Field(default="", description="Human-readable status summary or explanation")

