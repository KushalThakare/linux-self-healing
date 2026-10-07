"""Incident storage and audit logging interfaces and in-memory implementation."""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional

from self_healing.core.models import IncidentRecord
from self_healing.logging.logger import get_logger

logger = get_logger("incidents")


class BaseIncidentStore(ABC):
    """Abstract interface for storing and retrieving incident lifecycles."""

    @abstractmethod
    def save(self, record: IncidentRecord) -> None:
        """Persist or update an incident record."""
        pass

    @abstractmethod
    def get(self, incident_id: str) -> Optional[IncidentRecord]:
        """Retrieve an incident record by ID."""
        pass

    @abstractmethod
    def list_incidents(
        self,
        limit: int = 50,
        target_id: Optional[str] = None,
    ) -> List[IncidentRecord]:
        """List recent incident records with optional target filtering."""
        pass


class InMemoryIncidentStore(BaseIncidentStore):
    """In-memory implementation of IncidentStore for testing and baseline operation."""

    def __init__(self) -> None:
        self._records: Dict[str, IncidentRecord] = {}

    def save(self, record: IncidentRecord) -> None:
        self._records[record.incident_id] = record
        logger.info(
            "Recorded incident %s for target '%s' (status: %s)",
            record.incident_id,
            record.target_id,
            record.status.value,
        )

    def get(self, incident_id: str) -> Optional[IncidentRecord]:
        return self._records.get(incident_id)

    def list_incidents(
        self,
        limit: int = 50,
        target_id: Optional[str] = None,
    ) -> List[IncidentRecord]:
        results = list(self._records.values())
        if target_id:
            results = [r for r in results if r.target_id == target_id]
        results.sort(key=lambda r: r.started_at, reverse=True)
        return results[:limit]
