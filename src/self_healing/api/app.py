"""FastAPI management and health check application."""

from typing import Any, Dict, List, Optional
from fastapi import FastAPI, HTTPException
import psutil

from self_healing import __version__
from self_healing.config.settings import AppConfig, get_default_config
from self_healing.core.models import TargetSpec, utc_now
from self_healing.targets.registry import TargetRegistry


def create_app(
    config: Optional[AppConfig] = None,
    target_registry: Optional[TargetRegistry] = None,
) -> FastAPI:
    """Create and configure the FastAPI management application."""
    app_config = config or get_default_config()
    registry = target_registry or TargetRegistry(app_config.targets)

    app = FastAPI(
        title="Linux Self-Healing Management API",
        version=__version__,
        description="Operator telemetry and control endpoints for Linux self-healing framework.",
    )

    @app.get("/health")
    def health_check() -> Dict[str, Any]:
        """Basic system health check endpoint."""
        mem = psutil.virtual_memory()
        cpu = psutil.cpu_percent(interval=None)

        return {
            "status": "healthy",
            "version": __version__,
            "timestamp": utc_now().isoformat(),
            "dry_run": app_config.system.dry_run,
            "system": {
                "cpu_percent": float(cpu),
                "memory_percent": float(mem.percent),
                "memory_available_mb": round(mem.available / (1024 * 1024), 2),
            },
            "registered_targets": len(registry.list_targets()),
        }

    @app.get("/api/v1/status")
    def system_status() -> Dict[str, Any]:
        """Extended framework status endpoint."""
        return {
            "version": __version__,
            "mode": app_config.system.mode,
            "dry_run": app_config.system.dry_run,
            "log_level": app_config.system.log_level,
            "monitoring_interval_s": app_config.monitoring.sample_interval_seconds,
            "guardrails": {
                "max_actions_per_window": app_config.guardrails.max_actions_per_window,
                "flapping_window_s": app_config.guardrails.flapping_window_seconds,
                "cooldown_s": app_config.guardrails.default_cooldown_seconds,
            },
            "targets_count": len(registry.list_targets()),
        }

    @app.get("/api/v1/targets", response_model=List[TargetSpec])
    def list_targets() -> List[TargetSpec]:
        """List all approved demo targets under supervision."""
        return registry.list_targets()

    @app.get("/api/v1/targets/{target_id}", response_model=TargetSpec)
    def get_target(target_id: str) -> TargetSpec:
        """Get details for a specific registered target."""
        try:
            return registry.get(target_id)
        except Exception:
            raise HTTPException(status_code=404, detail=f"Target '{target_id}' not found")

    return app
