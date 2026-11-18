import React, { useState, useEffect, useCallback } from 'react';
import { Header } from './components/Header';
import { SystemHealthGauges } from './components/SystemHealthGauges';
import { WorkloadTables } from './components/WorkloadTables';
import { AutonomousLoopStepper } from './components/AutonomousLoopStepper';
import { IncidentHistoryTable } from './components/IncidentHistoryTable';
import { ForensicDrawer } from './components/ForensicDrawer';
import { FaultInjectionConsole } from './components/FaultInjectionConsole';
import { api } from './api/client';
import {
  HealthResponse,
  SystemStatusResponse,
  SystemSnapshot,
  ProcessMetrics,
  ServiceMetrics,
  IncidentRecord,
} from './types';

export const App: React.FC = () => {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [systemStatus, setSystemStatus] = useState<SystemStatusResponse | null>(null);
  const [metrics, setMetrics] = useState<SystemSnapshot | null>(null);
  const [processes, setProcesses] = useState<ProcessMetrics[]>([]);
  const [services, setServices] = useState<ServiceMetrics[]>([]);
  const [incidents, setIncidents] = useState<IncidentRecord[]>([]);
  const [selectedIncident, setSelectedIncident] = useState<IncidentRecord | null>(null);
  const [dryRun, setDryRun] = useState<boolean>(true);
  const [loading, setLoading] = useState<boolean>(false);
  const [apiError, setApiError] = useState<string | null>(null);

  // Fetch telemetry
  const refreshData = useCallback(async () => {
    try {
      setLoading(true);
      const [h, s, m, procs, svcs, incs] = await Promise.all([
        api.getHealth().catch(() => null),
        api.getSystemStatus().catch(() => null),
        api.getMetrics().catch(() => null),
        api.getProcesses().catch(() => []),
        api.getServices().catch(() => []),
        api.getIncidents({ limit: 50 }).catch(() => []),
      ]);

      if (h) setHealth(h);
      if (s) {
        setSystemStatus(s);
        setDryRun(s.dry_run);
      }
      if (m) setMetrics(m);
      if (procs) setProcesses(procs);
      if (svcs) setServices(svcs);
      if (incs && incs.length > 0) {
        setIncidents(incs);
        // Automatically track and update the latest incident or currently selected one
        const currentId = selectedIncident?.incident_id;
        const matching = currentId ? incs.find(i => i.incident_id === currentId) : null;
        if (matching) {
          setSelectedIncident(matching);
        } else {
          setSelectedIncident(incs[0]);
        }
      }
      setApiError(null);
    } catch (err: any) {
      setApiError(err.message || 'Failed to sync with API backend');
    } finally {
      setLoading(false);
    }
  }, [selectedIncident]);

  // Initial fetch and 1-second interval polling for real-time responsiveness
  useEffect(() => {
    refreshData();
    const interval = setInterval(refreshData, 1000);
    return () => clearInterval(interval);
  }, [refreshData]);

  // Operational Action Handlers
  const handleToggleDryRun = async (newVal: boolean) => {
    try {
      setDryRun(newVal);
      await api.setDryRun(newVal);
      await refreshData();
    } catch (err: any) {
      console.error('Error toggling dry run mode:', err);
    }
  };

  const handleTick = async () => {
    try {
      await api.controlMonitoring('tick');
      await refreshData();
    } catch (err: any) {
      console.error('Error executing discrete tick:', err);
    }
  };

  const handleToggleLoop = async (start: boolean) => {
    try {
      await api.controlMonitoring(start ? 'start' : 'stop');
      await refreshData();
    } catch (err: any) {
      console.error('Error toggling loop:', err);
    }
  };

  const handleResetGuardrails = async () => {
    try {
      await api.resetGuardrails();
      await refreshData();
    } catch (err: any) {
      console.error('Error resetting guardrails:', err);
    }
  };

  const handleStartFault = async (faultType: string, intensity: number = 85.0) => {
    setSelectedIncident(null);
    await api.startFault(faultType, intensity);
    await refreshData();
  };

  const handleStopFault = async (faultType: string) => {
    await api.stopFault(faultType);
    await refreshData();
  };

  return (
    <div className="min-h-screen bg-canvas text-charcoal flex flex-col font-sans">
      {/* Top Header & Operational State */}
      <Header
        status={systemStatus}
        dryRun={dryRun}
        onToggleDryRun={handleToggleDryRun}
        onResetGuardrails={handleResetGuardrails}
        onTick={handleTick}
        onToggleLoop={handleToggleLoop}
        onRefresh={refreshData}
        loading={loading}
      />

      {/* Main Workspace Layout */}
      <main className="flex-1 p-6 max-w-7xl w-full mx-auto space-y-6">
        {/* Error notification banner if any */}
        {apiError && (
          <div className="p-3 border border-status-failed-border bg-status-failed-bg text-status-failed rounded text-xs font-mono">
            Backend Connection Warning: {apiError}. Ensure backend daemon is listening on port 8000.
          </div>
        )}

        {/* Sections 1, 2, 3, 4: System Health, CPU, Memory, Disk Gauges */}
        <SystemHealthGauges
          health={health}
          status={systemStatus}
          metrics={metrics}
        />

        {/* Autonomous Loop Visual Stepper for active/selected incident */}
        <AutonomousLoopStepper incident={selectedIncident} />

        {/* Sections 5 & 6: Supervised Processes & Services */}
        <WorkloadTables
          processes={processes}
          services={services}
        />

        {/* Sections 7 & 8: Active & Historic Incident Audit Feed */}
        <IncidentHistoryTable
          incidents={incidents}
          selectedIncidentId={selectedIncident?.incident_id || null}
          onSelectIncident={(inc) => setSelectedIncident(inc)}
        />

        {/* Forensic Deep-Dive Drawer: Sections 9, 10, 11, 12 */}
        {selectedIncident && (
          <ForensicDrawer
            incident={selectedIncident}
            onClose={() => setSelectedIncident(null)}
          />
        )}

        {/* Section 13: Controlled Fault Injection Controls */}
        <FaultInjectionConsole
          onStartFault={handleStartFault}
          onStopFault={handleStopFault}
          loading={loading}
        />
      </main>

      {/* Editorial Footer */}
      <footer className="border-t border-border bg-surface px-6 py-3 text-center text-xs text-charcoal-muted font-mono">
        Autonomous Fault Detection and Self-Healing System for Linux &mdash; User-Space Research Platform
      </footer>
    </div>
  );
};

export default App;
