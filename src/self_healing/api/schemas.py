"""Pydantic schemas and models for the FastAPI management backend."""

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field

from self_healing.core.models import (
    FaultStatus,
    IncidentRecord,
    IncidentStatus,
    ProcessMetrics,
    ServiceMetrics,
    SystemSnapshot,
    TargetSpec,
)
from self_healing.orchestrator import OrchestratorStats


class HealthResponse(BaseModel):
    """Health probe response model."""

    status: str = Field(default="healthy", description="Application health status")
    version: str = Field(description="Package version")
    timestamp: datetime = Field(description="Current UTC timestamp")
    dry_run: bool = Field(description="Whether dry-run mode is currently enabled")
    system: Dict[str, Any] = Field(description="Basic host system resource summary")
    registered_targets: int = Field(description="Count of supervised targets")


class DryRunRequest(BaseModel):
    """Payload to toggle or update dry-run execution mode."""

    dry_run: bool = Field(description="True to simulate recovery actions safely without OS mutation")


class DryRunResponse(BaseModel):
    """Response returned upon dry-run mode update."""

    dry_run: bool = Field(description="Current dry-run mode state")
    message: str = Field(description="Confirmation message")


class MonitoringControlRequest(BaseModel):
    """Payload to control orchestrator monitoring loop."""

    action: Literal["start", "stop", "tick"] = Field(
        description="Action to perform: 'start' continuous daemon, 'stop' daemon, or 'tick' once"
    )
    interval: Optional[float] = Field(
        default=None, description="Optional polling interval in seconds if starting"
    )


class MonitoringControlResponse(BaseModel):
    """Response returned upon orchestrator control command."""

    action: str = Field(description="Action requested")
    status: str = Field(description="Status message or outcome")
    is_running: bool = Field(description="Whether orchestrator is currently looping in background")
    ticks_completed: int = Field(description="Cumulative tick counter")
    incidents_handled: Optional[int] = Field(
        default=None, description="Number of incidents processed if single tick"
    )


class FaultStartRequest(BaseModel):
    """Optional tuning parameters for controlled demo fault injection."""

    intensity: Optional[int] = Field(default=None, description="Intensity level for CPU/memory faults")
    max_mb: Optional[int] = Field(default=None, description="Max write allocation limit in MB for disk faults")
    rate_mb_per_sec: Optional[float] = Field(
        default=None, description="Allocation write speed limit in MB/s"
    )


class RecoveryHistoryItem(BaseModel):
    """Normalized summary of a recorded recovery intervention."""

    incident_id: str = Field(description="Associated incident identifier")
    target_id: str = Field(description="Supervised target identifier")
    fault_type: str = Field(description="Detected fault classification")
    timestamp: datetime = Field(description="Incident initiation timestamp")
    completed_at: Optional[datetime] = Field(default=None, description="Incident completion timestamp")
    action_type: Optional[str] = Field(default=None, description="Allowlisted recovery action attempted")
    allowed_by_guardrails: bool = Field(description="Whether policy engine approved the action")
    recovery_success: bool = Field(description="Whether recovery executor reported success")
    verification_status: Optional[str] = Field(
        default=None, description="Post-recovery verification result status"
    )
    duration_ms: Optional[float] = Field(default=None, description="Recovery execution duration in ms")
    is_dry_run: bool = Field(description="Whether the recovery was simulated in dry-run mode")
    final_status: IncidentStatus = Field(description="Lifecycle final incident status")


class GuardrailsSummary(BaseModel):
    """Summary of active guardrail rules, policies, and allowlists."""

    enforce_target_allowlist: bool = Field(description="Enforcing target registry allowlist check")
    default_cooldown_seconds: float = Field(description="Minimum cooldown between actions on same target")
    flapping_window_seconds: float = Field(description="Window duration for flapping rate limits")
    max_actions_per_window: int = Field(description="Maximum recovery actions permitted within flapping window")
    allowed_action_types: List[str] = Field(description="Allowlisted typed recovery action identifiers")
    forbidden_process_names: List[str] = Field(description="Forbidden system process names that can never be touched")
    forbidden_directory_prefixes: List[str] = Field(
        description="Protected operating system directory prefixes"
    )
    recent_actions_count: int = Field(description="Total recent action events stored in memory")


class SystemStatusResponse(BaseModel):
    """Comprehensive system daemon status and stats response."""

    version: str = Field(description="Package version")
    mode: str = Field(description="System operational mode (development/production)")
    dry_run: bool = Field(description="Global dry-run setting")
    orchestrator_running: bool = Field(description="Whether orchestrator continuous loop is active")
    poll_interval_seconds: float = Field(description="Orchestrator polling interval in seconds")
    active_targets_count: int = Field(description="Number of supervised targets currently enabled")
    active_faults_count: int = Field(description="Number of in-flight faults currently being tracked")
    stats: OrchestratorStats = Field(description="Orchestrator cumulative telemetry statistics")
