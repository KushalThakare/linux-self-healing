# Features, Architecture Status & Visualization Roadmap

**Project**: Autonomous Fault Detection and Self-Healing System for Linux  
**Repository**: [github.com/KushalThakare/linux-self-healing](https://github.com/KushalThakare/linux-self-healing)  
**Core Autonomous Loop**:
$$\mathbf{MONITOR} \longrightarrow \mathbf{DETECT} \longrightarrow \mathbf{DIAGNOSE} \longrightarrow \mathbf{GUARDRAIL} \longrightarrow \mathbf{RECOVER} \longrightarrow \mathbf{VERIFY} \longrightarrow \mathbf{RECORD}$$

---

## 1. Executive Summary

This document provides a comprehensive audit of the **current state of the system**, detailing all features implemented across **Phases 1 through 11**, the **remaining phases**, and the **visualization and demonstration strategy** for presenting telemetry, guardrail evaluations, recovery actions, and incident lifecycles.

As of Phase 11, the core autonomous user-space closed loop, guardrail safety engine, SQLite persistent audit store, and FastAPI backend are fully operational with **185 passing automated tests**.

---

## 2. Implemented Features (Phases 1 – 11)

### Phase 1: Architecture, Configuration & Domain Contracts
- **Typed Data Models ([`models.py`](src/self_healing/core/models.py))**: Strict Pydantic contracts for telemetry snapshots, process states, detection events, diagnostic reports, policy tokens, recovery results, and incident records.
- **Hierarchical Configuration ([`settings.py`](src/self_healing/config/settings.py))**: Configurable thresholds for CPU, RAM, disk, flapping windows, cooldowns, and database paths via YAML and environment overrides.
- **Safety Allowlist Registry ([`registry.py`](src/self_healing/targets/registry.py))**: Enforces approved demo targets (`demo-cpu`, `demo-memory`, `demo-service`, `demo-disk`, `demo-deadlock`). Blocks system PIDs (0, 1, 2, self), root system directories (`/etc`, `/bin`, `/usr`, `/root`), and critical daemon names (`systemd`, `dockerd`, `sshd`).

### Phase 2: Controlled Demo Fault Injection Subsystem
- **Sandboxed Workload Injectors ([`fault_injection/`](src/self_healing/fault_injection/))**:
  - `cpu`: Isolated multi-core CPU runaway simulation (`demo_workloads.py cpu_spin`).
  - `memory`: Predictable memory leak with hard growth limits (`demo_workloads.py memory_leak`).
  - `service`: Controlled service crash simulation (`demo_workloads.py service_crash`).
  - `disk`: Capped log/disk exhaustion generator (`demo_workloads.py disk_fill`).
  - `deadlock`: Multi-threaded circular lock acquisition simulation (`demo_workloads.py deadlock`).
- **Safety Enforcement**: PID validation, state tracking in `.fault_state/`, and automated cleanup routines via [`FaultManager`](src/self_healing/fault_injection/manager.py).

### Phase 3: Telemetry & Monitoring Subsystem
- **Non-Intrusive `/proc` Reader ([`proc_reader.py`](src/self_healing/monitoring/proc_reader.py))**: Direct, high-performance parsing of `/proc/stat`, `/proc/meminfo`, `/proc/loadavg`, and `/proc/uptime`.
- **Systemd Service Inspector ([`service_inspector.py`](src/self_healing/monitoring/service_inspector.py))**: Read-only status querying using `systemctl show` with regex protection against command injection.
- **Sliding Ring Buffers ([`collector.py`](src/self_healing/monitoring/collector.py))**: FIFO time-series ring buffers tracking multi-sample telemetry history for deterministic window analysis.

### Phase 4: Deterministic Rule-Based Detection Engine
- **Deterministic Detection Rules ([`detection/`](src/self_healing/detection/))**:
  - `CpuRunawayDetector`: Triggers on sustained CPU utilization exceeding thresholds across continuous sample windows.
  - `AbnormalMemoryDetector`: Detects monotonic RSS heap growth indicative of unconstrained leaks.
  - `ServiceFailureDetector`: Identifies service crashes, socket listening drops, or dead process states (strictly scoped to service units).
  - `DiskExhaustionDetector`: Detects rapid filesystem disk consumption or log inflation.
  - `DeadlockDetector`: Detects frozen workloads with 0% CPU consumption and stalled heartbeat files.

### Phase 5: Root-Cause Diagnosis Engine
- **Traceable Root Cause Inference ([`diagnosis/engine.py`](src/self_healing/diagnosis/engine.py))**:
  - Distinguishes compute-bound tight loops from I/O wait starvation.
  - Calculates transparent diagnostic confidence scores (0.0 to 1.0).
  - Produces structured diagnostic logs linking triggering evidence, host metrics, and candidate recovery action recommendations.

### Phase 6: Safety Guardrails & Policy Gatekeeper
- **8-Stage Safety Policy Engine ([`guardrails/engine.py`](src/self_healing/guardrails/engine.py))**:
  1. Target specification validation against `TargetRegistry`.
  2. Action type allowlist verification.
  3. Identity safety checks (preventing termination of protected OS binaries).
  4. Blast-radius containment to supervised demo targets.
  5. System starvation assessment (prevents actions under total host collapse).
  6. Rate limiting, flapping lockout, and per-target cooldown enforcement.
  7. Risk-level review (requires explicit operator override for critical actions).
  8. Mandatory diagnostic evidence presence check.

### Phase 7: Typed Allowlisted Recovery Action Registry
- **Zero Raw Shell Commands ([`recovery/`](src/self_healing/recovery/))**:
  - Recovery mechanisms never invoke raw shell execution (`os.system` or `shell=True`).
  - Actions execute strictly via typed handlers:
    1. `terminate_demo_process`: Graceful `SIGTERM` followed by bounded `SIGKILL`.
    2. `lower_demo_process_priority`: Safe process renicing (`psutil.nice(15)`).
    3. `restart_demo_service`: Recycling supervised service processes or systemd units.
    4. `restart_demo_application`: Graceful application restarts.
    5. `cleanup_demo_logs`: Truncating demo log files strictly inside workspace boundaries.
  - **Dry-Run Mode**: Full simulation capability logging intent without modifying OS state.

### Phase 8: Post-Recovery Verification Subsystem
- **Measurable Verification Probes ([`verification/`](src/self_healing/verification/))**:
  - Executes targeted verification probes following every remediation attempt.
  - Compares pre- and post-recovery telemetry (CPU normalized, RSS stabilized, service active, log growth stopped, deadlock heartbeat restored).
  - **Retry Policy & Escalation ([`coordinator.py`](src/self_healing/verification/coordinator.py))**: Evaluates retry budgets with exponential backoff; safely transitions to `ESCALATED` upon retry exhaustion.

### Phase 9: Persistent Incident Management (SQLite)
- **Persistent SQLite Repository ([`incidents/repository.py`](src/self_healing/incidents/repository.py))**:
  - WAL mode (`PRAGMA journal_mode=WAL`) and thread-locked synchronization.
  - Relational indexed columns for fast filtering by `fault_type`, `status`, and `target_id`.
  - Raw JSON serialization preserving 100% roundtrip model fidelity.

### Phase 10: Closed-Loop Self-Healing Orchestrator
- **Autonomous Control Loop ([`orchestrator.py`](src/self_healing/orchestrator.py))**:
  - Continuous loop: `MONITOR → DETECT → DIAGNOSE → GUARDRAIL → RECOVER → VERIFY → RECORD`.
  - Active fault deduplication (`_active_faults`) preventing duplicate incident storms.
  - Real-time telemetry statistics ([`OrchestratorStats`](src/self_healing/orchestrator.py)).
  - Discrete `tick()`, bounded loop (`run(max_ticks=N)`), and background thread (`start()` / `stop()`) execution.
  - CLI integration: `python -m self_healing run --dry-run --once`.

### Phase 11: FastAPI Operator & Telemetry Backend
- **13 REST API Endpoints ([`api/app.py`](src/self_healing/api/app.py))**:
  - `GET /health`: Overall health and resource availability.
  - `GET /metrics`: Comprehensive point-in-time system telemetry snapshot.
  - `GET /processes`: Supervised target process status (with optional `?target_id=`).
  - `GET /services`: Supervised systemd services status.
  - `GET /incidents`: Filtered persistent incident queries (`?fault_type=`, `?status=`, `?limit=`).
  - `GET /incidents/{id}`: Detailed single incident record by UUID.
  - `GET /system/status`: Daemon status, operational mode, and orchestrator metrics.
  - `GET /guardrails`: Policy configuration, cooldown limits, and action allowlists.
  - `GET /recovery/history`: Audit log of recovery interventions with duration and outcomes.
  - `POST /faults/{fault_type}/start`: Safely start demo fault on approved demo targets.
  - `POST /faults/{fault_type}/stop`: Stop active demo fault.
  - `POST /system/dry-run`: Dynamically toggle dry-run simulation mode.
  - `POST /system/monitoring`: Autonomous loop lifecycle control (`start`, `stop`, `tick`).

---

## 3. What Features Are Left to Build

| Phase | Milestone | Description | Priority |
|---|---|---|---|
| **Phase 12** | **Web Dashboard & Visual UI** | Interactive browser frontend to visualize live telemetry, incident lifecycles, and fault controls | **Immediate Next** |
| **Phase 13** | **Machine Learning Anomaly Detection** | Multivariate Isolation Forest detection baseline for gradual degradation before hard threshold breaches | Secondary |
| **Phase 14** | **Operator Notification & Webhooks** | Outbound alerting to Slack, Discord, PagerDuty, or webhooks on critical faults and escalations | Enhancement |
| **Phase 15** | **Multi-Node & Advanced Chaos Testing** | Expanded scenario suite testing cascading multi-fault interactions and worker fleets | Research Final |

---

## 4. How We'll Be Visualizing & Demonstrating the System

To effectively show the system in action (both for demonstrations and evaluation), we will employ a **multi-layer visualization strategy** spanning a **Web Dashboard**, **Live Telemetry Charts**, **Interactive Pipeline Visualizers**, and **Terminal Demonstrations**.

### 1. Real-Time Telemetry & System Gauges
- **Global Host Resource Meters**:
  - Circular / radial gauges for **System CPU %** and **Memory Usage %**.
  - Bar indicators for filesystem disk consumption across mounts.
  - Real-time load average display (1m, 5m, 15m) and uptime tracker.
- **Live Time-Series Charts**:
  - Dynamic sliding line chart showing target CPU utilization over time with a visible **threshold line (e.g. 80% / 90%)**.
  - Memory RSS growth chart clearly depicting memory leaks before and after remediation.

### 2. Autonomous Closed-Loop Pipeline Stepper
A visual representation of the 7-stage autonomous recovery loop:
```
[ 1. MONITOR ] ──> [ 2. DETECT ] ──> [ 3. DIAGNOSE ] ──> [ 4. GUARDRAIL ] ──> [ 5. RECOVER ] ──> [ 6. VERIFY ] ──> [ 7. RECORD ]
```
- **Live State Lighting**: Each step illuminates and animates in the UI as an incident progresses through the loop:
  - *Detect*: Lights up red/orange with detected fault and triggering telemetry.
  - *Diagnose*: Displays identified root cause and confidence percentage (e.g., `95% Confidence`).
  - *Guardrail*: Lights up green (`APPROVED`) or red (`REJECTED`) with check breakdown.
  - *Recover*: Displays recovery action type (e.g., `terminate_demo_process`, `restart_demo_service`) and execution latency.
  - *Verify*: Runs post-remedy probes and displays measurable outcome (`HEALTHY`).
  - *Record*: Shows persisted SQLite ID badge.

### 3. Incident Timeline & Root-Cause Drill-Down Modal
- **Chronological Incident Feed**:
  - Real-time table displaying recent incidents sorted by timestamp descending.
  - Color-coded status badges:
    - 🟢 `VERIFIED_SUCCESS`: Remediation succeeded and verified.
    - 🟡 `POLICY_REJECTED`: Guardrails intervened and prevented action.
    - 🔴 `ESCALATED`: Verification probes failed after retry budget exhaustion.
    - 🔵 `DRY_RUN`: Recovery simulated safely without OS modification.
- **Deep-Dive Inspection Modal**:
  - Clicking any incident opens a detailed modal with:
    1. **Telemetry Evidence**: Pre-remediation metric values vs. post-remediation metrics.
    2. **Diagnosis Trace**: Full reasoning chain and evaluated process metrics.
    3. **Guardrail Audit Matrix**: Checkmark table confirming all 8 safety criteria.
    4. **Verification Evidence**: Probe execution timing and probe outcome details.

### 4. Safety Guardrails & Cooldown Visualizer
- **Active Cooldown Countdown Bars**:
  - Live progress bars for targets in cooldown (e.g. `demo-cpu: Cooldown active (14s remaining)`).
  - Flapping rate indicator showing action attempts within the 15-minute sliding window.
- **Policy Allowlist Cards**:
  - Visual summary showing approved targets vs. protected system processes that cannot be modified.

### 5. Interactive Demo Fault Control Panel
- **One-Click Chaos Triggering**:
  - Control cards for all 5 demo fault types (`CPU Spin`, `Memory Leak`, `Service Crash`, `Disk Fill`, `Deadlock`).
  - Configuration sliders (e.g. CPU intensity, Disk write cap in MB).
  - Live buttons: **Trigger Fault**, **Stop Fault**, and **Reset Demo Targets**.
- **Live Demonstration Workflow**:
  1. Operator clicks **Trigger CPU Spin**.
  2. Telemetry chart shows CPU utilization spiking above 90%.
  3. Detection engine triggers within 1 polling interval.
  4. Diagnosis engine attributes the spike to compute-bound loop with 95% confidence.
  5. Guardrail evaluates target allowlist and cooldown, approving `terminate_demo_process`.
  6. Recovery executor safely terminates the demo process.
  7. Verification engine samples CPU and confirms it normalized below threshold.
  8. Incident record is saved to SQLite and appears instantly on the dashboard timeline.

### 6. Terminal / CLI Demonstration Support
For headless or terminal-only demonstration environments:
- Rich terminal telemetry views via `python -m self_healing monitor`.
- Real-time streaming daemon logs with colored stage tags via `python -m self_healing run`.
- Single-command automated verification script validating the end-to-end stack.

---

## 5. Verification & Test Suite Summary

Every layer is rigorously covered by unit and integration tests.

| Test Module | Coverage Focus | Test Count | Status |
|---|---|---|---|
| [`test_proc_reader.py`](tests/test_proc_reader.py) | `/proc` stat, uptime, meminfo, loadavg parsing | 9 | Passed |
| [`test_monitoring.py`](tests/test_monitoring.py) | Telemetry collection, snapshots, ring buffers | 6 | Passed |
| [`test_service_inspector.py`](tests/test_service_inspector.py) | Systemd unit querying and regex protection | 3 | Passed |
| [`test_detection.py`](tests/test_detection.py) | Rule detectors (CPU, Memory, Service, Disk, Deadlock) | 12 | Passed |
| [`test_diagnosis.py`](tests/test_diagnosis.py) | Diagnostic engine, root causes, confidence | 11 | Passed |
| [`test_guardrails.py`](tests/test_guardrails.py) | 8-stage policy engine, cooldowns, flapping | 17 | Passed |
| [`test_recovery.py`](tests/test_recovery.py) | Typed recovery actions, blast-radius, dry-run | 13 | Passed |
| [`test_verification.py`](tests/test_verification.py) | Verification probes, RetryPolicy, escalation | 25 | Passed |
| [`test_incidents.py`](tests/test_incidents.py) | Persistent SQLite CRUD, indexing, concurrency | 12 | Passed |
| [`test_orchestrator.py`](tests/test_orchestrator.py) | Autonomous closed loop, deduplication, lifecycle | 8 | Passed |
| [`test_api.py`](tests/test_api.py) | FastAPI 13 endpoints, schemas, injection safety | 13 | Passed |
| [`test_fault_injection.py`](tests/test_fault_injection.py) | 5 sandboxed demo fault injectors | 18 | Passed |
| [`test_interfaces.py`](tests/test_interfaces.py) | Core subsystem contracts and isolation | 10 | Passed |
| **Total** | **Full System Test Suite** | **185** | **100% Passed** |

---

## 6. Project Architecture Index

- **Documentation**:
  - [`docs/architecture.md`](docs/architecture.md): Overall system architecture.
  - [`docs/api_backend.md`](docs/api_backend.md): Full FastAPI endpoint documentation.
  - [`docs/orchestrator.md`](docs/orchestrator.md): Closed-loop orchestrator architecture.
  - [`docs/incident_management.md`](docs/incident_management.md): SQLite persistence schema and queries.
  - [`docs/verification_subsystem.md`](docs/verification_subsystem.md): Post-recovery verification subsystem.
  - [`docs/recovery_executor.md`](docs/recovery_executor.md): Recovery action handlers and allowlists.
  - [`docs/guardrails.md`](docs/guardrails.md): 8 safety guardrail checks.
  - [`docs/diagnosis_engine.md`](docs/diagnosis_engine.md): Deterministic diagnosis rules.
  - [`docs/detection_rules.md`](docs/detection_rules.md): Rule-based detection catalog.
  - [`docs/monitoring_metrics.md`](docs/monitoring_metrics.md): Telemetry metrics catalog.
  - [`docs/fault_injection.md`](docs/fault_injection.md): Controlled demo fault injection framework.
  - [`AGENTS.md`](AGENTS.md): Safety rules and development constraints.
