# Project Implementation Plan: Autonomous Fault Detection & Self-Healing System for Linux

## 1. Executive Summary & Research Objectives

The goal of this research project is to design, implement, and evaluate an **autonomous, user-space fault detection and self-healing system** for Linux operating environments (specifically validated on Ubuntu Linux inside a virtual machine).

Modern production systems suffer from transient and stateful faults—such as runaway CPU utilization, memory leaks, zombie process accumulations, thread deadlocks, hung sockets, and service crashes. Existing automated recovery mechanisms often rely on rigid restart scripts, unconstrained shell execution, or high-level container orchestrators that lack fine-grained, in-OS process observability and recovery semantics.

This project introduces a deterministic, safety-constrained, closed-loop framework operating strictly in Linux user space:
$$\text{MONITOR} \longrightarrow \text{DETECT} \longrightarrow \text{DIAGNOSE} \longrightarrow \text{GUARDRAIL} \longrightarrow \text{HEAL} \longrightarrow \text{VERIFY}$$

### Core Research Objectives
1. **Zero-Arbitrary-Execution Safety Guarantee**: Guarantee that recovery actions are strictly confined to a typed, allowlisted registry with explicit parameter bounds, never invoking unvalidated shell strings or hallucinated agent commands.
2. **Deterministic Baseline Priority**: Establish a deterministic, transparent rule-based detection engine before any statistical or machine-learning-based anomaly detection (e.g., Isolation Forest) is introduced.
3. **Strict Blast-Radius Containment**: Guarantee that monitoring and recovery operations only interact with explicitly designated, allowlisted demo workloads and services, completely isolating the host VM's system processes.
4. **Verifiable Auditability & Closed-Loop Feedback**: Ensure every intervention produces an immutable incident record and is immediately followed by a closed-loop verification phase to confirm recovery or escalate safely.

---

## 2. Technical Stack & Runtime Environment

- **Operating System**: Linux (Ubuntu 26.04.1 LTS x86_64, Linux Kernel 7.0 generic) inside a VMware Virtual Platform.
- **Runtime Environment**: Python 3.14.4 within virtual environment (`.venv`).
- **Process & System Observability**: `psutil` (7.2.2), Linux `/proc` filesystem parsing, `cgroup` v2 inspection, and systemd D-Bus/user-space interfaces.
- **Data Contracts & Modeling**: `pydantic` (2.13.5) and `pydantic_core` for strictly typed schemas, action descriptors, policy definitions, and incident records.
- **API & Operator Interface**: `fastapi` (0.142.2), `uvicorn` (0.54.0), and `starlette` for local monitoring and configuration endpoints.
- **Storage & Audit Logging**: Embedded SQLite database via standard Python libraries, alongside structured JSONL audit logs.
- **Testing & Verification**: `pytest` (9.1.1) for unit and integration testing; dedicated simulated fault injectors for controlled evaluation.
- **Future ML / Anomaly Baseline** (Phase 11 only): `scikit-learn` (1.9.1), `numpy` (2.5.3), `scipy` (1.18.1), and `pandas` (3.0.6).

---

## 3. Phased Implementation Roadmap

```
+---------------------------------------------------------------------------------+
| Phase 0: Project Architecture, Packaging & Domain Contracts                     |
+---------------------------------------+-----------------------------------------+
                                        |
+---------------------------------------v-----------------------------------------+
| Phase 1: Monitoring Subsystem & Allowlisted Target Registry                     |
+---------------------------------------+-----------------------------------------+
                                        |
+---------------------------------------v-----------------------------------------+
| Phase 2: Deterministic Rule-Based Detection Engine                              |
+---------------------------------------+-----------------------------------------+
                                        |
+---------------------------------------v-----------------------------------------+
| Phase 3: Root Cause Diagnosis & Telemetry Context Aggregator                    |
+---------------------------------------+-----------------------------------------+
                                        |
+---------------------------------------v-----------------------------------------+
| Phase 4: Policy Guardrails & Dry-Run Engine                                     |
+---------------------------------------+-----------------------------------------+
                                        |
+---------------------------------------v-----------------------------------------+
| Phase 5: Typed Allowlisted Recovery Action Registry                             |
+---------------------------------------+-----------------------------------------+
                                        |
+---------------------------------------v-----------------------------------------+
| Phase 6: Post-Healing Verification & Closed-Loop Escalation                     |
+---------------------------------------+-----------------------------------------+
                                        |
+---------------------------------------v-----------------------------------------+
| Phase 7: Persistent Incident Store & Structured Audit Trail                     |
+---------------------------------------+-----------------------------------------+
                                        |
+---------------------------------------v-----------------------------------------+
| Phase 8: Controlled Demo Workloads & Safe Fault Injection Suite                 |
+---------------------------------------+-----------------------------------------+
                                        |
+---------------------------------------v-----------------------------------------+
| Phase 9: Management API & Minimal Operator Web Dashboard / CLI                  |
+---------------------------------------+-----------------------------------------+
                                        |
+---------------------------------------v-----------------------------------------+
| Phase 10: End-to-End System Integration, Chaos Testing & Benchmarks             |
+---------------------------------------+-----------------------------------------+
                                        |
+---------------------------------------v-----------------------------------------+
| Phase 11 (Optional / Research): Statistical Anomaly Detection (Isolation Forest)|
+---------------------------------------------------------------------------------+
```

