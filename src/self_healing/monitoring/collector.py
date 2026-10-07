"""System and process metrics collection interfaces and implementations."""

from abc import ABC, abstractmethod
from collections import deque
from pathlib import Path
import time
from typing import List, Optional
import psutil

from self_healing.core.models import (
    DiskUsageMetrics,
    MetricSnapshot,
    ProcessMetrics,
    ProcessState,
    ServiceMetrics,
    SystemCpuMetrics,
    SystemMemoryMetrics,
    SystemSnapshot,
    TargetSpec,
    utc_now,
)
from self_healing.logging.logger import get_logger
from self_healing.monitoring.proc_reader import (
    map_proc_state_to_enum,
    parse_proc_loadavg,
    parse_proc_meminfo,
    parse_proc_pid_cmdline,
    parse_proc_pid_status,
    parse_proc_stat,
    parse_proc_uptime,
)
from self_healing.monitoring.service_inspector import ServiceInspector
from self_healing.targets.registry import is_safe_pid

logger = get_logger("monitoring")


class BaseMetricsCollector(ABC):
    """Abstract interface for metrics collectors."""

    @abstractmethod
    def collect_system_metrics(self) -> MetricSnapshot:
        """Capture global Linux system metrics."""
        pass

    @abstractmethod
    def collect_target_metrics(
        self,
        target: TargetSpec,
        pid: Optional[int] = None,
    ) -> Optional[MetricSnapshot]:
        """Capture metrics for an approved supervised target."""
        pass


class ProcessMetricsCollector:
    """Read-only process telemetry collector."""

    def __init__(self, proc_root: Path = Path("/proc")) -> None:
        self._proc_root = proc_root

    def collect_process_metrics(
        self,
        pid: int,
        target_id: Optional[str] = None,
        allow_self: bool = False,
    ) -> Optional[ProcessMetrics]:
        """Gather normalized telemetry for a single process.
        
        Args:
            pid: Process ID to inspect.
            target_id: Optional associated TargetSpec identifier.
            allow_self: If True, bypass self PID check (used for self-monitoring/tests).
            
        Returns:
            ProcessMetrics or None if PID is unsafe, dead, or inaccessible.
        """
        if not allow_self and not is_safe_pid(pid):
            logger.debug("PID %s failed safe PID boundary check", pid)
            return None

        try:
            proc = psutil.Process(pid)
            name = proc.name()
            ppid = proc.ppid()
            create_time = proc.create_time()
            cpu_percent = proc.cpu_percent(interval=None)
            mem_info = proc.memory_info()
            mem_percent = proc.memory_percent()
            num_threads = proc.num_threads()

            try:
                num_fds = proc.num_fds()
            except (AttributeError, psutil.AccessDenied):
                num_fds = None

            try:
                cmdline = proc.cmdline()
            except (psutil.AccessDenied, psutil.ZombieProcess):
                cmdline = parse_proc_pid_cmdline(pid, self._proc_root)

            # Determine state from psutil or /proc/[pid]/status
            proc_status_dict = parse_proc_pid_status(pid, self._proc_root)
            raw_state = proc_status_dict.get("State", "")
            if raw_state:
                state = map_proc_state_to_enum(raw_state)
            else:
                try:
                    state_str = proc.status()
                    state_upper = state_str.upper()
                    if hasattr(ProcessState, state_upper):
                        state = ProcessState(state_upper)
                    elif state_upper == "SLEEPING":
                        state = ProcessState.SLEEPING
                    elif state_upper == "RUNNING":
                        state = ProcessState.RUNNING
                    elif state_upper == "ZOMBIE":
                        state = ProcessState.ZOMBIE
                    elif state_upper == "STOPPED":
                        state = ProcessState.STOPPED
                    else:
                        state = ProcessState.UNKNOWN
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    state = ProcessState.UNKNOWN

            return ProcessMetrics(
                pid=pid,
                name=name,
                state=state,
                ppid=ppid,
                cpu_percent=float(cpu_percent),
                rss_bytes=int(mem_info.rss),
                vms_bytes=int(mem_info.vms),
                memory_percent=float(mem_percent),
                num_threads=num_threads,
                num_fds=num_fds,
                cmdline=cmdline,
                create_time=create_time,
                target_id=target_id,
            )
        except (psutil.NoSuchProcess, psutil.AccessDenied, ProcessLookupError) as e:
            logger.debug("Process %s not accessible: %s", pid, e)
            return None

    def find_target_processes(self, target: TargetSpec) -> List[ProcessMetrics]:
        """Find and collect metrics for all processes matching a TargetSpec."""
        results: List[ProcessMetrics] = []
        for proc in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                pid = proc.info["pid"]
                if not is_safe_pid(pid):
                    continue
                cmdline_str = " ".join(proc.info.get("cmdline") or [])
                proc_name = proc.info.get("name") or ""
                if target.process_name in proc_name and target.cmdline_substring in cmdline_str:
                    metrics = self.collect_process_metrics(pid, target_id=target.target_id)
                    if metrics:
                        results.append(metrics)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return results


