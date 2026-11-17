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

async function fetchJson<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${url}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...options?.headers,
    },
  });

  if (!response.ok) {
    let detail = response.statusText;
    try {
      const err = await response.json();
      detail = err.detail || detail;
    } catch {
      // ignore
    }
    throw new Error(`API ${response.status}: ${detail}`);
  }

  return response.json();
}

export const api = {
  getHealth: () => fetchJson<HealthResponse>('/health'),
  getSystemStatus: () => fetchJson<SystemStatusResponse>('/system/status'),
  getMetrics: () => fetchJson<SystemSnapshot>('/metrics'),
  getProcesses: (targetId?: string) => 
    fetchJson<ProcessMetrics[]>(`/processes${targetId ? `?target_id=${encodeURIComponent(targetId)}` : ''}`),
  getServices: (service?: string) => 
    fetchJson<ServiceMetrics[]>(`/services${service ? `?service=${encodeURIComponent(service)}` : ''}`),
  getIncidents: (params?: { fault_type?: string; status?: string; limit?: number }) => {
    const query = new URLSearchParams();
    if (params?.fault_type) query.append('fault_type', params.fault_type);
    if (params?.status) query.append('status', params.status);
    if (params?.limit) query.append('limit', String(params.limit));
    return fetchJson<IncidentRecord[]>(`/incidents?${query.toString()}`);
  },
  getIncident: (id: string) => fetchJson<IncidentRecord>(`/incidents/${id}`),
  getGuardrails: () => fetchJson<GuardrailsSummary>('/guardrails'),

  setDryRun: (dryRun: boolean) => 
    fetchJson<{ dry_run: boolean; message: string }>('/system/dry-run', {
      method: 'POST',
      body: JSON.stringify({ dry_run: dryRun }),
    }),

  startFault: (faultType: string, intensity: number = 85.0) => 
    fetchJson<{ fault_type: string; is_active: boolean }>(`/faults/${encodeURIComponent(faultType)}/start`, {
      method: 'POST',
      body: JSON.stringify({ intensity }),
    }),

  stopFault: (faultType: string) => 
    fetchJson<{ fault_type: string; is_active: boolean }>(`/faults/${encodeURIComponent(faultType)}/stop`, {
      method: 'POST',
    }),

  controlMonitoring: (action: 'start' | 'stop' | 'tick', interval?: number) => 
    fetchJson<{ action: string; status: string; is_running: boolean; ticks_completed: number }>('/system/monitoring', {
      method: 'POST',
      body: JSON.stringify({ action, interval }),
    }),
};
