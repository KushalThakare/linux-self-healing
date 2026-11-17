import React from 'react';
import { ShieldCheck, Play, Pause, FastForward, RefreshCw } from 'lucide-react';
import { SystemStatusResponse } from '../types';

interface HeaderProps {
  status: SystemStatusResponse | null;
  dryRun: boolean;
  onToggleDryRun: (newDryRun: boolean) => void;
  onTick: () => void;
  onToggleLoop: (start: boolean) => void;
  onRefresh: () => void;
  loading: boolean;
}

export const Header: React.FC<HeaderProps> = ({
  status,
  dryRun,
  onToggleDryRun,
  onTick,
  onToggleLoop,
  onRefresh,
  loading,
}) => {
  const isLoopRunning = status?.orchestrator_running ?? false;

  return (
    <header className="border-b border-border bg-surface px-6 py-4">
      <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
        {/* Title & System Identity */}
        <div>
          <div className="flex items-center gap-2.5">
            <h1 className="text-xl font-bold tracking-tight text-charcoal">
              Autonomous Linux Self-Healing
            </h1>
            <span className="text-xs px-2 py-0.5 rounded font-mono font-medium border border-border bg-surface-subtle text-charcoal-muted">
              v{status?.version || '0.1.0'}
            </span>
            <span className="text-xs px-2 py-0.5 rounded font-mono font-medium border border-border bg-surface-subtle text-charcoal-secondary">
              Linux user-space vm
            </span>
          </div>
          <p className="text-xs text-charcoal-muted mt-1">
            Closed-loop fault detection, safety guardrails, and deterministic recovery monitor
          </p>
        </div>

        {/* Operational Controls & Dry-Run Indicator */}
        <div className="flex flex-wrap items-center gap-3">
          {/* Section 14: Dry-run indicator */}
          <div className="flex items-center gap-2 border border-border rounded px-3 py-1.5 bg-surface-subtle">
            <ShieldCheck className={`w-4 h-4 ${dryRun ? 'text-charcoal-secondary' : 'text-accent'}`} />
            <div className="text-xs">
              <span className="text-charcoal-muted uppercase text-[10px] tracking-wider block font-medium">
                Operational Mode
              </span>
              <span className={`font-mono font-semibold ${dryRun ? 'text-charcoal-secondary' : 'text-status-rejected'}`}>
                {dryRun ? 'DRY-RUN (SIMULATED)' : 'ACTIVE MUTATION'}
              </span>
            </div>
            <button
              onClick={() => onToggleDryRun(!dryRun)}
              className="ml-2 text-xs px-2 py-1 rounded border border-border bg-surface hover:bg-canvas text-charcoal transition-colors font-medium"
            >
              Toggle
            </button>
          </div>

          {/* Autonomous Loop Control */}
          <div className="flex items-center gap-1.5 border border-border rounded px-2.5 py-1.5 bg-surface-subtle">
            <div className="text-xs mr-2">
              <span className="text-charcoal-muted uppercase text-[10px] tracking-wider block font-medium">
                Autonomous Loop
              </span>
              <span className="font-mono font-semibold text-charcoal">
                {isLoopRunning ? 'RUNNING' : 'STOPPED'}
              </span>
            </div>
            <button
              onClick={() => onToggleLoop(!isLoopRunning)}
              className={`p-1.5 rounded border transition-colors ${
                isLoopRunning
                  ? 'border-status-failed text-status-failed bg-status-failed-bg hover:opacity-90'
                  : 'border-status-success text-status-success bg-status-success-bg hover:opacity-90'
              }`}
              title={isLoopRunning ? 'Pause background loop' : 'Start background loop'}
            >
              {isLoopRunning ? <Pause className="w-3.5 h-3.5" /> : <Play className="w-3.5 h-3.5" />}
            </button>
            <button
              onClick={onTick}
              className="p-1.5 rounded border border-border bg-surface hover:bg-canvas text-charcoal transition-colors"
              title="Execute discrete tick"
            >
              <FastForward className="w-3.5 h-3.5" />
            </button>
          </div>

          {/* Refresh Action */}
          <button
            onClick={onRefresh}
            className="p-2 rounded border border-border bg-surface hover:bg-canvas text-charcoal transition-colors"
            title="Refresh telemetry"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin text-accent' : 'text-charcoal-secondary'}`} />
          </button>
        </div>
      </div>
    </header>
  );
};
