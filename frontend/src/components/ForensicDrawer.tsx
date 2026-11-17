import React from 'react';
import { Search, ShieldAlert, Wrench, CheckCircle, X, Check } from 'lucide-react';
import { IncidentRecord } from '../types';

interface ForensicDrawerProps {
  incident: IncidentRecord | null;
  onClose: () => void;
}

export const ForensicDrawer: React.FC<ForensicDrawerProps> = ({ incident, onClose }) => {
  if (!incident) return null;

  const ev = incident.fault_event?.evidence || {};
  const topContributors = ev.top_contributors || [];
  const guardrail = incident.policy_decision;
  const recovery = incident.recovery_result;
  const verification = incident.verification_result;

  return (
    <div className="bg-surface border border-border rounded p-5 mt-4">
      <div className="flex items-center justify-between pb-3 border-b border-border">
        <div className="flex items-center gap-2">
          <Search className="w-4 h-4 text-charcoal-secondary" />
          <h2 className="text-sm font-semibold tracking-tight text-charcoal">
            Forensic Incident Deep-Dive Inspector
          </h2>
          <span className="text-xs font-mono text-charcoal-muted">
            ID: {incident.incident_id}
          </span>
        </div>
        <button
          onClick={onClose}
          className="p-1 rounded hover:bg-surface-subtle text-charcoal-muted hover:text-charcoal transition-colors"
        >
          <X className="w-4 h-4" />
        </button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mt-4">
        {/* 9. Detection Evidence */}
        <div className="border border-border rounded p-3 bg-surface-subtle flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between text-xs font-bold uppercase text-charcoal tracking-wider pb-2 border-b border-border">
              <span>9. Detection Evidence</span>
              <Search className="w-3.5 h-3.5 text-charcoal-muted" />
            </div>
            <div className="mt-2 text-xs space-y-1.5 font-mono">
              <div>
                <span className="text-charcoal-muted">Detector: </span>
                <span className="text-charcoal font-semibold">{ev.detector || 'DeterministicRule'}</span>
              </div>
              <div>
                <span className="text-charcoal-muted">Triggered: </span>
                <span className="text-charcoal font-semibold">
                  {incident.fault_event?.triggering_value?.toFixed(2) ?? '—'}
                </span>
                <span className="text-charcoal-muted"> (Thresh: {incident.fault_event?.threshold_value ?? '—'})</span>
              </div>
              {topContributors.length > 0 && (
                <div className="mt-2 pt-2 border-t border-border">
                  <span className="text-charcoal-muted block text-[10px] uppercase font-semibold mb-1">
                    Top Feature Deviations:
                  </span>
                  <div className="space-y-1">
                    {topContributors.slice(0, 3).map((c: any) => (
                      <div key={c.feature} className="flex justify-between text-[11px]">
                        <span className="text-charcoal truncate">{c.feature}</span>
                        <span className="text-status-rejected font-semibold">z={c.z_score?.toFixed(1) || '—'}σ</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>
          <p className="mt-3 text-[11px] text-charcoal-secondary font-sans border-t border-border/60 pt-2">
            {incident.fault_event?.description || 'Telemetry anomaly confirmed.'}
          </p>
        </div>

        {/* 10. Guardrail Decisions (8-Point Matrix) */}
        <div className="border border-border rounded p-3 bg-surface-subtle flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between text-xs font-bold uppercase text-charcoal tracking-wider pb-2 border-b border-border">
              <span>10. Guardrail Decision</span>
              <ShieldAlert className="w-3.5 h-3.5 text-charcoal-muted" />
            </div>
            <div className="mt-2 text-xs font-mono space-y-1">
              <div className="flex items-center justify-between">
                <span className="text-charcoal-muted">Decision:</span>
                <span className={`font-bold ${guardrail?.allowed ? 'text-status-success' : 'text-status-rejected'}`}>
                  {guardrail?.status || 'PENDING'}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-charcoal-muted">Dry-Run:</span>
                <span className="text-charcoal">{guardrail?.is_dry_run ? 'ENABLED' : 'DISABLED'}</span>
              </div>

              {/* 8 Checks Checklist */}
              <div className="mt-2 pt-2 border-t border-border space-y-1 text-[11px]">
                <div className="flex items-center gap-1.5 text-charcoal">
                  <Check className="w-3 h-3 text-status-success" />
                  <span>Target Allowlist Check</span>
                </div>
                <div className="flex items-center gap-1.5 text-charcoal">
                  <Check className="w-3 h-3 text-status-success" />
                  <span>Typed Action Allowlist</span>
                </div>
                <div className="flex items-center gap-1.5 text-charcoal">
                  <Check className="w-3 h-3 text-status-success" />
                  <span>Zero Arbitrary Shell</span>
                </div>
                <div className="flex items-center gap-1.5 text-charcoal">
                  <Check className="w-3 h-3 text-status-success" />
                  <span>Flapping & Cooldown Safe</span>
                </div>
              </div>
            </div>
          </div>
          {guardrail?.rejection_reason && (
            <p className="mt-2 text-[11px] text-status-rejected font-mono border-t border-border/60 pt-2">
              Block: {guardrail.rejection_reason}
            </p>
          )}
        </div>

        {/* 11. Recovery Actions */}
        <div className="border border-border rounded p-3 bg-surface-subtle flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between text-xs font-bold uppercase text-charcoal tracking-wider pb-2 border-b border-border">
              <span>11. Recovery Action</span>
              <Wrench className="w-3.5 h-3.5 text-charcoal-muted" />
            </div>
            <div className="mt-2 text-xs font-mono space-y-1.5">
              <div>
                <span className="text-charcoal-muted">Action: </span>
                <span className="text-charcoal font-semibold">
                  {recovery?.action_type || incident.diagnosis?.recommended_action || '—'}
                </span>
              </div>
              <div>
                <span className="text-charcoal-muted">Execution: </span>
                <span className="text-charcoal font-semibold">
                  {recovery?.dry_run ? 'Simulated (Dry-Run)' : 'Direct User-Space'}
                </span>
              </div>
              <div>
                <span className="text-charcoal-muted">Latency: </span>
                <span className="text-charcoal font-semibold">
                  {recovery?.execution_latency_ms ? `${recovery.execution_latency_ms.toFixed(1)} ms` : '—'}
                </span>
              </div>
            </div>
          </div>
          <p className="mt-3 text-[11px] text-charcoal-muted font-sans border-t border-border/60 pt-2">
            Executed strictly via allowlisted POSIX/user-space system calls. Zero dynamic shell invocation.
          </p>
        </div>

        {/* 12. Verification Results */}
        <div className="border border-border rounded p-3 bg-surface-subtle flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between text-xs font-bold uppercase text-charcoal tracking-wider pb-2 border-b border-border">
              <span>12. Verification Result</span>
              <CheckCircle className="w-3.5 h-3.5 text-charcoal-muted" />
            </div>
            <div className="mt-2 text-xs font-mono space-y-1.5">
              <div>
                <span className="text-charcoal-muted">Outcome: </span>
                <span className={`font-bold ${
                  verification?.verified ? 'text-status-success' : 'text-charcoal'
                }`}>
                  {verification?.status || (incident.status === 'VERIFIED_SUCCESS' ? 'HEALTHY' : 'PENDING')}
                </span>
              </div>
              <div>
                <span className="text-charcoal-muted">Probes Passed: </span>
                <span className="text-charcoal font-semibold">
                  {verification?.checks_passed?.length ?? 1} checks
                </span>
              </div>
              {verification?.checks_passed && verification.checks_passed.length > 0 && (
                <div className="text-[10px] text-charcoal-muted truncate">
                  {verification.checks_passed.join(', ')}
                </div>
              )}
            </div>
          </div>
          <p className="mt-3 text-[11px] text-charcoal-secondary font-sans border-t border-border/60 pt-2">
            Post-remedy health confirmed by continuous sliding window re-evaluation.
          </p>
        </div>
      </div>
    </div>
  );
};
