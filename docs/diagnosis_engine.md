# Deterministic Root Cause Diagnosis Engine

## 1. Overview and Core Invariants

The **Diagnosis Subsystem** implements deterministic, explainable root cause analysis for the Linux Self-Healing Framework. Operating immediately after the detection phase, it takes a `DetectionEvent` and current system metrics, evaluates the evidence, and generates a structured, traceable `DiagnosisResult`.

### Core Safety & Architecture Invariants
- **Zero LLM Dependency**: Reasoning is 100% deterministic and rule-grounded. No large language models, stochastic heuristics, or hallucinated Linux commands are permitted (`AGENTS.md` Rule 5).
- **Strict Separation from Recovery**: The diagnosis engine evaluates evidence and recommends an allowlisted recovery class; it **never executes** recovery commands (`AGENTS.md` Rule 9 & 15).
- **Explainable Traceability**: Every conclusion is accompanied by a step-by-step reasoning log (`traceability_log`) that cites specific observed metrics, timestamps, and state transitions.
- **Allowlisted Action Recommendations**: Remediations are strictly drawn from the typed `ActionType` registry (`GRACEFUL_TERMINATE`, `RESTART_SERVICE`, `CLEAN_TEMP_DIR`, `RENICE_PROCESS`).

---

## 2. Pipeline and Data Flow

```
+-----------------------------------------------------------------------------------+
|               DetectionEvent                       Current System Metrics         |
|   (Emitted by Phase 4 detector)             (SystemSnapshot or MetricSnapshot)    |
+-----------------------------------------------------------------------------------+
                                       |
                                       v
+-----------------------------------------------------------------------------------+
|                        DeterministicDiagnosisEngine                               |
|                  (Pure deterministic rule-based correlator)                       |
+-----------------------------------------------------------------------------------+
         |               |                 |                 |               |
         v               v                 v                 v               v
  +-------------+ +---------------+ +---------------+ +-------------+ +---------------+
  | CPU Runaway | | Memory Leak   | | Service Crash | | Disk Growth | |   Deadlock    |
  |  Reasoning  | |   Reasoning   | |   Reasoning   | |  Reasoning  | |   Reasoning   |
  +-------------+ +---------------+ +---------------+ +-------------+ +---------------+
         |               |                 |                 |               |
         +---------------+-----------------+-----------------+---------------+
                                       |
                                       v
+-----------------------------------------------------------------------------------+
|                               DiagnosisResult                                     |
|   - diagnosis_id: str (UUID)                                                      |
|   - event_id: str                                                                 |
|   - fault_type: FaultType                                                         |
|   - target_id: str                                                                |
|   - evidence: Dict[str, Any] (fused detection + system metrics)                  |
|   - probable_cause: str (concise, deterministic root cause explanation)           |
|   - severity: FaultSeverity                                                       |
|   - confidence: float (0.0 - 1.0, derived from evidence strength)                 |
|   - recommended_action: ActionType (allowlisted action registry)                  |
|   - traceability_log: List[str] (verifiable reasoning trail)                      |
+-----------------------------------------------------------------------------------+
```

---

## 3. DiagnosisResult Contract

The output of the engine is the strongly typed `DiagnosisResult` Pydantic v2 model:

| Field | Type | Description |
| :--- | :--- | :--- |
| `diagnosis_id` | `str` (UUID) | Unique diagnostic identifier |
| `event_id` | `str` (UUID) | Identifier of the originating `DetectionEvent` |
| `fault_type` | `FaultType` | Anomaly category being diagnosed |
| `target_id` | `str` | Identifier of the affected supervised demo target |
| `evidence` | `Dict[str, Any]` | Consolidated telemetry evidence from detection and host state |
| `probable_cause` | `str` | Concise, evidence-backed root cause explanation |
| `severity` | `FaultSeverity` | Diagnostic severity (`LOW`, `MEDIUM`, `HIGH`, `CRITICAL`) |
| `confidence` | `float` ($0.0 \le c \le 1.0$) | Deterministic confidence score based on evidence strength |
| `recommended_action`| `ActionType` | Recommended recovery class from typed allowlist |
| `traceability_log` | `List[str]` | Sequential deduction steps explaining the conclusion |

---

## 4. Deterministic Reasoning by Fault Type

