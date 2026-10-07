"""Unit tests for FastAPI management endpoints."""

import pytest
from starlette.testclient import TestClient

from self_healing.api.app import create_app
from self_healing.config.settings import AppConfig, get_default_config
from self_healing.core.models import TargetSpec
from self_healing.targets.registry import TargetRegistry


@pytest.fixture
def client(default_config: AppConfig, sample_target: TargetSpec) -> TestClient:
    """Fixture providing TestClient instance."""
    registry = TargetRegistry([sample_target])
    app = create_app(config=default_config, target_registry=registry)
    return TestClient(app)


def test_api_health_endpoint(client: TestClient):
    """Verify GET /health returns 200 and healthy status structure."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "version" in data
    assert "system" in data
    assert "cpu_percent" in data["system"]
    assert "memory_percent" in data["system"]
    assert data["registered_targets"] == 1


def test_api_status_endpoint(client: TestClient):
    """Verify GET /api/v1/status returns framework configuration state."""
    response = client.get("/api/v1/status")
    assert response.status_code == 200
    data = response.json()
    assert data["dry_run"] is True
    assert "guardrails" in data
    assert data["targets_count"] == 1


def test_api_targets_endpoints(client: TestClient):
    """Verify listing and retrieving targets."""
    response = client.get("/api/v1/targets")
    assert response.status_code == 200
    targets = response.json()
    assert len(targets) == 1
    assert targets[0]["target_id"] == "demo-test-app"

    # Specific existing target
    single_res = client.get("/api/v1/targets/demo-test-app")
    assert single_res.status_code == 200
    assert single_res.json()["target_id"] == "demo-test-app"

    # Nonexistent target
    missing_res = client.get("/api/v1/targets/non-existent-app")
    assert missing_res.status_code == 404
