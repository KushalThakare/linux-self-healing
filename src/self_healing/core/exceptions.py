"""Custom exception hierarchy for the self-healing system.

All custom errors derive from SelfHealingError to allow explicit error handling
and clean failure reporting.
"""


class SelfHealingError(Exception):
    """Base exception for all self-healing system errors."""
    pass


class ConfigurationError(SelfHealingError):
    """Raised when configuration validation or file parsing fails."""
    pass


class SecurityViolationError(SelfHealingError):
    """Raised when an operation attempts to target an unauthorized host process
    or execute an unallowlisted action.
    """
    pass


class TargetNotFoundError(SelfHealingError):
    """Raised when a requested target is not found in the allowlisted TargetRegistry."""
    pass


class GuardrailViolationError(SelfHealingError):
    """Raised when an action violates safety guardrails (flapping, cooldown, scope)."""
    pass


class ActionExecutionError(SelfHealingError):
    """Raised when an allowlisted recovery action encounters an execution failure."""
    pass


class VerificationTimeoutError(SelfHealingError):
    """Raised when health probes exceed their maximum timeout during post-healing check."""
    pass
