# System Architecture & Phase 1 Skeleton Specification

## 1. Executive Summary

The **Autonomous Fault Detection and Self-Healing System for Linux** is an automated, user-space reliability engineering framework operating inside an Ubuntu VM.

The core framework enforces a closed-loop, deterministic, safety-constrained architecture:

$$\mathbf{MONITOR} \longrightarrow \mathbf{DETECT} \longrightarrow \mathbf{DIAGNOSE} \longrightarrow \mathbf{GUARDRAIL} \longrightarrow \mathbf{HEAL} \longrightarrow \mathbf{VERIFY}$$

Phase 1 establishes the foundational project skeleton, clean module interfaces, typing contracts, configuration, logging, health-check command, and testing infrastructure without implementing complex healing logic.

---

## 2. Core Safety Guarantees & Invariants

In accordance with system design principles and safety rules:

1. **Zero-Arbitrary Shell Execution**:
   - The framework strictly prohibits executing arbitrary shell command strings (`os.system`, `shell=True`).
   - All remediation operations are defined as typed Python classes in an allowlisted `ActionRegistry`.
2. **Explicit Target Allowlist & Blast-Radius Containment**:
   - Any process or directory outside the supervised `TargetRegistry` is completely ignored.
   - Core system processes (PID $\le$ 2, `systemd`, `init`, `sshd`, shells, system directories) are strictly forbidden and raise `SecurityViolationError` if accessed.
3. **Mandatory Guardrail Evaluation**:
   - No recovery action can ever execute directly from diagnosis.
   - Every action proposal must pass through the `PolicyGuardrailEngine`, which evaluates target eligibility, flapping lockout thresholds, cooldown windows, and the active `dry_run` flag.
4. **Deterministic Priority**:
   - Detection is rooted in deterministic, transparent rules over time-series metric buffers.
   - Statistical or machine learning anomaly detection is strictly deferred until deterministic baselines are verified.
5. **Immutable Incident Records**:
   - Every detected anomaly, diagnosis report, policy evaluation, recovery result, and post-healing verification outcome is recorded in a unified `IncidentRecord`.
6. **Closed-Loop Verification**:
   - Remediation actions must be followed by active health verification probes (process state, socket availability, HTTP `/health`).
7. **First-Class Dry-Run Mode**:
   - The framework supports dry-run execution (`dry_run=True`), where recovery actions are simulated, measured, and logged without modifying system state.

---

## 3. Package & Directory Structure

```
linux-self-healing/
├── pyproject.toml              # Modern package metadata, dependencies & pytest configuration
├── requirements.txt           # Pinned production runtime dependencies
├── requirements-dev.txt       # Development & testing dependencies
├── config/
│   ├── default_config.yaml    # System defaults, intervals, thresholds, and guardrail limits
│   └── targets.yaml           # Allowlisted demo target specifications
├── docs/
│   ├── architecture.md        # Architecture specification (this file)
│   └── environment.md         # Phase 0 environment validation report
├── scripts/
│   ├── health_check.sh        # Health check helper script
│   └── run_tests.sh           # Test suite runner helper script
├── src/
│   └── self_healing/
│       ├── __init__.py        # Version 0.1.0 and package root
│       ├── __main__.py        # python -m self_healing entry point
│       ├── cli.py             # Click CLI application and health-check command
│       ├── core/              # Shared data contracts and exception hierarchy
│       │   ├── __init__.py
│       │   ├── models.py      # Strongly typed Pydantic v2 domain schemas
│       │   └── exceptions.py  # Structured custom exception classes
│       ├── config/            # Strongly typed configuration models and YAML loaders
│       │   ├── __init__.py
│       │   └── settings.py
│       ├── logging/           # Structured JSON and readable console logging
│       │   ├── __init__.py
│       │   └── logger.py
│       ├── targets/           # Allowlisted target registry and safety validators
│       │   ├── __init__.py
│       │   └── registry.py
│       ├── monitoring/        # System & target metrics collectors and ring buffer
│       │   ├── __init__.py
│       │   └── collector.py
│       ├── detection/         # Deterministic rule engine and base rule interfaces
│       │   ├── __init__.py
│       │   └── base.py
│       ├── diagnosis/         # Root cause analysis interfaces and heuristic engine
│       │   ├── __init__.py
│       │   └── base.py
│       ├── guardrails/        # Safety policy gatekeeper, flapping and cooldown enforcement
│       │   ├── __init__.py
│       │   └── base.py
│       ├── recovery/          # Typed allowlisted recovery action registry and stubs
│       │   ├── __init__.py
│       │   └── base.py
│       ├── verification/      # Closed-loop verification probes and engine
│       │   ├── __init__.py
│       │   └── base.py
│       ├── incidents/         # Incident recording and audit trail store
│       │   ├── __init__.py
│       │   └── store.py
│       ├── fault_injection/   # Safe controlled demo fault injection interfaces
│       │   ├── __init__.py
│       │   └── base.py
│       └── api/               # FastAPI management endpoints (/health, /api/v1/status)
│           ├── __init__.py
│           └── app.py
└── tests/                     # Automated pytest test suites
    ├── conftest.py            # Shared fixtures
    ├── test_environment.py   # Phase 0 environment validation
    ├── test_config.py        # Configuration loading and schema validation
    ├── test_logging.py       # JSON and console formatting tests
    ├── test_models.py        # Pydantic data model and validation tests
    ├── test_interfaces.py    # Interface contracts and safety boundary tests
    ├── test_api.py           # FastAPI endpoint tests
    └── test_cli.py           # CLI commands and health-check verification tests
```

