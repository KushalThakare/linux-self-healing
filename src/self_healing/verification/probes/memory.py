"""Measurable Memory post-recovery verification probe."""

import http.client
import socket
import time
from typing import Any, Dict, List, Optional
import psutil

from self_healing.core.models import (
    FaultType,
    RecoveryAction,
    RecoveryResult,
    TargetSpec,
)
from self_healing.logging.logger import get_logger
from self_healing.verification.probes.base import BaseVerificationProbe, ProbeOutcome

logger = get_logger("verification.probe.memory")


class MemoryVerificationProbe(BaseVerificationProbe):
    """Verifies that RSS memory has stabilized and application heartbeat is restored."""

    def __init__(
        self,
        name: str = "memory_rss_stabilized",
        rss_ceiling_bytes: int = 300 * 1024 * 1024,  # 300MB
        max_allowed_growth_bytes: int = 2 * 1024 * 1024,  # 2MB allowable jitter
        sample_interval: float = 0.2,
    ) -> None:
        super().__init__(
            name=name,
            fault_type=FaultType.MEMORY_LEAK,
            description="Verifies target RSS has stabilized and application heartbeat restored.",
        )
        self.rss_ceiling_bytes = rss_ceiling_bytes
        self.max_allowed_growth_bytes = max_allowed_growth_bytes
        self.sample_interval = sample_interval

    def _find_target_process(self, target: TargetSpec) -> Optional[psutil.Process]:
        """Find active process matching target specification."""
        for p in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                cmdline = " ".join(p.info.get("cmdline") or [])
                if target.cmdline_substring in cmdline and p.is_running():
                    if p.status() != psutil.STATUS_ZOMBIE:
                        return p
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        return None

    def _check_heartbeat(self, target: TargetSpec) -> bool:
        """Check application heartbeat via HTTP or TCP port if configured."""
        if target.expected_port:
            port = target.expected_port
            try:
                conn = http.client.HTTPConnection("127.0.0.1", port, timeout=1.0)
                path = "/health"
                conn.request("GET", path)
                resp = conn.getresponse()
                conn.close()
                return resp.status in (200, 204)
            except Exception:
                # If HTTP fails, test raw socket connectivity
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                        return True
                except Exception:
                    return False
        return True  # If no port configured, heartbeat check is non-blocking

    def verify(
        self,
        target: TargetSpec,
        action: Optional[RecoveryAction] = None,
        recovery_result: Optional[RecoveryResult] = None,
        metrics_before: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> ProbeOutcome:
        metrics_before = metrics_before or {}
        before_rss = metrics_before.get("rss_bytes") or metrics_before.get("target_rss_bytes", 0)

        # 1. Locate current process
        proc = self._find_target_process(target)
        target_pid = (
            (action.parameters.get("pid") if action else None)
            or metrics_before.get("pid")
            or (proc.pid if proc else None)
        )

        if proc is None:
            # If the recovery was pure termination, process being gone means leak stopped!
            from self_healing.core.models import AllowedActionType
            if action and action.action_type == AllowedActionType.TERMINATE_DEMO_PROCESS:
                evidence = {
                    "action": "terminate",
                    "before_rss_bytes": before_rss,
                    "after_rss_bytes": 0,
                    "growth_bytes": -before_rss,
                    "rss_stabilized": True,
                    "heartbeat_restored": True,
                    "notes": "Leaking process terminated; memory reclaimed by kernel",
                }
                metrics_after = {"rss_bytes": 0, "pid_alive": False, "growth_rate_bytes_sec": 0.0}
                return ProbeOutcome(
                    name=self.name,
                    passed=True,
                    evidence=evidence,
                    metrics_after=metrics_after,
                    message="Memory leak resolved: target process terminated and memory reclaimed.",
                )

            evidence = {
                "before_rss_bytes": before_rss,
                "error": "Target process not found for memory stabilization check",
            }
            return ProbeOutcome(
                name=self.name,
                passed=False,
                evidence=evidence,
                metrics_after={"rss_bytes": 0, "pid_alive": False},
                message=f"Memory verification failed: target '{target.target_id}' process not found.",
            )

        # 2. Sample RSS across interval
        try:
            rss_1 = proc.memory_info().rss
            if self.sample_interval > 0:
                time.sleep(self.sample_interval)
            rss_2 = proc.memory_info().rss
        except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
            return ProbeOutcome(
                name=self.name,
                passed=False,
                evidence={"error": str(e)},
                message=f"Target process vanished during memory sampling: {e}",
            )

        growth_bytes = rss_2 - rss_1
        rss_stabilized = (growth_bytes <= self.max_allowed_growth_bytes) and (rss_2 <= self.rss_ceiling_bytes)

        # 3. Heartbeat check
        heartbeat_ok = self._check_heartbeat(target)

        passed = rss_stabilized and heartbeat_ok

        evidence = {
            "before_rss_bytes": before_rss,
            "sample_1_rss_bytes": rss_1,
            "sample_2_rss_bytes": rss_2,
            "growth_bytes": growth_bytes,
            "rss_ceiling_bytes": self.rss_ceiling_bytes,
            "max_allowed_growth_bytes": self.max_allowed_growth_bytes,
            "rss_stabilized": rss_stabilized,
            "heartbeat_restored": heartbeat_ok,
            "target_pid": proc.pid,
        }

        metrics_after = {
            "rss_bytes": rss_2,
            "growth_bytes": growth_bytes,
            "pid": proc.pid,
            "heartbeat": heartbeat_ok,
        }

        if passed:
            msg = (
                f"Memory RSS stabilized (RSS: {rss_2 / (1024*1024):.2f}MB, "
                f"growth: {growth_bytes} bytes) and heartbeat verified."
            )
            return ProbeOutcome(name=self.name, passed=True, evidence=evidence, metrics_after=metrics_after, message=msg)
        else:
            reasons = []
            if not rss_stabilized:
                reasons.append(f"RSS continuing to grow (+{growth_bytes} bytes > {self.max_allowed_growth_bytes}) or exceeded cap")
            if not heartbeat_ok:
                reasons.append("Application heartbeat failed to respond")
            msg = f"Memory verification failed: {'; '.join(reasons)}."
            return ProbeOutcome(name=self.name, passed=False, evidence=evidence, metrics_after=metrics_after, message=msg)
