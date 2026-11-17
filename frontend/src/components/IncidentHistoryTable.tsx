import React, { useState } from 'react';
import { History, Filter } from 'lucide-react';
import { IncidentRecord } from '../types';

interface IncidentHistoryTableProps {
  incidents: IncidentRecord[];
  selectedIncidentId: string | null;
  onSelectIncident: (incident: IncidentRecord) => void;
}

export const IncidentHistoryTable: React.FC<IncidentHistoryTableProps> = ({
  incidents,
  selectedIncidentId,
  onSelectIncident,
}) => {
  const [filterType, setFilterType] = useState<string>('ALL');

  const filteredIncidents = incidents.filter((inc) => {
    if (filterType === 'ALL') return true;
    if (filterType === 'ACTIVE') {
      return !['VERIFIED_SUCCESS', 'DRY_RUN', 'POLICY_REJECTED', 'ESCALATED'].includes(inc.status);
    }
    return inc.fault_event?.fault_type === filterType;
  });

  const activeIncidents = incidents.filter(
    (inc) => !['VERIFIED_SUCCESS', 'DRY_RUN', 'POLICY_REJECTED', 'ESCALATED'].includes(inc.status)
  );

  return (
    <div className="bg-surface border border-border rounded p-4 flex flex-col">
      {/* 7. Active Incidents Alert Banner if any active */}
      {activeIncidents.length > 0 && (
        <div className="mb-4 p-3 border border-status-rejected-border bg-status-rejected-bg rounded flex items-center justify-between">
          <div className="flex items-center gap-2 text-xs text-status-rejected font-medium">
            <span className="relative flex h-2 w-2">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-status-rejected opacity-75"></span>
              <span className="relative inline-flex rounded-full h-2 w-2 bg-status-rejected"></span>
            </span>
            <span>
              <strong>{activeIncidents.length} active incident(s)</strong> currently under autonomous closed-loop evaluation
            </span>
          </div>
          <button
            onClick={() => onSelectIncident(activeIncidents[0])}
            className="text-xs font-mono font-semibold text-status-rejected underline hover:opacity-80"
          >
            Inspect Active &rarr;
          </button>
        </div>
      )}

      {/* Header and Filter */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 pb-3 border-b border-border">
        <div className="flex items-center gap-2">
          <History className="w-4 h-4 text-charcoal-secondary" />
          <h2 className="text-sm font-semibold tracking-tight text-charcoal">
            Incident Lifecycles & Audit History
          </h2>
        </div>

        <div className="flex items-center gap-2 text-xs">
          <Filter className="w-3.5 h-3.5 text-charcoal-muted" />
          <select
            value={filterType}
            onChange={(e) => setFilterType(e.target.value)}
            className="bg-surface border border-border rounded px-2 py-1 text-xs font-mono text-charcoal focus:outline-none focus:border-accent"
          >
            <option value="ALL">Filter: All Incidents ({incidents.length})</option>
            <option value="ACTIVE">Filter: Active Loop In-Progress</option>
            <option value="HIGH_CPU">Filter: HIGH_CPU</option>
            <option value="MEMORY_LEAK">Filter: MEMORY_LEAK</option>
            <option value="STATISTICAL_ANOMALY">Filter: STATISTICAL_ANOMALY</option>
            <option value="DEADLOCK">Filter: DEADLOCK</option>
            <option value="DISK_GROWTH">Filter: DISK_GROWTH</option>
          </select>
        </div>
      </div>

      {/* Incident History Table */}
      <div className="overflow-x-auto mt-3">
        <table className="w-full text-left text-xs font-mono">
          <thead>
            <tr className="border-b border-border text-charcoal-muted uppercase text-[10px] tracking-wider">
              <th className="py-2 pr-3">Timestamp</th>
              <th className="py-2 pr-3">Target</th>
              <th className="py-2 pr-3">Fault Category</th>
              <th className="py-2 pr-3">Recommended Action</th>
              <th className="py-2 text-right">Outcome Status</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {filteredIncidents.length === 0 ? (
              <tr>
                <td colSpan={5} className="py-8 text-center text-charcoal-muted font-sans text-xs">
                  No incident records match the active filter criteria.
                </td>
              </tr>
            ) : (
              filteredIncidents.map((inc) => {
                const isSelected = inc.incident_id === selectedIncidentId;
                const faultName = inc.fault_event?.fault_type || 'UNKNOWN';
                const actionName = inc.diagnosis?.recommended_action || inc.recovery_result?.action_type || '—';
                const timeStr = new Date(inc.started_at).toLocaleTimeString();

                let statusBadge = 'text-charcoal-muted bg-surface-subtle border-border';
                if (inc.status === 'VERIFIED_SUCCESS' || inc.status === 'DRY_RUN') {
                  statusBadge = 'text-status-success bg-status-success-bg border-status-success-border';
                } else if (inc.status === 'POLICY_REJECTED') {
                  statusBadge = 'text-status-rejected bg-status-rejected-bg border-status-rejected-border';
                } else if (inc.status === 'RECOVERY_FAILED' || inc.status === 'ESCALATED') {
                  statusBadge = 'text-status-failed bg-status-failed-bg border-status-failed-border';
                } else {
                  statusBadge = 'text-status-progress bg-status-progress-bg border-status-progress-border';
                }

                return (
                  <tr
                    key={inc.incident_id}
                    onClick={() => onSelectIncident(inc)}
                    className={`cursor-pointer transition-colors ${
                      isSelected ? 'bg-accent-subtle/80 font-medium' : 'hover:bg-surface-subtle'
                    }`}
                  >
                    <td className="py-2.5 pr-3 text-charcoal-secondary">{timeStr}</td>
                    <td className="py-2.5 pr-3 font-semibold text-charcoal">{inc.target_id}</td>
                    <td className="py-2.5 pr-3 text-charcoal font-medium">
                      <span className="px-1.5 py-0.5 rounded text-[10px] border border-border bg-surface">
                        {faultName}
                      </span>
                    </td>
                    <td className="py-2.5 pr-3 text-charcoal-secondary truncate max-w-[180px]">
                      {actionName}
                    </td>
                    <td className="py-2.5 text-right">
                      <span className={`inline-block px-1.5 py-0.5 rounded text-[10px] font-semibold uppercase border ${statusBadge}`}>
                        {inc.status}
                      </span>
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
};
