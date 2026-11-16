# Multivariate Isolation Forest Anomaly Detection Subsystem

**Phase 13 Component**: Secondary Unsupervised ML Anomaly Detection  
**Module**: [`src/self_healing/anomaly/`](../src/self_healing/anomaly/)  
**Evaluation Script**: [`scripts/evaluate_anomaly_detection.py`](../scripts/evaluate_anomaly_detection.py)  
**Test Suite**: [`tests/test_anomaly_detection.py`](../tests/test_anomaly_detection.py)  

---

## 1. Overview & Coexistence Architecture

The self-healing framework utilizes a **dual detection paradigm**:
1. **Deterministic Rule Engine (Primary & Authoritative)**: Evaluates strict threshold boundaries and categorical state invariants (CPU $\ge 80\%$, memory budget breaches, DEAD process states).
2. **Isolation Forest Engine (Secondary & Advisory)**: Operates concurrently on sliding telemetry windows, extracting 10-dimensional feature vectors to detect multi-dimensional degradation and subtle precursor anomalies.

```
                      [ TELEMETRY STREAM (Collector / Ring Buffer) ]
                                            │
                     ┌──────────────────────┴──────────────────────┐
                     ▼                                             ▼
       [ DETERMINISTIC RULE ENGINE ]                [ ISOLATION FOREST ENGINE ]
       • CpuRunawayDetector                         • Multi-dimensional feature vector
       • AbnormalMemoryDetector                     • Unsupervised anomaly scoring
       • ServiceFailureDetector                     • Feature contribution & deviation
       • DiskExhaustionDetector                       attribution (Explainability)
       • DeadlockDetector                           • Advisory confidence score
                     │                                             │
                     └──────────────────────┬──────────────────────┘
                                            ▼
                           [ CORRELATION & AGGREGATION ]
                                            ▼
                           [ DIAGNOSIS ENGINE (Phase 5) ]
                                            ▼
                           [ SAFETY GUARDRAILS (Phase 6) ]
                                            ▼
                           [ TYPED RECOVERY (Phase 7) ]
                                            ▼
                           [ VERIFICATION ENGINE (Phase 8) ]
                                            ▼
                           [ PERSISTENT AUDIT (Phase 9) ]
```

---

## 2. Safety Invariants & Closed-Loop Gatekeeping

- **Zero Direct Recovery**: The ML anomaly detector is completely forbidden from triggering recovery actions directly.
- **Mandatory Closed-Loop Traversal**: Output events emit structured `DetectionEvent` objects with `fault_type=STATISTICAL_ANOMALY`. These events strictly pass through:
  $$\text{Detection} \longrightarrow \text{Diagnosis} \longrightarrow \text{Guardrail} \longrightarrow \text{Recovery} \longrightarrow \text{Verification}$$
- **8-Stage Guardrail Protection**: Even when recommended by diagnosis, every recovery action must pass the 8 safety checks (target allowlist, PID bounds, cooldown timer, flapping lockout, zero arbitrary shell execution).

---

## 3. 10-Dimensional Feature Extraction Pipeline

The [`TelemetryFeatureExtractor`](../src/self_healing/anomaly/features.py) converts raw system and target telemetry into normalized numerical feature vectors:

| Index | Feature Dimension | Data Source | Interpretation |
| :---: | :--- | :--- | :--- |
| 0 | `system_cpu_percent` | `/proc/stat` | Overall host CPU utilization ($0 - 100\%$) |
| 1 | `system_memory_percent` | `/proc/meminfo` | Host physical RAM utilization ($0 - 100\%$) |
| 2 | `target_cpu_percent` | `/proc/[pid]/stat` | Supervised demo target CPU utilization ($0 - \infty\%$) |
| 3 | `target_rss_mb` | `/proc/[pid]/status` | Resident set size memory in megabytes |
| 4 | `target_num_threads` | `/proc/[pid]/status` | Active thread count |
| 5 | `target_num_fds` | `/proc/[pid]/fd` | Open file descriptor count |
| 6 | `disk_used_percent` | `statvfs` | Filesystem mount capacity ($0 - 100\%$) |
| 7 | `service_state_numeric` | `systemctl` / state | Scalar encoding ($1.0$: RUNNING, $0.5$: SLEEPING, $0.0$: STOPPED, $-1.0$: DEAD) |
| 8 | `cpu_delta` | Temporal differencing | First difference in CPU ($\Delta\text{CPU} = \text{CPU}_t - \text{CPU}_{t-1}$) |
| 9 | `rss_growth_rate_mb` | Temporal differencing | Memory growth rate per sampling interval ($\Delta\text{RSS}$) |

