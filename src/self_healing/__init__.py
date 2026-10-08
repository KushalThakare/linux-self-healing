"""Autonomous Fault Detection and Self-Healing System for Linux.

User-space Linux self-healing framework implementing the closed-loop cycle:
MONITOR -> DETECT -> DIAGNOSE -> GUARDRAIL -> HEAL -> VERIFY.
"""

from self_healing.orchestrator import OrchestratorStats, SelfHealingOrchestrator

__version__ = "0.1.0"
__author__ = "Self-Healing Research Team"

__all__ = [
    "__version__",
    "__author__",
    "SelfHealingOrchestrator",
    "OrchestratorStats",
]