### Phase 0: Project Architecture, Packaging & Domain Contracts
- **Objective**: Establish the repository layout, configuration schema, typing baseline, and core domain entities.
- **Key Deliverables**:
  - `pyproject.toml` and package configuration for `self_healing`.
  - Directory structure separating modules: `monitoring`, `targets`, `detection`, `diagnosis`, `policy`, `recovery`, `verification`, `incidents`, `api`, `demo`.
  - Base domain models (`MetricSnapshot`, `TargetSpec`, `FaultEvent`, `DiagnosisReport`, `PolicyEvaluation`, `RecoveryActionRecord`, `VerificationResult`, `IncidentRecord`).
- **Acceptance Criteria**: All models compile under Python 3.14 with Pydantic v2; strict type annotations verified with zero import cycles.

### Phase 1: Monitoring Subsystem & Allowlisted Target Registry
- **Objective**: Build a high-performance, non-intrusive Linux user-space metrics collector and a strict target allowlist.
- **Key Deliverables**:
  - `TargetRegistry`: In-memory and configuration-driven registry defining approved demo targets (e.g., target names, command patterns, service names, port numbers, working directories).
  - Safety filter: Hard rejection of any process not matching approved demo target specifications (blocking PIDs like 1, system daemons, user shells).
  - `SystemMonitor`: Periodic collector for CPU, virtual memory, disk I/O, file descriptors, open ports, and thread count via `psutil` and `/proc`.
  - `ProcessMonitor`: Filtered collector gathering per-process telemetry only for approved targets.
- **Acceptance Criteria**: Metrics collection cycle completes in $< 100\text{ ms}$; strict unit tests confirm that system processes are completely ignored and cannot be targeted.

### Phase 2: Deterministic Rule-Based Detection Engine
- **Objective**: Implement deterministic threshold and pattern-based fault detection without probabilistic guesswork.
- **Key Deliverables**:
  - Rule specification interfaces (`FaultRule`, `EvaluationContext`, `RuleResult`).
  - Predefined deterministic rules:
    - `HighCpuRule`: Sustained CPU above threshold ($X\%$ over $N$ windows).
    - `MemoryLeakRule`: Monotonic RSS/VMS memory growth exceeding critical limit.
    - `ZombieProcessRule`: Detection of `Z` state child processes under demo targets.
    - `HungProcessRule`: Unresponsive socket/port or zero I/O progress during active request state.
    - `ProcessCrashRule`: Unexpected termination of an active supervised service.
    - `FileDescriptorExhaustionRule`: FD usage approaching per-process soft/hard limits.
- **Acceptance Criteria**: 100% precision on synthetic telemetry fixtures; deterministic triggers fire within designated window; zero false triggers on nominal load fixtures.

### Phase 3: Root Cause Diagnosis & Telemetry Context Aggregator
- **Objective**: Correlate detected fault events with process lineage, resource history, and recent logs to produce a structured diagnosis.
- **Key Deliverables**:
  - `DiagnosisEngine`: Evaluates fault events against dependency graphs and temporal metric buffers.
  - Context enrichment: Attaches 60-second historical metric window, process environment, thread counts, open socket states, and recent stderr snippets.
  - Diagnosis output: Strongly typed `DiagnosisReport` containing probable root cause, confidence score, affected target, and recommended recovery intent.
- **Acceptance Criteria**: Generates clear, structured diagnosis reports detailing root cause without invoking external or hallucinated commands.