---

## 4. Mathematical Model & Explainability Engine

### Isolation Forest Formulation
An ensemble of $T$ isolation trees is fit on healthy baseline telemetry:
$$s(x, n) = 2^{-\frac{\mathbb{E}(h(x))}{c(n)}}$$
where $h(x)$ is path length, $c(n)$ is average path length of unsuccessful BST search, and $s(x, n)$ is the anomaly score.

Calibrated anomaly scores are computed as:
$$\text{Score}(x) = \text{clip}\Big(0.50 - 2.0 \cdot \text{decision\_function}(x), \, 0.0, \, 1.0\Big)$$
Anomalies fire when $\text{Score}(x) \ge \tau$ (default $\tau = 0.50$).

### Explainable Forensic Attribution
The [`ExplainabilityEngine`](../src/self_healing/anomaly/explainability.py) calculates standardized $Z$-scores against the healthy training baseline:
$$z_i = \frac{|x_i - \mu_i|}{\sigma_i + \epsilon}$$
Top contributing features are ranked and attached to `DetectionEvent.evidence` to provide human-interpretable reasoning for why the model flagged the condition.

---

## 5. Comparative Evaluation Benchmark

The benchmark script ([`scripts/evaluate_anomaly_detection.py`](../scripts/evaluate_anomaly_detection.py)) compares deterministic rules against Isolation Forest:

```
==========================================================================================================================================
COMPARATIVE EVALUATION: DETERMINISTIC RULES vs. ISOLATION FOREST ANOMALY DETECTION
==========================================================================================================================================
Scenario                         | Ground Truth | Rule Engine    | Rule Step  | ML Engine      | ML Step    | ML Top Attribution          
------------------------------------------------------------------------------------------------------------------------------------------
1. Nominal Baseline Traffic      | HEALTHY      | NOMINAL        | -          | NOMINAL        | -          | -                           
2. CPU Runaway (Tight Loop)      | ANOMALY      | DETECTED       | 2          | DETECTED       | Step 5     | target_cpu_percent, system_cpu_percent
3. Progressive Memory Leak       | ANOMALY      | DETECTED       | 2          | DETECTED       | Step 2     | target_rss_mb, rss_growth_rate_mb
4. Process Deadlock (0% CPU)     | ANOMALY      | DETECTED       | 3          | NOMINAL        | -          | -                           
5. Sub-Threshold Degradation     | ANOMALY      | NOMINAL        | -          | DETECTED       | Step 1     | target_cpu_percent, system_cpu_percent
------------------------------------------------------------------------------------------------------------------------------------------
```

### Key Scientific Findings:
1. **0.0% False Positive Rate**: Under nominal baseline workload traffic, both the rule engine and the calibrated Isolation Forest produced zero false alarms.
2. **Sub-Threshold Early Warning**: In scenario 5 (compound degradation with 55% CPU and 500KB/s creep), deterministic rules were completely blind because individual metrics stayed below hard thresholds ($80\%$ CPU and $2\text{ MB/s}$ creep). Isolation Forest detected the multi-dimensional correlation at Step 1.
3. **Forensic Attribution**: Top $Z$-score deviations accurately identified `target_cpu_percent` during tight loops and `target_rss_mb` / `rss_growth_rate_mb` during memory leaks.