class SystemMetricsCollector(BaseMetricsCollector):
    """Metrics collector implementation using psutil, user-space /proc, and systemctl."""

    def __init__(
        self,
        service_inspector: Optional[ServiceInspector] = None,
        process_collector: Optional[ProcessMetricsCollector] = None,
        proc_root: Path = Path("/proc"),
    ) -> None:
        self._proc_root = proc_root
        self._service_inspector = service_inspector or ServiceInspector()
        self._process_collector = process_collector or ProcessMetricsCollector(proc_root)

    def collect_system_snapshot(
        self,
        services: Optional[List[str]] = None,
        targets: Optional[List[TargetSpec]] = None,
    ) -> SystemSnapshot:
        """Capture a comprehensive normalized system telemetry snapshot."""
        # 1. System Uptime & Idle time
        uptime_sec, idle_sec = parse_proc_uptime(self._proc_root / "uptime")
        if uptime_sec == 0.0:
            uptime_sec = max(0.0, time.time() - psutil.boot_time())

        # 2. CPU Metrics
        cpu_pct = float(psutil.cpu_percent(interval=None))
        per_cpu = [float(p) for p in psutil.cpu_percent(interval=None, percpu=True)]
        l1, l5, l15 = parse_proc_loadavg(self._proc_root / "loadavg")
        stat_dict = parse_proc_stat(self._proc_root / "stat")

        cpu_metrics = SystemCpuMetrics(
            percent=cpu_pct,
            per_cpu_percent=per_cpu,
            load_1m=l1 if l1 > 0.0 else None,
            load_5m=l5 if l5 > 0.0 else None,
            load_15m=l15 if l15 > 0.0 else None,
            context_switches=stat_dict.get("ctxt"),
            procs_running=stat_dict.get("procs_running"),
            procs_blocked=stat_dict.get("procs_blocked"),
        )

        # 3. Memory Metrics
        vmem = psutil.virtual_memory()
        smem = psutil.swap_memory()
        meminfo = parse_proc_meminfo(self._proc_root / "meminfo")

        memory_metrics = SystemMemoryMetrics(
            total_bytes=vmem.total,
            available_bytes=vmem.available,
            used_bytes=vmem.used,
            free_bytes=vmem.free,
            percent=float(vmem.percent),
            buffers_bytes=meminfo.get("Buffers"),
            cached_bytes=meminfo.get("Cached"),
            swap_total_bytes=smem.total,
            swap_used_bytes=smem.used,
            swap_percent=float(smem.percent),
        )

        # 4. Disk Usage
        disks: List[DiskUsageMetrics] = []
        try:
            root_usage = psutil.disk_usage("/")
            disks.append(
                DiskUsageMetrics(
                    mount_point="/",
                    total_bytes=root_usage.total,
                    used_bytes=root_usage.used,
                    free_bytes=root_usage.free,
                    percent=float(root_usage.percent),
                )
            )
        except Exception as e:
            logger.debug("Failed to inspect disk usage: %s", e)

        # 5. Service Status
        inspected_services: List[ServiceMetrics] = []
        if services:
            for s in services:
                try:
                    metric = self._service_inspector.inspect_service(s)
                    inspected_services.append(metric)
                except ValueError as ve:
                    logger.warning("Skipping invalid service name %s: %s", s, ve)

        # 6. Monitored Processes
        monitored_procs: List[ProcessMetrics] = []
        if targets:
            for target in targets:
                target_procs = self._process_collector.find_target_processes(target)
                monitored_procs.extend(target_procs)

        return SystemSnapshot(
            timestamp=utc_now(),
            uptime_seconds=uptime_sec,
            idle_seconds=idle_sec if idle_sec > 0.0 else None,
            cpu=cpu_metrics,
            memory=memory_metrics,
            disks=disks,
            processes=monitored_procs,
            services=inspected_services,
        )

    def collect_system_metrics(self) -> MetricSnapshot:
        """Capture global system CPU and memory metrics (backwards-compatible contract)."""
        snapshot = self.collect_system_snapshot()

        return MetricSnapshot(
            timestamp=snapshot.timestamp,
            system_cpu_percent=snapshot.cpu.percent,
            system_memory_percent=snapshot.memory.percent,
            uptime_seconds=snapshot.uptime_seconds,
            cpu_details=snapshot.cpu,
            memory_details=snapshot.memory,
            disks=snapshot.disks,
            services=snapshot.services,
        )

    def collect_target_metrics(
        self,
        target: TargetSpec,
        pid: Optional[int] = None,
    ) -> Optional[MetricSnapshot]:
        """Capture metrics for an approved target process."""
        if pid is None or not is_safe_pid(pid):
            return None

        proc_metrics = self._process_collector.collect_process_metrics(
            pid, target_id=target.target_id
        )
        if proc_metrics is None:
            return None

        sys_metrics = self.collect_system_metrics()

        return MetricSnapshot(
            timestamp=utc_now(),
            system_cpu_percent=sys_metrics.system_cpu_percent,
            system_memory_percent=sys_metrics.system_memory_percent,
            uptime_seconds=sys_metrics.uptime_seconds,
            target_id=target.target_id,
            target_pid=pid,
            target_cpu_percent=proc_metrics.cpu_percent,
            target_rss_bytes=proc_metrics.rss_bytes,
            target_num_threads=proc_metrics.num_threads,
            target_num_fds=proc_metrics.num_fds,
            target_state=proc_metrics.state,
            cpu_details=sys_metrics.cpu_details,
            memory_details=sys_metrics.memory_details,
            disks=sys_metrics.disks,
        )


class MetricRingBuffer:
    """Fixed-capacity circular buffer storing time-series metric snapshots."""

    def __init__(self, capacity: int = 60) -> None:
        if capacity < 1:
            raise ValueError("Ring buffer capacity must be >= 1")
        self._buffer: deque[MetricSnapshot] = deque(maxlen=capacity)

    def append(self, snapshot: MetricSnapshot) -> None:
        """Add a metric snapshot to the buffer."""
        self._buffer.append(snapshot)

    def get_window(self) -> List[MetricSnapshot]:
        """Retrieve all snapshots in current window in chronological order."""
        return list(self._buffer)

    def get_latest(self) -> Optional[MetricSnapshot]:
        """Retrieve the most recent snapshot."""
        return self._buffer[-1] if self._buffer else None

    def __len__(self) -> int:
        return len(self._buffer)

    def clear(self) -> None:
        """Clear all stored snapshots."""
        self._buffer.clear()
