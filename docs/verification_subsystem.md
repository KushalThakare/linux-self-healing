# Post-Recovery Verification Subsystem (Phase 8)

The **Post-Recovery Verification Subsystem** closes the autonomous healing feedback loop:
```
MONITOR -> DETECT -> DIAGNOSE -> GUARDRAIL -> HEAL -> VERIFY
```
Rather than assuming recovery succeeded based on command exit codes, the verification subsystem determines whether the fault has **actually been resolved** using measurable system state.

---

## 1. Safety Principles & Invariants

1. **Measurable Telemetry Grounding**: Every verification probe inspects concrete operating system signals (e.g. `/proc`, socket ping, HTTP health endpoints, directory size deltas, thread states).
2. **Failure Marks Recovery Unsuccessful**: If verification probes fail, the initial `RecoveryResult` is explicitly marked as unsuccessful (`success=False`), preventing false confidence in failed remediations.
3. **Bounded Retries (No Infinite Loops)**: The `RetryPolicy` strictly limits recovery attempts per incident or target (`max_retries`). When retries are exhausted, automatic intervention halts and the incident escalates (`IncidentStatus.ESCALATED`).
4. **Dry-Run Integrity**: In simulation mode (`dry_run=True`), the verification engine records simulation checks without assuming false host mutations.

---

## 2. Core Data Models

### `VerificationResult`

Defined in [`src/self_healing/core/models.py`](../src/self_healing/core/models.py):

| Field | Type | Description |
| :--- | :--- | :--- |
| `verification_id` | `str` (UUID) | Unique identifier for the verification execution. |
| `incident_id` | `str` | Identifier of the incident being remediated. |
| `target_id` | `str` | Target supervised. |
| `status` | `VerificationStatus` | Enum: `HEALTHY`, `FAILED`, `FLAPPING`, `TIMEOUT`. |
| `verified` | `bool` | `True` if all probes passed and the fault was resolved. |
| `failed` | `bool` | `True` if any probe failed or the fault persists. |
| `evidence` | `Dict[str, Any]` | Forensic telemetry metrics explaining the verification outcome. |
| `verification_duration` | `float` | Duration in seconds spent conducting verification checks. |
| `metrics_before` | `Dict[str, Any]` | Metric snapshot captured before the recovery action. |
| `metrics_after` | `Dict[str, Any]` | Metric snapshot captured after the recovery action. |
| `checks_passed` | `List[str]` | Names of probes that passed. |
| `checks_failed` | `List[str]` | Names of probes that failed. |
| `details` | `str` | Diagnostic summary of probe results. |
| `retry_recommended` | `bool` | Whether `RetryPolicy` permits an intervention retry. |
| `retry_count` | `int` | Current retry attempt index. |

---

## 3. Measurable Verification Probes

Implemented in `src/self_healing/verification/probes/`:

### 3.1 CPU Verification Probe (`CpuVerificationProbe`)
- **Measurable checks**:
  - Measures CPU utilization over multiple samples ($N$ observation samples).
  - Asserts that CPU returned below threshold (e.g. $\le 60\%$).
  - Asserts that lower CPU usage was sustained across the observation window.
  - For process termination, verifies the runaway PID is no longer alive in `/proc`.

### 3.2 Memory Verification Probe (`MemoryVerificationProbe`)
- **Measurable checks**:
  - Samples RSS memory at $t_1$ and $t_2$.
  - Asserts that RSS growth rate stabilized ($\Delta\text{RSS} \le \text{allowable jitter}$).
  - Asserts that RSS remains below maximum ceiling.
  - Verifies application heartbeat restored (HTTP `/health` check or TCP socket connection).

### 3.3 Service Verification Probe (`ServiceVerificationProbe`)
- **Measurable checks**:
  - Asserts that the target process exists and is in a valid execution state (`RUNNING` or `SLEEPING`).
  - Probes HTTP `/health` endpoint on `expected_port` or `health_check_url`, expecting HTTP 200 OK.
  - Re-checks service health after a sustain interval to ensure it does not immediately flap or crash.
  - If a systemd unit, queries `ServiceInspector` to verify active unit state.

### 3.4 Disk Verification Probe (`DiskVerificationProbe`)
- **Measurable checks**:
  - Samples log directory size before and after cleanup; asserts disk usage reduced.
  - Samples directory size across an observation interval; asserts $\Delta\text{size} \le 0$ (log growth stopped).

### 3.5 Deadlock Verification Probe (`DeadlockVerificationProbe`)
- **Measurable checks**:
  - For termination remediation, asserts the deadlocked PID was terminated.
  - For application restart, asserts the new process is actively running and worker threads are executing without mutex hang.

---

## 4. Retry Policy & Escalation (`RetryPolicy`)

Defined in [`src/self_healing/verification/retry.py`](../src/self_healing/verification/retry.py):
- **Maximum Retries**: Defaults to 3 attempts (or `action.max_retries`).
- **Exponential Backoff**: Calculates delay between retry attempts ($t = \text{base} \times \text{factor}^{\text{attempt}-1}$).
- **Escalation**: When `retry_count >= max_retries` and verification continues to fail, the orchestrator halts automated recovery and transitions the incident to `IncidentStatus.ESCALATED`.

---

## 5. Remediation Coordinator (`RemediationCoordinator`)

Coordinates the end-to-end closed loop in [`src/self_healing/verification/coordinator.py`](../src/self_healing/verification/coordinator.py):
1. **Guardrails**: Evaluates candidate `RecoveryAction` via `SafetyGuardrailEngine`. Rejects unsafe actions (`POLICY_REJECTED`).
2. **Execution**: Executes approved action via `RecoveryExecutor`.
3. **Verification**: Invokes `VerificationEngine` to measure post-recovery state.
4. **Failure Handling**:
   - If verification fails, marks `recovery_result` as unsuccessful (`success=False`).
   - Marks incident as `VERIFICATION_FAILED`.
   - Checks `RetryPolicy`: retries with backoff if permitted, or escalates (`ESCALATED`) if limits are reached.

---

## 6. CLI Verification Command

Operators can execute standalone verification on any supervised target:

```bash
# Human-readable formatted verification
python3 -m self_healing.cli verify demo-cpu

# Structured JSON output
python3 -m self_healing.cli verify demo-cpu --json
```
