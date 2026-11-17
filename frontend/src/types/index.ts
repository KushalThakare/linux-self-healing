export type IncidentStatus = 
  | 'DETECTED'
  | 'DIAGNOSED'
  | 'GUARDRAIL_EVALUATED'
  | 'POLICY_REJECTED'
  | 'RECOVERING'
  | 'RECOVERY_FAILED'
  | 'VERIFYING'
  | 'VERIFIED_SUCCESS'
  | 'VERIFIED_FAILED'
  | 'ESCALATED'
  | 'DRY_RUN';

export type PipelineStage = 'DETECTED' | 'DIAGNOSED' | 'GUARDRAIL' | 'RECOVERED' | 'VERIFIED';
export type StageStatus = 'SUCCESS' | 'FAILED' | 'REJECTED' | 'IN_PROGRESS' | 'PENDING';

export interface HealthResponse {
  status: string;
  version: string;
  timestamp: string;
  dry_run: boolean;
  system: {
    cpu_percent: number;
    memory_percent: number;
    memory_available_mb: number;
  };
  registered_targets: number;
}

export interface SystemStatusResponse {
  version: string;
  mode: string;
  dry_run: boolean;
  orchestrator_running: boolean;
  poll_interval_seconds: number;
  active_targets_count: number;
  active_faults_count: number;
  stats: {
    ticks_count: number;
    snapshots_collected: number;
    incidents_handled: number;
    recovery_actions_attempted: number;
    recovery_actions_succeeded: number;
    incidents_escalated: number;
    last_tick_at: string | null;
  };
}

export interface SystemCpuMetrics {
  percent: number;
  per_cpu_percent?: number[];
  load_1m?: number;
  load_5m?: number;
  load_15m?: number;
}

export interface SystemMemoryMetrics {
  total_bytes: number;
  available_bytes: number;
  used_bytes: number;
  free_bytes: number;
  percent: number;
  swap_total_bytes?: number;
  swap_used_bytes?: number;
  swap_percent?: number;
}

export interface DiskUsageMetrics {
  mount_point: string;
  total_bytes: number;
  used_bytes: number;
  free_bytes: number;
  percent: number;
}

export interface ProcessMetrics {
  pid: number;
  name: string;
  cpu_percent: number;
  rss_bytes: number;
  vms_bytes?: number;
  memory_percent?: number;
  num_threads?: number;
  num_fds?: number;
  state: string;
  cmdline: string[];
  target_id?: string;
}

export interface ServiceMetrics {
  service_name: string;
  is_active: boolean;
  active_state: string;
  sub_state: string;
  is_enabled?: boolean;
}

export interface SystemSnapshot {
  timestamp: string;
  uptime_seconds: number;
  cpu: SystemCpuMetrics;
  memory: SystemMemoryMetrics;
  disks: DiskUsageMetrics[];
  processes: ProcessMetrics[];
  services: ServiceMetrics[];
}

export interface FaultEvent {
  event_id: string;
  target_id: string;
  fault_type: string;
  severity: string;
  detected_at: string;
  triggering_value: number;
  threshold_value: number;
  description: string;
  evidence?: Record<string, any>;
}

export interface DiagnosisResult {
  diagnosis_id: string;
  event_id: string;
  fault_type: string;
  target_id: string;
  evidence: Record<string, any>;
  probable_cause: string;
  severity: string;
  confidence: number;
  recommended_action: string;
  traceability_log: string[];
}

export interface GuardrailDecision {
  decision_id: string;
  target_id: string;
  action_type: string;
  status: string;
  allowed: boolean;
  is_dry_run: boolean;
  risk_level: string;
  rejection_reason?: string;
  evaluated_at: string;
  check_breakdown?: Record<string, boolean>;
}

export interface RecoveryResult {
  action_id: string;
  action_type: string;
  target_id: string;
  success: boolean;
  dry_run: boolean;
  execution_latency_ms: number;
  pre_execution_state?: Record<string, any>;
  post_execution_state?: Record<string, any>;
  error_message?: string;
  started_at: string;
  completed_at: string;
}

export interface VerificationResult {
  incident_id: string;
  target_id: string;
  verified: boolean;
  status: string;
  checks_passed: string[];
  checks_failed: string[];
  evidence: Record<string, any>;
  verification_duration_ms: number;
  verified_at: string;
}

export interface IncidentRecord {
  incident_id: string;
  target_id: string;
  status: IncidentStatus;
  started_at: string;
  completed_at?: string;
  fault_event?: FaultEvent;
  diagnosis?: DiagnosisResult;
  policy_decision?: GuardrailDecision;
  recovery_result?: RecoveryResult;
  verification_result?: VerificationResult;
}

export interface GuardrailsSummary {
  enforce_target_allowlist: boolean;
  default_cooldown_seconds: number;
  flapping_window_seconds: number;
  max_actions_per_window: number;
  allowed_action_types: string[];
  forbidden_process_names: string[];
  forbidden_directory_prefixes: string[];
  recent_actions_count: number;
}
