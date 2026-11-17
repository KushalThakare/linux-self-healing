import React from 'react';
import { Terminal, Layers } from 'lucide-react';
import { ProcessMetrics, ServiceMetrics } from '../types';

interface WorkloadTablesProps {
  processes: ProcessMetrics[];
  services: ServiceMetrics[];
}

function formatBytesMB(bytes: number): string {
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export const WorkloadTables: React.FC<WorkloadTablesProps> = ({ processes, services }) => {
  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
      {/* 5. Supervised Target Processes */}
      <div className="bg-surface border border-border rounded p-4 flex flex-col">
        <div className="flex items-center justify-between pb-3 border-b border-border">
          <div className="flex items-center gap-2">
            <Terminal className="w-4 h-4 text-charcoal-secondary" />
            <h2 className="text-sm font-semibold tracking-tight text-charcoal">
              Supervised Processes
            </h2>
          </div>
          <span className="text-xs font-mono text-charcoal-muted">
            {processes.length} active instances
          </span>
        </div>

        <div className="overflow-x-auto mt-3">
          <table className="w-full text-left text-xs font-mono">
            <thead>
              <tr className="border-b border-border text-charcoal-muted uppercase text-[10px] tracking-wider">
                <th className="py-2 pr-3">Target ID</th>
                <th className="py-2 pr-3">PID</th>
                <th className="py-2 pr-3 text-right">CPU %</th>
                <th className="py-2 pr-3 text-right">RSS</th>
                <th className="py-2 text-center">State</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {processes.length === 0 ? (
                <tr>
                  <td colSpan={5} className="py-6 text-center text-charcoal-muted font-sans text-xs">
                    No matching demo processes currently running.
                  </td>
                </tr>
              ) : (
                processes.map((proc) => {
                  const isHighCpu = proc.cpu_percent >= 80;
                  return (
                    <tr key={`${proc.pid}-${proc.target_id}`} className="hover:bg-surface-subtle transition-colors">
                      <td className="py-2.5 pr-3 font-semibold text-charcoal">
                        {proc.target_id || proc.name}
                      </td>
                      <td className="py-2.5 pr-3 text-charcoal-secondary">{proc.pid}</td>
                      <td className={`py-2.5 pr-3 text-right font-medium ${isHighCpu ? 'text-status-failed font-bold' : 'text-charcoal'}`}>
                        {proc.cpu_percent.toFixed(1)}%
                      </td>
                      <td className="py-2.5 pr-3 text-right text-charcoal-secondary">
                        {formatBytesMB(proc.rss_bytes)}
                      </td>
                      <td className="py-2.5 text-center">
                        <span className={`inline-block px-1.5 py-0.5 rounded text-[10px] font-semibold uppercase ${
                          proc.state === 'RUNNING'
                            ? 'text-status-success bg-status-success-bg border border-status-success-border'
                            : proc.state === 'DEAD'
                            ? 'text-status-failed bg-status-failed-bg border border-status-failed-border'
                            : 'text-charcoal-muted bg-surface-subtle border border-border'
                        }`}>
                          {proc.state}
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

      {/* 6. Supervised Systemd Services */}
      <div className="bg-surface border border-border rounded p-4 flex flex-col">
        <div className="flex items-center justify-between pb-3 border-b border-border">
          <div className="flex items-center gap-2">
            <Layers className="w-4 h-4 text-charcoal-secondary" />
            <h2 className="text-sm font-semibold tracking-tight text-charcoal">
              Supervised Services
            </h2>
          </div>
          <span className="text-xs font-mono text-charcoal-muted">
            {services.length} supervised units
          </span>
        </div>

        <div className="overflow-x-auto mt-3">
          <table className="w-full text-left text-xs font-mono">
            <thead>
              <tr className="border-b border-border text-charcoal-muted uppercase text-[10px] tracking-wider">
                <th className="py-2 pr-3">Service Unit</th>
                <th className="py-2 pr-3">Active State</th>
                <th className="py-2 pr-3">Substate</th>
                <th className="py-2 text-right">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {services.length === 0 ? (
                <tr>
                  <td colSpan={4} className="py-6 text-center text-charcoal-muted font-sans text-xs">
                    No supervised service units found.
                  </td>
                </tr>
              ) : (
                services.map((svc) => {
                  const isOk = svc.is_active && svc.active_state === 'active';
                  return (
                    <tr key={svc.service_name} className="hover:bg-surface-subtle transition-colors">
                      <td className="py-2.5 pr-3 font-semibold text-charcoal">
                        {svc.service_name}
                      </td>
                      <td className="py-2.5 pr-3 text-charcoal-secondary">
                        {svc.active_state}
                      </td>
                      <td className="py-2.5 pr-3 text-charcoal-muted">
                        {svc.sub_state}
                      </td>
                      <td className="py-2.5 text-right">
                        <span className={`inline-block px-1.5 py-0.5 rounded text-[10px] font-semibold uppercase ${
                          isOk
                            ? 'text-status-success bg-status-success-bg border border-status-success-border'
                            : 'text-status-failed bg-status-failed-bg border border-status-failed-border'
                        }`}>
                          {isOk ? 'ACTIVE' : 'INACTIVE'}
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
    </div>
  );
};
