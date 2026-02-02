"""Tests for Unified Error Hierarchy.

Tests the structured exception system for ReActAgent.
"""

import pytest
from datetime import datetime

from src.infrastructure.agent.errors import (
    ErrorSeverity,
    ErrorCategory,
    ErrorContext,
    AgentError,
    AgentValidationError,
    AgentExecutionError,
    AgentPermissionError,
    AgentResourceError,
    AgentCommunicationError,
    AgentTimeoutError,
    AgentInternalError,
    wrap_error,
)


class TestErrorContext:
    """Tests for ErrorContext."""

    def test_create_minimal_context(self) -> None:
        """Should create context with minimal fields."""
        context = ErrorContext(operation="test_operation")

        assert context.operation == "test_operation"
        assert context.sandbox_id is None
        assert context.conversation_id is None
        assert isinstance(context.timestamp, datetime)

    def test_create_full_context(self) -> None:
        """Should create context with all fields."""
        context = ErrorContext(
            operation="test_operation",
            sandbox_id="sb-123",
            conversation_id="conv-456",
            user_id="user-789",
            details={"key": "value"},
        )

        assert context.operation == "test_operation"
        assert context.sandbox_id == "sb-123"
        assert context.conversation_id == "conv-456"
        assert context.user_id == "user-789"
        assert context.details == {"key": "value"}

    def test_to_dict(self) -> None:
        """Should convert context to dictionary."""
        context = ErrorContext(
            operation="test_operation",
            sandbox_id="sb-123",
        )

        result = context.to_dict()

        assert result["operation"] == "test_operation"
        assert result["sandbox_id"] == "sb-123"
        assert "timestamp" in result


class TestAgentError:
    """Tests for base AgentError."""

    def test_create_minimal_error(self) -> None:
        """Should create error with minimal fields."""
        error = AgentError(message="Test error")

        assert str(error) == "[INTERNAL] Test error"
        assert error.message == "Test error"
        assert error.category == ErrorCategory.INTERNAL
        assert error.severity == ErrorSeverity.ERROR

    def test_create_with_all_fields(self) -> None:
        """Should create error with all fields."""
        context = ErrorContext(operation="test_op")
        cause = ValueError("Original error")

        error = AgentError(
            message="Test error",
            category=ErrorCategory.EXECUTION,
            severity=ErrorSeverity.CRITICAL,
            context=context,
            cause=cause,
        )

        assert error.message == "Test error"
        assert error.category == ErrorCategory.EXECUTION
        assert error.severity == ErrorSeverity.CRITICAL
        assert error.context == context
        assert error.cause == cause

    def test_to_dict(self) -> None:
        """Should convert error to dictionary."""
        error = AgentError(
            message="Test error",
            category=ErrorCategory.VALIDATION,
            context=ErrorContext(operation="test_op"),
        )

        result = error.to_dict()

        assert result["error_type"] == "AgentError"
        assert result["message"] == "Test error"
        assert result["category"] == "validation"
        assert result["severity"] == "error"

    def test_str_with_context(self) -> None:
        """Should format string with context."""
        error = AgentError(
            message="Test error",
            context=ErrorContext(
                operation="test_op",
                sandbox_id="sb-123",
            ),
        )

        error_str = str(error)

        assert "test_op" in error_str
        assert "sb-123" in error_str

    def test_str_without_context(self) -> None:
        """Should format string without context details."""
        error = AgentError(message="Test error")

        error_str = str(error)

        assert "[INTERNAL]" in error_str
        assert "Test error" in error_str


class TestAgentValidationError:
    """Tests for AgentValidationError."""

    def test_create_validation_error(self) -> None:
        """Should create validation error."""
        error = AgentValidationError(
            message="Invalid input",
            field="email",
            value="not-an-email",
        )

        assert error.message == "Invalid input"
        assert error.field == "email"
        assert error.value == "not-an-email"
        assert error.category == ErrorCategory.VALIDATION
        assert error.severity == ErrorSeverity.WARNING

    def test_to_dict_with_field(self) -> None:
        """Should include field in dict output."""
        error = AgentValidationError(
            message="Invalid input",
            field="email",
            value="bad",
        )

        result = error.to_dict()

        assert result["field"] == "email"
        assert result["value"] == "bad"


class TestAgentExecutionError:
    """Tests for AgentExecutionError."""

    def test_create_execution_error(self) -> None:
        """Should create execution error."""
        cause = RuntimeError("Tool failed")
        error = AgentExecutionError(
            message="Execution failed",
            step="tool_execution",
            tool_name="bash",
            cause=cause,
        )

        assert error.message == "Execution failed"
        assert error.step == "tool_execution"
        assert error.tool_name == "bash"
        assert error.cause == cause
        assert error.category == ErrorCategory.EXECUTION


class TestAgentPermissionError:
    """Tests for AgentPermissionError."""

    def test_create_permission_error(self) -> None:
        """Should create permission error."""
        error = AgentPermissionError(
            message="Access denied",
            action="write_file",
            resource="/etc/passwd",
        )

        assert error.message == "Access denied"
        assert error.action == "write_file"
        assert error.resource == "/etc/passwd"
        assert error.category == ErrorCategory.PERMISSION
        assert error.severity == ErrorSeverity.WARNING


class TestAgentResourceError:
    """Tests for AgentResourceError."""

    def test_create_retryable_resource_error(self) -> None:
        """Should create retryable resource error."""
        error = AgentResourceError(
            message="Port exhausted",
            resource_type="port",
            retryable=True,
        )

        assert error.message == "Port exhausted"
        assert error.resource_type == "port"
        assert error.retryable is True
        assert error.severity == ErrorSeverity.ERROR

    def test_create_non_retryable_resource_error(self) -> None:
        """Should create non-retryable resource error."""
        error = AgentResourceError(
            message="Disk full",
            resource_type="disk",
            retryable=False,
        )

        assert error.retryable is False
        assert error.severity == ErrorSeverity.CRITICAL


