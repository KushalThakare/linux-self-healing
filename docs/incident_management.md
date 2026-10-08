# Incident Management & SQLite Persistence Subsystem (Phase 9)

The **Incident Management Subsystem** provides persistent storage and query capabilities for all self-healing interventions, creating an immutable, traceable audit log across restarts.

---

## 1. Safety Principles & Architecture

1. **Persistent Audit Guarantee**: Every intervention across the closed-loop recovery cycle (`MONITOR -> DETECT -> DIAGNOSE -> GUARDRAIL -> HEAL -> VERIFY`) produces a strongly typed [`IncidentRecord`](../src/self_healing/core/models.py).
2. **Dual Representation**:
   - **Relational Columns**: Indexed SQL columns for query filtering, dashboard sorting, and latency monitoring.
   - **Complete Model JSON**: Stored in `raw_json` for 100% roundtrip deserialization fidelity back into [`IncidentRecord`](../src/self_healing/core/models.py).
3. **Thread Safety & Concurrency**: Uses SQLite with WAL mode (`PRAGMA journal_mode=WAL`) and thread locks to allow concurrent thread operations.

---

## 2. SQLite Database Schema

Defined in [`src/self_healing/incidents/repository.py`](../src/self_healing/incidents/repository.py):

```sql
CREATE TABLE IF NOT EXISTS incidents (
    incident_id TEXT PRIMARY KEY,
    timestamp TEXT NOT NULL,                -- ISO 8601 UTC timestamp
    completed_at TEXT,                      -- ISO 8601 UTC timestamp (if resolved)
    fault_type TEXT NOT NULL,               -- e.g. 'HIGH_CPU', 'MEMORY_LEAK'
    severity TEXT NOT NULL,                 -- e.g. 'CRITICAL', 'HIGH'
    affected_target TEXT NOT NULL,          -- e.g. 'demo-cpu', 'demo-service'
    detection_evidence TEXT,                -- JSON-encoded evidence dictionary
    diagnosis TEXT,                         -- Root cause explanation or diagnosis JSON
    detector TEXT,                          -- Detector or rule name (e.g. 'cpu_runaway')
    confidence REAL,                        -- Diagnostic confidence score (0.0 to 1.0)
    recovery_action TEXT,                   -- Allowlisted recovery action dispatched
    guardrail_decision TEXT,                -- 'GUARDRAIL APPROVED' or 'GUARDRAIL REJECTED'
    recovery_result TEXT,                   -- 'SUCCESS' or 'FAILED'
    verification_result TEXT,               -- 'HEALTHY', 'FAILED', 'FLAPPING', etc.
    detection_latency REAL DEFAULT 0.0,     -- Latency in milliseconds
    recovery_latency REAL DEFAULT 0.0,      -- Recovery action duration in milliseconds
    final_status TEXT NOT NULL,             -- IncidentStatus enum string
    raw_json TEXT NOT NULL                  -- Complete IncidentRecord Pydantic JSON
);

CREATE INDEX IF NOT EXISTS idx_incidents_timestamp ON incidents(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_incidents_fault_type ON incidents(fault_type);
CREATE INDEX IF NOT EXISTS idx_incidents_status ON incidents(final_status);
CREATE INDEX IF NOT EXISTS idx_incidents_target ON incidents(affected_target);
```

---

## 3. `IncidentRepository` API

Implemented in [`IncidentRepository`](../src/self_healing/incidents/repository.py) (aliased as `SqliteIncidentStore`):

### Core Operations
* `create_incident(incident: IncidentRecord) -> IncidentRecord`: Inserts a new incident into SQLite. Raises `ValueError` if ID already exists.
* `update_incident(incident: IncidentRecord) -> IncidentRecord`: Updates existing record state across lifecycle transitions. Raises `KeyError` if ID not found.
* `get_incident(incident_id: str) -> Optional[IncidentRecord]`: Retrieves and validates incident into an [`IncidentRecord`](../src/self_healing/core/models.py).
* `save(record: IncidentRecord) -> None`: Performs UPSERT (insert or update on conflict), fulfilling the [`BaseIncidentStore`](../src/self_healing/incidents/store.py) interface.
* `get_incident_dict(incident_id: str) -> Optional[Dict[str, Any]]`: Returns the raw column mapping dictionary for an incident.

### Querying & Filtering
* `list_incidents(limit: int = 50, target_id: Optional[str] = None) -> List[IncidentRecord]`: Returns incidents sorted by timestamp descending.
* `filter_by_fault_type(fault_type: Union[FaultType, str], limit: int = 50) -> List[IncidentRecord]`: Filters incidents by specific fault category.
* `filter_by_status(status: Union[IncidentStatus, str], limit: int = 50) -> List[IncidentRecord]`: Filters incidents by lifecycle status (e.g. `VERIFIED_SUCCESS`, `ESCALATED`).
* `get_recent(limit: int = 10) -> List[IncidentRecord]`: Returns the most recent $N$ incidents.

---

## 4. Integration with Remediation Coordinator

When [`RemediationCoordinator`](../src/self_healing/verification/coordinator.py) executes recovery actions, it writes updates directly to `IncidentRepository` via `save()`:
```python
from self_healing.incidents import IncidentRepository
from self_healing.verification.coordinator import RemediationCoordinator

repo = IncidentRepository(db_path="data/incidents.db")
coordinator = RemediationCoordinator(incident_store=repo)

# During execute_and_verify, the coordinator updates SQLite at each lifecycle stage:
# 1. Guardrail evaluation decision (POLICY_APPROVED / POLICY_REJECTED)
# 2. Recovery execution result (EXECUTED)
# 3. Post-healing verification outcome (VERIFIED_SUCCESS / VERIFICATION_FAILED / ESCALATED)
```