---

## 4. Module Interfaces & Contracts

### 4.1 Monitoring (`self_healing.monitoring`)
- `BaseMetricsCollector(ABC)`:
  - `collect_system_metrics() -> MetricSnapshot`: Captures host CPU, RAM, and load averages.
  - `collect_target_metrics(target: TargetSpec, pid: Optional[int]) -> Optional[MetricSnapshot]`: Captures per-process CPU, RSS memory, thread count, and open file descriptors.
- `MetricRingBuffer`: Circular sliding window maintaining time-series telemetry.

### 4.2 Detection (`self_healing.detection`)
- `BaseFaultRule(ABC)`:
  - `evaluate(target: TargetSpec, window: List[MetricSnapshot]) -> Optional[FaultEvent]`: Evaluates time-series telemetry against deterministic threshold rules.
- `BaseDetectionEngine(ABC)`:
  - `register_rule(rule: BaseFaultRule) -> None`
  - `evaluate(target: TargetSpec, window: List[MetricSnapshot]) -> List[FaultEvent]`

### 4.3 Diagnosis (`self_healing.diagnosis`)
- `BaseDiagnosisEngine(ABC)`:
  - `diagnose(fault_event: FaultEvent, metric_history: List[MetricSnapshot], target: TargetSpec) -> DiagnosisReport`: Synthesizes fault event and metric window into a structured root cause diagnosis recommending a typed action.

### 4.4 Guardrails (`self_healing.guardrails`)
- `BaseGuardrail(ABC)`:
  - `evaluate_action(target: TargetSpec, diagnosis: DiagnosisReport, dry_run: bool) -> PolicyDecision`:
    - Checks target presence and active status in `TargetRegistry`.
    - Enforces flapping lockout (max actions per time window).
    - Enforces cooldown quiet period.
    - Emits immutable `PolicyDecision` token.

### 4.5 Recovery (`self_healing.recovery`)
- `BaseRecoveryAction(ABC)`:
  - `execute(target: TargetSpec, params: Optional[Dict[str, Any]], dry_run: bool) -> RecoveryResult`: Executes or simulates the remediation action.
- `ActionRegistry`:
  - Allowlisted mapping between `ActionType` and concrete `BaseRecoveryAction` instances. Prevents any unallowlisted action execution.

### 4.6 Verification (`self_healing.verification`)
- `BaseVerificationProbe(ABC)`:
  - `probe(target: TargetSpec) -> bool`: Active probe (process alive, HTTP `/health`, TCP socket check).
- `BaseVerificationEngine(ABC)`:
  - `verify(target: TargetSpec, incident_id: str) -> VerificationResult`: Aggregates probe outcomes into a verified closed-loop health status.

### 4.7 Incidents (`self_healing.incidents`)
- `BaseIncidentStore(ABC)`:
  - `save(record: IncidentRecord) -> None`
  - `get(incident_id: str) -> Optional[IncidentRecord]`
  - `list_incidents(limit: int, target_id: Optional[str]) -> List[IncidentRecord]`

### 4.8 Fault Injection (`self_healing.fault_injection`)
- `BaseFaultInjector(ABC)`:
  - `validate_target_safety(target: TargetSpec)`: Ensures target is not a protected host system process or directory.
  - `inject(target: TargetSpec) -> bool`
  - `restore(target: TargetSpec) -> bool`

---

## 5. Health Check & CLI Interface

The system provides a CLI entry point via `self-healing` (or `scripts/health_check.sh`):

### Commands:
- `self-healing health`: Evaluates Python version, Linux `/proc` filesystem accessibility, `systemd` init status, host resource capacity, and configuration validity. Exits 0 on success.
- `self-healing health --json`: Emits structured JSON health telemetry suitable for automated monitoring and CI/CD pipelines.
- `self-healing config [--path PATH]`: Validates and inspects configuration files.
- `self-healing run [--dry-run/--no-dry-run]`: Runs the daemon in dry-run mode.
- `self-healing --version`: Displays framework version (`0.1.0`).

---

