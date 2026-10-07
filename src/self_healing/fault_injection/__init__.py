"""Controlled fault injection subsystem for isolated research demo targets."""

from self_healing.fault_injection.base import (
    BaseFaultInjector,
    StubFaultInjector,
)
from self_healing.fault_injection.cpu import CpuRunawayInjector
from self_healing.fault_injection.deadlock import DeadlockInjector
from self_healing.fault_injection.disk import DiskGrowthInjector
from self_healing.fault_injection.manager import FAULT_TO_TARGET_MAP, FaultManager
from self_healing.fault_injection.memory import MemoryGrowthInjector
from self_healing.fault_injection.service import ServiceCrashInjector

__all__ = [
    "BaseFaultInjector",
    "StubFaultInjector",
    "CpuRunawayInjector",
    "MemoryGrowthInjector",
    "ServiceCrashInjector",
    "DiskGrowthInjector",
    "DeadlockInjector",
    "FaultManager",
    "FAULT_TO_TARGET_MAP",
]
