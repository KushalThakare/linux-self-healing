"""Configuration system for the self-healing framework.

Provides strongly typed configuration models and loaders from YAML files.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional
import yaml
from pydantic import BaseModel, Field, field_validator

from self_healing.core.exceptions import ConfigurationError
from self_healing.core.models import TargetSpec


class SystemConfig(BaseModel):
    """Core runtime environment configuration."""
    mode: str = Field(default="development", description="Execution mode ('development' or 'production')")
    dry_run: bool = Field(default=True, description="Enforce dry-run mode (log recovery actions without executing)")
    log_level: str = Field(default="INFO", description="Logging verbosity (DEBUG, INFO, WARNING, ERROR)")
    workspace_root: str = Field(default="/home/arskage/linux-self-healing", description="Root path for project")

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper_v = v.upper()
        if upper_v not in valid_levels:
            raise ValueError(f"Invalid log_level '{v}'. Must be one of {valid_levels}")
        return upper_v


class MonitoringConfig(BaseModel):
    """Metrics collection and buffer configuration."""
    sample_interval_seconds: float = Field(default=1.0, ge=0.1, le=60.0, description="Collection interval in seconds")
    ring_buffer_size: int = Field(default=60, ge=5, le=3600, description="Number of historical metric samples retained")
    cpu_percent_threshold: float = Field(default=90.0, ge=1.0, le=100.0, description="High CPU trigger threshold")
    memory_rss_mb_threshold: float = Field(default=250.0, ge=1.0, description="Memory leak threshold in MB")


class GuardrailsConfig(BaseModel):
    """Safety policy and rate-limiting configuration."""
    max_actions_per_window: int = Field(default=3, ge=1, description="Max actions per target within flapping window")
    flapping_window_seconds: float = Field(default=900.0, ge=10.0, description="Flapping evaluation window (seconds)")
    default_cooldown_seconds: float = Field(default=30.0, ge=0.0, description="Minimum cooldown period between actions")
    enforce_target_allowlist: bool = Field(default=True, description="Strictly block non-allowlisted target operations")


class StorageConfig(BaseModel):
    """Persistence and audit logging configuration."""
    db_path: str = Field(default="data/incidents.db", description="Path to SQLite incidents database")
    audit_log_path: str = Field(default="logs/incidents.jsonl", description="Path to structured JSONL audit log")


class APIConfig(BaseModel):
    """Operator HTTP API configuration."""
    host: str = Field(default="127.0.0.1", description="Bind IP address for API server")
    port: int = Field(default=8000, ge=1024, le=65535, description="Port for API server")
    reload: bool = Field(default=False, description="Enable auto-reload for local development")


class AppConfig(BaseModel):
    """Top-level unified application configuration."""
    system: SystemConfig = Field(default_factory=SystemConfig)
    monitoring: MonitoringConfig = Field(default_factory=MonitoringConfig)
    guardrails: GuardrailsConfig = Field(default_factory=GuardrailsConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    api: APIConfig = Field(default_factory=APIConfig)
    targets: List[TargetSpec] = Field(default_factory=list, description="Approved supervised demo targets")


def get_default_config() -> AppConfig:
    """Return an AppConfig instance populated with safe defaults."""
    default_targets = [
        TargetSpec(
            target_id="demo-web",
            process_name="python3",
            cmdline_substring="demo_web_service.py",
            expected_port=8080,
            working_dir_prefix="/home/arskage/linux-self-healing",
            max_restarts_per_window=3,
            cooldown_seconds=30.0,
            health_check_url="http://127.0.0.1:8080/health",
        ),
        TargetSpec(
            target_id="demo-worker",
            process_name="python3",
            cmdline_substring="demo_worker_service.py",
            expected_port=None,
            working_dir_prefix="/home/arskage/linux-self-healing",
            max_restarts_per_window=3,
            cooldown_seconds=30.0,
            health_check_url=None,
        ),
    ]
    return AppConfig(targets=default_targets)


def load_config(config_path: Optional[str | Path] = None) -> AppConfig:
    """Load configuration from a YAML file, merging with default targets if available.
    
    Args:
        config_path: Path to YAML config file. If None, checks default locations.
        
    Returns:
        Validated AppConfig instance.
        
    Raises:
        ConfigurationError: If the file is invalid or validation fails.
    """
    candidate_paths = []
    if config_path:
        candidate_paths.append(Path(config_path))
    else:
        candidate_paths.extend([
            Path("config/default_config.yaml"),
            Path("/etc/self-healing/config.yaml"),
        ])

    target_file = None
    for p in candidate_paths:
        if p.exists() and p.is_file():
            target_file = p
            break

    if target_file is None:
        if config_path:
            raise ConfigurationError(f"Specified configuration file not found: {config_path}")
        # If no config file exists yet, return default config
        return get_default_config()

    try:
        with open(target_file, "r", encoding="utf-8") as f:
            raw_data: Dict[str, Any] = yaml.safe_load(f) or {}
    except Exception as e:
        raise ConfigurationError(f"Failed to parse YAML from {target_file}: {e}") from e

    # Also check if targets.yaml exists in same folder if not explicitly present in config
    if "targets" not in raw_data:
        targets_file = target_file.parent / "targets.yaml"
        if targets_file.exists():
            try:
                with open(targets_file, "r", encoding="utf-8") as tf:
                    targets_data = yaml.safe_load(tf) or {}
                    if isinstance(targets_data, dict) and "targets" in targets_data:
                        raw_data["targets"] = targets_data["targets"]
                    elif isinstance(targets_data, list):
                        raw_data["targets"] = targets_data
            except Exception as e:
                raise ConfigurationError(f"Failed to load targets from {targets_file}: {e}") from e

    try:
        return AppConfig(**raw_data)
    except Exception as e:
        raise ConfigurationError(f"Invalid configuration data in {target_file}: {e}") from e