### Phase 4: Policy Guardrails & Dry-Run Engine
- **Objective**: Enforce safety boundaries, rate limiting, flapping detection, blast-radius limits, and operational modes.
- **Key Deliverables**:
  - `PolicyEngine`: Validates any proposed healing action against security and operational rules.
  - `DryRunManager`: Global and per-rule toggle ensuring recovery actions can be simulated and logged without applying OS-level changes.
  - Guardrail policies:
    - **Target Scope Guard**: Blocks any action whose target is not in the active approved list.
    - **Flapping Prevention**: Maximum $M$ recovery actions per target within time window $T$ (e.g., max 3 restarts per 15 minutes); locks out target and alerts if threshold exceeded.
    - **Cooldown Guard**: Enforces mandatory quiet period between consecutive healing attempts.
    - **Dangerous Action Prohibition**: Outlaws raw shell commands, recursive directory deletions, kernel parameter alterations, or unmanaged signals.
- **Acceptance Criteria**: Attempting an action on an unlisted PID or exceeding rate limits raises a `GuardrailViolation` and records an incident without executing the action.

### Phase 5: Typed Allowlisted Recovery Action Registry
- **Objective**: Implement safe, typed, parameterized recovery executors using user-space Linux system calls and standard libraries.
- **Key Deliverables**:
  - Base abstract class `BaseRecoveryAction` with validation, execution, and rollback stubs.
  - Explicit Action Registry:
    1. `GracefulTerminateAction`: Sends `SIGTERM`, waits for grace period, verifies termination.
    2. `ForcedKillAction`: Escalation to `SIGKILL` only after `SIGTERM` failure and target re-validation.
    3. `RestartDemoServiceAction`: Restarts a registered demo user-space daemon or systemd user unit.
    4. `ReniceProcessAction`: Adjusts process nice value within safe boundaries ($0 \le \text{nice} \le 19$).
    5. `CleanDemoTempDirAction`: Deletes temporary files strictly within an approved, designated scratch directory (`demo/scratch/`).
  - Zero-shell enforcement: Execution via direct OS APIs (`os.kill`, `psutil.Process`, `subprocess.run(args, shell=False)` with pre-validated arguments).
- **Acceptance Criteria**: 100% rejection of dynamic strings or unallowlisted actions; successful execution of typed actions against dummy demo processes.

### Phase 6: Post-Healing Verification & Closed-Loop Escalation
- **Objective**: Validate that recovery restored system and service health, or safely escalate if the target remains degraded.
- **Key Deliverables**:
  - `VerificationEngine`: Executes target-specific health probes (HTTP GET `/health`, TCP port check, process alive check, memory stabilization check).
  - Configurable verification windows (e.g., sample at $t+2\text{s}$, $t+5\text{s}$, $t+10\text{s}$).
  - Closed-loop outcomes: `HEALTHY`, `UNRESOLVED`, `FLAPPING`, or `ESCALATED`.
  - Fail-safe escalation: Marks target as unhealable and halts automatic remediation to prevent cascading instability.
- **Acceptance Criteria**: Detects failed restarts or continued resource exhaustion, terminating remediation loops safely.

### Phase 7: Persistent Incident Store & Structured Audit Trail
- **Objective**: Persist comprehensive incident lifecycles to disk for historical auditing, forensic analysis, and reporting.
- **Key Deliverables**:
  - `IncidentStore`: SQLite database with migrations for storing `IncidentRecord`.
  - Structured JSON Lines audit logger with cryptographically verifiable sequence or timestamps.
  - Query interface: Retrieve incidents by target, fault type, time range, status, or dry-run flag.
- **Acceptance Criteria**: Complete record persisted for every healing lifecycle, containing original telemetry, rule triggered, guardrail decision, action executed, and verification result.

### Phase 8: Controlled Demo Workloads & Safe Fault Injection Suite
- **Objective**: Provide self-contained demo applications and fault injectors for hands-on, reproducible demonstrations and tests.
- **Key Deliverables**:
  - Demo Applications:
    - `demo_web_service.py`: Lightweight HTTP worker with simulated work endpoints and health checks.
    - `demo_worker_service.py`: Background queue processor.
  - Fault Injectors (controlled scripts modifying only demo processes):
    - `inject_cpu_spin.py`: Induces tight loop in demo target.
    - `inject_memory_leak.py`: Allocates memory in demo target until threshold crossed.
    - `inject_hung_socket.py`: Simulates unresponsive listener or thread lock.
    - `inject_crash.py`: Induces sudden crash/exit in demo worker.
