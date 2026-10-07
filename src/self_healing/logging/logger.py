"""Structured logging subsystem for the self-healing system.

Supports both human-readable console logging and machine-readable JSON logging
with ISO 8601 UTC timestamps, component names, and structured metadata.
"""

from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import sys
from typing import Any, Dict, Optional


class JSONFormatter(logging.Formatter):
    """Custom formatter producing single-line JSON logs."""

    def format(self, record: logging.LogRecord) -> str:
        log_data: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "file": f"{record.filename}:{record.lineno}",
        }

        # Include custom extra attributes if provided
        for key, val in record.__dict__.items():
            if key not in {
                "args", "asctime", "created", "exc_info", "exc_text", "filename",
                "funcName", "id", "levelname", "levelno", "lineno", "module",
                "msecs", "message", "msg", "name", "pathname", "process",
                "processName", "relativeCreated", "stack_info", "thread",
                "threadName",
            }:
                log_data[key] = val

        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_data)


class ConsoleFormatter(logging.Formatter):
    """Clean, readable console formatter."""

    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        prefix = f"[{ts}] [{record.levelname:7s}] [{record.name}]:"
        msg = f"{prefix} {record.getMessage()}"
        if record.exc_info:
            msg += "\n" + self.formatException(record.exc_info)
        return msg


def setup_logging(
    log_level: str = "INFO",
    json_format: bool = False,
    log_file: Optional[str | Path] = None,
) -> None:
    """Configure system-wide logging.
    
    Args:
        log_level: Logging verbosity (DEBUG, INFO, WARNING, ERROR).
        json_format: If True, output structured JSON; otherwise clean text.
        log_file: Optional path to append log entries to.
    """
    root_logger = logging.getLogger("self_healing")
    root_logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))
    root_logger.handlers.clear()

    formatter = JSONFormatter() if json_format else ConsoleFormatter()

    # Console Handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # File Handler if path specified
    if log_file:
        file_path = Path(log_file)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(file_path, encoding="utf-8")
        file_handler.setFormatter(JSONFormatter() if json_format else console_handler.formatter)
        root_logger.addHandler(file_handler)


def get_logger(name: str) -> logging.Logger:
    """Get a namespaced logger under the 'self_healing' hierarchy.
    
    Args:
        name: Sub-module name (e.g. 'monitoring', 'detection').
        
    Returns:
        logging.Logger instance.
    """
    if name.startswith("self_healing"):
        return logging.getLogger(name)
    return logging.getLogger(f"self_healing.{name}")
