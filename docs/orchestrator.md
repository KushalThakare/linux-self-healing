# Autonomous Self-Healing Orchestrator (Phase 10)

The **Self-Healing Orchestrator** is the central closed-loop controller that continuously coordinates the complete lifecycle across user-space Linux target workloads:

```
MONITOR → DETECT → DIAGNOSE → GUARDRAIL → RECOVER → VERIFY → RECORD
```

---

## 1. Architecture Overview

Implemented in [`SelfHealingOrchestrator`](../src/self_healing/orchestrator.py), the orchestrator brings together the modular components developed throughout Phases 1–9 into an autonomous closed loop.

```
       +-----------------------------------------------------------+
       |                  SelfHealingOrchestrator                  |
       |                                                           |
       |  +------------------+             +--------------------+  |
       |  |  System Metrics  |             | Rule Detection     |  |
       |  |  Collector       | ----------> | Engine (5 Rules)   |  |
       |  +------------------+             +--------------------+  |
       |           |                                 |             |
       |           v                                 v             |
       |  +------------------+             +--------------------+  |
       |  | Metric Ring      |             | In-Flight Dedup &  |  |
       |  | Buffers (FIFO)   |             | Fault Dispatcher   |  |
       |  +------------------+             +--------------------+  |
       |           |                                 |             |
       |           +---------------+   +-------------+             |
       |                           |   |                           |
       |                           v   v                           |
       |                   +--------------------+                  |
       |                   | Deterministic      |                  |
       |                   | Diagnosis Engine   |                  |
       |                   +--------------------+                  |
       |                             |                             |
       |                             v                             |
       |                   +--------------------+                  |
       |                   | Allowed Action     |                  |
       |                   | Registry Lookup    |                  |
       |                   +--------------------+                  |
       |                             |                             |
       |                             v                             |
       |                   +--------------------+                  |
       |                   | Safety Guardrail   |                  |
       |                   | Engine (8 Checks)  |                  |
       |                   +--------------------+                  |
       |                             |                             |
       |                             v                             |
       |                   +--------------------+                  |
       |                   | Recovery Executor  |                  |
       |                   | (Allowlisted Only) |                  |
       |                   +--------------------+                  |
       |                             |                             |
       |                             v                             |
       |                   +--------------------+                  |
       |                   | Post-Recovery      |                  |
       |                   | VerificationEngine |                  |
       |                   +--------------------+                  |
       |                             |                             |
       |                             v                             |
       |                   +--------------------+                  |
       |                   | IncidentRepository |                  |
       |                   | (SQLite & Audit)   |                  |
       |                   +--------------------+                  |
       +-----------------------------------------------------------+
```

---

## 2. Core Operational Stages

Each discrete cycle (`orchestrator.tick()`) carries out the following deterministic steps:

1. **MONITOR**:
   - Gathers fresh system snapshots via `SystemMetricsCollector` (`/proc/stat`, `/proc/meminfo`, `/proc/loadavg`, and process tables).
   - Feeds time-series telemetry into per-target sliding FIFO ring buffers (`MetricRingBuffer`).
2. **DETECT**:
   - Evaluates the registered deterministic rules:
     - `CpuRunawayDetector`
     - `AbnormalMemoryDetector`
     - `ServiceFailureDetector` (strictly scoped to services)
     - `DiskExhaustionDetector`
     - `DeadlockDetector`
   - Produces strongly typed `DetectionEvent` objects upon threshold breaches.
3. **DEDUPLICATE**:
   - Checks `(target_id, fault_type)` against `orchestrator._active_faults`.
   - Suppresses duplicate incident creation for faults that are already actively being handled.
4. **DIAGNOSE**:
   - Passes the fault event and telemetry sliding window to `DeterministicDiagnosisEngine`.
   - Derives root cause explanation, confidence level, and recommended allowlisted action.
5. **ACTION RESOLUTION**:
   - Translates diagnosis recommendation via `AllowedActionRegistry.from_diagnosis(diagnosis)`.
   - Enriches action parameters with live process telemetry (e.g. current target PID).
6. **GUARDRAIL CHECK**:
   - Submits action to `SafetyGuardrailEngine` to enforce the 8 safety checks (dry-run, safe PID, directory containment, flapping, cooldown).
   - If rejected, updates incident status to `POLICY_REJECTED` and halts execution.
7. **RECOVERY EXECUTION**:
   - Dispatches approved typed action to `RecoveryExecutor`.
   - In dry-run mode, logs intent and simulates outcome without altering system state.
8. **POST-RECOVERY VERIFICATION**:
   - Executes domain-specific probes via `VerificationEngine`.
   - Compares pre- and post-recovery measurable states.
   - If verification fails, consults `RetryPolicy`. Retries with exponential backoff if budget remains; transitions to `ESCALATED` upon retry exhaustion.
9. **RECORD & AUDIT**:
   - Persists the complete `IncidentRecord` with all telemetry, decisions, and outcomes into `IncidentRepository` (SQLite).
   - Clears resolved faults from active tracking and notifies event listeners (`incident_created`, `incident_resolved`, etc.).

---

## 3. Autonomous Execution & Controls

### Synchronous / Discrete Execution
```python
from self_healing.orchestrator import SelfHealingOrchestrator

orchestrator = SelfHealingOrchestrator(dry_run=True)
incidents = orchestrator.tick()
```

### Continuous Loop Execution
```python
# Run with max ticks or indefinite execution
orchestrator.run(max_ticks=10)

# Or run in a separate background daemon thread
orchestrator.start()
# ... do work ...
orchestrator.stop()
```

### Configuration & Safety Controls
- **Dry-Run Mode (`--dry-run`)**: Recovery actions are evaluated and verified through dry-run simulation without touching OS state.
- **Polling Interval (`--interval`)**: Configurable sleep between ticks (default: 1.0s).
- **Flapping & Cooldown Prevention**: Evaluated per target before any recovery action is dispatched.
- **Bounded Retries & Escalation**: Prevents infinite loops; transitions to `ESCALATED` if target fails post-recovery probes after retry budget.

---

## 4. CLI Daemon Integration

Run the autonomous daemon directly via the CLI:

```bash
# Run 1 tick in dry-run mode
python -m self_healing run --dry-run --once

# Run continuous loop with custom polling interval
python -m self_healing run --interval 2.0 --dry-run

# Run bounded loop with maximum tick limit
python -m self_healing run --max-ticks 5
```
