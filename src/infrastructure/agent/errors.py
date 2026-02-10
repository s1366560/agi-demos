"""Unified Error Hierarchy for ReActAgent.

This module provides a structured exception hierarchy for the ReActAgent system,
enabling consistent error handling and better error reporting.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional


class ErrorSeverity(Enum):
    """Severity levels for agent errors."""
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class ErrorCategory(Enum):
    """Categories of agent errors."""
    VALIDATION = "validation"           # Input validation errors
    EXECUTION = "execution"             # Runtime execution errors
    PERMISSION = "permission"           # Permission/authorization errors
    RESOURCE = "resource"               # Resource exhaustion/unavailable
    COMMUNICATION = "communication"     # External service communication
    TIMEOUT = "timeout"                 # Operation timeout
    INTERNAL = "internal"               # Internal system errors


@dataclass
class ErrorContext:
    """Context information for an error."""
    operation: str
    sandbox_id: Optional[str] = None
    conversation_id: Optional[str] = None
    user_id: Optional[str] = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert context to dictionary."""
        return {
            "operation": self.operation,
            "sandbox_id": self.sandbox_id,
            "conversation_id": self.conversation_id,
            "user_id": self.user_id,
            "timestamp": self.timestamp.isoformat(),
            "details": self.details,
        }


class AgentError(Exception):
    """Base exception for all ReActAgent errors.

    Provides consistent error structure with context, severity, and category.
    """

    def __init__(
        self,
        message: str,
        category: ErrorCategory = ErrorCategory.INTERNAL,
        severity: ErrorSeverity = ErrorSeverity.ERROR,
        context: Optional[ErrorContext] = None,
        cause: Optional[Exception] = None,
    ) -> None:
        """Initialize the agent error.

        Args:
            message: Human-readable error message
            category: Error category for filtering/routing
            severity: Error severity level
            context: Additional context about the error
            cause: Original exception that caused this error
        """
        super().__init__(message)
        self.message = message
        self.category = category
        self.severity = severity
        self.context = context or ErrorContext(operation="unknown")
        self.cause = cause

    def to_dict(self) -> Dict[str, Any]:
        """Convert error to dictionary for API responses."""
        return {
            "error_type": self.__class__.__name__,
            "message": self.message,
            "category": self.category.value,
            "severity": self.severity.value,
            "context": self.context.to_dict(),
        }

    def __str__(self) -> str:
        """String representation of the error."""
        parts = [f"[{self.category.value.upper()}] {self.message}"]
        if self.context.operation != "unknown":
            parts.append(f"operation={self.context.operation}")
        if self.context.sandbox_id:
            parts.append(f"sandbox_id={self.context.sandbox_id}")
        return " | ".join(parts)


class AgentValidationError(AgentError):
    """Raised when input validation fails."""

    def __init__(
        self,
        message: str,
        field: Optional[str] = None,
        value: Optional[Any] = None,
        context: Optional[ErrorContext] = None,
    ) -> None:
        super().__init__(
            message=message,
            category=ErrorCategory.VALIDATION,
            severity=ErrorSeverity.WARNING,
            context=context,
        )
        self.field = field
        self.value = value

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary with field info."""
        data = super().to_dict()
        if self.field:
            data["field"] = self.field
        if self.value is not None:
            data["value"] = str(self.value)
        return data


class AgentExecutionError(AgentError):
    """Raised when execution phase fails."""

    def __init__(
        self,
        message: str,
        step: Optional[str] = None,
        tool_name: Optional[str] = None,
        context: Optional[ErrorContext] = None,
        cause: Optional[Exception] = None,
    ) -> None:
        super().__init__(
            message=message,
            category=ErrorCategory.EXECUTION,
            severity=ErrorSeverity.ERROR,
            context=context,
            cause=cause,
        )
        self.step = step
        self.tool_name = tool_name


class AgentPermissionError(AgentError):
    """Raised when permission is denied or required."""

    def __init__(
        self,
        message: str,
        action: Optional[str] = None,
        resource: Optional[str] = None,
        context: Optional[ErrorContext] = None,
    ) -> None:
        super().__init__(
            message=message,
            category=ErrorCategory.PERMISSION,
            severity=ErrorSeverity.WARNING,
            context=context,
        )
        self.action = action
        self.resource = resource


class AgentResourceError(AgentError):
    """Raised when resources are exhausted or unavailable."""

    def __init__(
        self,
        message: str,
        resource_type: Optional[str] = None,
        retryable: bool = True,
        context: Optional[ErrorContext] = None,
    ) -> None:
        super().__init__(
            message=message,
            category=ErrorCategory.RESOURCE,
            severity=ErrorSeverity.ERROR if retryable else ErrorSeverity.CRITICAL,
            context=context,
        )
        self.resource_type = resource_type
        self.retryable = retryable


class AgentCommunicationError(AgentError):
    """Raised when external service communication fails."""

    def __init__(
        self,
        message: str,
        service: Optional[str] = None,
        status_code: Optional[int] = None,
        context: Optional[ErrorContext] = None,
        cause: Optional[Exception] = None,
    ) -> None:
        super().__init__(
            message=message,
            category=ErrorCategory.COMMUNICATION,
            severity=ErrorSeverity.ERROR,
            context=context,
            cause=cause,
        )
        self.service = service
        self.status_code = status_code


class AgentTimeoutError(AgentError):
    """Raised when an operation times out."""

    def __init__(
        self,
        message: str,
        timeout_seconds: Optional[float] = None,
        operation: Optional[str] = None,
        context: Optional[ErrorContext] = None,
    ) -> None:
        super().__init__(
            message=message,
            category=ErrorCategory.TIMEOUT,
            severity=ErrorSeverity.WARNING,
            context=context,
        )
        self.timeout_seconds = timeout_seconds
        self.operation = operation


class AgentInternalError(AgentError):
    """Raised when an internal system error occurs."""

    def __init__(
        self,
        message: str,
        component: Optional[str] = None,
        context: Optional[ErrorContext] = None,
        cause: Optional[Exception] = None,
    ) -> None:
        super().__init__(
            message=message,
            category=ErrorCategory.INTERNAL,
            severity=ErrorSeverity.CRITICAL,
            context=context,
            cause=cause,
        )
        self._component = component

    @property
    def component(self) -> Optional[str]:
        """Get the component name."""
        return self._component


def wrap_error(
    error: Exception,
    message: Optional[str] = None,
    category: Optional[ErrorCategory] = None,
    context: Optional[ErrorContext] = None,
) -> AgentError:
    """Wrap a generic exception into an AgentError.

    Args:
        error: The original exception
        message: Optional override message
        category: Optional error category
        context: Optional error context

    Returns:
        An AgentError wrapping the original exception
    """
    if isinstance(error, AgentError):
        return error

    error_message = message or str(error)
    error_type = type(error).__name__

    # Determine category based on exception type
    if category is None:
        if "timeout" in error_type.lower() or "timeout" in error_message.lower():
            category = ErrorCategory.TIMEOUT
        elif "permission" in error_type.lower() or "denied" in error_message.lower():
            category = ErrorCategory.PERMISSION
        elif "connection" in error_type.lower() or "network" in error_message.lower():
            category = ErrorCategory.COMMUNICATION
        else:
            category = ErrorCategory.INTERNAL

    # Create base AgentError with appropriate category
    return AgentError(
        message=error_message,
        category=category,
        context=context,
        cause=error,
    )
