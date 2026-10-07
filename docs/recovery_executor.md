# Recovery Executor Subsystem Specification & Architecture

## 1. Executive Summary & Design Principles

The **Recovery Executor Subsystem** (`self_healing.recovery`) provides safe, deterministic remediation for diagnosed faults affecting monitored demo workloads. Adhering strictly to project safety invariants:

1. **Zero Shell Commands**: The executor **NEVER** accepts or executes raw shell strings, bash scripts, subshell commands, or dynamic command strings.
2. **Typed Inputs Only**: The executor exclusively receives strongly typed, validated [`RecoveryAction`](file:///home/arskage/linux-self-healing/src/self_healing/core/models.py#L284-L300) models.
3. **Guardrail Enforced**: The executor provides [`execute_guardrail_approved()`](file:///home/arskage/linux-self-healing/src/self_healing/recovery/executor.py#L225-L259) to guarantee that actions possess a verified `GUARDRAIL APPROVED` decision token before mutating system state.
4. **Target Isolation**: All interventions are restricted to authorized demo targets (`demo-cpu`, `demo-memory`, `demo-service`, `demo-disk`, `demo-deadlock`, `demo-worker`). Host system processes (PID 1, `systemd`, `kthreadd`, `sshd`) are guarded with hard security boundaries.
5. **Native User-Space Linux APIs**: Interventions execute via standard Linux system call interfaces (`os.kill`, `os.setpriority`, `pathlib.Path.unlink`) and structured argument subprocesses (`shell=False`).
6. **Full Dry-Run Support**: Every handler provides a simulation mode that evaluates candidate processes and files without altering OS state.

---

## 2. The Three-Phase Execution Lifecycle

Every recovery intervention executed by `RecoveryExecutor.execute()` traverses a strictly enforced 3-phase lifecycle:

```
                  [Validated RecoveryAction]
                              │
  ┌───────────────────────────┴───────────────────────────┐
  │ 1. PRE-EXECUTION VALIDATION                           │
  │    ├─ Validate Action Object (RecoveryAction instance)│
  │    ├─ Validate Target in TargetRegistry & Allowlist   │
  │    ├─ Validate User-Space Permissions (os.kill 0, W_OK)│
  │    └─ Record Structured Intent ([RECOVERY INTENT])    │
  └───────────────────────────┬───────────────────────────┘
                              │
  ┌───────────────────────────┴───────────────────────────┐
  │ 2. DURING EXECUTION                                   │
  │    ├─ Record High-Resolution Start Time               │
  │    ├─ Dispatch to Allowlisted Handler                 │
  │    │  (Dry-Run Simulation OR Safe Native Linux API)   │
  │    └─ Capture Telemetry, Result Metrics & Exceptions  │
  └───────────────────────────┬───────────────────────────┘
                              │
  ┌───────────────────────────┴───────────────────────────┐
  │ 3. POST-EXECUTION RECORDING                           │
  │    ├─ Calculate Latency (execution_latency_ms)        │
  │    ├─ Log Audit Summary ([RECOVERY SUCCESS/FAILED])   │
  │    └─ Return Typed RecoveryResult Object              │
  └───────────────────────────────────────────────────────┘
```

### Phase 1: Pre-Execution Validation
- **Action Type Verification**: Confirms `isinstance(action, RecoveryAction)` and `action.action_type in AllowedActionType`. Rejects any string, dict, or unrecognized input with `SecurityViolationError`.
- **Target Verification**: Validates target against `TargetRegistry`. Ensures target is active, not in `FORBIDDEN_PROCESS_NAMES`, and within `action.allowed_targets`.
- **Permission Checking**: Probes target processes using `os.kill(pid, 0)` to verify signaling rights without sending signals. Verifies directory write permissions (`os.W_OK`) for disk actions.
- **Intent Recording**: Emits structured log `[RECOVERY INTENT] action_id='...' type='...' target='...' dry_run=... reason='...'`.

### Phase 2: During Execution
- Dispatches to dedicated allowlisted handler classes.
- Real execution uses structured argument arrays (`shell=False`) or direct C-level POSIX bindings.
- Exceptions (`ProcessLookupError`, `PermissionError`, `ActionExecutionError`) are caught, measured, and formatted into error details.

### Phase 3: Post-Execution
- Returns an immutable, strongly typed `RecoveryResult` documenting:
  - `action_id`, `target_id`, `action_type`
  - `success` (boolean)
  - `dry_run` (boolean)
  - `execution_latency_ms` (float)
  - `output_message` (human-readable summary)
  - `details` (dictionary of PIDs, reclaimed bytes, niceness levels)
  - `error` (error string if failed)

---

## 3. Concrete Recovery Action Handlers

### 1. `terminate_demo_process` (`TerminateProcessHandler`)
- **Allowed Targets**: `demo-cpu`, `demo-deadlock`, `demo-worker`, `demo-memory`.
- **Linux APIs**: Native `os.kill(pid, signal.SIGTERM)`, polling loop with configurable `grace_period_seconds`, and escalation to `os.kill(pid, signal.SIGKILL)`.
- **Process Status Check**: Uses `is_pid_dead(pid)` checking for process absence or Linux `psutil.STATUS_ZOMBIE`.
- **Safety Boundary**: Verifies target PID satisfies `is_safe_pid(pid)` (blocks PID 1, kernel threads, current process).

### 2. `lower_demo_process_priority` (`LowerPriorityHandler`)
- **Allowed Targets**: `demo-cpu`, `demo-worker`.
- **Linux APIs**: Native `os.setpriority(os.PRIO_PROCESS, pid, new_nice)` / `psutil.Process(pid).nice(new_nice)`.
- **User-Space Permission Rules**: Increasing nice value (+10 or +15) decreases CPU scheduling priority, which is completely unprivileged on Linux and requires no root / `CAP_SYS_NICE` privileges.
- **Verification**: Reads updated priority via `os.getpriority(os.PRIO_PROCESS, pid)`.

### 3. `cleanup_demo_logs` (`CleanupLogsHandler`)
- **Allowed Targets**: `demo-disk`.
- **Linux APIs**: Native `pathlib.Path.unlink()` and file iteration.
- **Safety Boundary**: Canonical path resolution strictly enforces that the target directory is contained within the workspace root (`working_dir_prefix`). Any path outside the workspace (e.g. `/var/log`, `/etc`, or directory traversal `../../`) is immediately blocked with `SecurityViolationError`.
- **Reclaimed Telemetry**: Records list of purged filenames and total bytes reclaimed.

### 4. `restart_demo_service` (`RestartServiceHandler`)
- **Allowed Targets**: `demo-service`, `demo-web`.
- **Linux APIs**: Graceful `SIGTERM` of current service instance, port release verification, followed by respawn using `subprocess.Popen([sys.executable, "-m", ...], shell=False, start_new_session=True)`.
- **Safety Boundary**: Restricts execution to localhost binding (`127.0.0.1`) on configured demo ports (e.g., 8085, 8095).

### 5. `restart_demo_application` (`RestartApplicationHandler`)
- **Allowed Targets**: `demo-cpu`, `demo-memory`, `demo-service`, `demo-web`, `demo-worker`.
- **Linux APIs**: Graceful recycling of rogue process instances via `SIGTERM`, followed by fresh instantiation via `subprocess.Popen(..., shell=False)`.
- **Output Details**: Tracks old PIDs recycled and newly assigned PID.

---

## 4. Guardrail-Approved Execution Bridge

To enforce the core loop constraint that recovery must only follow approved policy evaluation, `RecoveryExecutor` exposes:

```python
def execute_guardrail_approved(
    self,
    decision: GuardrailDecision,
    action: RecoveryAction,
    target_spec: Optional[TargetSpec] = None,
    dry_run: Optional[bool] = None,
) -> RecoveryResult:
```

- Verifies `decision.status == GuardrailStatus.APPROVED`.
- Verifies `decision.allowed is True`.
- Verifies `decision.action_id == action.action_id`.
- If any check fails, raises `SecurityViolationError` without executing.

---

## 5. Verification & Test Suite

The test suite in [`tests/test_recovery.py`](file:///home/arskage/linux-self-healing/tests/test_recovery.py) provides 14 unit and live execution tests:

| Test Name | Description |
|---|---|
| `test_reject_arbitrary_shell_command_string` | Verifies rejection of string and shell commands |
| `test_reject_unapproved_target_id` | Verifies rejection of unregistered targets |
| `test_reject_protected_system_entities` | Verifies protection of PID 1, systemd, and system binaries |
| `test_reject_target_incompatible_with_action` | Verifies action-target compatibility matrix |
| `test_reject_execution_without_guardrail_approval` | Verifies `execute_guardrail_approved` gatekeeper |
| `test_reject_mismatched_guardrail_decision_action_id` | Verifies decision-action UUID matching |
| `test_dry_run_all_five_actions` | Validates simulation across all 5 recovery actions |
| `test_real_execute_terminate_demo_process` | Starts real demo workload, terminates it, verifies exit |
| `test_real_execute_lower_demo_process_priority` | Starts real demo workload, lowers priority (+8), verifies niceness |
| `test_real_execute_cleanup_demo_logs` | Generates dummy logs, cleans them up, verifies bytes reclaimed |
| `test_cleanup_demo_logs_rejects_paths_outside_workspace` | Verifies rejection of `/var/log` and traversal paths |
| `test_real_execute_restart_demo_service` | Starts demo HTTP service, restarts it, verifies new PID |
| `test_real_execute_restart_demo_application` | Starts demo workload, restarts it, verifies new PID |
| `test_guardrail_approved_end_to_end_flow` | Verifies end-to-end GuardrailEngine -> RecoveryExecutor chain |
