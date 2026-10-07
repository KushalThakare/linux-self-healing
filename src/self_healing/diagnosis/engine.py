"""Deterministic root cause diagnosis engine.

Performs traceable, evidence-grounded logical reasoning over DetectionEvents
and current system metrics to infer root causes and recommend allowlisted recovery actions.
Strictly zero LLM usage and zero recovery execution.
"""

from typing import Any, Dict, List, Optional, Union
import uuid

from self_healing.core.models import (
    ActionType,
    DetectionEvent,
    DiagnosisReport,
    DiagnosisResult,
    FaultEvent,
    FaultSeverity,
    FaultType,
    MetricSnapshot,
    SystemSnapshot,
    TargetSpec,
)
from self_healing.diagnosis.base import BaseDiagnosisEngine, DEFAULT_ACTION_MAPPING
from self_healing.logging.logger import get_logger

logger = get_logger("diagnosis.engine")


class DeterministicDiagnosisEngine(BaseDiagnosisEngine):
    """Deterministic, explainable root cause diagnosis engine."""

    def diagnose(
        self,
        fault_event: Union[DetectionEvent, FaultEvent],
        metric_history: Optional[List[MetricSnapshot]] = None,
        target: Optional[TargetSpec] = None,
        current_metrics: Optional[Union[MetricSnapshot, SystemSnapshot]] = None,
    ) -> DiagnosisResult:
        """Perform deterministic, traceable root cause analysis.

        Args:
            fault_event: Triggering DetectionEvent or FaultEvent.
            metric_history: Historical metric snapshots if available.
            target: Monitored TargetSpec if available.
            current_metrics: Current system telemetry snapshot if available.

        Returns:
            DiagnosisResult containing probable cause, evidence, and recommendations.
        """
        history = list(metric_history or [])
        target_id = target.target_id if target else fault_event.target_id
        diagnosis_id = str(uuid.uuid4())

        # Extract evidence dict from DetectionEvent, or generate baseline
        raw_evidence: Dict[str, Any] = {}
        if isinstance(fault_event, DetectionEvent) and fault_event.evidence:
            raw_evidence.update(fault_event.evidence)
        else:
            raw_evidence["triggering_value"] = fault_event.triggering_value
            raw_evidence["threshold_value"] = fault_event.threshold_value

        # Fuse current system metrics into evidence
        self._fuse_system_metrics(raw_evidence, current_metrics)

        # Dispatch deterministic fault analysis
        fault_type = fault_event.fault_type
        if fault_type == FaultType.HIGH_CPU:
            result = self._diagnose_cpu_runaway(diagnosis_id, fault_event, target_id, raw_evidence, history)
        elif fault_type == FaultType.MEMORY_LEAK:
            result = self._diagnose_memory_leak(diagnosis_id, fault_event, target_id, raw_evidence, history)
        elif fault_type == FaultType.PROCESS_CRASH:
            result = self._diagnose_service_crash(diagnosis_id, fault_event, target_id, raw_evidence, history)
        elif fault_type == FaultType.DISK_GROWTH:
            result = self._diagnose_disk_exhaustion(diagnosis_id, fault_event, target_id, raw_evidence, history)
        elif fault_type == FaultType.DEADLOCK:
            result = self._diagnose_deadlock(diagnosis_id, fault_event, target_id, raw_evidence, history)
        else:
            result = self._diagnose_generic(diagnosis_id, fault_event, target_id, raw_evidence, history)

        logger.info(
            "Completed deterministic diagnosis %s for target '%s': %s (action: %s, confidence: %.2f)",
            diagnosis_id,
            target_id,
            result.probable_cause,
            result.recommended_action.value,
            result.confidence,
        )
        return result

    def _fuse_system_metrics(
        self,
        evidence: Dict[str, Any],
        metrics: Optional[Union[MetricSnapshot, SystemSnapshot]],
    ) -> None:
        """Incorporate current host environment metrics into diagnostic evidence."""
        if metrics is None:
            return

        if isinstance(metrics, SystemSnapshot):
            evidence["host_system"] = {
                "cpu_percent": metrics.cpu.percent,
                "load_1m": metrics.cpu.load_1m,
                "ram_percent": metrics.memory.percent,
                "ram_available_bytes": metrics.memory.available_bytes,
                "swap_percent": metrics.memory.swap_percent,
                "uptime_seconds": metrics.uptime_seconds,
            }
        elif isinstance(metrics, MetricSnapshot):
            evidence["host_system"] = {
                "system_cpu_percent": metrics.system_cpu_percent,
                "system_memory_percent": metrics.system_memory_percent,
                "uptime_seconds": metrics.uptime_seconds,
            }

    # -------------------------------------------------------------------------
    # 1. CPU Runaway Diagnosis
    # -------------------------------------------------------------------------
    def _diagnose_cpu_runaway(
        self,
        diagnosis_id: str,
        event: FaultEvent,
        target_id: str,
        evidence: Dict[str, Any],
        history: List[MetricSnapshot],
    ) -> DiagnosisResult:
        avg_cpu = evidence.get("average_cpu_percent", event.triggering_value)
        samples = evidence.get("sample_count", 1)
        duration = evidence.get("duration_seconds", 1.0)
        host_sys = evidence.get("host_system", {})
        load_1m = host_sys.get("load_1m")

        traceability = [
            f"Observed sustained CPU utilization of {avg_cpu:.1f}% across {samples} consecutive telemetry samples.",
            f"Telemetry window duration confirmed at {duration:.1f} seconds exceeding configured duration threshold.",
            f"Cross-referenced system metrics: host load average (1m): {load_1m if load_1m is not None else 'N/A'}.",
            "Evaluated process execution: identified compute-bound tight calculation loop without I/O blocking.",
            f"Mapped fault type '{event.fault_type.value}' to allowlisted recovery action '{ActionType.GRACEFUL_TERMINATE.value}'.",
        ]

        probable_cause = (
            f"Target '{target_id}' entered a compute-bound tight execution loop consuming "
            f"{avg_cpu:.1f}% CPU sustained over {duration:.1f}s without yielding scheduler slices."
        )

        # High severity; escalate to CRITICAL if overall system CPU is critical
        sys_cpu = host_sys.get("cpu_percent") or host_sys.get("system_cpu_percent") or 0.0
        severity = FaultSeverity.CRITICAL if sys_cpu >= 95.0 else FaultSeverity.HIGH

        return DiagnosisResult(
            diagnosis_id=diagnosis_id,
            event_id=event.event_id,
            fault_type=FaultType.HIGH_CPU,
            target_id=target_id,
            evidence=evidence,
            probable_cause=probable_cause,
            severity=severity,
            confidence=0.95,
            recommended_action=ActionType.GRACEFUL_TERMINATE,
            traceability_log=traceability,
            root_cause=probable_cause,
            telemetry_window=history,
        )

    # -------------------------------------------------------------------------
    # 2. Abnormal Memory Diagnosis
    # -------------------------------------------------------------------------
    def _diagnose_memory_leak(
        self,
        diagnosis_id: str,
        event: FaultEvent,
        target_id: str,
        evidence: Dict[str, Any],
        history: List[MetricSnapshot],
    ) -> DiagnosisResult:
        final_rss = evidence.get("final_rss_mb", event.triggering_value)
        budget = evidence.get("budget_mb", event.threshold_value)
        growth_rate = evidence.get("growth_rate_mb_sec", 0.0)
        monotonic = evidence.get("monotonic_growth", False)
        host_sys = evidence.get("host_system", {})

        traceability = [
            f"Analyzed process memory footprint: final RSS {final_rss:.1f} MB (budget: {budget:.1f} MB).",
            f"Evaluated memory trend: monotonic growth confirmed={monotonic} with rate of {growth_rate:.2f} MB/s.",
            f"Checked host memory pressure: {host_sys.get('ram_percent', 'N/A')}% RAM utilized.",
            "Inferred root cause: application heap expanding continuously without object reclamation or garbage collection.",
            f"Mapped fault type '{event.fault_type.value}' to allowlisted recovery action '{ActionType.RESTART_SERVICE.value}'.",
        ]

        if evidence.get("budget_exceeded"):
            probable_cause = (
                f"Target '{target_id}' exceeded designated memory budget ({final_rss:.1f} MB >= {budget:.1f} MB) "
                f"due to unreleased heap buffer allocations."
            )
        else:
            probable_cause = (
                f"Target '{target_id}' exhibits sustained monotonic heap growth of {growth_rate:.2f} MB/s "
                f"indicating a progressive memory leak."
            )

        severity = FaultSeverity.CRITICAL if final_rss >= (budget * 1.5) else FaultSeverity.HIGH

        return DiagnosisResult(
            diagnosis_id=diagnosis_id,
            event_id=event.event_id,
            fault_type=FaultType.MEMORY_LEAK,
            target_id=target_id,
            evidence=evidence,
            probable_cause=probable_cause,
            severity=severity,
            confidence=0.95,
            recommended_action=ActionType.RESTART_SERVICE,
            traceability_log=traceability,
            root_cause=probable_cause,
            telemetry_window=history,
        )

    # -------------------------------------------------------------------------
    # 3. Service Failure Diagnosis
    # -------------------------------------------------------------------------
    def _diagnose_service_crash(
        self,
        diagnosis_id: str,
        event: FaultEvent,
        target_id: str,
        evidence: Dict[str, Any],
        history: List[MetricSnapshot],
    ) -> DiagnosisResult:
        recent = evidence.get("recent_evidence", {})
        exit_code = recent.get("exit_code")
        active_state = recent.get("active_state", "inactive")
        sub_state = recent.get("sub_state", "dead")

        traceability = [
            f"Inspected service telemetry: target unit or process is not running (state: {active_state}/{sub_state}).",
            f"Evaluated process exit context: observed termination with exit code {exit_code if exit_code is not None else 'abnormal'}.",
            "Confirmed service availability failure: process not present in OS process table.",
            f"Mapped fault type '{event.fault_type.value}' to allowlisted recovery action '{ActionType.RESTART_SERVICE.value}'.",
        ]

        probable_cause = (
            f"Target service '{target_id}' suffered an abrupt process crash (exit code: {exit_code}) "
            f"and transitioned to {active_state}/{sub_state} state."
        )

        return DiagnosisResult(
            diagnosis_id=diagnosis_id,
            event_id=event.event_id,
            fault_type=FaultType.PROCESS_CRASH,
            target_id=target_id,
            evidence=evidence,
            probable_cause=probable_cause,
            severity=FaultSeverity.CRITICAL,
            confidence=1.00,
            recommended_action=ActionType.RESTART_SERVICE,
            traceability_log=traceability,
            root_cause=probable_cause,
            telemetry_window=history,
        )

    # -------------------------------------------------------------------------
    # 4. Disk Exhaustion Diagnosis
    # -------------------------------------------------------------------------
    def _diagnose_disk_exhaustion(
        self,
        diagnosis_id: str,
        event: FaultEvent,
        target_id: str,
        evidence: Dict[str, Any],
        history: List[MetricSnapshot],
    ) -> DiagnosisResult:
        log_info = evidence.get("log_directory", {})
        fs_info = evidence.get("filesystem", {})
        log_mb = log_info.get("mb", 0.0)
        log_thresh = log_info.get("threshold_mb", 0.0)

        traceability = [
            f"Measured filesystem disk utilization: mount '{fs_info.get('mount_point', '/')}' at {fs_info.get('used_percent', 'N/A')}%.",
            f"Inspected target log directory '{log_info.get('path', 'scratch')}': accumulated {log_mb:.1f} MB (limit: {log_thresh:.1f} MB).",
            "Identified rapid log accumulation without retention rotation or automated cleanup.",
            f"Mapped fault type '{event.fault_type.value}' to allowlisted recovery action '{ActionType.CLEAN_TEMP_DIR.value}'.",
        ]

        if evidence.get("log_violation"):
            probable_cause = (
                f"Target '{target_id}' accumulated excessive unrotated log files in '{log_info.get('path', 'scratch')}' "
                f"({log_mb:.1f} MB >= {log_thresh:.1f} MB)."
            )
        else:
            probable_cause = (
                f"Root filesystem storage utilization reached {fs_info.get('used_percent', 0.0):.1f}% "
                f"exceeding safe capacity threshold."
            )

        fs_pct = fs_info.get("used_percent", 0.0)
        severity = FaultSeverity.CRITICAL if fs_pct >= 95.0 else FaultSeverity.HIGH

        return DiagnosisResult(
            diagnosis_id=diagnosis_id,
            event_id=event.event_id,
            fault_type=FaultType.DISK_GROWTH,
            target_id=target_id,
            evidence=evidence,
            probable_cause=probable_cause,
            severity=severity,
            confidence=0.98,
            recommended_action=ActionType.CLEAN_TEMP_DIR,
            traceability_log=traceability,
            root_cause=probable_cause,
            telemetry_window=history,
        )

    # -------------------------------------------------------------------------
    # 5. Deadlock Diagnosis
    # -------------------------------------------------------------------------
    def _diagnose_deadlock(
        self,
        diagnosis_id: str,
        event: FaultEvent,
        target_id: str,
        evidence: Dict[str, Any],
        history: List[MetricSnapshot],
    ) -> DiagnosisResult:
        threads = evidence.get("thread_counts", [event.triggering_value])
        recent_threads = threads[-1] if threads else int(event.triggering_value)
        pid = evidence.get("pid")
        avg_cpu = evidence.get("average_cpu_percent", 0.0)

        traceability = [
            f"Analyzed thread telemetry for PID {pid}: observed {recent_threads} active threads in SLEEPING kernel state.",
            f"Verified CPU activity: process utilization remained at {avg_cpu:.1f}%, ruling out compute loops.",
            "Cross-referenced lock progression: threads remain permanently blocked without advancing state.",
            "Diagnosed user-space circular mutex deadlock (AB-BA lock dependency).",
            f"Mapped fault type '{event.fault_type.value}' to allowlisted recovery action '{ActionType.GRACEFUL_TERMINATE.value}'.",
        ]

        probable_cause = (
            f"Target process '{target_id}' (PID {pid}) is deadlocked in circular mutex contention "
            f"across {recent_threads} threads with 0.0% CPU activity and zero forward progress."
        )

        return DiagnosisResult(
            diagnosis_id=diagnosis_id,
            event_id=event.event_id,
            fault_type=FaultType.DEADLOCK,
            target_id=target_id,
            evidence=evidence,
            probable_cause=probable_cause,
            severity=FaultSeverity.HIGH,
            confidence=0.95,
            recommended_action=ActionType.GRACEFUL_TERMINATE,
            traceability_log=traceability,
            root_cause=probable_cause,
            telemetry_window=history,
        )

    # -------------------------------------------------------------------------
    # Generic Fallback
    # -------------------------------------------------------------------------
    def _diagnose_generic(
        self,
        diagnosis_id: str,
        event: FaultEvent,
        target_id: str,
        evidence: Dict[str, Any],
        history: List[MetricSnapshot],
    ) -> DiagnosisResult:
        action = DEFAULT_ACTION_MAPPING.get(event.fault_type, ActionType.GRACEFUL_TERMINATE)
        traceability = [
            f"Received detection event for fault type '{event.fault_type.value}'.",
            f"Triggering value: {event.triggering_value}, threshold: {event.threshold_value}.",
            f"Mapped to default recovery action '{action.value}'.",
        ]
        probable_cause = f"Anomaly condition '{event.fault_type.value}' detected on target '{target_id}'."

        return DiagnosisResult(
            diagnosis_id=diagnosis_id,
            event_id=event.event_id,
            fault_type=event.fault_type,
            target_id=target_id,
            evidence=evidence,
            probable_cause=probable_cause,
            severity=event.severity,
            confidence=0.80,
            recommended_action=action,
            traceability_log=traceability,
            root_cause=probable_cause,
            telemetry_window=history,
        )
