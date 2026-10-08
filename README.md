# Autonomous Fault Detection and Self-Healing System for Linux

A research-oriented, deterministic, user-space reliability and self-healing framework for Linux operating environments.

$$\mathbf{MONITOR} \longrightarrow \mathbf{DETECT} \longrightarrow \mathbf{DIAGNOSE} \longrightarrow \mathbf{GUARDRAIL} \longrightarrow \mathbf{HEAL} \longrightarrow \mathbf{VERIFY}$$

---

## Safety Guarantees & Operating Rules

1. **Strictly User-Space**: No Linux kernel modifications or kernel module dependencies.
2. **Zero Arbitrary Execution**: Never invokes raw shell commands (`os.system` or `shell=True`) for recovery. All operations use a typed, allowlisted action registry.
3. **Mandatory Guardrail Evaluation**: Every proposed healing action passes through a policy engine checking blast radius, target allowlists, flapping prevention, and cooldown periods.
4. **Deterministic Priority**: Deterministic rule-based detection precedes any statistical anomaly detection.
5. **Read-Only Monitoring**: The monitoring subsystem is strictly non-intrusive and cannot alter operating system state.
6. **Immutable Audit Trail**: Every detection and remediation intervention produces a structured `IncidentRecord`.

---

## Installation & Setup

```bash
# Clone the repository
git clone https://github.com/KushalThakare/linux-self-healing.git
cd linux-self-healing

# Create and activate Python virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies and package in editable mode
pip install -e .
pip install -r requirements-dev.txt
```

---

## Quick Start: Telemetry Monitoring (Phase 2)

Capture an instant snapshot of the host operating system, memory, CPU, filesystem, systemd services, and supervised processes:

```bash
# Formatted terminal output:
python -m self_healing monitor

# Normalized JSON output (suitable for pipelines):
python -m self_healing monitor --json

# Inspect specific systemd services:
python -m self_healing monitor --service systemd-journald --service cron

# Filter telemetry to a specific target:
python -m self_healing monitor --target demo-web
```

### System Health Verification

```bash
# Run foundational health probes:
self-healing health

# Check active configuration:
self-healing config
```

---

## Testing

```bash
# Run pytest test suite:
./scripts/run_tests.sh

# Or directly:
pytest
```

---

## Documentation & Roadmap

- [Features, Status & Visualization Roadmap](FEATURES_AND_ROADMAP.md)
- [System Architecture](docs/architecture.md)
- [FastAPI Backend & API Endpoints](docs/api_backend.md)
- [Autonomous Orchestrator](docs/orchestrator.md)
- [Incident Management & Persistence](docs/incident_management.md)
- [Post-Recovery Verification](docs/verification_subsystem.md)
- [Recovery Action Registry](docs/recovery_executor.md)
- [Safety Guardrails](docs/guardrails.md)
- [Deterministic Diagnosis Engine](docs/diagnosis_engine.md)
- [Detection Rules Catalog](docs/detection_rules.md)
- [Monitoring Metrics Catalog](docs/monitoring_metrics.md)
- [Fault Injection Framework](docs/fault_injection.md)
- [Safety Rules & Operating Guidelines](AGENTS.md)