class TestAgentCommunicationError:
    """Tests for AgentCommunicationError."""

    def test_create_communication_error(self) -> None:
        """Should create communication error."""
        cause = ConnectionError("Connection refused")
        error = AgentCommunicationError(
            message="Service unavailable",
            service="openai",
            status_code=503,
            cause=cause,
        )

        assert error.message == "Service unavailable"
        assert error.service == "openai"
        assert error.status_code == 503
        assert error.cause == cause
        assert error.category == ErrorCategory.COMMUNICATION


class TestAgentTimeoutError:
    """Tests for AgentTimeoutError."""

    def test_create_timeout_error(self) -> None:
        """Should create timeout error."""
        error = AgentTimeoutError(
            message="Operation timed out",
            timeout_seconds=30.0,
            operation="llm_call",
        )

        assert error.message == "Operation timed out"
        assert error.timeout_seconds == 30.0
        assert error.operation == "llm_call"
        assert error.category == ErrorCategory.TIMEOUT
        assert error.severity == ErrorSeverity.WARNING


class TestAgentInternalError:
    """Tests for AgentInternalError."""

    def test_create_internal_error(self) -> None:
        """Should create internal error."""
        cause = AssertionError("Unexpected state")
        error = AgentInternalError(
            message="Internal error occurred",
            component="SessionProcessor",
            cause=cause,
        )

        assert error.message == "Internal error occurred"
        assert error.component == "SessionProcessor"
        assert error.cause == cause
        assert error.category == ErrorCategory.INTERNAL
        assert error.severity == ErrorSeverity.CRITICAL


class TestWrapError:
    """Tests for wrap_error utility."""

    def test_wrap_agent_error_returns_same(self) -> None:
        """Should return AgentError unchanged."""
        original = AgentExecutionError("Failed")
        result = wrap_error(original)

        assert result is original

    def test_wrap_timeout_error(self) -> None:
        """Should detect timeout from exception type."""
        original = TimeoutError("Operation timed out")
        result = wrap_error(original)

        assert isinstance(result, AgentError)
        assert result.category == ErrorCategory.TIMEOUT

    def test_wrap_timeout_from_message(self) -> None:
        """Should detect timeout from message content."""
        original = RuntimeError("Request timeout after 30s")
        result = wrap_error(original)

        assert isinstance(result, AgentError)
        assert result.category == ErrorCategory.TIMEOUT

    def test_wrap_permission_from_message(self) -> None:
        """Should detect permission from message."""
        original = ValueError("Access denied")
        result = wrap_error(original)

        assert isinstance(result, AgentError)
        assert result.category == ErrorCategory.PERMISSION

    def test_wrap_connection_from_message(self) -> None:
        """Should detect connection from message."""
        original = Exception("Network connection lost")
        result = wrap_error(original)

        assert isinstance(result, AgentError)
        assert result.category == ErrorCategory.COMMUNICATION

    def test_wrap_with_custom_message(self) -> None:
        """Should override message."""
        original = ValueError("Original error")
        result = wrap_error(original, message="Custom message")

        assert result.message == "Custom message"
        assert result.cause == original

    def test_wrap_with_custom_category(self) -> None:
        """Should use custom category."""
        original = ValueError("Error")
        result = wrap_error(original, category=ErrorCategory.VALIDATION)

        assert result.category == ErrorCategory.VALIDATION

    def test_wrap_with_context(self) -> None:
        """Should include context."""
        original = ValueError("Error")
        context = ErrorContext(operation="test_op")
        result = wrap_error(original, context=context)

        assert result.context == context


class TestErrorInheritance:
    """Tests for error inheritance."""

    def test_agent_error_is_exception(self) -> None:
        """Should be compatible with Exception."""
        error = AgentError("Test")

        assert isinstance(error, Exception)
        assert isinstance(error, AgentError)

    def test_all_errors_inherit_from_agent_error(self) -> None:
        """All specific errors should inherit from AgentError."""
        errors = [
            AgentValidationError("test"),
            AgentExecutionError("test"),
            AgentPermissionError("test"),
            AgentResourceError("test"),
            AgentCommunicationError("test"),
            AgentTimeoutError("test"),
            AgentInternalError("test"),
        ]

        for error in errors:
            assert isinstance(error, AgentError)

    def test_catch_as_agent_error(self) -> None:
        """Should be catchable as AgentError."""
        try:
            raise AgentValidationError("Invalid")
        except AgentError as e:
            assert e.category == ErrorCategory.VALIDATION


class TestErrorFormatting:
    """Tests for error formatting in different contexts."""

    def test_format_for_api_response(self) -> None:
        """Should format for JSON API response."""
        error = AgentValidationError(
            message="Invalid email format",
            field="email",
            value="bad",
        )

        result = error.to_dict()

        assert "error_type" in result
        assert "message" in result
        assert "category" in result
        assert "severity" in result

    def test_format_for_logging(self) -> None:
        """Should format for log output."""
        error = AgentExecutionError(
            message="Tool failed",
            step="execution",
            tool_name="bash",
            context=ErrorContext(
                operation="process_message",
                sandbox_id="sb-123",
            ),
        )

        log_str = str(error)

        assert "EXECUTION" in log_str
        assert "process_message" in log_str
        assert "sb-123" in log_str
