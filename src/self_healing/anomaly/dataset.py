"""Synthetic and telemetry dataset generators for baseline training and evaluation."""

from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional
import numpy as np

from self_healing.core.models import (
    DiskUsageMetrics,
    MetricSnapshot,
    ProcessMetrics,
    ProcessState,
    ServiceMetrics,
    SystemCpuMetrics,
    SystemMemoryMetrics,
)


def generate_healthy_snapshots(
    n_samples: int = 150,
    target_id: str = "demo-cpu",
    interval_seconds: float = 1.0,
    random_seed: int = 42,
) -> List[MetricSnapshot]:
    """Generate realistic baseline healthy telemetry snapshots for a supervised demo target.
    
    Produces stochastic fluctuations within nominal operating boundaries:
    - Host CPU: 5% - 20%
    - Target CPU: 1% - 10%
    - Target RSS: 25MB - 35MB
    - Threads: 2 - 4
    - Open FDs: 12 - 18
    - Disk: ~30%
    - State: RUNNING
    """
    rng = np.random.default_rng(random_seed)
    base_time = datetime.now(timezone.utc) - timedelta(seconds=n_samples * interval_seconds)
    snapshots: List[MetricSnapshot] = []

    for i in range(n_samples):
        timestamp = base_time + timedelta(seconds=i * interval_seconds)
        sys_cpu = float(np.clip(rng.normal(loc=12.0, scale=3.0), 2.0, 30.0))
        sys_mem = float(np.clip(rng.normal(loc=25.0, scale=1.5), 15.0, 35.0))
        target_cpu = float(np.clip(rng.normal(loc=5.0, scale=1.5), 0.5, 15.0))
        rss_bytes = int(np.clip(rng.normal(loc=30 * 1024 * 1024, scale=200 * 1024), 25 * 1024 * 1024, 35 * 1024 * 1024))
        threads = int(rng.choice([2, 3, 4]))
        fds = int(rng.integers(12, 18))
        disk_pct = float(np.clip(rng.normal(loc=30.0, scale=1.0), 20.0, 40.0))

        snap = MetricSnapshot(
            timestamp=timestamp,
            system_cpu_percent=sys_cpu,
            system_memory_percent=sys_mem,
            uptime_seconds=3600.0 + i,
            target_id=target_id,
            target_pid=10001,
            target_cpu_percent=target_cpu,
            target_rss_bytes=rss_bytes,
            target_num_threads=threads,
            target_num_fds=fds,
            target_state=ProcessState.RUNNING,
            cpu_details=SystemCpuMetrics(percent=sys_cpu),
            memory_details=SystemMemoryMetrics(total_bytes=16 * 1024 * 1024 * 1024, available_bytes=12 * 1024 * 1024 * 1024, used_bytes=4 * 1024 * 1024 * 1024, free_bytes=12 * 1024 * 1024 * 1024, percent=sys_mem),
            disks=[DiskUsageMetrics(mount_point="/", total_bytes=100 * 1024 * 1024 * 1024, used_bytes=int(disk_pct * 1024 * 1024 * 1024), free_bytes=int((100 - disk_pct) * 1024 * 1024 * 1024), percent=disk_pct)],
            services=[ServiceMetrics(service_name="demo-service", is_active=True, active_state="active", sub_state="running")],
            processes=[
                ProcessMetrics(
                    pid=10001,
                    name="python3",
                    cpu_percent=target_cpu,
                    memory_percent=1.0,
                    rss_bytes=rss_bytes,
                    vms_bytes=rss_bytes * 2,
                    state=ProcessState.RUNNING,
                    num_threads=threads,
                    num_fds=fds,
                    cmdline=["python3", "demo_workloads.py", "cpu_spin"],
                    target_id=target_id,
                )
            ],
        )
        snapshots.append(snap)

    return snapshots


