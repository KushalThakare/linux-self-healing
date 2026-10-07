"""Unit tests for logging system."""

import json
import logging
from pathlib import Path
import pytest

from self_healing.logging.logger import (
    ConsoleFormatter,
    JSONFormatter,
    get_logger,
    setup_logging,
)


def test_get_logger_prefixing():
    """Verify logger names are properly namespaced under self_healing."""
    log1 = get_logger("monitoring")
    assert log1.name == "self_healing.monitoring"

    log2 = get_logger("self_healing.detection")
    assert log2.name == "self_healing.detection"


def test_json_formatter_output():
    """Verify JSONFormatter creates valid JSON with required keys."""
    formatter = JSONFormatter()
    record = logging.LogRecord(
        name="self_healing.test",
        level=logging.INFO,
        pathname="test_file.py",
        lineno=42,
        msg="Test event occurred",
        args=(),
        exc_info=None,
    )
    record.target_id = "demo-web"

    formatted = formatter.format(record)
    parsed = json.loads(formatted)

    assert parsed["level"] == "INFO"
    assert parsed["logger"] == "self_healing.test"
    assert parsed["message"] == "Test event occurred"
    assert parsed["target_id"] == "demo-web"
    assert "timestamp" in parsed


def test_console_formatter_output():
    """Verify ConsoleFormatter creates human-readable log line."""
    formatter = ConsoleFormatter()
    record = logging.LogRecord(
        name="self_healing.test",
        level=logging.WARNING,
        pathname="test_file.py",
        lineno=10,
        msg="Resource threshold exceeded",
        args=(),
        exc_info=None,
    )
    formatted = formatter.format(record)
    assert "[WARNING]" in formatted
    assert "Resource threshold exceeded" in formatted


def test_setup_logging_file(tmp_path: Path):
    """Verify setup_logging can output to a file."""
    log_file = tmp_path / "test.log"
    setup_logging(log_level="DEBUG", json_format=True, log_file=log_file)
    logger = get_logger("file_test")
    logger.info("Writing test line to file")

    assert log_file.exists()
    content = log_file.read_text()
    assert "Writing test line to file" in content
