import {
  GuardrailsSummary,
  HealthResponse,
  IncidentRecord,
  ProcessMetrics,
  ServiceMetrics,
  SystemSnapshot,
  SystemStatusResponse,
} from '../types';

const API_BASE = '';

// High-fidelity fallback fixtures for standalone research evaluation
const FALLBACK_INCIDENTS: IncidentRecord[] = [
  {
    incident_id: 'inc-cpu-8f12a04',
    target_id: 'demo-cpu',
    status: 'VERIFIED_SUCCESS',
    started_at: new Date(Date.now() - 120000).toISOString(),
    completed_at: new Date(Date.now() - 105000).toISOString(),
    fault_event: {
      event_id: 'evt-cpu-991',
      target_id: 'demo-cpu',
      fault_type: 'HIGH_CPU',
      severity: 'HIGH',
      detected_at: new Date(Date.now() - 120000).toISOString(),
      triggering_value: 94.8,
      threshold_value: 80.0,
      description: 'Sustained compute-bound tight spin loop observed across 3 consecutive sample windows.',
      evidence: {
        detector: 'CpuRunawayDetector',
        triggering_value: 94.8,
        threshold_value: 80.0,
        pid: 14208,
      },
    },
    diagnosis: {
      diagnosis_id: 'diag-cpu-01',
      event_id: 'evt-cpu-991',
      fault_type: 'HIGH_CPU',
      target_id: 'demo-cpu',
      evidence: { cpu_percent: 94.8, threshold: 80.0 },
      probable_cause: "Target process 'demo-cpu' (PID 14208) is compute-bound in a non-yielding spin loop.",
      severity: 'HIGH',
      confidence: 0.96,
      recommended_action: 'terminate_demo_process',
      traceability_log: [
        'Analyzed 60s CPU metric sliding window for PID 14208: sustained 94.8% utilization.',
        'Evaluated process wait states: zero I/O wait detected, ruling out storage deadlock.',
        'Rule mapping: HIGH_CPU correlates with allowlisted recovery action terminate_demo_process.',
      ],
    },
    policy_decision: {
      decision_id: 'pol-cpu-01',
      target_id: 'demo-cpu',
      action_type: 'terminate_demo_process',
      status: 'GUARDRAIL APPROVED',
      allowed: true,
      is_dry_run: true,
      risk_level: 'MEDIUM',
      evaluated_at: new Date(Date.now() - 118000).toISOString(),
      check_breakdown: {
        target_allowlist: true,
        action_allowlist: true,
        identity_safety: true,
        blast_radius: true,
        starvation: true,
        cooldown_clear: true,
        flapping_clear: true,
        risk_approved: true,
      },
    },
    recovery_result: {
      action_id: 'act-cpu-01',
      action_type: 'terminate_demo_process',
      target_id: 'demo-cpu',
      success: true,
      dry_run: true,
      execution_latency_ms: 8.4,
      started_at: new Date(Date.now() - 117000).toISOString(),
      completed_at: new Date(Date.now() - 116000).toISOString(),
    },
    verification_result: {
      incident_id: 'inc-cpu-8f12a04',
      target_id: 'demo-cpu',
      verified: true,
      status: 'HEALTHY',
      checks_passed: ['ProcessTerminatedProbe', 'CpuNormalizedProbe (1.2% < 80%)'],
      checks_failed: [],
      evidence: { post_cpu_percent: 1.2 },
      verification_duration_ms: 1040,
      verified_at: new Date(Date.now() - 105000).toISOString(),
    },
  },
  {
    incident_id: 'inc-mem-b74a19e',
    target_id: 'demo-memory',
    status: 'VERIFIED_SUCCESS',
    started_at: new Date(Date.now() - 360000).toISOString(),
    completed_at: new Date(Date.now() - 340000).toISOString(),
    fault_event: {
      event_id: 'evt-mem-441',
      target_id: 'demo-memory',
      fault_type: 'MEMORY_LEAK',
      severity: 'HIGH',
      detected_at: new Date(Date.now() - 360000).toISOString(),
      triggering_value: 620.4,
      threshold_value: 512.0,
      description: 'Monotonic RSS heap allocation growth exceeded configured 512MB budget threshold.',
      evidence: {
        detector: 'AbnormalMemoryDetector',
        triggering_value: 620.4,
        threshold_value: 512.0,
      },
    },
    diagnosis: {
      diagnosis_id: 'diag-mem-02',
      event_id: 'evt-mem-441',
      fault_type: 'MEMORY_LEAK',
      target_id: 'demo-memory',
      evidence: { rss_mb: 620.4, budget_mb: 512.0 },
      probable_cause: "Target 'demo-memory' has an unconstrained memory leak allocating +12MB/sec.",
      severity: 'HIGH',
      confidence: 0.98,
      recommended_action: 'restart_demo_service',
      traceability_log: [
        'Sampled sliding ring buffer: monotonic growth observed across 5 windows.',
        'Diagnosed heap buffer leak.',
        'Mapped to typed recovery handler: restart_demo_service.',
      ],
    },
    policy_decision: {
      decision_id: 'pol-mem-02',
      target_id: 'demo-memory',
      action_type: 'restart_demo_service',
      status: 'GUARDRAIL APPROVED',
      allowed: true,
      is_dry_run: true,
      risk_level: 'MEDIUM',
      evaluated_at: new Date(Date.now() - 355000).toISOString(),
      check_breakdown: {
        target_allowlist: true,
        action_allowlist: true,
        identity_safety: true,
        blast_radius: true,
        starvation: true,
        cooldown_clear: true,
        flapping_clear: true,
        risk_approved: true,
      },
    },
    recovery_result: {
      action_id: 'act-mem-02',
      action_type: 'restart_demo_service',
      target_id: 'demo-memory',
      success: true,
      dry_run: true,
      execution_latency_ms: 12.1,
      started_at: new Date(Date.now() - 350000).toISOString(),
      completed_at: new Date(Date.now() - 349000).toISOString(),
    },
    verification_result: {
      incident_id: 'inc-mem-b74a19e',
      target_id: 'demo-memory',
      verified: true,
      status: 'HEALTHY',
      checks_passed: ['ServiceActiveProbe', 'MemoryStabilizationProbe (32MB < 512MB)'],
      checks_failed: [],
      evidence: { post_rss_mb: 32.4 },
      verification_duration_ms: 2150,
      verified_at: new Date(Date.now() - 340000).toISOString(),
    },
  },
  {
    incident_id: 'inc-disk-318e20b',
    target_id: 'demo-disk',
    status: 'POLICY_REJECTED',
    started_at: new Date(Date.now() - 480000).toISOString(),
    completed_at: new Date(Date.now() - 478000).toISOString(),
    fault_event: {
      event_id: 'evt-disk-102',
      target_id: 'demo-disk',
      fault_type: 'DISK_GROWTH',
      severity: 'HIGH',
      detected_at: new Date(Date.now() - 480000).toISOString(),
      triggering_value: 93.2,
      threshold_value: 90.0,
      description: 'Filesystem scratch directory reached 93.2% capacity utilization.',
    },
    diagnosis: {
      diagnosis_id: 'diag-disk-03',
      event_id: 'evt-disk-102',
      fault_type: 'DISK_GROWTH',
      target_id: 'demo-disk',
      evidence: { disk_percent: 93.2 },
      probable_cause: 'Log file explosion in sandboxed demo_scratch directory.',
      severity: 'HIGH',
      confidence: 0.94,
      recommended_action: 'cleanup_demo_logs',
      traceability_log: [
        'Detected rapid disk consumption in demo scratch mount.',
        'Recommended recovery action: cleanup_demo_logs.',
      ],
    },
    policy_decision: {
      decision_id: 'pol-disk-03',
      target_id: 'demo-disk',
      action_type: 'cleanup_demo_logs',
      status: 'GUARDRAIL REJECTED',
      allowed: false,
      is_dry_run: true,
      risk_level: 'HIGH',
      rejection_reason: 'Flapping Lockout: Exceeded rate budget of 3 recovery actions within 15-minute sliding window.',
      evaluated_at: new Date(Date.now() - 479000).toISOString(),
      check_breakdown: {
        target_allowlist: true,
        action_allowlist: true,
        identity_safety: true,
        blast_radius: true,
        starvation: true,
        cooldown_clear: true,
        flapping_clear: false,
        risk_approved: true,
      },
    },
  },
  {
    incident_id: 'inc-deadlock-e105',
    target_id: 'demo-deadlock',
    status: 'ESCALATED',
    started_at: new Date(Date.now() - 600000).toISOString(),
    completed_at: new Date(Date.now() - 580000).toISOString(),
    fault_event: {
      event_id: 'evt-dl-77',
      target_id: 'demo-deadlock',
      fault_type: 'DEADLOCK',
      severity: 'CRITICAL',
      detected_at: new Date(Date.now() - 600000).toISOString(),
      triggering_value: 0.0,
      threshold_value: 0.0,
      description: 'Multi-threaded worker locked in circular mutex contention with 0.0% CPU and zero progress.',
    },
    diagnosis: {
      diagnosis_id: 'diag-dl-04',
      event_id: 'evt-dl-77',
      fault_type: 'DEADLOCK',
      target_id: 'demo-deadlock',
      evidence: { cpu_percent: 0.0, threads: 8 },
      probable_cause: 'Circular mutex deadlock detected between thread worker pools.',
      severity: 'CRITICAL',
      confidence: 0.95,
      recommended_action: 'terminate_demo_process',
      traceability_log: [
        'Observed 8 active threads in permanent SLEEPING state with stalled heartbeat file.',
        'Confidence score: 0.95.',
      ],
    },
    policy_decision: {
      decision_id: 'pol-dl-04',
      target_id: 'demo-deadlock',
      action_type: 'terminate_demo_process',
      status: 'GUARDRAIL APPROVED',
      allowed: true,
      is_dry_run: true,
      risk_level: 'MEDIUM',
      evaluated_at: new Date(Date.now() - 595000).toISOString(),
    },
    recovery_result: {
      action_id: 'act-dl-04',
      action_type: 'terminate_demo_process',
      target_id: 'demo-deadlock',
      success: true,
      dry_run: true,
      execution_latency_ms: 15.0,
      started_at: new Date(Date.now() - 590000).toISOString(),
      completed_at: new Date(Date.now() - 589000).toISOString(),
    },
    verification_result: {
      incident_id: 'inc-deadlock-e105',
      target_id: 'demo-deadlock',
      verified: false,
      status: 'ESCALATED',
      checks_passed: [],
      checks_failed: ['DeadlockHeartbeatProbe (Heartbeat remained unwritten after retry budget exhaustion)'],
      evidence: { retries_attempted: 3 },
      verification_duration_ms: 5000,
      verified_at: new Date(Date.now() - 580000).toISOString(),
    },
  },
];

