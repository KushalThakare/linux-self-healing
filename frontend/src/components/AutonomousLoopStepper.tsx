import React from 'react';
import { CheckCircle2, XCircle, AlertTriangle, Loader2, Clock } from 'lucide-react';
import { IncidentRecord, StageStatus } from '../types';

interface AutonomousLoopStepperProps {
  incident: IncidentRecord | null;
}

interface StepInfo {
  label: string;
  status: StageStatus;
  detail: string;
  subDetail?: string;
}

export const AutonomousLoopStepper: React.FC<AutonomousLoopStepperProps> = ({ incident }) => {
  if (!incident) {
    return (
      <div className="bg-surface border border-border rounded p-6 text-center text-xs text-charcoal-muted">
        Select an incident to view the closed-loop autonomous recovery progression.
      </div>
    );
  }

  // Derive stage statuses
  const isRejected = incident.status === 'POLICY_REJECTED' || (incident.policy_decision && !incident.policy_decision.allowed);
  const isFailed = incident.status === 'RECOVERY_FAILED' || incident.status === 'VERIFIED_FAILED' || incident.status === 'ESCALATED';
  const isSuccess = incident.status === 'VERIFIED_SUCCESS' || incident.status === 'DRY_RUN';

  // 1. DETECTED
  const stepDetected: StepInfo = {
    label: '1. DETECTED',
    status: 'SUCCESS',
    detail: incident.fault_event?.fault_type || 'FAULT',
    subDetail: incident.fault_event ? `Val: ${incident.fault_event.triggering_value.toFixed(1)} (Thresh: ${incident.fault_event.threshold_value})` : undefined,
  };

  // 2. DIAGNOSED
  let stepDiagnosed: StepInfo;
  if (incident.diagnosis) {
    stepDiagnosed = {
      label: '2. DIAGNOSED',
      status: 'SUCCESS',
      detail: `${(incident.diagnosis.confidence * 100).toFixed(0)}% Confidence`,
      subDetail: incident.diagnosis.recommended_action,
    };
  } else if (incident.status === 'DETECTED') {
    stepDiagnosed = {
      label: '2. DIAGNOSED',
      status: 'IN_PROGRESS',
      detail: 'Analyzing Evidence...',
    };
  } else {
    stepDiagnosed = {
      label: '2. DIAGNOSED',
      status: 'PENDING',
      detail: 'Pending',
    };
  }

  // 3. GUARDRAIL
  let stepGuardrail: StepInfo;
  if (incident.policy_decision) {
    if (incident.policy_decision.allowed) {
      stepGuardrail = {
        label: '3. GUARDRAIL',
        status: 'SUCCESS',
        detail: 'APPROVED',
        subDetail: incident.policy_decision.is_dry_run ? 'Dry-Run Validated' : 'Live Allowed',
      };
    } else {
      stepGuardrail = {
        label: '3. GUARDRAIL',
        status: 'REJECTED',
        detail: 'REJECTED',
        subDetail: incident.policy_decision.rejection_reason || 'Policy Check Failed',
      };
    }
  } else if (incident.status === 'DIAGNOSED') {
    stepGuardrail = {
      label: '3. GUARDRAIL',
      status: 'IN_PROGRESS',
      detail: 'Evaluating 8 Checks...',
    };
  } else {
    stepGuardrail = {
      label: '3. GUARDRAIL',
      status: 'PENDING',
      detail: 'Pending',
    };
  }

  // 4. RECOVERED
  let stepRecovered: StepInfo;
  if (isRejected) {
    stepRecovered = {
      label: '4. RECOVERED',
      status: 'REJECTED',
      detail: 'BYPASSED',
      subDetail: 'Blocked by policy',
    };
  } else if (incident.recovery_result) {
    if (incident.recovery_result.success) {
      stepRecovered = {
        label: '4. RECOVERED',
        status: 'SUCCESS',
        detail: incident.recovery_result.dry_run ? 'SIMULATED' : 'EXECUTED',
        subDetail: `${incident.recovery_result.execution_latency_ms.toFixed(1)}ms latency`,
      };
    } else {
      stepRecovered = {
        label: '4. RECOVERED',
        status: 'FAILED',
        detail: 'FAILED',
        subDetail: incident.recovery_result.error_message || 'Execution error',
      };
    }
  } else if (incident.status === 'RECOVERING' || incident.status === 'GUARDRAIL_EVALUATED') {
    stepRecovered = {
      label: '4. RECOVERED',
      status: 'IN_PROGRESS',
      detail: 'Executing Action...',
    };
  } else {
    stepRecovered = {
      label: '4. RECOVERED',
      status: 'PENDING',
      detail: 'Pending',
    };
  }

  // 5. VERIFIED
  let stepVerified: StepInfo;
  if (isRejected) {
    stepVerified = {
      label: '5. VERIFIED',
      status: 'REJECTED',
      detail: 'BYPASSED',
    };
  } else if (incident.verification_result) {
    if (incident.verification_result.verified) {
      stepVerified = {
        label: '5. VERIFIED',
        status: 'SUCCESS',
        detail: 'HEALTHY',
        subDetail: `${incident.verification_result.checks_passed.length} probes verified`,
      };
    } else {
      stepVerified = {
        label: '5. VERIFIED',
        status: 'FAILED',
        detail: 'ESCALATED',
        subDetail: `${incident.verification_result.checks_failed.length} probes failed`,
      };
    }
  } else if (incident.status === 'VERIFYING') {
    stepVerified = {
      label: '5. VERIFIED',
      status: 'IN_PROGRESS',
      detail: 'Probing State...',
    };
  } else {
    stepVerified = {
      label: '5. VERIFIED',
      status: 'PENDING',
      detail: 'Pending',
    };
  }

  const steps: StepInfo[] = [stepDetected, stepDiagnosed, stepGuardrail, stepRecovered, stepVerified];

  return (
    <div className="bg-surface border border-border rounded p-5">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2 pb-4 border-b border-border">
        <div>
          <div className="text-xs text-charcoal-muted uppercase tracking-wider font-medium">
            Autonomous Closed-Loop Pipeline Stepper
          </div>
          <div className="flex items-center gap-2 mt-1">
            <span className="font-mono text-sm font-bold text-charcoal">
              {incident.incident_id.slice(0, 16)}
            </span>
            <span className="text-xs font-mono text-charcoal-secondary">
              Target: <strong className="text-charcoal">{incident.target_id}</strong>
            </span>
          </div>
        </div>

        {/* Global Outcome Badge */}
        <div>
          <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded text-xs font-bold uppercase tracking-wider ${
            isSuccess
              ? 'text-status-success bg-status-success-bg border border-status-success-border'
              : isRejected
              ? 'text-status-rejected bg-status-rejected-bg border border-status-rejected-border'
              : isFailed
              ? 'text-status-failed bg-status-failed-bg border border-status-failed-border'
              : 'text-status-progress bg-status-progress-bg border border-status-progress-border'
          }`}>
            {isSuccess && <CheckCircle2 className="w-3.5 h-3.5" />}
            {isRejected && <AlertTriangle className="w-3.5 h-3.5" />}
            {isFailed && <XCircle className="w-3.5 h-3.5" />}
            {!isSuccess && !isRejected && !isFailed && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
            {incident.status}
          </span>
        </div>
      </div>

      {/* Stepper Visualization */}
      <div className="grid grid-cols-1 md:grid-cols-5 gap-3 mt-4">
        {steps.map((step) => {
          let badgeStyles = 'border-border bg-surface text-charcoal-muted';
          let icon = <Clock className="w-3.5 h-3.5 text-charcoal-muted" />;

          if (step.status === 'SUCCESS') {
            badgeStyles = 'border-status-success-border bg-status-success-bg text-status-success';
            icon = <CheckCircle2 className="w-3.5 h-3.5 text-status-success" />;
          } else if (step.status === 'REJECTED') {
            badgeStyles = 'border-status-rejected-border bg-status-rejected-bg text-status-rejected';
            icon = <AlertTriangle className="w-3.5 h-3.5 text-status-rejected" />;
          } else if (step.status === 'FAILED') {
            badgeStyles = 'border-status-failed-border bg-status-failed-bg text-status-failed';
            icon = <XCircle className="w-3.5 h-3.5 text-status-failed" />;
          } else if (step.status === 'IN_PROGRESS') {
            badgeStyles = 'border-status-progress-border bg-status-progress-bg text-status-progress';
            icon = <Loader2 className="w-3.5 h-3.5 animate-spin text-status-progress" />;
          }

          return (
            <div
              key={step.label}
              className={`border rounded p-3 flex flex-col justify-between transition-colors ${badgeStyles}`}
            >
              <div>
                <div className="flex items-center justify-between">
                  <span className="text-[11px] font-bold tracking-tight uppercase">
                    {step.label}
                  </span>
                  {icon}
                </div>
                <div className="mt-2 font-mono text-xs font-semibold text-charcoal">
                  {step.detail}
                </div>
              </div>
              {step.subDetail && (
                <div className="mt-2 pt-1.5 border-t border-border/50 text-[10px] font-mono text-charcoal-secondary truncate" title={step.subDetail}>
                  {step.subDetail}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
};
