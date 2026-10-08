"""Persistent SQLite incident repository for the self-healing framework.

Provides strongly typed storage, filtering, querying, and audit history
for the closed-loop recovery lifecycle.
"""

from contextlib import contextmanager
from datetime import datetime
import json
from pathlib import Path
import sqlite3
import threading
from typing import Any, Dict, Iterator, List, Optional, Union

from self_healing.core.models import (
    DetectionEvent,
    DiagnosisReport,
    DiagnosisResult,
    FaultEvent,
    FaultSeverity,
    FaultType,
    GuardrailDecision,
    IncidentRecord,
    IncidentStatus,
    PolicyDecision,
    RecoveryResult,
    VerificationResult,
)
from self_healing.incidents.store import BaseIncidentStore
from self_healing.logging.logger import get_logger

logger = get_logger("incidents.repository")

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS incidents (
    incident_id TEXT PRIMARY KEY,
    timestamp TEXT NOT NULL,
    completed_at TEXT,
    fault_type TEXT NOT NULL,
    severity TEXT NOT NULL,
    affected_target TEXT NOT NULL,
    detection_evidence TEXT,
    diagnosis TEXT,
    detector TEXT,
    confidence REAL,
    recovery_action TEXT,
    guardrail_decision TEXT,
    recovery_result TEXT,
    verification_result TEXT,
    detection_latency REAL DEFAULT 0.0,
    recovery_latency REAL DEFAULT 0.0,
    final_status TEXT NOT NULL,
    raw_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_incidents_timestamp ON incidents(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_incidents_fault_type ON incidents(fault_type);
CREATE INDEX IF NOT EXISTS idx_incidents_status ON incidents(final_status);
CREATE INDEX IF NOT EXISTS idx_incidents_target ON incidents(affected_target);
"""


class IncidentRepository(BaseIncidentStore):
    """SQLite-backed incident repository supporting relational querying and full model persistence."""

    def __init__(self, db_path: Union[str, Path] = "data/incidents.db") -> None:
        self.db_path = str(db_path)
        self._is_memory = self.db_path == ":memory:"
        self._lock = threading.RLock()

        if not self._is_memory:
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
            self._mem_conn: Optional[sqlite3.Connection] = None
        else:
            # For in-memory DB, keep a single persistent connection across calls
            self._mem_conn = sqlite3.connect(":memory:", check_same_thread=False)
            self._mem_conn.row_factory = sqlite3.Row

        self._init_db()

    @contextmanager
    def _get_connection(self) -> Iterator[sqlite3.Connection]:
        """Provide a thread-safe connection with row_factory enabled."""
        with self._lock:
            if self._is_memory:
                assert self._mem_conn is not None
                yield self._mem_conn
            else:
                conn = sqlite3.connect(self.db_path, timeout=30.0, check_same_thread=False)
                conn.row_factory = sqlite3.Row
                try:
                    conn.execute("PRAGMA journal_mode=WAL")
                    conn.execute("PRAGMA synchronous=NORMAL")
                    yield conn
                finally:
                    conn.close()

    def _init_db(self) -> None:
        """Initialize SQLite database schema and indexes."""
        with self._get_connection() as conn:
            conn.executescript(SCHEMA_SQL)
            conn.commit()
        logger.debug("Initialized incident repository database at '%s'", self.db_path)

    # -------------------------------------------------------------------------
    # Column Extraction Helpers
    # -------------------------------------------------------------------------
    def _extract_columns(self, incident: IncidentRecord) -> Dict[str, Any]:
        """Extract relational column values from an IncidentRecord instance."""
        fault_type_val = (
            incident.fault_event.fault_type.value
            if hasattr(incident.fault_event.fault_type, "value")
            else str(incident.fault_event.fault_type)
        )
        severity_val = (
            incident.fault_event.severity.value
            if hasattr(incident.fault_event.severity, "value")
            else str(incident.fault_event.severity)
        )

        # Detection evidence
        evidence_dict: Dict[str, Any] = {}
        if isinstance(incident.fault_event, DetectionEvent) and incident.fault_event.evidence:
            evidence_dict = dict(incident.fault_event.evidence)
        else:
            evidence_dict = {
                "triggering_value": incident.fault_event.triggering_value,
                "threshold_value": incident.fault_event.threshold_value,
                "description": incident.fault_event.description,
            }

        # Diagnosis string
        diagnosis_text = None
        confidence_val: Optional[float] = None
        if incident.diagnosis:
            if hasattr(incident.diagnosis, "confidence"):
                confidence_val = float(incident.diagnosis.confidence)
            if hasattr(incident.diagnosis, "probable_cause"):
                diagnosis_text = incident.diagnosis.probable_cause
            elif hasattr(incident.diagnosis, "root_cause"):
                diagnosis_text = incident.diagnosis.root_cause
            else:
                diagnosis_text = str(incident.diagnosis)

        # Detector rule name
        detector_name = getattr(incident.fault_event, "rule_name", None)
        if not detector_name:
            detector_name = f"{fault_type_val.lower()}_detector"

        # Recovery action name
        recovery_action_name = None
        if incident.recovery_result:
            act = incident.recovery_result.action_type
            recovery_action_name = act.value if hasattr(act, "value") else str(act)
        elif incident.policy_decision:
            act = incident.policy_decision.action_type
            recovery_action_name = act.value if hasattr(act, "value") else str(act)
        elif incident.diagnosis and hasattr(incident.diagnosis, "recommended_action"):
            act = incident.diagnosis.recommended_action
            recovery_action_name = act.value if hasattr(act, "value") else str(act)

        # Guardrail decision
        guardrail_str = None
        if incident.policy_decision:
            if hasattr(incident.policy_decision, "status"):
                guardrail_str = (
                    incident.policy_decision.status.value
                    if hasattr(incident.policy_decision.status, "value")
                    else str(incident.policy_decision.status)
                )
            else:
                guardrail_str = "GUARDRAIL APPROVED" if incident.policy_decision.allowed else "GUARDRAIL REJECTED"

        # Recovery result
        recovery_str = None
        if incident.recovery_result:
            recovery_str = "SUCCESS" if incident.recovery_result.success else "FAILED"

        # Verification result
        verification_str = None
        if incident.verification_result:
            verification_str = (
                incident.verification_result.status.value
                if hasattr(incident.verification_result.status, "value")
                else str(incident.verification_result.status)
            )

        # Latencies
        detection_latency = 0.0
        if "detection_latency_ms" in evidence_dict:
            try:
                detection_latency = float(evidence_dict["detection_latency_ms"])
            except (ValueError, TypeError):
                detection_latency = 0.0

        recovery_latency = 0.0
        if incident.recovery_result:
            recovery_latency = float(incident.recovery_result.execution_latency_ms)

        final_status_val = (
            incident.status.value
            if hasattr(incident.status, "value")
            else str(incident.status)
        )

        return {
            "incident_id": incident.incident_id,
            "timestamp": incident.started_at.isoformat(),
            "completed_at": incident.completed_at.isoformat() if incident.completed_at else None,
            "fault_type": fault_type_val,
            "severity": severity_val,
            "affected_target": incident.target_id,
            "detection_evidence": json.dumps(evidence_dict),
            "diagnosis": diagnosis_text,
            "detector": detector_name,
            "confidence": confidence_val,
            "recovery_action": recovery_action_name,
            "guardrail_decision": guardrail_str,
            "recovery_result": recovery_str,
            "verification_result": verification_str,
            "detection_latency": detection_latency,
            "recovery_latency": recovery_latency,
            "final_status": final_status_val,
            "raw_json": incident.model_dump_json(),
        }

    # -------------------------------------------------------------------------
    # Core Repository Operations
    # -------------------------------------------------------------------------
    def create_incident(self, incident: IncidentRecord) -> IncidentRecord:
        """Create a new incident record in persistent storage.
        
        Raises:
            ValueError: If an incident with the same incident_id already exists.
        """
        cols = self._extract_columns(incident)
        sql = """
        INSERT INTO incidents (
            incident_id, timestamp, completed_at, fault_type, severity,
            affected_target, detection_evidence, diagnosis, detector, confidence,
            recovery_action, guardrail_decision, recovery_result, verification_result,
            detection_latency, recovery_latency, final_status, raw_json
        ) VALUES (
            :incident_id, :timestamp, :completed_at, :fault_type, :severity,
            :affected_target, :detection_evidence, :diagnosis, :detector, :confidence,
            :recovery_action, :guardrail_decision, :recovery_result, :verification_result,
            :detection_latency, :recovery_latency, :final_status, :raw_json
        )
        """
        try:
            with self._get_connection() as conn:
                conn.execute(sql, cols)
                conn.commit()
            logger.info("Created incident %s (target: %s, status: %s)", incident.incident_id, incident.target_id, cols["final_status"])
            return incident
        except sqlite3.IntegrityError as e:
            raise ValueError(f"Incident with ID '{incident.incident_id}' already exists.") from e

    def update_incident(self, incident: IncidentRecord) -> IncidentRecord:
        """Update an existing incident record in persistent storage.
        
        Raises:
            KeyError: If the incident does not exist.
        """
        cols = self._extract_columns(incident)
        sql = """
        UPDATE incidents SET
            timestamp = :timestamp,
            completed_at = :completed_at,
            fault_type = :fault_type,
            severity = :severity,
            affected_target = :affected_target,
            detection_evidence = :detection_evidence,
            diagnosis = :diagnosis,
            detector = :detector,
            confidence = :confidence,
            recovery_action = :recovery_action,
            guardrail_decision = :guardrail_decision,
            recovery_result = :recovery_result,
            verification_result = :verification_result,
            detection_latency = :detection_latency,
            recovery_latency = :recovery_latency,
            final_status = :final_status,
            raw_json = :raw_json
        WHERE incident_id = :incident_id
        """
        with self._get_connection() as conn:
            cursor = conn.execute(sql, cols)
            if cursor.rowcount == 0:
                raise KeyError(f"Incident with ID '{incident.incident_id}' does not exist.")
            conn.commit()

        logger.info("Updated incident %s (status: %s)", incident.incident_id, cols["final_status"])
        return incident

    def save(self, record: IncidentRecord) -> None:
        """Persist or update an incident record (UPSERT semantics)."""
        cols = self._extract_columns(record)
        sql = """
        INSERT INTO incidents (
            incident_id, timestamp, completed_at, fault_type, severity,
            affected_target, detection_evidence, diagnosis, detector, confidence,
            recovery_action, guardrail_decision, recovery_result, verification_result,
            detection_latency, recovery_latency, final_status, raw_json
        ) VALUES (
            :incident_id, :timestamp, :completed_at, :fault_type, :severity,
            :affected_target, :detection_evidence, :diagnosis, :detector, :confidence,
            :recovery_action, :guardrail_decision, :recovery_result, :verification_result,
            :detection_latency, :recovery_latency, :final_status, :raw_json
        )
        ON CONFLICT(incident_id) DO UPDATE SET
            timestamp = excluded.timestamp,
            completed_at = excluded.completed_at,
            fault_type = excluded.fault_type,
            severity = excluded.severity,
            affected_target = excluded.affected_target,
            detection_evidence = excluded.detection_evidence,
            diagnosis = excluded.diagnosis,
            detector = excluded.detector,
            confidence = excluded.confidence,
            recovery_action = excluded.recovery_action,
            guardrail_decision = excluded.guardrail_decision,
            recovery_result = excluded.recovery_result,
            verification_result = excluded.verification_result,
            detection_latency = excluded.detection_latency,
            recovery_latency = excluded.recovery_latency,
            final_status = excluded.final_status,
            raw_json = excluded.raw_json
        """
        with self._get_connection() as conn:
            conn.execute(sql, cols)
            conn.commit()

    def get_incident(self, incident_id: str) -> Optional[IncidentRecord]:
        """Retrieve an incident by ID."""
        sql = "SELECT raw_json FROM incidents WHERE incident_id = ?"
        with self._get_connection() as conn:
            row = conn.execute(sql, (incident_id,)).fetchone()
            if not row:
                return None
            return IncidentRecord.model_validate_json(row["raw_json"])

    def get(self, incident_id: str) -> Optional[IncidentRecord]:
        """Alias implementing BaseIncidentStore interface."""
        return self.get_incident(incident_id)

    def get_incident_dict(self, incident_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve raw relational column dictionary for an incident."""
        sql = "SELECT * FROM incidents WHERE incident_id = ?"
        with self._get_connection() as conn:
            row = conn.execute(sql, (incident_id,)).fetchone()
            if not row:
                return None
            return dict(row)

    # -------------------------------------------------------------------------
    # Querying and Filtering
    # -------------------------------------------------------------------------
    def list_incidents(
        self,
        limit: int = 50,
        target_id: Optional[str] = None,
        fault_type: Optional[Union[FaultType, str]] = None,
        status: Optional[Union[IncidentStatus, str]] = None,
    ) -> List[IncidentRecord]:
        """List incidents with optional filtering, ordered by timestamp descending."""
        clauses = []
        params = []
        if target_id:
            clauses.append("affected_target = ?")
            params.append(target_id)
        if fault_type:
            ft_val = fault_type.value if hasattr(fault_type, "value") else str(fault_type)
            clauses.append("fault_type = ?")
            params.append(ft_val)
        if status:
            st_val = status.value if hasattr(status, "value") else str(status)
            clauses.append("final_status = ?")
            params.append(st_val)

        where_clause = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = f"SELECT raw_json FROM incidents {where_clause} ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        with self._get_connection() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
            return [IncidentRecord.model_validate_json(r["raw_json"]) for r in rows]

    def filter_by_fault_type(
        self,
        fault_type: Union[FaultType, str],
        limit: int = 50,
    ) -> List[IncidentRecord]:
        """Retrieve incidents matching a specific fault type."""
        ft_val = fault_type.value if hasattr(fault_type, "value") else str(fault_type)
        sql = "SELECT raw_json FROM incidents WHERE fault_type = ? ORDER BY timestamp DESC LIMIT ?"
        with self._get_connection() as conn:
            rows = conn.execute(sql, (ft_val, limit)).fetchall()
            return [IncidentRecord.model_validate_json(r["raw_json"]) for r in rows]

    def filter_by_status(
        self,
        status: Union[IncidentStatus, str],
        limit: int = 50,
    ) -> List[IncidentRecord]:
        """Retrieve incidents matching a specific lifecycle status."""
        st_val = status.value if hasattr(status, "value") else str(status)
        sql = "SELECT raw_json FROM incidents WHERE final_status = ? ORDER BY timestamp DESC LIMIT ?"
        with self._get_connection() as conn:
            rows = conn.execute(sql, (st_val, limit)).fetchall()
            return [IncidentRecord.model_validate_json(r["raw_json"]) for r in rows]

    def get_recent(self, limit: int = 10) -> List[IncidentRecord]:
        """Retrieve the most recent incidents ordered by timestamp descending."""
        return self.list_incidents(limit=limit)

    def close(self) -> None:
        """Close persistent in-memory database connection if open."""
        with self._lock:
            if self._mem_conn:
                self._mem_conn.close()
                self._mem_conn = None
