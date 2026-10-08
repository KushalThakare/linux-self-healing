"""Incident audit and persistence subsystem."""

from self_healing.incidents.repository import (
    IncidentRepository,
)
from self_healing.incidents.store import (
    BaseIncidentStore,
    InMemoryIncidentStore,
)

SqliteIncidentStore = IncidentRepository

__all__ = [
    "BaseIncidentStore",
    "InMemoryIncidentStore",
    "IncidentRepository",
    "SqliteIncidentStore",
]
