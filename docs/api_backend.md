# FastAPI Backend & Operator Management Interface (Phase 11)

The **FastAPI Backend** provides an authenticated, operator-facing HTTP REST API for telemetry inspection, incident audit logging, guardrail policy visibility, orchestrator control, and isolated demo fault triggering.

---

## 1. Safety Principles & System Invariants

1. **No Arbitrary Shell Command Execution**:
   - The API never accepts shell command strings or arbitrary executable paths.
   - All recovery actions dispatch exclusively through typed allowlisted handlers in [`AllowedActionRegistry`](../src/self_healing/recovery/registry.py).

2. **Strict Guardrail Enforcement**:
   - No API endpoint bypasses the safety guardrail engine.
   - All recovery actions, whether initiated autonomously or triggered, must satisfy the 8 guardrail criteria before execution.

3. **Restricted Fault Injection Blast-Radius**:
   - `POST /faults/{fault_type}/start` and `POST /faults/{fault_type}/stop` interact strictly through [`FaultManager`](../src/self_healing/fault_injection/manager.py).
   - Injections are restricted to pre-approved demo targets (`demo-cpu`, `demo-memory`, `demo-service`, `demo-disk`, `demo-deadlock`).

---

## 2. API Endpoints Specification

### Observability & Telemetry

#### `GET /health`
Returns host health status, uptime, system CPU/RAM usage, and registered target count.

**Response (`200 OK`)**:
```json
{
  "status": "healthy",
  "version": "0.1.0",
  "timestamp": "2026-10-09T01:05:00Z",
  "dry_run": true,
  "system": {
    "cpu_percent": 12.5,
    "memory_percent": 45.2,
    "memory_available_mb": 4210.5
  },
  "registered_targets": 6
}
```

#### `GET /metrics`
Captures and returns the complete normalized system telemetry snapshot.

**Response (`200 OK`)**:
```json
{
  "timestamp": "2026-10-09T01:05:00Z",
  "uptime_seconds": 12450.2,
  "idle_seconds": 45102.1,
  "cpu": {
    "percent": 14.2,
    "per_cpu_percent": [12.0, 16.4],
    "load_1m": 0.45,
    "load_5m": 0.32,
    "load_15m": 0.28
  },
  "memory": {
    "total_bytes": 8589934592,
    "available_bytes": 4294967296,
    "used_bytes": 4294967296,
    "free_bytes": 4294967296,
    "percent": 50.0
  },
  "disks": [
    {
      "mount_point": "/",
      "total_bytes": 52428800000,
      "used_bytes": 10485760000,
      "free_bytes": 41943040000,
      "percent": 20.0
    }
  ]
}
```

#### `GET /processes`
Lists monitored process metrics for approved supervised targets.

- **Query Parameters**:
  - `target_id` (optional): Filter to processes matching a specific target ID (e.g. `?target_id=demo-cpu`). Returns `404` if target does not exist.

**Response (`200 OK`)**:
```json
[
  {
    "pid": 54321,
    "name": "python3",
    "state": "RUNNING",
    "cpu_percent": 98.2,
    "rss_bytes": 104857600,
    "target_id": "demo-cpu",
    "cmdline": ["python3", "-m", "self_healing.demo_workloads", "cpu_spin"]
  }
]
```

#### `GET /services`
Inspects status of supervised systemd services using read-only `systemctl show`.

- **Query Parameters**:
  - `service` (optional): Specific service unit name (e.g. `?service=cron`). Validated against strict regex pattern `^[a-zA-Z0-9_\-\.@]+(\.service)?$`.

**Response (`200 OK`)**:
```json
[
  {
    "service_name": "cron",
    "is_active": true,
    "active_state": "active",
    "sub_state": "running",
    "is_enabled": true,
    "checked_at": "2026-10-09T01:05:00Z"
  }
]
```

---

### Incidents & Audit History

#### `GET /incidents`
Queries persistent incident records from SQLite.

- **Query Parameters**:
  - `fault_type` (optional): e.g. `?fault_type=HIGH_CPU`
  - `status` (optional): e.g. `?status=VERIFIED_SUCCESS`
  - `target_id` (optional): e.g. `?target_id=demo-cpu`
  - `limit` (optional, default `50`, max `500`)

**Response (`200 OK`)**: Array of [`IncidentRecord`](../src/self_healing/core/models.py).