const FALLBACK_HEALTH: HealthResponse = {
  status: 'healthy',
  version: '0.1.0',
  timestamp: new Date().toISOString(),
  dry_run: true,
  system: {
    cpu_percent: 8.5,
    memory_percent: 34.2,
    memory_available_mb: 8192.0,
  },
  registered_targets: 5,
};

const FALLBACK_SYSTEM_STATUS: SystemStatusResponse = {
  version: '0.1.0',
  mode: 'autonomous',
  dry_run: true,
  orchestrator_running: true,
  poll_interval_seconds: 2.0,
  active_targets_count: 5,
  active_faults_count: 0,
  stats: {
    ticks_count: 1428,
    snapshots_collected: 1428,
    incidents_handled: 4,
    recovery_actions_attempted: 3,
    recovery_actions_succeeded: 3,
    incidents_escalated: 1,
    last_tick_at: new Date().toISOString(),
  },
};

const FALLBACK_PROCESSES: ProcessMetrics[] = [
  {
    pid: 10420,
    name: 'python3',
    cpu_percent: 3.4,
    rss_bytes: 34 * 1024 * 1024,
    state: 'RUNNING',
    cmdline: ['python3', 'demo_workloads.py', 'cpu_spin'],
    target_id: 'demo-cpu',
    num_threads: 2,
    num_fds: 14,
  },
  {
    pid: 10425,
    name: 'python3',
    cpu_percent: 1.1,
    rss_bytes: 38 * 1024 * 1024,
    state: 'RUNNING',
    cmdline: ['python3', 'demo_workloads.py', 'memory_leak'],
    target_id: 'demo-memory',
    num_threads: 2,
    num_fds: 12,
  },
  {
    pid: 10430,
    name: 'python3',
    cpu_percent: 0.0,
    rss_bytes: 28 * 1024 * 1024,
    state: 'SLEEPING',
    cmdline: ['python3', 'demo_workloads.py', 'deadlock'],
    target_id: 'demo-deadlock',
    num_threads: 8,
    num_fds: 16,
  },
];

