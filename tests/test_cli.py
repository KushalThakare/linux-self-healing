"""Unit tests for CLI commands and health-check command."""

import json
from click.testing import CliRunner
import pytest

from self_healing.cli import cli, run_system_health_checks


def test_run_system_health_checks_structure():
    """Verify run_system_health_checks returns required keys and passes on Ubuntu VM."""
    results = run_system_health_checks()
    assert "healthy" in results
    assert "checks" in results
    assert results["checks"]["python_runtime"]["status"] == "PASS"
    assert results["checks"]["proc_filesystem"]["status"] == "PASS"
    assert results["checks"]["configuration"]["status"] == "PASS"


def test_cli_health_command():
    """Verify 'self-healing health' executes and outputs report."""
    runner = CliRunner()
    result = runner.invoke(cli, ["health"])
    assert result.exit_code == 0
    assert "Health Report" in result.output
    assert "OVERALL SYSTEM STATUS: HEALTHY" in result.output


def test_cli_health_command_json():
    """Verify 'self-healing health --json' outputs valid JSON."""
    runner = CliRunner()
    result = runner.invoke(cli, ["health", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["healthy"] is True
    assert "checks" in data


def test_cli_config_command():
    """Verify 'self-healing config' parses and displays default config."""
    runner = CliRunner()
    result = runner.invoke(cli, ["config"])
    assert result.exit_code == 0
    assert "Configuration validated successfully" in result.output
    assert "Dry-Run Enforced: True" in result.output


def test_cli_version():
    """Verify 'self-healing --version' outputs version string."""
    runner = CliRunner()
    result = runner.invoke(cli, ["--version"])
    assert result.exit_code == 0
    assert "0.1.0" in result.output


def test_cli_run_dry_run():
    """Verify 'self-healing run --dry-run' executes skeleton safely."""
    runner = CliRunner()
    result = runner.invoke(cli, ["run", "--dry-run"])
    assert result.exit_code == 0
    assert "Starting Linux Self-Healing Daemon" in result.output
    assert "Dry-Run: True" in result.output