#### `GET /incidents/{incident_id}`
Retrieves full details of a single incident by its UUID. Returns `404` if not found.

#### `GET /recovery/history`
Historical audit log of recovery interventions executed or simulated.

- **Query Parameters**:
  - `target_id` (optional): Filter to interventions for a specific target.
  - `limit` (optional, default `50`, max `500`).

**Response (`200 OK`)**:
```json
[
  {
    "incident_id": "e886cbb0-3b83-4db0-bfae-2883553cb120",
    "target_id": "demo-service",
    "fault_type": "PROCESS_CRASH",
    "timestamp": "2026-10-09T01:04:00Z",
    "completed_at": "2026-10-09T01:04:01Z",
    "action_type": "restart_demo_service",
    "allowed_by_guardrails": true,
    "recovery_success": true,
    "verification_status": "HEALTHY",
    "duration_ms": 21.04,
    "is_dry_run": true,
    "final_status": "VERIFIED_SUCCESS"
  }
]
```

---

### System Status & Guardrails

#### `GET /system/status`
Current operational state and telemetry counters of the autonomous loop.

**Response (`200 OK`)**:
```json
{
  "version": "0.1.0",
  "mode": "development",
  "dry_run": true,
  "orchestrator_running": false,
  "poll_interval_seconds": 1.0,
  "active_targets_count": 6,
  "active_faults_count": 0,
  "stats": {
    "ticks_count": 12,
    "snapshots_collected": 12,
    "faults_detected": 2,
    "diagnoses_performed": 2,
    "actions_approved": 2,
    "actions_rejected": 0,
    "remediations_executed": 2,
    "verifications_passed": 2,
    "verifications_failed": 0,
    "incidents_escalated": 0
  }
}
```

#### `GET /guardrails`
Inspects active guardrail policies, rate limits, action allowlists, and forbidden target names.

**Response (`200 OK`)**:
```json
{
  "enforce_target_allowlist": true,
  "default_cooldown_seconds": 30.0,
  "flapping_window_seconds": 900.0,
  "max_actions_per_window": 3,
  "allowed_action_types": [
    "terminate_demo_process",
    "lower_demo_process_priority",
    "restart_demo_service",
    "restart_demo_application",
    "cleanup_demo_logs"
  ],
  "forbidden_process_names": [
    "systemd",
    "init",
    "dockerd",
    "sshd",
    "containerd"
  ],
  "forbidden_directory_prefixes": [
    "/",
    "/etc",
    "/var",
    "/usr",
    "/root",
    "/bin"
  ],
  "recent_actions_count": 0
}
```

---

### Control & Fault Injection

#### `POST /faults/{fault_type}/start`
Starts an isolated demo fault condition strictly on mapped demo targets.

- **Path Parameters**:
  - `fault_type`: `cpu`, `memory`, `service`, `disk`, or `deadlock`.
- **Request Body (optional)**:
  ```json
  {
    "intensity": 80,
    "max_mb": 50,
    "rate_mb_per_sec": 5.0
  }
  ```
- **Response (`200 OK`)**: [`FaultStatus`](../src/self_healing/core/models.py). Returns `400` if unsupported fault type.

#### `POST /faults/{fault_type}/stop`
Stops an active demo fault condition and terminates injected workloads.

- **Response (`200 OK`)**: [`FaultStatus`](../src/self_healing/core/models.py).

#### `POST /system/dry-run`
Dynamically updates dry-run simulation mode across orchestrator, guardrails, and recovery executor.

- **Request Body**:
  ```json
  {
    "dry_run": false
  }
  ```
- **Response (`200 OK`)**:
  ```json
  {
    "dry_run": false,
    "message": "Dry-run mode successfully set to False"
  }
  ```

#### `POST /system/monitoring`
Controls autonomous orchestrator lifecycle.

- **Request Body**:
  ```json
  {
    "action": "tick"  // "start", "stop", or "tick"
  }
  ```
- **Response (`200 OK`)**:
  ```json
  {
    "action": "tick",
    "status": "Tick completed successfully (0 incidents handled)",
    "is_running": false,
    "ticks_completed": 13,
    "incidents_handled": 0
  }
  ```

---

## 3. Running the API Server

The API application factory is exported in [`src/self_healing/api/app.py`](../src/self_healing/api/app.py):

```bash
# Launch via uvicorn
uvicorn self_healing.api.app:create_app --factory --host 127.0.0.1 --port 8000
```