- **Acceptance Criteria**: Fault injectors only target demo instances; full recovery loop successfully detects, heals, and verifies without manual intervention.

### Phase 9: Management API & Minimal Operator Web Dashboard / CLI
- **Objective**: Expose system status, active incidents, policies, and manual controls to operators.
- **Key Deliverables**:
  - FastAPI application:
    - `GET /api/status`: Overall system health, daemon status, and active targets.
    - `GET /api/incidents`: List recent incidents with filtering.
    - `GET /api/incidents/{id}`: Detailed incident lifecycle inspection.
    - `POST /api/policy/dry-run`: Toggle dry-run mode on/off.
    - `GET /api/targets`: List currently registered and approved targets.
  - Minimal, lightweight web dashboard (single HTML/JS page) or Rich CLI terminal dashboard (`self-healing status`).
- **Acceptance Criteria**: Web UI and API respond with sub-50ms latency; allows toggling dry-run mode and inspecting incidents.

### Phase 10: End-to-End System Integration, Chaos Testing & Benchmarks
- **Objective**: Run exhaustive integration test suites, stress testing, and benchmark recovery latency and reliability.
- **Key Deliverables**:
  - Comprehensive automated test suite in `tests/`.
  - End-to-end chaos test runner executing automated inject-heal-verify cycles.
  - Benchmark report measuring:
    - Mean Time to Detect (MTTD).
    - Mean Time to Remediate (MTTR).
    - False positive rate under baseline load.
    - Verification accuracy rate.
- **Acceptance Criteria**: 100% test pass rate across unit and integration suites; zero safety boundary violations during chaos injection.

### Phase 11 (Optional / Research): Statistical Anomaly Detection (Isolation Forest)
- **Objective**: Implement ML-based unsupervised anomaly detection as a secondary, advisory layer after deterministic rules are fully validated.
- **Key Deliverables**:
  - Baseline feature extractor: rolling mean, standard deviation, and delta of resource metrics.
  - `IsolationForestDetector`: Unsupervised model trained on baseline healthy workload metrics.
  - Advisory correlation: Anomaly scores provide diagnostic context or feed into diagnostic confirmation, but do NOT execute unguided recovery actions directly.
- **Acceptance Criteria**: ML pipeline operates independently from deterministic pipeline without regressing rule-based reliability.

---

## 4. Verification & Testing Strategy

In compliance with Rule 14, every phase will follow rigorous verification:
1. **Automated Unit Tests**:
   - Mocked `/proc` and `psutil` data to test detection rules against known telemetry curves.
   - Guardrail test cases covering every edge case (invalid targets, rate-limiting violations, missing parameters).
   - Action registry test cases verifying exact signal dispatch and argument validation.
2. **Integration Tests**:
   - Running real user-space demo processes and asserting process termination/restart within sandbox bounds.
   - Testing persistence in SQLite and verifying schema consistency.
3. **Dry-Run Validation**:
   - Running full detection cycles in `DRY_RUN=True` mode, asserting that all actions produce log entries and audit records with zero side effects on running processes.
4. **Safety Regression Tests**:
   - Explicit tests asserting that attempting to target PID 1, systemd, sshd, or arbitrary user PIDs fails immediately with security exceptions.

---

## 5. Development Invariants & Safety Checklist

| Invariant | Enforcement Mechanism |
| :--- | :--- |
| **No Arbitrary Shell Execution** | Action registry uses strictly typed classes; no `shell=True` in subprocess calls; no dynamic shell strings. |
| **Target Allowlist Only** | `TargetRegistry` strictly validates process name, path, and PID before any action is approved. |
| **Mandatory Guardrail Approval** | Pipeline cannot transition from Diagnosis to Recovery without an affirmative `PolicyEvaluation` token. |
| **Mandatory Incident Auditing** | Every transition emits a structured event; recovery execution is impossible without an active `IncidentRecord`. |
| **Mandatory Post-Healing Verification** | Recovery is marked incomplete until health probes confirm recovery or trigger escalation. |
| **Dry-Run Capability** | Default or flag-activated dry-run mode bypasses OS mutations while maintaining complete logging. |
| **User-Space Only** | Operates strictly via standard user-space APIs without kernel modules or eBPF kernel patching. |