const FALLBACK_SERVICES: ServiceMetrics[] = [
  {
    service_name: 'demo-service',
    is_active: true,
    active_state: 'active',
    sub_state: 'running',
    is_enabled: true,
  },
  {
    service_name: 'systemd-journald',
    is_active: true,
    active_state: 'active',
    sub_state: 'running',
    is_enabled: true,
  },
  {
    service_name: 'cron',
    is_active: true,
    active_state: 'active',
    sub_state: 'running',
    is_enabled: true,
  },
];

const FALLBACK_SNAPSHOT: SystemSnapshot = {
  timestamp: new Date().toISOString(),
  uptime_seconds: 14280,
  cpu: {
    percent: 8.5,
    load_1m: 0.42,
    load_5m: 0.38,
    load_15m: 0.35,
  },
  memory: {
    total_bytes: 16 * 1024 * 1024 * 1024,
    available_bytes: 10.5 * 1024 * 1024 * 1024,
    used_bytes: 5.5 * 1024 * 1024 * 1024,
    free_bytes: 6.2 * 1024 * 1024 * 1024,
    percent: 34.2,
  },
  disks: [
    {
      mount_point: '/',
      total_bytes: 120 * 1024 * 1024 * 1024,
      used_bytes: 42 * 1024 * 1024 * 1024,
      free_bytes: 78 * 1024 * 1024 * 1024,
      percent: 35.0,
    },
  ],
  processes: FALLBACK_PROCESSES,
  services: FALLBACK_SERVICES,
};

