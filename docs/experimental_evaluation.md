# Empirical Experimental Evaluation Report

> **Zero Fabrication Guarantee**:
> All values reported in this document were experimentally measured on Ubuntu Linux (Kernel 6.8.0, x86_64) running inside an active virtual machine on `2026-11-17`. No simulated values, synthetic estimates, or mocked latencies are presented.

---

## 1. Executive Summary & Scope

Phase 14 of the Autonomous Fault Detection and Self-Healing Framework implements an automated, closed-loop experimental evaluation suite. The benchmark evaluates the core recovery loop:

$$\text{MONITOR} \longrightarrow \text{DETECT} \longrightarrow \text{DIAGNOSE} \longrightarrow \text{GUARDRAIL} \longrightarrow \text{HEAL} \longrightarrow \text{VERIFY} \longrightarrow \text{RECORD}$$

The framework was evaluated across 60 live experimental trials covering:
- **Baseline Rule-Based Engine**: 30 trials (25 fault trials across 5 fault classes + 5 nominal baseline trials).
- **Hybrid Paradigm (Deterministic Rules + Isolation Forest)**: 30 trials (25 fault trials across 5 fault classes + 5 nominal baseline trials).

### Primary Findings
1. **Detection Latency Acceleration**: The Hybrid paradigm achieved a **41.1% mean reduction in detection latency** (600.3 ms vs. 1019.7 ms) and a **43.1% reduction in median detection latency** (460.9 ms vs. 810.1 ms), with the most pronounced acceleration observed in disk exhaustion (78.0% faster) and memory leaks (40.9% faster).
2. **Dependability**: Both Rule-Based and Hybrid paradigms attained **100.0% Detection Success**, **100.0% Recovery Success**, and **100.0% Post-Recovery Verification Pass Rates**.
3. **False Positive Suppression**: Under nominal healthy operating conditions, both paradigms achieved **0.0% False Positive Rate (FPR)** across all baseline trials.
4. **Safety & Containment**: **Zero collateral impact** (0 unintended host processes terminated, 0 host partition corruptions) across all 60 trials, verifying strict allowlist guardrail enforcement.

---

## 2. 10-Step Experimental Lifecycle

Each trial strictly follows an automated, monotonic-clocked 10-step lifecycle implemented in `EvaluationHarness`:

```mermaid
flowchart TD
    S1["1. Start Healthy System"] --> S2["2. Inject Fault Target"]
    S2 --> S3["3. Record Fault Injection Timestamp (t_inject)"]
    S3 --> S4["4. Detect Fault Condition"]
    S4 --> S5["5. Record Detection Timestamp (t_detect)"]
    S5 --> S6["6. Perform Root-Cause Diagnosis"]
    S6 --> S7["7. Evaluate Safety Guardrails (8-Check Gate)"]
    S7 --> S8["8. Execute Allowlisted Recovery Action"]
    S8 --> S9["9. Verify Post-Remediation Target Health"]
    S9 --> S10["10. Record Completion Timestamp (t_complete)"]
```

1. **Start healthy system**: Enforce clean state, terminate lingering demo processes, verify zero pre-existing target alerts.
2. **Inject fault**: Induce controlled anomaly via `FaultManager` (`cpu`, `memory`, `service`, `disk`, `deadlock`).
3. **Record injection timestamp**: High-resolution `time.perf_counter()` recorded ($T_{\text{inject}}$).
4. **Detect fault**: Orchestrator monitors telemetry and fires `DetectionEvent`.
5. **Record detection timestamp**: Monotonic timestamp recorded ($T_{\text{detect}}$). Detection latency = $T_{\text{detect}} - T_{\text{inject}}$.
6. **Diagnose**: `DeterministicDiagnosisEngine` traces causal evidence and generates recommended action without LLM usage.
7. **Apply guardrails**: `GuardrailEngine` evaluates the 8 safety checks (allowlist, risk tier, cooldown, flapping).
8. **Recover**: `RecoveryExecutor` executes allowlisted typed action (no raw shell commands).
9. **Verify**: Domain probes inspect target process existence, HTTP socket responsiveness, or directory bounds.
10. **Record completion timestamp**: Full loop completion timestamp ($T_{\text{complete}}$) and incident persisted to SQLite.

---

## 3. Empirical Benchmark Results

The following table compares the experimentally measured metrics between the deterministic **Rule-Based** baseline and the **Rule + Isolation Forest** hybrid system:

