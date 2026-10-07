"""Unit tests for Linux /proc filesystem reader."""

from pathlib import Path
import pytest

from self_healing.core.models import ProcessState
from self_healing.monitoring.proc_reader import (
    map_proc_state_to_enum,
    parse_proc_loadavg,
    parse_proc_meminfo,
    parse_proc_pid_cmdline,
    parse_proc_pid_status,
    parse_proc_stat,
    parse_proc_uptime,
)


def test_parse_proc_uptime_real():
    """Verify parse_proc_uptime succeeds against real /proc/uptime."""
    uptime, idle = parse_proc_uptime()
    assert uptime > 0.0
    assert idle >= 0.0


def test_parse_proc_uptime_mock(tmp_path: Path):
    """Verify parse_proc_uptime correctly parses custom mock file."""
    mock_file = tmp_path / "uptime"
    mock_file.write_text("3600.50 14400.25\n")
    uptime, idle = parse_proc_uptime(mock_file)
    assert uptime == 3600.50
    assert idle == 14400.25


def test_parse_proc_uptime_nonexistent(tmp_path: Path):
    """Verify parse_proc_uptime handles missing file gracefully."""
    uptime, idle = parse_proc_uptime(tmp_path / "nonexistent")
    assert uptime == 0.0
    assert idle == 0.0


def test_parse_proc_loadavg_real():
    """Verify parse_proc_loadavg succeeds against real /proc/loadavg."""
    l1, l5, l15 = parse_proc_loadavg()
    assert l1 >= 0.0
    assert l5 >= 0.0
    assert l15 >= 0.0


def test_parse_proc_loadavg_mock(tmp_path: Path):
    """Verify parse_proc_loadavg correctly parses custom mock loadavg."""
    mock_file = tmp_path / "loadavg"
    mock_file.write_text("0.15 0.35 0.55 2/250 12345\n")
    l1, l5, l15 = parse_proc_loadavg(mock_file)
    assert l1 == 0.15
    assert l5 == 0.35
    assert l15 == 0.55


def test_parse_proc_meminfo_real():
    """Verify parse_proc_meminfo extracts bytes from real /proc/meminfo."""
    meminfo = parse_proc_meminfo()
    assert "MemTotal" in meminfo
    assert meminfo["MemTotal"] > 0
    assert "MemFree" in meminfo


def test_parse_proc_meminfo_mock(tmp_path: Path):
    """Verify parse_proc_meminfo converts kB values to bytes accurately."""
    mock_file = tmp_path / "meminfo"
    mock_file.write_text(
        "MemTotal:        1048576 kB\n"
        "MemFree:          524288 kB\n"
        "Buffers:           65536 kB\n"
        "Cached:           131072 kB\n"
    )
    meminfo = parse_proc_meminfo(mock_file)
    assert meminfo["MemTotal"] == 1048576 * 1024
    assert meminfo["MemFree"] == 524288 * 1024
    assert meminfo["Buffers"] == 65536 * 1024
    assert meminfo["Cached"] == 131072 * 1024


def test_parse_proc_stat_real():
    """Verify parse_proc_stat extracts counters from real /proc/stat."""
    stat = parse_proc_stat()
    assert "ctxt" in stat
    assert stat["ctxt"] > 0
    assert "processes" in stat


def test_parse_proc_stat_mock(tmp_path: Path):
    """Verify parse_proc_stat parses target keys correctly."""
    mock_file = tmp_path / "stat"
    mock_file.write_text(
        "cpu  100 200 300 400\n"
        "ctxt 9876543\n"
        "btime 1700000000\n"
        "processes 54321\n"
        "procs_running 2\n"
        "procs_blocked 1\n"
    )
    stat = parse_proc_stat(mock_file)
    assert stat["ctxt"] == 9876543
    assert stat["processes"] == 54321
    assert stat["procs_running"] == 2
    assert stat["procs_blocked"] == 1


def test_parse_proc_pid_status_and_cmdline_mock(tmp_path: Path):
    """Verify reading PID status and cmdline from simulated /proc tree."""
    pid = 9999
    pid_dir = tmp_path / str(pid)
    pid_dir.mkdir(parents=True)

    status_file = pid_dir / "status"
    status_file.write_text(
        "Name:\tself-healing\n"
        "State:\tS (sleeping)\n"
        "VmRSS:\t1024 kB\n"
        "Threads:\t4\n"
    )

    cmdline_file = pid_dir / "cmdline"
    cmdline_file.write_bytes(b"python\x00-m\x00self_healing\x00")

    status = parse_proc_pid_status(pid, proc_root=tmp_path)
    assert status["Name"] == "self-healing"
    assert status["State"] == "S (sleeping)"
    assert status["Threads"] == "4"

    cmdline = parse_proc_pid_cmdline(pid, proc_root=tmp_path)
    assert cmdline == ["python", "-m", "self_healing"]


def test_map_proc_state_to_enum():
    """Verify Linux process state character mapping to canonical enum."""
    assert map_proc_state_to_enum("R (running)") == ProcessState.RUNNING
    assert map_proc_state_to_enum("S (sleeping)") == ProcessState.SLEEPING
    assert map_proc_state_to_enum("D (disk sleep)") == ProcessState.DISK_SLEEP
    assert map_proc_state_to_enum("T (stopped)") == ProcessState.STOPPED
    assert map_proc_state_to_enum("Z (zombie)") == ProcessState.ZOMBIE
    assert map_proc_state_to_enum("X (dead)") == ProcessState.DEAD
    assert map_proc_state_to_enum("I (idle)") == ProcessState.IDLE
    assert map_proc_state_to_enum("unknown") == ProcessState.UNKNOWN
    assert map_proc_state_to_enum("") == ProcessState.UNKNOWN
