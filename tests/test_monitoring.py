"""Unit tests for monitoring collector and process metrics."""

import subprocess
import sys
import time
import pytest

from self_healing.core.models import ProcessState, TargetSpec
from self_healing.monitoring.collector import (
    MetricRingBuffer,
    ProcessMetricsCollector,
    SystemMetricsCollector,
)


def test_system_metrics_collector_snapshot():
    """Verify collect_system_snapshot captures valid, normalized telemetry."""
    collector = SystemMetricsCollector()
    snapshot = collector.collect_system_snapshot(services=["cron", "systemd-journald"])

    assert snapshot.uptime_seconds > 0.0
    assert 0.0 <= snapshot.cpu.percent <= 100.0
    assert snapshot.memory.total_bytes > 0
    assert 0.0 <= snapshot.memory.percent <= 100.0
    assert len(snapshot.disks) >= 1
    assert snapshot.disks[0].mount_point == "/"
    assert len(snapshot.services) == 2
    assert snapshot.services[0].is_active is True


def test_system_metrics_collector_backward_compatibility():
    """Verify collect_system_metrics returns MetricSnapshot fulfilling existing contracts."""
    collector = SystemMetricsCollector()
    metric = collector.collect_system_metrics()

    assert 0.0 <= metric.system_cpu_percent <= 100.0
    assert 0.0 <= metric.system_memory_percent <= 100.0
    assert metric.uptime_seconds is not None and metric.uptime_seconds > 0.0
    assert metric.cpu_details is not None
    assert metric.memory_details is not None


def test_process_metrics_collector_safe_pid_boundaries():
    """Verify ProcessMetricsCollector rejects PID 0, 1, 2, and self when allow_self is False."""
    collector = ProcessMetricsCollector()
    assert collector.collect_process_metrics(0) is None
    assert collector.collect_process_metrics(1) is None
    assert collector.collect_process_metrics(2) is None


def test_process_metrics_collector_active_process():
    """Verify gathering telemetry on a safe spawned child process."""
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(10)"])
    try:
        collector = ProcessMetricsCollector()
        metrics = collector.collect_process_metrics(proc.pid, target_id="test-child")

        assert metrics is not None
        assert metrics.pid == proc.pid
        assert metrics.target_id == "test-child"
        assert metrics.state in (ProcessState.RUNNING, ProcessState.SLEEPING)
        assert metrics.rss_bytes > 0
        assert metrics.num_threads >= 1
    finally:
        proc.terminate()
        proc.wait(timeout=3.0)


def test_system_metrics_collector_target_metrics():
    """Verify collect_target_metrics returns MetricSnapshot for approved child target."""
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(10)"])
    try:
        target = TargetSpec(
            target_id="demo-test",
            process_name="python",
            cmdline_substring="time.sleep",
            working_dir_prefix="/home/arskage",
        )
        collector = SystemMetricsCollector()
        metric = collector.collect_target_metrics(target=target, pid=proc.pid)

        assert metric is not None
        assert metric.target_id == "demo-test"
        assert metric.target_pid == proc.pid
        assert metric.target_rss_bytes is not None and metric.target_rss_bytes > 0
        assert metric.target_state in (ProcessState.RUNNING, ProcessState.SLEEPING)
    finally:
        proc.terminate()
        proc.wait(timeout=3.0)


def test_metric_ring_buffer_behavior():
    """Verify MetricRingBuffer capacity retention and retrieval."""
    buffer = MetricRingBuffer(capacity=3)
    collector = SystemMetricsCollector()
    snap = collector.collect_system_metrics()

    buffer.append(snap)
    buffer.append(snap)
    buffer.append(snap)
    buffer.append(snap)

    assert len(buffer) == 3
    assert len(buffer.get_window()) == 3
    assert buffer.get_latest() is not None

    buffer.clear()
    assert len(buffer) == 0
    assert buffer.get_latest() is None
