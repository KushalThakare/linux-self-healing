"""Read-only systemd service status inspection interface."""

import re
import shutil
import subprocess
from typing import Optional

from self_healing.core.models import ServiceMetrics, utc_now
from self_healing.logging.logger import get_logger

logger = get_logger("monitoring.service")

# Strict regex allowlist for systemd service unit names
SERVICE_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9_\-\.@]+(\.service)?$")


class ServiceInspector:
    """Safe, read-only systemd service status inspector."""

    def __init__(self, systemctl_binary: Optional[str] = None) -> None:
        self._binary = systemctl_binary or shutil.which("systemctl") or "/bin/systemctl"

    def inspect_service(self, service_name: str) -> ServiceMetrics:
        """Inspect the status of a specified systemd service unit.
        
        This method is strictly read-only and never performs service modifications.
        
        Args:
            service_name: Name of the systemd unit (e.g. 'cron', 'nginx.service')
            
        Returns:
            ServiceMetrics snapshot containing active_state, sub_state, is_enabled.
            
        Raises:
            ValueError: If the service name contains illegal characters.
        """
        service_name = service_name.strip()
        if not SERVICE_NAME_PATTERN.match(service_name):
            raise ValueError(
                f"Invalid service name format: {service_name!r}. Only alphanumeric, '.', '-', '@', and '_' allowed."
            )

        unit = service_name if service_name.endswith(".service") else f"{service_name}.service"

        # Safe read-only query using systemctl show
        cmd = [
            self._binary,
            "show",
            "-p", "ActiveState",
            "-p", "SubState",
            "-p", "UnitFileState",
            unit,
        ]

        active_state = "unknown"
        sub_state = "unknown"
        is_enabled: Optional[bool] = None

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
                timeout=3.0,
            )
            for line in proc.stdout.splitlines():
                if "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().lower()
                if k == "ActiveState":
                    active_state = v
                elif k == "SubState":
                    sub_state = v
                elif k == "UnitFileState":
                    if v in ("enabled", "enabled-runtime", "static", "generated"):
                        is_enabled = True
                    elif v in ("disabled", "masked", "bad"):
                        is_enabled = False
        except (subprocess.SubprocessError, FileNotFoundError, OSError) as e:
            logger.debug("Failed to inspect systemd service %s: %s", unit, e)

        is_active = (active_state == "active")

        return ServiceMetrics(
            service_name=unit,
            is_active=is_active,
            active_state=active_state,
            sub_state=sub_state,
            is_enabled=is_enabled,
            checked_at=utc_now(),
        )
