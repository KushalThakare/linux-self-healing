"""Unit tests for systemd service inspector."""

import pytest

from self_healing.monitoring.service_inspector import ServiceInspector


def test_service_inspector_valid_service():
    """Verify inspection of active standard services on Ubuntu."""
    inspector = ServiceInspector()
    result = inspector.inspect_service("systemd-journald")
    assert result.service_name == "systemd-journald.service"
    assert result.is_active is True
    assert result.active_state == "active"
    assert result.sub_state in ("running", "active")


def test_service_inspector_inactive_service():
    """Verify inspection of a nonexistent service reports inactive."""
    inspector = ServiceInspector()
    result = inspector.inspect_service("nonexistent-test-service")
    assert result.service_name == "nonexistent-test-service.service"
    assert result.is_active is False
    assert result.active_state in ("inactive", "unknown", "failed")


def test_service_inspector_rejects_injection_attempts():
    """Verify malicious or invalid service names are rejected with ValueError."""
    inspector = ServiceInspector()

    malicious_inputs = [
        "cron; rm -rf /",
        "nginx | cat /etc/passwd",
        "test && reboot",
        "service name with spaces",
        "$(whoami)",
        "`touch /tmp/evil`",
    ]

    for bad_name in malicious_inputs:
        with pytest.raises(ValueError):
            inspector.inspect_service(bad_name)