def generate_anomalous_snapshots(
    fault_type: str,
    n_samples: int = 15,
    target_id: str = "demo-cpu",
    interval_seconds: float = 1.0,
    random_seed: int = 99,
) -> List[MetricSnapshot]:
    """Generate telemetry snapshots exhibiting a specific injected fault condition.
    
    Supported fault types:
    - 'cpu_runaway': Sustained 90%+ CPU utilization.
    - 'memory_leak': Monotonically growing RSS footprint (+50MB per step).
    - 'deadlock': 0% CPU, static threads, zero progress.
    - 'service_crash': Dead process state, exit code non-zero.
    - 'disk_exhaustion': Disk usage spiking to 95%+.
    """
    rng = np.random.default_rng(random_seed)
    base_time = datetime.now(timezone.utc)
    snapshots: List[MetricSnapshot] = []

    for i in range(n_samples):
        timestamp = base_time + timedelta(seconds=i * interval_seconds)
        sys_cpu = 15.0
        sys_mem = 25.0
        target_cpu = 5.0
        rss_bytes = 30 * 1024 * 1024
        threads = 3
        fds = 15
        state = ProcessState.RUNNING
        disk_pct = 30.0

        if fault_type in ("cpu", "cpu_runaway", "cpu_spin"):
            target_cpu = float(np.clip(rng.normal(loc=95.0, scale=2.0), 90.0, 100.0))
            sys_cpu = float(np.clip(target_cpu * 0.9, 85.0, 100.0))
        elif fault_type in ("memory", "memory_leak"):
            # Progressive linear leak
            growth_mb = (i + 1) * 60
            rss_bytes = int((30 + growth_mb) * 1024 * 1024)
            target_cpu = 12.0
            sys_mem = float(min(25.0 + (i * 2.0), 90.0))
        elif fault_type in ("deadlock",):
            target_cpu = 0.0
            threads = 8
            state = ProcessState.SLEEPING
        elif fault_type in ("service", "service_crash", "crash"):
            target_cpu = 0.0
            rss_bytes = 0
            state = ProcessState.DEAD
        elif fault_type in ("disk", "disk_fill", "disk_exhaustion"):
            disk_pct = min(30.0 + (i * 6.0), 98.0)

        snap = MetricSnapshot(
            timestamp=timestamp,
            system_cpu_percent=sys_cpu,
            system_memory_percent=sys_mem,
            uptime_seconds=5000.0 + i,
            target_id=target_id,
            target_pid=10001 if state != ProcessState.DEAD else None,
            target_cpu_percent=target_cpu,
            target_rss_bytes=rss_bytes,
            target_num_threads=threads,
            target_num_fds=fds,
            target_state=state,
            cpu_details=SystemCpuMetrics(percent=sys_cpu),
            memory_details=SystemMemoryMetrics(total_bytes=16 * 1024 * 1024 * 1024, available_bytes=8 * 1024 * 1024 * 1024, used_bytes=8 * 1024 * 1024 * 1024, free_bytes=8 * 1024 * 1024 * 1024, percent=50.0),
            disks=[DiskUsageMetrics(mount_point="/", total_bytes=100 * 1024 * 1024 * 1024, used_bytes=int(disk_pct * 1024 * 1024 * 1024), free_bytes=int((100 - disk_pct) * 1024 * 1024 * 1024), percent=disk_pct)],
            services=[
                ServiceMetrics(
                    service_name="demo-service",
                    is_active=False if state == ProcessState.DEAD else True,
                    active_state="failed" if state == ProcessState.DEAD else "active",
                    sub_state="failed" if state == ProcessState.DEAD else "running",
                )
            ],
            processes=[] if state == ProcessState.DEAD else [
                ProcessMetrics(
                    pid=10001,
                    name="python3",
                    cpu_percent=target_cpu,
                    memory_percent=2.0,
                    rss_bytes=rss_bytes,
                    vms_bytes=rss_bytes * 2,
                    state=state,
                    num_threads=threads,
                    num_fds=fds,
                    cmdline=["python3", "demo_workloads.py"],
                    target_id=target_id,
                )
            ],
        )
        snapshots.append(snap)

    return snapshots
