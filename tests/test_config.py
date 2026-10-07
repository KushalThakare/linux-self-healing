"""Unit tests for configuration system."""

import pytest
from pathlib import Path
from pydantic import ValidationError

from self_healing.config.settings import (
    AppConfig,
    SystemConfig,
    MonitoringConfig,
    GuardrailsConfig,
    StorageConfig,
    APIConfig,
    get_default_config,
    load_config,
)
from self_healing.core.exceptions import ConfigurationError


def test_default_config_validity():
    """Verify that get_default_config() produces valid default configuration."""
    cfg = get_default_config()
    assert isinstance(cfg, AppConfig)
    assert cfg.system.dry_run is True
    assert cfg.system.log_level == "INFO"
    assert len(cfg.targets) >= 1
    assert cfg.monitoring.sample_interval_seconds == 1.0
    assert cfg.guardrails.enforce_target_allowlist is True


def test_system_config_log_level_validation():
    """Verify invalid log_level raises validation error."""
    with pytest.raises(ValidationError):
        SystemConfig(log_level="INVALID_LEVEL")

    valid_cfg = SystemConfig(log_level="debug")
    assert valid_cfg.log_level == "DEBUG"


def test_monitoring_config_bounds():
    """Verify bounds checking on sample interval and buffer size."""
    with pytest.raises(ValidationError):
        MonitoringConfig(sample_interval_seconds=0.0)

    with pytest.raises(ValidationError):
        MonitoringConfig(ring_buffer_size=0)

    valid_mon = MonitoringConfig(sample_interval_seconds=2.5, ring_buffer_size=120)
    assert valid_mon.sample_interval_seconds == 2.5
    assert valid_mon.ring_buffer_size == 120


def test_load_config_from_repo_files():
    """Verify load_config() correctly parses config/default_config.yaml."""
    cfg = load_config("config/default_config.yaml")
    assert isinstance(cfg, AppConfig)
    assert cfg.system.mode in ("development", "production")
    assert len(cfg.targets) >= 1


def test_load_config_nonexistent_file():
    """Verify load_config() raises ConfigurationError for nonexistent files."""
    with pytest.raises(ConfigurationError):
        load_config("config/does_not_exist_xyz.yaml")