### 4.1 CPU Runaway (`HIGH_CPU`)
- **Reasoning**: Evaluates target process CPU series against host system metrics (1-minute/5-minute load averages, context switches).
- **Probable Cause**: Target entered a compute-bound arithmetic spin loop on 1 core without yielding CPU slices.
- **Traceability Trail**:
  1. Observed sustained CPU utilization $\ge 90.0\%$ across consecutive telemetry samples.
  2. Window duration confirmed exceeding configured threshold.
  3. Cross-referenced host load average and scheduler metrics.
  4. Ruled out I/O waiting or external lock contention.
  5. Mapped to allowlisted recovery action `ActionType.GRACEFUL_TERMINATE`.
- **Confidence**: `0.95`.
- **Recommended Action**: `ActionType.GRACEFUL_TERMINATE`.

### 4.2 Abnormal Memory (`MEMORY_LEAK`)
- **Reasoning**: Analyzes monotonic RSS expansion rate and memory budget violations against host available memory.
- **Probable Cause**: Target exceeded designated memory budget or exhibits monotonic heap allocation without garbage collection.
- **Traceability Trail**:
  1. Analyzed process RSS progression over time.
  2. Verified strictly non-negative memory delta across all observed sample intervals.
  3. Checked host memory pressure (RAM percentage, swap usage).
  4. Inferred unreleased heap allocations or progressive buffer accumulation.
  5. Mapped to allowlisted recovery action `ActionType.RESTART_SERVICE`.
- **Confidence**: `0.95`.
- **Recommended Action**: `ActionType.RESTART_SERVICE`.

### 4.3 Service Failure (`PROCESS_CRASH`)
- **Reasoning**: Correlates service unit state (`failed`/`inactive`), process exit codes, and listening socket health.
- **Probable Cause**: Target service suffered an abrupt fatal termination (exit code $1$) and port closed.
- **Traceability Trail**:
  1. Inspected service telemetry: target unit reported inactive/dead.
  2. Evaluated process exit context: observed termination with non-zero exit code.
  3. Confirmed service availability failure: process not present in OS process table.
  4. Mapped to allowlisted recovery action `ActionType.RESTART_SERVICE`.
- **Confidence**: `1.00`.
- **Recommended Action**: `ActionType.RESTART_SERVICE`.

### 4.4 Disk Exhaustion (`DISK_GROWTH`)
- **Reasoning**: Measures file byte accumulation in monitored scratch directory and host mount partition utilization.
- **Probable Cause**: Monitored scratch log directory accumulated excessive unrotated log files exceeding threshold.
- **Traceability Trail**:
  1. Measured disk usage in monitored scratch directory against quota.
  2. Evaluated root mount usage percentage.
  3. Identified rapid log accumulation without retention rotation.
  4. Mapped to allowlisted recovery action `ActionType.CLEAN_TEMP_DIR`.
- **Confidence**: `0.98`.
- **Recommended Action**: `ActionType.CLEAN_TEMP_DIR`.

### 4.5 Deadlock (`DEADLOCK`)
- **Reasoning**: Analyzes multi-threading ($\ge 3$ threads), process state (`SLEEPING`), and CPU progress ($0.0\%$).
- **Probable Cause**: Target process is permanently deadlocked in circular thread mutex contention across worker threads with $0.0\%$ CPU activity and zero progress.
- **Traceability Trail**:
  1. Analyzed thread telemetry: observed $\ge 3$ active worker threads.
  2. Verified process execution state: kernel state confirmed as `SLEEPING` across all samples.
  3. Verified CPU activity: utilization strictly $0.0\%$, ruling out compute loops.
  4. Confirmed circular mutex deadlock (AB-BA lock dependency).
  5. Mapped to allowlisted recovery action `ActionType.GRACEFUL_TERMINATE`.
- **Confidence**: `0.95`.
- **Recommended Action**: `ActionType.GRACEFUL_TERMINATE`.

---

## 5. Verification & Test Evidence

The test suite in `tests/test_diagnosis.py` validates the entire subsystem:
```
tests/test_diagnosis.py::test_diagnose_cpu_runaway PASSED
tests/test_diagnosis.py::test_diagnose_memory_leak_budget_exceeded PASSED
tests/test_diagnosis.py::test_diagnose_memory_leak_monotonic_growth PASSED
tests/test_diagnosis.py::test_diagnose_service_crash PASSED
tests/test_diagnosis.py::test_diagnose_disk_exhaustion_log_directory PASSED
tests/test_diagnosis.py::test_diagnose_deadlock PASSED
tests/test_diagnosis.py::test_diagnosis_result_backward_compatibility_attributes PASSED
```
Full repository test suite: **100 passed in 5.52s (100% pass rate)**.
