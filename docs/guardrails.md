# Safety Guardrail Subsystem Specification & Architecture

## 1. Executive Summary & Design Principles

The **Safety Guardrail Engine** (`self_healing.guardrails`) enforces strict, deterministic policy validation before any recovery action can touch system or process state. In accordance with the project safety invariants:

1. **Policy-First Interventions**: No remediation action may execute without passing through the guardrail.
2. **Zero Shell Commands**: The system strictly forbids arbitrary shell execution, bash scripts, subshell commands, or dynamic command generation.
3. **Typed Action Allowlist**: Recovery actions must be instances of strongly typed `RecoveryAction` data models belonging to an explicit allowlist.
4. **Target Isolation**: All actions are restricted to explicitly registered and approved demo targets (`demo-cpu`, `demo-memory`, `demo-service`, `demo-disk`, `demo-deadlock`, `demo-worker`). Unrelated host processes and critical system services are protected with hard rejection boundaries.
5. **Traceable Decisions**: Every validation produces an explicit `GuardrailDecision` with status `GUARDRAIL APPROVED` or `GUARDRAIL REJECTED`, complete with violation descriptions and timestamps.
6. **Dry-Run Mode**: Full support for simulation where detection, diagnosis, and guardrail policies evaluate without executing any mutating changes.

---

## 2. Typed RecoveryAction Data Contract

The `RecoveryAction` model (defined in `src/self_healing/core/models.py`) defines the strictly typed specification for remediation:

```python
class RecoveryAction(BaseModel):
    action_id: str                      # Unique UUID
    action_type: AllowedActionType      # Allowlisted action enum
    target: str                         # Demo target identifier
    reason: str                         # Diagnostic justification
    required_evidence: List[str]        # Required telemetry evidence keys
    risk_level: RiskLevel               # LOW, MEDIUM, HIGH, CRITICAL
    max_retries: int                    # Max permitted attempts (default: 3)
    retry_count: int                    # Current retry count (default: 0)
    allowed_targets: List[str]          # Whitelisted target IDs for this action
    preconditions: List[str]            # Invariant preconditions
    parameters: Dict[str, Any]          # Action-specific typed parameters
```

### Risk Level Hierarchy (`RiskLevel`)
- `LOW`: Read-only or clean-up actions with negligible side-effects (e.g., `CLEANUP_DEMO_LOGS`, `LOWER_DEMO_PROCESS_PRIORITY`).
- `MEDIUM`: Restarting controlled demo worker processes or mock services (e.g., `RESTART_DEMO_SERVICE`, `RESTART_DEMO_APPLICATION`).
- `HIGH`: Terminating rogue demo processes (e.g., `TERMINATE_DEMO_PROCESS`).
- `CRITICAL`: System-wide or state-destroying actions (blocked by default; requires explicit safety policy override).

---

## 3. Allowlisted Action Registry (`AllowedActionRegistry`)

The `AllowedActionRegistry` (`src/self_healing/guardrails/registry.py`) acts as the single source of truth for permissible operations.

### Permitted Action Types (`AllowedActionType`)

| Action Type | Description | Permitted Demo Targets | Required Evidence | Default Risk |
|---|---|---|---|---|
| `restart_demo_service` | Restarts an approved demo mock systemd service | `demo-service`, `demo-web` | `target_id` (or `service_name`) | `MEDIUM` |
| `terminate_demo_process` | Gracefully sends SIGTERM (or SIGKILL) to a demo process | `demo-cpu`, `demo-deadlock`, `demo-worker`, `demo-memory` | `target_id`, `average_cpu_percent` (or `thread_counts`) | `HIGH` |
| `lower_demo_process_priority` | Increases process niceness (`renice +10`) for runaway CPU | `demo-cpu`, `demo-worker` | `target_id`, `average_cpu_percent` | `LOW` |
| `cleanup_demo_logs` | Safely purges simulated log files strictly within workspace | `demo-disk` | `target_id` (or `log_directory`) | `LOW` |
| `restart_demo_application` | Restarts a demo python workload | `demo-cpu`, `demo-memory`, `demo-worker` | `target_id` | `MEDIUM` |

### Security Boundaries: Shell Command Rejection
Any attempt to register or construct an action using shell strings or unlisted commands (e.g., `rm -rf /`, `bash -c ...`, `systemctl stop sshd`, `kill -9 1`) is immediately rejected with a `SecurityViolationError`:

```python
try:
    AllowedActionRegistry.validate_action_type("bash -c 'kill -9 1'")
except SecurityViolationError as e:
    # Security violation: action 'bash -c ...' is not an allowlisted recovery action
```

### Diagnostic Bridging (`from_diagnosis`)
The registry provides an automated bridge from deterministic `DiagnosisResult` records to typed `RecoveryAction` instances, verifying target-action compatibility and pre-populating required forensic evidence requirements.

---

## 4. The 8-Point Guardrail Validation Pipeline

When `SafetyGuardrailEngine.evaluate(action, context)` is invoked, it evaluates the action against 8 sequential safety checks. If **any** check fails, evaluation terminates with status `GUARDRAIL REJECTED` and a complete list of violation reasons.

