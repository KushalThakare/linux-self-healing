"""Unit tests for monitor CLI command and formatting helpers."""

import json
from click.testing import CliRunner
import pytest

from self_healing.cli import cli, format_bytes, format_uptime


def test_format_bytes():
    """Verify format_bytes human-readable conversions."""
    assert format_bytes(500) == "500.0 B"
    assert format_bytes(1024) == "1.0 KB"
    assert format_bytes(1024 * 1024 * 50) == "50.0 MB"
    assert format_bytes(1024 * 1024 * 1024 * 2) == "2.0 GB"


def test_format_uptime():
    """Verify format_uptime duration formatting."""
    assert format_uptime(45) == "45s"
    assert format_uptime(125) == "2m 5s"
    assert format_uptime(3665) == "1h 1m 5s"
    assert format_uptime(90000) == "1d 1h"


def test_cli_monitor_standard():
    """Verify 'self-healing monitor' executes successfully and outputs sections."""
    runner = CliRunner()
    result = runner.invoke(cli, ["monitor"])
    assert result.exit_code == 0
    assert "LINUX SYSTEM TELEMETRY SNAPSHOT" in result.output
    assert "[CPU & SCHEDULER]" in result.output
    assert "[MEMORY & SWAP]" in result.output
    assert "[FILESYSTEM DISK USAGE]" in result.output
    assert "[SYSTEMD SERVICES]" in result.output
    assert "[SUPERVISED PROCESSES]" in result.output


def test_cli_monitor_json():
    """Verify 'self-healing monitor --json' outputs valid normalized JSON."""
    runner = CliRunner()
    result = runner.invoke(cli, ["monitor", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert "timestamp" in data
    assert "uptime_seconds" in data
    assert "cpu" in data
    assert "memory" in data
    assert "disks" in data
    assert "services" in data
    assert data["cpu"]["percent"] >= 0.0
    assert data["memory"]["total_bytes"] > 0
