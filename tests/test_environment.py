"""Minimal environment validation test suite.

Verifies runtime environment, dependencies, Linux /proc interfaces,
process inspection, memory inspection, disk inspection, and system tools.
"""

import os
import shutil
import signal
import sys
from pathlib import Path
import pytest


def test_python_version():
    """Verify Python runtime version is 3.10+ (current: 3.14.4)."""
    assert sys.version_info >= (3, 10), f"Expected Python >= 3.10, found: {sys.version}"


def test_core_dependencies():
    """Verify all required framework libraries are importable and functional."""
    import psutil
    import pydantic
    import fastapi
    import yaml
    import sqlite3

    assert hasattr(psutil, "__version__")
    assert hasattr(pydantic, "__version__")
    assert hasattr(fastapi, "__version__")
    assert hasattr(yaml, "__version__")
    assert sqlite3.sqlite_version is not None


def test_system_binaries():
    """Verify critical Linux tools (git, systemctl, journalctl) are available in PATH."""
    git_bin = shutil.which("git")
    systemctl_bin = shutil.which("systemctl")
    journalctl_bin = shutil.which("journalctl")

    assert git_bin is not None, "git executable not found in PATH"
    assert systemctl_bin is not None, "systemctl executable not found in PATH"
    assert journalctl_bin is not None, "journalctl executable not found in PATH"


def test_systemd_active():
    """Verify systemd is running as init (PID 1)."""
    comm_path = Path("/proc/1/comm")
    assert comm_path.exists(), "/proc/1/comm does not exist"
    comm_name = comm_path.read_text().strip()
    assert comm_name == "systemd", f"Expected PID 1 to be systemd, found '{comm_name}'"


def test_proc_filesystem_interfaces():
    """Verify vital Linux /proc filesystem interfaces are readable."""
    required_proc_paths = [
        "/proc/version",
        "/proc/meminfo",
        "/proc/cpuinfo",
        "/proc/loadavg",
        "/proc/stat",
        "/proc/self/status",
        "/proc/self/cmdline",
        "/proc/sys/fs/file-nr",
    ]
    for path_str in required_proc_paths:
        path = Path(path_str)
        assert path.exists(), f"Missing required /proc path: {path_str}"
        assert os.access(path, os.R_OK), f"Cannot read /proc path: {path_str}"
        # Ensure file content is non-empty
        content = path.read_bytes()
        assert len(content) > 0, f"Empty /proc file: {path_str}"


def test_process_inspection_capability():
    """Verify psutil can inspect running processes in user space."""
    import psutil

    procs = list(psutil.process_iter(["pid", "name", "status"]))
    assert len(procs) > 0, "Failed to enumerate running processes"

    current = psutil.Process()
    assert current.pid == os.getpid()
    assert current.name() is not None
    assert current.status() in [psutil.STATUS_RUNNING, psutil.STATUS_SLEEPING]

    mem_info = current.memory_info()
    assert mem_info.rss > 0
    assert current.num_threads() >= 1


def test_memory_inspection_capability():
    """Verify ability to read system RAM and Swap metrics."""
    import psutil

    vmem = psutil.virtual_memory()
    assert vmem.total > 0
    assert vmem.available > 0
    assert 0.0 <= vmem.percent <= 100.0

    smem = psutil.swap_memory()
    assert smem.total >= 0
    assert 0.0 <= smem.percent <= 100.0


def test_disk_inspection_capability():
    """Verify ability to inspect filesystem disk metrics."""
    import psutil

    disk = psutil.disk_usage("/")
    assert disk.total > 0
    assert disk.used > 0
    assert disk.free > 0
    assert 0.0 <= disk.percent <= 100.0


def test_signals_and_capabilities():
    """Verify user-space POSIX signals are available for typed actions."""
    for sig_name in ("SIGTERM", "SIGKILL", "SIGINT", "SIGHUP", "SIGSTOP", "SIGCONT"):
        assert hasattr(signal, sig_name), f"Missing signal: {sig_name}"


if __name__ == "__main__":
    # Direct execution support
    ret = pytest.main(["-v", __file__])
    sys.exit(ret)
