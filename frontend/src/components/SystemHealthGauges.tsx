import React from 'react';
import { Cpu, HardDrive, Database, CheckCircle2, Clock } from 'lucide-react';
import { HealthResponse, SystemSnapshot, SystemStatusResponse } from '../types';

interface SystemHealthGaugesProps {
  health: HealthResponse | null;
  status: SystemStatusResponse | null;
  metrics: SystemSnapshot | null;
}

function formatBytes(bytes: number): string {
  if (bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`;
}

function formatUptime(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  return `${h}h ${m}m ${s}s`;
}

export const SystemHealthGauges: React.FC<SystemHealthGaugesProps> = ({
  health,
  status,
  metrics,
}) => {
  const cpuPercent = metrics?.cpu?.percent ?? health?.system?.cpu_percent ?? 0;
  const memPercent = metrics?.memory?.percent ?? health?.system?.memory_percent ?? 0;
  const disk = metrics?.disks?.[0];
  const diskPercent = disk?.percent ?? 0;

  const uptimeStr = metrics?.uptime_seconds ? formatUptime(metrics.uptime_seconds) : '—';
  const targetsCount = status?.active_targets_count ?? health?.registered_targets ?? 0;
  const activeFaults = status?.active_faults_count ?? 0;

  return (
    <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
      {/* 1. System Health Status Card */}
      <div className="bg-surface border border-border rounded p-4 flex flex-col justify-between">
        <div>
          <div className="flex items-center justify-between text-xs text-charcoal-muted uppercase tracking-wider font-medium">
            <span>System Health</span>
            <CheckCircle2 className="w-4 h-4 text-status-success" />
          </div>
          <div className="mt-2 flex items-baseline gap-2">
            <span className="text-2xl font-bold font-mono tracking-tight text-charcoal">
              {health?.status?.toUpperCase() || 'ONLINE'}
            </span>
            <span className="text-xs px-1.5 py-0.5 rounded font-mono text-status-success bg-status-success-bg border border-status-success-border">
              NORMAL
            </span>
          </div>
        </div>

        <div className="mt-4 pt-3 border-t border-border flex items-center justify-between text-xs text-charcoal-secondary font-mono">
          <div className="flex items-center gap-1.5">
            <Clock className="w-3.5 h-3.5 text-charcoal-muted" />
            <span>{uptimeStr}</span>
          </div>
          <span className="text-charcoal-muted">
            {targetsCount} targets {activeFaults > 0 ? `(${activeFaults} active)` : ''}
          </span>
        </div>
      </div>

      {/* 2. CPU Utilization Gauge */}
      <div className="bg-surface border border-border rounded p-4 flex flex-col justify-between">
        <div>
          <div className="flex items-center justify-between text-xs text-charcoal-muted uppercase tracking-wider font-medium">
            <span>CPU Utilization</span>
            <Cpu className="w-4 h-4 text-charcoal-secondary" />
          </div>
          <div className="mt-2 flex items-baseline justify-between">
            <span className="text-2xl font-bold font-mono tracking-tight text-charcoal">
              {cpuPercent.toFixed(1)}%
            </span>
            <span className="text-xs text-charcoal-muted font-mono">
              Threshold: 80.0%
            </span>
          </div>

          {/* Bar with threshold marker */}
          <div className="mt-2 relative w-full h-2 bg-surface-subtle rounded overflow-hidden">
            <div
              className={`h-full transition-all duration-500 ${
                cpuPercent >= 80 ? 'bg-status-failed' : 'bg-charcoal'
              }`}
              style={{ width: `${Math.min(cpuPercent, 100)}%` }}
            />
            {/* 80% threshold line indicator */}
            <div
              className="absolute top-0 bottom-0 w-0.5 bg-status-rejected"
              style={{ left: '80%' }}
              title="Deterministic Rule Threshold (80%)"
            />
          </div>
        </div>

        <div className="mt-4 pt-3 border-t border-border flex items-center justify-between text-xs text-charcoal-secondary font-mono">
          <span>Load Avg:</span>
          <span>
            {metrics?.cpu?.load_1m?.toFixed(2) ?? '0.00'} / {metrics?.cpu?.load_5m?.toFixed(2) ?? '0.00'}
          </span>
        </div>
      </div>

      {/* 3. Memory Utilization Gauge */}
      <div className="bg-surface border border-border rounded p-4 flex flex-col justify-between">
        <div>
          <div className="flex items-center justify-between text-xs text-charcoal-muted uppercase tracking-wider font-medium">
            <span>RAM Utilization</span>
            <Database className="w-4 h-4 text-charcoal-secondary" />
          </div>
          <div className="mt-2 flex items-baseline justify-between">
            <span className="text-2xl font-bold font-mono tracking-tight text-charcoal">
              {memPercent.toFixed(1)}%
            </span>
            <span className="text-xs text-charcoal-muted font-mono">
              {health?.system?.memory_available_mb
                ? `${health.system.memory_available_mb} MB avail`
                : ''}
            </span>
          </div>

          <div className="mt-2 w-full h-2 bg-surface-subtle rounded overflow-hidden">
            <div
              className={`h-full transition-all duration-500 ${
                memPercent >= 85 ? 'bg-status-failed' : 'bg-charcoal'
              }`}
              style={{ width: `${Math.min(memPercent, 100)}%` }}
            />
          </div>
        </div>

        <div className="mt-4 pt-3 border-t border-border flex items-center justify-between text-xs text-charcoal-secondary font-mono">
          <span>Used / Total:</span>
          <span>
            {metrics?.memory
              ? `${formatBytes(metrics.memory.used_bytes)} / ${formatBytes(metrics.memory.total_bytes)}`
              : '—'}
          </span>
        </div>
      </div>

      {/* 4. Filesystem Storage Gauge */}
      <div className="bg-surface border border-border rounded p-4 flex flex-col justify-between">
        <div>
          <div className="flex items-center justify-between text-xs text-charcoal-muted uppercase tracking-wider font-medium">
            <span>Disk Storage</span>
            <HardDrive className="w-4 h-4 text-charcoal-secondary" />
          </div>
          <div className="mt-2 flex items-baseline justify-between">
            <span className="text-2xl font-bold font-mono tracking-tight text-charcoal">
              {diskPercent.toFixed(1)}%
            </span>
            <span className="text-xs text-charcoal-muted font-mono">
              Mount: {disk?.mount_point || '/'}
            </span>
          </div>

          <div className="mt-2 w-full h-2 bg-surface-subtle rounded overflow-hidden">
            <div
              className={`h-full transition-all duration-500 ${
                diskPercent >= 90 ? 'bg-status-failed' : 'bg-charcoal'
              }`}
              style={{ width: `${Math.min(diskPercent, 100)}%` }}
            />
          </div>
        </div>

        <div className="mt-4 pt-3 border-t border-border flex items-center justify-between text-xs text-charcoal-secondary font-mono">
          <span>Free Space:</span>
          <span>
            {disk ? formatBytes(disk.free_bytes) : '—'}
          </span>
        </div>
      </div>
    </div>
  );
};