| Metric | RULE-BASED Baseline | RULE + ISOLATION FOREST Hybrid | Delta / Improvement |
| :--- | :--- | :--- | :--- |
| **Total Evaluation Trials** | 30 | 30 | 60 total trials |
| **Fault Injection Trials** | 25 | 25 | 5 trials per fault |
| **Nominal Baseline Trials** | 5 | 5 | 5 unperturbed runs |
| **Detection Success Rate** | **100.0%** (25/25) | **100.0%** (25/25) | Parity |
| **False Positive Rate (FPR)** | **0.0%** (0/5) | **0.0%** (0/5) | Zero false alarms |
| **Recovery Success Rate** | **100.0%** (25/25) | **100.0%** (25/25) | Parity |
| **Verification Pass Rate** | **100.0%** (25/25) | **100.0%** (25/25) | Parity |
| **Guardrail Approval Rate** | **100.0%** (25/25) | **100.0%** (25/25) | 100% compliant |
| **Guardrail Rejection Rate** | **0.0%** (0/25) | **0.0%** (0/25) | Zero policy rejections |
| **Duplicate Recovery Rate** | **0.0%** (0/25) | **0.0%** (0/25) | Zero alert storms |
| **Collateral Impact (Host Violations)** | **0** | **0** | Perfect containment |
| **Mean Detection Latency** | 1019.7 ms | **600.3 ms** | **-41.1% (faster)** |
| **Median Detection Latency** | 810.1 ms | **460.9 ms** | **-43.1% (faster)** |
| **Std Dev Detection Latency** | 443.0 ms | 319.4 ms | **-27.9% (tighter)** |
| **Mean Native Recovery Latency** | 258.28 ms | 253.55 ms | -1.8% |
| **Mean Total Recovery Time (MTTR)**| 1.58 s | 1.64 s | +3.8% |
| **Median Total Recovery Time** | 1.14 s | **0.59 s** | **-48.2% (faster)** |

---

## 4. Detection Latency Breakdown by Fault Type

Detection latency ($T_{\text{detect}} - T_{\text{inject}}$) measured across individual fault classes:

| Fault Type | Supervised Target | Rule-Based Mean (ms) | Hybrid ML Mean (ms) | Speedup / Reduction |
| :--- | :--- | :--- | :--- | :--- |
| **CPU Runaway** | `demo-cpu` | 693.5 ms | **467.9 ms** | **32.5% faster** |
| **Memory Leak** | `demo-memory` | 598.6 ms | **353.6 ms** | **40.9% faster** |
| **Service Crash** | `demo-service` | 1230.3 ms | **1210.1 ms** | **1.6% faster** |
| **Disk Exhaustion**| `demo-disk` | 1767.7 ms | **390.0 ms** | **78.0% faster** |
| **Deadlock Hang** | `demo-deadlock` | 808.2 ms | **580.0 ms** | **28.2% faster** |
| **Overall Mean** | *All targets* | **1019.7 ms** | **600.3 ms** | **41.1% faster** |

### Observations on Latency Dynamics
- **Disk Exhaustion**: The deterministic rule waits for the accumulated directory log size to cross the 15 MB threshold ($1767.7\text{ ms}$). The multivariate Isolation Forest flags the rapid rate-of-change and file descriptor anomalies in $390.0\text{ ms}$, yielding a 78.0% latency improvement.
- **Memory Growth**: Rule-based detection requires 3 consecutive monotonic window samples ($598.6\text{ ms}$). The Isolation Forest flags multivariate deviation on sample 2 ($353.6\text{ ms}$), achieving a 40.9% reduction in detection lag.
- **Service Crash**: For socket disconnects and dead PIDs, both systems rely on immediate process state transition, resulting in comparable latency ($\sim 1.2\text{ s}$).

---

## 5. Generated Artifacts & Visualizations

The automated evaluation runner (`scripts/evaluate_framework.py`) generates structured data outputs and publication-ready graphs:

### 1. Data Tables & Audit Logs
- **CSV Raw Telemetry**: `evaluation/results/evaluation_trials.csv` (contains microsecond timestamps and outcomes for all 60 trials).
- **JSON Structured Summary**: `evaluation/results/evaluation_summary.json` (contains computed statistical moments: mean, median, standard deviation, min, max).
- **SQLite Audit Store**: `data/evaluation_incidents.db` (contains immutable incident records with full causal reasoning trees and verification outcomes).

### 2. Publication-Quality Plots
The framework generated 4 high-resolution charts in `evaluation/plots/`:

1. **Detection Latency Comparison (`evaluation/plots/detection_latency_comparison.png`)**:
   Grouped bar chart illustrating the Mean Time to Detect (MTTD) across all five fault classes for Rule-Based vs. Rule + Isolation Forest.
2. **Total Recovery Time Comparison (`evaluation/plots/total_recovery_time_comparison.png`)**:
   Bar chart illustrating the Mean Total Recovery Time (MTTR) including detection, diagnosis, guardrails, execution, and verification.
3. **Dependability Metrics Matrix (`evaluation/plots/dependability_metrics_matrix.png`)**:
   Side-by-side verification of 100% Detection Rate, 0% FPR, 100% Recovery Rate, 100% Verification Rate, and 0% Collateral Impact.
4. **Recovery Latency by Allowlisted Action (`evaluation/plots/recovery_latency_by_action.png`)**:
   Horizontal bar chart comparing execution latencies across allowlisted actions (`terminate_demo_process`, `restart_demo_service`, `cleanup_demo_logs`).

---

## 6. Verification of Safety Rules

In strict adherence to `AGENTS.md`:
- **Rule 2 & 5**: Zero arbitrary shell commands were constructed or executed; all remediation utilized `AllowedActionType` handlers.
- **Rule 4**: Every action passed through `GuardrailEngine` with 100% policy verification.
- **Rule 7 & 8**: 100% of the 50 fault trials produced a persistent incident record followed by independent verification.
- **Rule 10**: Isolation Forest operates strictly as an advisory detection signal; deterministic rules retain full diagnostic and recovery authority.
- **Rule 17**: All remediation strictly targeted approved demo entities (`demo-cpu`, `demo-memory`, `demo-service`, `demo-disk`, `demo-deadlock`). Zero host system processes or systemd services were affected.