```
       [Proposed RecoveryAction]
                  │
                  ▼
   1. Target Identity & Format Validation
                  │
                  ▼
   2. Action Type Allowlist Validation
                  │
                  ▼
   3. Process / Service Identity Protection
      (Blocks PID 1, systemd, kernel, sshd)
                  │
                  ▼
   4. Approved Demo Target Validation
      (Must exist in TargetRegistry & match compatibility)
                  │
                  ▼
   5. Current System State & Preconditions
      (Process existence check, workspace prefix)
                  │
                  ▼
   6. Retry Limits, Cooldown & Flapping Lockout
      (retry_count < max_retries, cooldown elapsed)
                  │
                  ▼
   7. Operational Risk Level Evaluation
      (CRITICAL rejected unless allow_critical_risk=True)
                  │
                  ▼
   8. Forensic Telemetry Evidence Completeness
      (All required_evidence keys present in context)
                  │
        ┌─────────┴─────────┐
        ▼                   ▼
[GUARDRAIL APPROVED]  [GUARDRAIL REJECTED]
```

### Validation Details

1. **Target Identity**: Target string must be non-empty and well-formed.
2. **Action Type**: Must exactly match an enum member of `AllowedActionType`.
3. **Protected Process Identity**:
   - Explicitly rejects PID 1 (`init`/`systemd`), kernel daemons (`kthreadd`, `kworker`), `sshd`, `dbus`, `syslog`, and host system processes.
   - Verifies target names against forbidden system identities.
4. **Approved Demo Target**:
   - The target must be registered and enabled in `TargetRegistry`.
   - The target must be enumerated in `action.allowed_targets` and `ACTION_TARGET_COMPATIBILITY`.
5. **System State & Preconditions**:
   - If PID is provided in context, confirms process exists and cmdline matches the approved demo workload.
   - For disk cleanup, ensures the path is strictly within the user workspace directory (`working_dir_prefix`).
6. **Retry Count & Flapping/Cooldown Rate Limiting**:
   - Rejects if `action.retry_count >= action.max_retries`.
   - Rejects if cooldown period has not elapsed since the last intervention on the same target.
   - Rejects with flapping lockout if intervention frequency exceeds `max_restarts_per_window` within the rolling observation window.
7. **Action Risk Evaluation**:
   - `CRITICAL` risk actions are blocked unconditionally unless `allow_critical_risk=True` is explicitly passed in engine policy configuration.
8. **Required Forensic Evidence**:
   - The evaluation context must contain all keys specified in `action.required_evidence` (e.g., `average_cpu_percent`, `final_rss_mb`, `log_directory`).

---

## 5. Decision Outcomes & Logging

The evaluation yields a frozen `GuardrailDecision` model:

```python
class GuardrailDecision(BaseModel):
    decision_id: str                    # Unique UUID
    action_id: str                      # Proposed action ID
    target_id: str                      # Target evaluated
    status: GuardrailStatus             # "GUARDRAIL APPROVED" or "GUARDRAIL REJECTED"
    allowed: bool                       # True if APPROVED, False if REJECTED
    is_dry_run: bool                    # Preserves dry-run mode state
    violations: List[str]               # Specific safety violations if rejected
    reasons: List[str]                  # Detailed diagnostic rationale
    timestamp: datetime                 # UTC timestamp
```

Every decision is logged using structured JSON logging:
- Approved actions log at level `INFO` with `[GUARDRAIL APPROVED]`.
- Rejected actions log at level `WARNING` with `[GUARDRAIL REJECTED]` and the full list of violation codes.

---

## 6. DRY-RUN Simulation Mode

The system supports a full dry-run mode via the `dry_run=True` flag:
- Guardrail validates all 8 safety dimensions identically to live mode.
- If passed, the decision receives status `GUARDRAIL APPROVED` with `is_dry_run=True`.
- The downstream orchestrator inspects `is_dry_run` and logs the remediation proposal without modifying the process, file, or system state.
- Cooldown and retry histories are preserved for audit inspection.

---

## 7. Verification Test Suite

The test suite in `tests/test_guardrails.py` covers 16 comprehensive unit and edge cases:

- `test_action_registry_permitted_actions`: Verifies allowlisted action set.
- `test_action_registry_rejects_arbitrary_shell_commands`: Proves rejection of shell commands and scripts.
- `test_action_creation_from_diagnosis`: Bridges diagnosis results into valid actions.
- `test_guardrail_approved_cpu_terminate`: Proves approval for rogue CPU terminate action.
- `test_guardrail_approved_memory_restart`: Proves approval for memory leak service restart.
- `test_guardrail_approved_disk_cleanup`: Proves approval for safe workspace log cleanup.
- `test_guardrail_rejected_empty_target`: Check 1 failure verification.
- `test_guardrail_rejected_protected_process_identity`: Check 3 PID 1 / systemd rejection.
- `test_guardrail_rejected_unapproved_target`: Check 4 unlisted target rejection.
- `test_guardrail_rejected_target_incompatible_with_action`: Check 4 incompatible target rejection.
- `test_guardrail_rejected_retry_count_exceeded`: Check 6 retry limit exhaustion rejection.
- `test_guardrail_rejected_flapping_lockout`: Check 6 flapping lockout rejection.
- `test_guardrail_rejected_cooldown_active`: Check 6 quiet period rejection.
- `test_guardrail_rejected_critical_risk_without_override`: Check 7 risk threshold rejection.
- `test_guardrail_rejected_missing_required_evidence`: Check 8 missing evidence rejection.
- `test_dry_run_mode_preserves_safety`: Verifies dry-run flag preservation and audit log.