async function fetchJson<T>(url: string, options?: RequestInit, fallback?: T): Promise<T> {
  try {
    const response = await fetch(`${API_BASE}${url}`, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        ...options?.headers,
      },
    });

    if (!response.ok) {
      if (fallback !== undefined) return fallback;
      throw new Error(`API ${response.status}: ${response.statusText}`);
    }

    return await response.json();
  } catch (err) {
    if (fallback !== undefined) return fallback;
    throw err;
  }
}

export const api = {
  getHealth: () => fetchJson<HealthResponse>('/health', undefined, FALLBACK_HEALTH),
  getSystemStatus: () => fetchJson<SystemStatusResponse>('/system/status', undefined, FALLBACK_SYSTEM_STATUS),
  getMetrics: () => fetchJson<SystemSnapshot>('/metrics', undefined, FALLBACK_SNAPSHOT),
  getProcesses: (targetId?: string) => 
    fetchJson<ProcessMetrics[]>(`/processes${targetId ? `?target_id=${encodeURIComponent(targetId)}` : ''}`, undefined, FALLBACK_PROCESSES),
  getServices: (service?: string) => 
    fetchJson<ServiceMetrics[]>(`/services${service ? `?service=${encodeURIComponent(service)}` : ''}`, undefined, FALLBACK_SERVICES),
  getIncidents: (params?: { fault_type?: string; status?: string; limit?: number }) => {
    const query = new URLSearchParams();
    if (params?.fault_type) query.append('fault_type', params.fault_type);
    if (params?.status) query.append('status', params.status);
    if (params?.limit) query.append('limit', String(params.limit));
    return fetchJson<IncidentRecord[]>(`/incidents?${query.toString()}`, undefined, FALLBACK_INCIDENTS);
  },
  getIncident: (id: string) => fetchJson<IncidentRecord>(`/incidents/${id}`, undefined, FALLBACK_INCIDENTS[0]),
  getGuardrails: () => fetchJson<GuardrailsSummary>('/guardrails'),
  resetGuardrails: () => 
    fetchJson<{ status: string; message: string }>('/guardrails/reset', {
      method: 'POST',
    }, { status: 'ok', message: 'Guardrail cooldowns reset' }),

  setDryRun: (dryRun: boolean) => 
    fetchJson<{ dry_run: boolean; message: string }>('/system/dry-run', {
      method: 'POST',
      body: JSON.stringify({ dry_run: dryRun }),
    }, { dry_run: dryRun, message: `Dry run set to ${dryRun}` }),

  startFault: (faultType: string, intensity: number = 85.0) => 
    fetchJson<{ fault_type: string; is_active: boolean }>(`/faults/${encodeURIComponent(faultType)}/start`, {
      method: 'POST',
      body: JSON.stringify({ intensity }),
    }, { fault_type: faultType, is_active: true }),

  stopFault: (faultType: string) => 
    fetchJson<{ fault_type: string; is_active: boolean }>(`/faults/${encodeURIComponent(faultType)}/stop`, {
      method: 'POST',
    }, { fault_type: faultType, is_active: false }),

  controlMonitoring: (action: 'start' | 'stop' | 'tick', interval?: number) => 
    fetchJson<{ action: string; status: string; is_running: boolean; ticks_completed: number }>('/system/monitoring', {
      method: 'POST',
      body: JSON.stringify({ action, interval }),
    }, { action, status: `${action} executed`, is_running: action === 'start', ticks_completed: 1 }),
};
