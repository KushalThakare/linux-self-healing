# Deterministic Rule-Based Fault Detection

## 1. Overview and Core Invariants

The **Fault Detection Subsystem** provides deterministic, rule-based anomaly detection for the Linux Self-Healing Framework. In strict accordance with **Rules 9, 10, and 15** of `AGENTS.md`:

- **Strict Separation from Recovery**: The detection engine evaluates historical telemetry and outputs detection events; it **never** triggers or executes recovery actions directly.
- **Purely Deterministic**: Every detector evaluates explicit mathematical, threshold-based, or state-based invariants. Unsupervised machine learning models (e.g., Isolation Forest) are deliberately deferred until rule-based baselines are proven.
- **Standardized Evidence Contract**: Every detected anomaly emits a strongly typed `DetectionEvent` containing structured, forensic telemetry evidence.

---

## 2. Architecture and Data Flow

```
+-----------------------------------------------------------------------------------+
|                        Telemetry & Time-Series History                            |
|             (List[MetricSnapshot] collected at regular sample intervals)          |
+-----------------------------------------------------------------------------------+
                                       |
                                       v
+-----------------------------------------------------------------------------------+
|                         RuleDetectionEngine                                       |
|                  (Orchestrates registered deterministic rules)                    |
+-----------------------------------------------------------------------------------+
         |               |                 |                 |               |
         v               v                 v                 v               v
  +-------------+ +---------------+ +---------------+ +-------------+ +---------------+
  | CpuRunaway  | | AbnormalMem   | | ServiceFailure| | DiskExhaust | |   Deadlock    |
  |  Detector   | |   Detector    | |   Detector    | |  Detector   | |   Detector    |
  +-------------+ +---------------+ +---------------+ +-------------+ +---------------+
         |               |                 |                 |               |
         +---------------+-----------------+-----------------+---------------+
                                       |
                                       v (Rule Tripped)
+-----------------------------------------------------------------------------------+
|                       Standardized DetectionEvent                                 |
|   - event_id: str (UUID)                                                          |
|   - target_id: str                                                                |
|   - fault_type: FaultType                                                         |
|   - severity: FaultSeverity                                                       |
|   - triggering_value: float                                                       |
|   - threshold_value: float                                                        |
|   - evidence: Dict[str, Any] (metrics history, duration, rates, states)          |
|   - description: str                                                              |
+-----------------------------------------------------------------------------------+
```

---

## 3. Deterministic Detectors Specification

### 3.1 CPU Runaway Detector (`CpuRunawayDetector`)
- **Fault Type**: `FaultType.HIGH_CPU`
- **Configurable Parameters**:
  - `cpu_percent_threshold: float = 90.0` (trigger limit)
  - `duration_seconds: float = 3.0` (minimum sustained anomaly duration)
  - `min_samples: int = 3` (minimum consecutive telemetry observations)
- **Logic**: Evaluates trailing metric window. Tripped only if all observations in the evaluated sample span meet or exceed `cpu_percent_threshold` for the required duration. Transient single-point bursts are filtered out as false positives.
- **Evidence Fields**:
  - `measured_cpu_series`: Array of observed CPU percentages.
  - `average_cpu_percent`: Computed mean utilization.
  - `sample_count`: Total evaluated samples.
  - `duration_seconds`: Real or effective time span.
  - `timestamps`: ISO 8601 timestamps of evaluated snapshots.

### 3.2 Abnormal Memory Detector (`AbnormalMemoryDetector`)
- **Fault Type**: `FaultType.MEMORY_LEAK`
- **Configurable Parameters**:
  - `budget_bytes: int = 150 * 1024 * 1024` (150 MB hard budget)
  - `min_growth_rate_bytes_sec: float = 2 * 1024 * 1024` (2 MB/s monotonic growth)
  - `min_samples: int = 3` (minimum evaluation window)
- **Logic**: Fires on two distinct memory conditions:
  1. **Budget Violation**: Target process Resident Set Size (RSS) exceeds `budget_bytes`.
  2. **Monotonic Leak**: Target RSS exhibits continuous monotonic growth exceeding `min_growth_rate_bytes_sec` across the evaluation window.
- **Evidence Fields**:
  - `rss_bytes_series`: Raw RSS bytes over time.
  - `final_rss_mb`: Latest measured RSS in MB.
  - `budget_mb`: Configured memory ceiling.
  - `budget_exceeded`: Boolean flag.
  - `monotonic_growth`: Boolean flag.
  - `growth_rate_mb_sec`: Computed expansion rate.

### 3.3 Service Failure Detector (`ServiceFailureDetector`)
- **Fault Type**: `FaultType.PROCESS_CRASH`
- **Configurable Parameters**:
  - `expected_active: bool = True` (baseline expectation)
  - `min_failed_samples: int = 1` (consecutive failure requirement)
- **Logic**: Inspects target process and supervised systemd unit state. Tripped if:
  1. Systemd unit reports `failed`, `inactive`, or `dead`.
  2. Target process transitions into `DEAD` or `STOPPED` execution states.
  3. Supervised target PID disappears from the process table.
- **Evidence Fields**:
  - `expected_active`: Expected boolean state.
  - `recent_evidence`: Specific breakdown including unit sub-state, target state enum, or missing PID details.

### 3.4 Disk Exhaustion Detector (`DiskExhaustionDetector`)
- **Fault Type**: `FaultType.DISK_GROWTH`
- **Configurable Parameters**:
  - `fs_percent_threshold: float = 85.0` (filesystem capacity ceiling, %)
  - `log_dir_bytes_threshold: int = 15 * 1024 * 1024` (15 MB demo log threshold)
  - `log_dir_path: Optional[Path] = demo_scratch/logs` (monitored directory)
- **Logic**: Tripped if:
  1. Global root filesystem percentage exceeds `fs_percent_threshold`.
  2. Target application log directory accumulation exceeds `log_dir_bytes_threshold`.
- **Evidence Fields**:
  - `fs_violation`: Boolean indicator of filesystem exhaustion.
  - `filesystem`: Mount point, total bytes, used bytes, and percent.
  - `log_violation`: Boolean indicator of log folder accumulation.
  - `log_directory`: Path, total bytes, and threshold.

### 3.5 Deadlock Detector (`DeadlockDetector`)
- **Fault Type**: `FaultType.DEADLOCK`
- **Configurable Parameters**:
  - `min_threads: int = 3` (minimum thread count)
  - `max_cpu_percent: float = 1.0` (upper bound for CPU activity)
  - `min_samples: int = 3` (consecutive window)
- **Logic**: Detects multi-threaded circular lock contention and hung application states. Tripped if:
  1. Process is multi-threaded (`num_threads >= min_threads`).
  2. Process state is `SLEEPING` or `IDLE`.
  3. CPU utilization remains $\le 1.0\%$ across all consecutive samples.
- **Evidence Fields**:
  - `thread_counts`: Observed thread counts over time.
  - `cpu_percent_series`: Measured CPU usage (verifying lack of forward progress).
  - `states_series`: State transitions (e.g. `['SLEEPING', 'SLEEPING', 'SLEEPING']`).

---

## 4. Verification and Test Matrix

The test suite in `tests/test_detection.py` provides 100% deterministic coverage:
- **True Positives**: Validates triggering when fault thresholds are violated.
- **False Positives**: Validates silence during transient CPU bursts, fluctuating memory, healthy services, normal disk usage, and standard sleeping single-threaded jobs.
- **Boundary Conditions**: Asserts behavior at exact threshold equality, empty windows, single snapshots, and missing metric fields.
