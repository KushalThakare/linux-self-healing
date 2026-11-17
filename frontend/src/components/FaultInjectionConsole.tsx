import React, { useState } from 'react';
import { Flame } from 'lucide-react';

interface FaultInjectionConsoleProps {
  onStartFault: (faultType: string, intensity?: number) => Promise<void>;
  onStopFault: (faultType: string) => Promise<void>;
  loading: boolean;
}

const FAULTS = [
  { id: 'cpu', label: 'CPU Runaway', target: 'demo-cpu', desc: 'Induces compute-bound spin loop (>90% CPU)' },
  { id: 'memory', label: 'Memory Leak', target: 'demo-memory', desc: 'Monotonically allocates RSS heap buffers' },
  { id: 'service', label: 'Service Crash', target: 'demo-service', desc: 'Simulates sudden supervised daemon failure' },
  { id: 'disk', label: 'Disk Fill', target: 'demo-disk', desc: 'Fills sandboxed demo scratch directory' },
  { id: 'deadlock', label: 'Thread Deadlock', target: 'demo-deadlock', desc: 'Induces circular mutex contention (0% CPU)' },
];

export const FaultInjectionConsole: React.FC<FaultInjectionConsoleProps> = ({
  onStartFault,
  onStopFault,
  loading,
}) => {
  const [activeFault, setActiveFault] = useState<string | null>(null);
  const [injectedAction, setInjectedAction] = useState<string | null>(null);

  const handleStart = async (faultId: string) => {
    try {
      setInjectedAction(faultId);
      await onStartFault(faultId);
      setActiveFault(faultId);
    } finally {
      setInjectedAction(null);
    }
  };

  const handleStop = async (faultId: string) => {
    try {
      setInjectedAction(`stop-${faultId}`);
      await onStopFault(faultId);
      if (activeFault === faultId) {
        setActiveFault(null);
      }
    } finally {
      setInjectedAction(null);
    }
  };

  return (
    <div className="bg-surface border border-border rounded p-4">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2 pb-3 border-b border-border">
        <div className="flex items-center gap-2">
          <Flame className="w-4 h-4 text-status-rejected" />
          <h2 className="text-sm font-semibold tracking-tight text-charcoal">
            13. Controlled Fault Injection Console
          </h2>
        </div>
        <span className="text-xs text-charcoal-muted font-mono">
          Strictly confined to allowlisted demo targets
        </span>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-5 gap-3 mt-4">
        {FAULTS.map((fault) => {
          const isActive = activeFault === fault.id;
          const isPending = injectedAction === fault.id || injectedAction === `stop-${fault.id}`;

          return (
            <div
              key={fault.id}
              className={`border rounded p-3 flex flex-col justify-between transition-colors ${
                isActive ? 'border-status-rejected bg-status-rejected-bg' : 'border-border bg-surface'
              }`}
            >
              <div>
                <div className="flex items-center justify-between">
                  <span className="text-xs font-bold text-charcoal">{fault.label}</span>
                  {isActive && (
                    <span className="text-[10px] font-mono px-1 py-0.5 rounded font-bold uppercase text-status-rejected bg-status-rejected-border/40">
                      ACTIVE
                    </span>
                  )}
                </div>
                <div className="text-[11px] font-mono text-charcoal-secondary mt-1">
                  Target: {fault.target}
                </div>
                <p className="text-[11px] text-charcoal-muted mt-2 leading-relaxed">
                  {fault.desc}
                </p>
              </div>

              <div className="mt-4 pt-2 border-t border-border flex items-center gap-2">
                {!isActive ? (
                  <button
                    disabled={loading || isPending}
                    onClick={() => handleStart(fault.id)}
                    className="w-full text-xs font-medium py-1 px-2 rounded border border-border bg-surface hover:bg-canvas text-charcoal transition-colors disabled:opacity-50"
                  >
                    {isPending ? 'Injecting...' : 'Trigger Fault'}
                  </button>
                ) : (
                  <button
                    disabled={loading || isPending}
                    onClick={() => handleStop(fault.id)}
                    className="w-full text-xs font-medium py-1 px-2 rounded border border-status-rejected text-status-rejected bg-surface hover:bg-status-rejected-bg transition-colors disabled:opacity-50"
                  >
                    {isPending ? 'Stopping...' : 'Stop Fault'}
                  </button>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};