## 6. Verification Results

All 40 unit, interface, model, configuration, API, and environment tests pass:

```
============================== test session starts ==============================
platform linux -- Python 3.14.4, pytest-9.1.1, pluggy-1.6.0
rootdir: /home/arskage/linux-self-healing
configfile: pyproject.toml
testpaths: tests
plugins: anyio-4.15.1
collected 40 items

tests/test_api.py::test_api_health_endpoint PASSED                       [  2%]
tests/test_api.py::test_api_status_endpoint PASSED                       [  5%]
tests/test_api.py::test_api_targets_endpoints PASSED                     [  7%]
tests/test_cli.py::test_run_system_health_checks_structure PASSED        [ 10%]
tests/test_cli.py::test_cli_health_command PASSED                        [ 12%]
tests/test_cli.py::test_cli_health_command_json PASSED                   [ 15%]
tests/test_cli.py::test_cli_config_command PASSED                        [ 17%]
tests/test_cli.py::test_cli_version PASSED                               [ 20%]
tests/test_cli.py::test_cli_run_dry_run PASSED                           [ 22%]
tests/test_config.py::test_default_config_validity PASSED                [ 25%]
tests/test_config.py::test_system_config_log_level_validation PASSED     [ 27%]
tests/test_config.py::test_monitoring_config_bounds PASSED               [ 30%]
tests/test_config.py::test_load_config_from_repo_files PASSED            [ 32%]
tests/test_config.py::test_load_config_nonexistent_file PASSED           [ 35%]
tests/test_environment.py::test_python_version PASSED                    [ 37%]
tests/test_environment.py::test_core_dependencies PASSED                 [ 40%]
tests/test_environment.py::test_system_binaries PASSED                   [ 42%]
tests/test_environment.py::test_systemd_active PASSED                    [ 45%]
tests/test_environment.py::test_proc_filesystem_interfaces PASSED        [ 47%]
tests/test_environment.py::test_process_inspection_capability PASSED     [ 50%]
tests/test_environment.py::test_memory_inspection_capability PASSED      [ 52%]
tests/test_environment.py::test_disk_inspection_capability PASSED        [ 55%]
tests/test_environment.py::test_signals_and_capabilities PASSED          [ 57%]
tests/test_interfaces.py::test_target_registry_blocks_critical_system_entities PASSED [ 60%]
tests/test_interfaces.py::test_is_safe_pid_boundaries PASSED             [ 62%]
tests/test_interfaces.py::test_monitoring_collector_and_ring_buffer PASSED [ 65%]
tests/test_interfaces.py::test_detection_engine_contract PASSED          [ 67%]
tests/test_interfaces.py::test_diagnosis_engine_contract PASSED          [ 70%]
tests/test_interfaces.py::test_guardrails_flapping_and_cooldown_enforcement PASSED [ 72%]
tests/test_interfaces.py::test_recovery_registry_execution PASSED        [ 75%]
tests/test_interfaces.py::test_verification_engine_contract PASSED       [ 77%]
tests/test_interfaces.py::test_incident_store_contract PASSED            [ 80%]
tests/test_interfaces.py::test_fault_injector_safety PASSED              [ 82%]
tests/test_logging.py::test_get_logger_prefixing PASSED                  [ 85%]
tests/test_logging.py::test_json_formatter_output PASSED                 [ 87%]
tests/test_logging.py::test_console_formatter_output PASSED              [ 90%]
tests/test_logging.py::test_setup_logging_file PASSED                    [ 92%]
tests/test_models.py::test_metric_snapshot_bounds PASSED                 [ 95%]
tests/test_models.py::test_target_spec_validation PASSED                 [ 97%]
tests/test_models.py::test_incident_record_full_lifecycle PASSED         [100%]

======================== 40 passed, 1 warning in 0.28s =========================
```

---

## 9. Phase 2 — Linux Monitoring Implementation

Phase 2 implements the dedicated, read-only Linux telemetry monitoring subsystem:
- **`proc_reader.py`**: Direct zero-dependency parsing of `/proc/uptime`, `/proc/loadavg`, `/proc/meminfo`, `/proc/stat`, and `/proc/[pid]/status`.
- **`service_inspector.py`**: Safe regex-validated `systemctl show` status inspection of systemd service units.
- **`collector.py`**: `SystemMetricsCollector` and `ProcessMetricsCollector` aggregating full-system snapshots into the normalized `SystemSnapshot` and `MetricSnapshot` models.
- **CLI `monitor` Command**: `python -m self_healing monitor [--json]` providing terminal and structured snapshot reporting.
- **Metrics Catalog**: Complete documentation of metrics and sources in [docs/monitoring_metrics.md](file:///home/arskage/linux-self-healing/docs/monitoring_metrics.md).
- **Test Suite**: 64 comprehensive tests passing with zero failures.
