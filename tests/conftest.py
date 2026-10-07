"""Shared pytest fixtures for the self-healing test suite."""

from pathlib import Path
import pytest

from self_healing.config.settings import AppConfig, get_default_config
from self_healing.core.models import (
    ActionType,
    DiagnosisReport,
    FaultEvent,
    FaultSeverity,
    FaultType,
    MetricSnapshot,
    PolicyDecision,
    TargetSpec,
    utc_now,
)
from self_healing.targets.registry import TargetRegistry


@pytest.fixture
def default_config() -> AppConfig:
    """Fixture providing default AppConfig instance."""
    return get_default_config()


@pytest.fixture
def sample_target() -> TargetSpec:
    """Fixture providing a standard demo target specification."""
    return TargetSpec(
        target_id="demo-test-app",
        process_name="python3",
        cmdline_substring="demo_test_app.py",
        expected_port=8080,
        working_dir_prefix="/home/arskage/linux-self-healing",
        max_restarts_per_window=3,
        cooldown_seconds=5.0,
        health_check_url="http://127.0.0.1:8080/health",
        enabled=True,
    )


@pytest.fixture
def target_registry(sample_target: TargetSpec) -> TargetRegistry:
    """Fixture providing a TargetRegistry with sample target registered."""
    return TargetRegistry([sample_target])


@pytest.fixture
def sample_metric() -> MetricSnapshot:
    """Fixture providing a healthy sample metric snapshot."""
    return MetricSnapshot(
        timestamp=utc_now(),
        system_cpu_percent=15.5,
        system_memory_percent=25.0,
        target_id="demo-test-app",
        target_pid=12345,
        target_cpu_percent=5.0,
        target_rss_bytes=50 * 1024 * 1024,
        target_num_threads=4,
        target_num_fds=12,
    )


@pytest.fixture
def sample_fault_event() -> FaultEvent:
    """Fixture providing a sample FaultEvent."""
    return FaultEvent(
        event_id="evt-12345",
        target_id="demo-test-app",
        fault_type=FaultType.HIGH_CPU,
        severity=FaultSeverity.HIGH,
        detected_at=utc_now(),
        triggering_value=96.5,
        threshold_value=90.0,
        description="CPU sustained above threshold",
    )


@pytest.fixture
def sample_diagnosis(sample_fault_event: FaultEvent, sample_metric: MetricSnapshot) -> DiagnosisReport:
    """Fixture providing a sample DiagnosisReport."""
    return DiagnosisReport(
        diagnosis_id="diag-12345",
        event_id=sample_fault_event.event_id,
        target_id=sample_fault_event.target_id,
        fault_type=sample_fault_event.fault_type,
        root_cause="Runaway worker loop causing sustained 100% CPU",
        confidence=0.95,
        recommended_action=ActionType.GRACEFUL_TERMINATE,
        telemetry_window=[sample_metric],
    )
