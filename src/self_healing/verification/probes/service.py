"""Measurable Service post-recovery verification probe."""

import http.client
import socket
import time
from typing import Any, Dict, List, Optional
import psutil

from self_healing.core.models import (
    FaultType,
    ProcessState,
    RecoveryAction,
    RecoveryResult,
    TargetSpec,
)
from self_healing.logging.logger import get_logger
from self_healing.monitoring.service_inspector import ServiceInspector
from self_healing.verification.probes.base import BaseVerificationProbe, ProbeOutcome

logger = get_logger("verification.probe.service")


class ServiceVerificationProbe(BaseVerificationProbe):
    """Verifies that service is active, process exists, and service remains healthy."""

    def __init__(
        self,
        name: str = "service_health_probe",
        service_inspector: Optional[ServiceInspector] = None,
        timeout: float = 2.0,
        sustain_interval: float = 0.2,
    ) -> None:
        super().__init__(
            name=name,
            fault_type=FaultType.PROCESS_CRASH,
            description="Verifies service is active, process exists, and remains healthy.",
        )
        self.service_inspector = service_inspector or ServiceInspector()
        self.timeout = timeout
        self.sustain_interval = sustain_interval

    def _find_target_process(self, target: TargetSpec) -> Optional[psutil.Process]:
        """Find active process for the supervised target."""
        for p in psutil.process_iter(["pid", "name", "cmdline", "status"]):
            try:
                cmdline = " ".join(p.info.get("cmdline") or [])
                if target.cmdline_substring in cmdline and p.is_running():
                    if p.status() != psutil.STATUS_ZOMBIE:
                        return p
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        return None

    def _probe_http_health(self, target: TargetSpec) -> Dict[str, Any]:
        """Send HTTP GET request to check service liveness."""
        if not target.expected_port and not target.health_check_url:
            return {"tested": False, "ok": True, "detail": "No HTTP endpoint configured"}

        port = target.expected_port or 8085
        t0 = time.perf_counter()
        try:
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=self.timeout)
            path = "/health"
            conn.request("GET", path)
            resp = conn.getresponse()
            latency_ms = (time.perf_counter() - t0) * 1000.0
            status_code = resp.status
            conn.close()
            return {
                "tested": True,
                "ok": status_code in (200, 204),
                "status_code": status_code,
                "latency_ms": round(latency_ms, 2),
                "port": port,
            }
        except Exception as ex:
            latency_ms = (time.perf_counter() - t0) * 1000.0
            return {
                "tested": True,
                "ok": False,
                "error": str(ex),
                "latency_ms": round(latency_ms, 2),
                "port": port,
            }

    def verify(
        self,
        target: TargetSpec,
        action: Optional[RecoveryAction] = None,
        recovery_result: Optional[RecoveryResult] = None,
        metrics_before: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> ProbeOutcome:
        metrics_before = metrics_before or {}

        # 1. Check systemd service if this target corresponds to a known systemd unit
        is_systemd = False
        systemd_active = False
        service_name = target.target_id.replace("demo-", "") + ".service"
        try:
            # Only inspect if name looks like a service
            s_metric = self.service_inspector.inspect_service(service_name)
            if s_metric.unit_file_state != "not-found":
                is_systemd = True
                systemd_active = s_metric.is_active
        except Exception:
            pass

        # 2. Check process existence
        proc = self._find_target_process(target)
        process_exists = proc is not None and proc.is_running()
        proc_status = proc.status() if proc else None

        # 3. HTTP health probe
        http_result = self._probe_http_health(target)

        # 4. Sustained health check (confirm process doesn't immediately flap or crash)
        if self.sustain_interval > 0 and process_exists:
            time.sleep(self.sustain_interval)
            process_exists = proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE
            if http_result.get("tested"):
                http_result = self._probe_http_health(target)

        # Overall verification pass criteria:
        # If HTTP tested: http_result["ok"] must be True.
        # Process must exist.
        passed = process_exists and http_result.get("ok", True)
        if is_systemd:
            passed = passed and systemd_active

        evidence = {
            "target_id": target.target_id,
            "process_exists": process_exists,
            "pid": proc.pid if proc else None,
            "process_status": proc_status,
            "is_systemd": is_systemd,
            "systemd_active": systemd_active,
            "http_health": http_result,
            "sustain_interval": self.sustain_interval,
            "remains_healthy": passed,
        }

        metrics_after = {
            "service_active": passed,
            "process_exists": process_exists,
            "pid": proc.pid if proc else None,
            "http_status": http_result.get("status_code"),
            "latency_ms": http_result.get("latency_ms"),
        }

        if passed:
            msg = f"Service '{target.target_id}' verified healthy: process PID {proc.pid if proc else 'N/A'} active and responding."
            return ProbeOutcome(name=self.name, passed=True, evidence=evidence, metrics_after=metrics_after, message=msg)
        else:
            reasons = []
            if not process_exists:
                reasons.append("target process does not exist or died")
            if not http_result.get("ok", True):
                err = http_result.get("error") or f"HTTP status {http_result.get('status_code')}"
                reasons.append(f"HTTP health check failed ({err})")
            if is_systemd and not systemd_active:
                reasons.append("systemd unit is inactive")
            msg = f"Service verification failed: {'; '.join(reasons)}."
            return ProbeOutcome(name=self.name, passed=False, evidence=evidence, metrics_after=metrics_after, message=msg)
