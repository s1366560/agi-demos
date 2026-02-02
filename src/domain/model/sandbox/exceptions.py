"""Sandbox exception types with fine-grained error handling.

This module defines a hierarchy of sandbox-related exceptions to enable
better error handling and retry logic.
"""

from typing import Any, Dict, Optional


class SandboxError(Exception):
    """Base exception for all sandbox-related errors."""

    def __init__(
        self,
        message: str,
        sandbox_id: Optional[str] = None,
        operation: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message)
        self.message = message
        self.sandbox_id = sandbox_id
        self.operation = operation
        self.details = details or {}

    def to_dict(self) -> Dict[str, Any]:
        """Convert exception to dictionary for API responses."""
        return {
            "error_type": self.__class__.__name__,
            "message": self.message,
            "sandbox_id": self.sandbox_id,
            "operation": self.operation,
            "details": self.details,
        }


class SandboxConnectionError(SandboxError):
    """Raised when connection to sandbox fails."""

    def __init__(
        self,
        message: str,
        sandbox_id: Optional[str] = None,
        endpoint: Optional[str] = None,
        retryable: bool = True,
        operation: Optional[str] = None,
    ):
        super().__init__(message, sandbox_id, operation or "connect")
        self.endpoint = endpoint
        self.retryable = retryable


class SandboxResourceError(SandboxError):
    """Raised when sandbox resources cannot be acquired."""

    def __init__(
        self,
        message: str,
        resource_type: str,
        sandbox_id: Optional[str] = None,
        available: Optional[int] = None,
    ):
        super().__init__(message, sandbox_id, "acquire_resource")
        self.resource_type = resource_type
        self.available = available
        self.retryable = False  # Resource exhaustion is not retryable immediately


class SandboxTimeoutError(SandboxError):
    """Raised when sandbox operation times out."""

    def __init__(
        self,
        message: str,
        sandbox_id: Optional[str] = None,
        operation: Optional[str] = None,
        timeout_seconds: Optional[float] = None,
    ):
        super().__init__(message, sandbox_id, operation)
        self.timeout_seconds = timeout_seconds
        self.retryable = True


class SandboxValidationError(SandboxError):
    """Raised when sandbox configuration is invalid."""

    def __init__(
        self,
        message: str,
        field: Optional[str] = None,
        value: Optional[Any] = None,
    ):
        super().__init__(message, None, "validate")
        self.field = field
        self.value = value
        self.retryable = False


class SandboxStateTransitionError(SandboxError):
    """Raised when an invalid state transition is attempted."""

    def __init__(
        self,
        sandbox_id: str,
        current_state: str,
        target_state: str,
        allowed_transitions: Optional[Dict[str, set]] = None,
    ):
        message = (
            f"Invalid state transition for sandbox {sandbox_id}: "
            f"{current_state} -> {target_state}"
        )
        super().__init__(message, sandbox_id, "transition")
        self.current_state = current_state
        self.target_state = target_state
        self.allowed_transitions = allowed_transitions
        self.retryable = False


class SandboxHealthCheckError(SandboxError):
    """Raised when sandbox health check fails."""

    def __init__(
        self,
        message: str,
        sandbox_id: Optional[str] = None,
        health_check_type: Optional[str] = None,
    ):
        super().__init__(message, sandbox_id, "health_check")
        self.health_check_type = health_check_type
        self.retryable = True


# Retryable error check
def is_retryable_error(error: Exception) -> bool:
    """Check if an error is retryable.

    Args:
        error: The exception to check

    Returns:
        True if the error should be retried, False otherwise
    """
    if isinstance(error, SandboxError):
        return getattr(error, "retryable", False)
    # Default non-sandbox errors to not retryable
    return False
