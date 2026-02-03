"""Tests for Sandbox exceptions.

Tests the exception hierarchy, retry logic, and serialization.
"""


from src.domain.model.sandbox.exceptions import (
    SandboxConnectionError,
    SandboxError,
    SandboxHealthCheckError,
    SandboxResourceError,
    SandboxStateTransitionError,
    SandboxTimeoutError,
    SandboxValidationError,
    is_retryable_error,
)


class TestSandboxError:
    """Tests for base SandboxError."""

    def test_should_create_with_basic_params(self) -> None:
        """Should create exception with message."""
        error = SandboxError("Test error")
        assert error.message == "Test error"
        assert error.sandbox_id is None
        assert error.operation is None

    def test_should_create_with_all_params(self) -> None:
        """Should create exception with all parameters."""
        error = SandboxError(
            message="Test error",
            sandbox_id="sb-123",
            operation="create",
            details={"key": "value"},
        )
        assert error.message == "Test error"
        assert error.sandbox_id == "sb-123"
        assert error.operation == "create"
        assert error.details == {"key": "value"}

    def test_to_dict(self) -> None:
        """Should convert to dictionary."""
        error = SandboxError(
            message="Test error",
            sandbox_id="sb-123",
            operation="create",
        )
        data = error.to_dict()
        assert data["error_type"] == "SandboxError"
        assert data["message"] == "Test error"
        assert data["sandbox_id"] == "sb-123"
        assert data["operation"] == "create"


class TestSandboxConnectionError:
    """Tests for SandboxConnectionError."""

    def test_should_create_connection_error(self) -> None:
        """Should create connection error."""
        error = SandboxConnectionError(
            message="Connection failed",
            sandbox_id="sb-123",
            endpoint="ws://localhost:8765",
        )
        assert error.message == "Connection failed"
        assert error.sandbox_id == "sb-123"
        assert error.operation == "connect"
        assert error.endpoint == "ws://localhost:8765"
        assert error.retryable is True  # Connection errors are retryable

    def test_should_be_retryable_by_default(self) -> None:
        """Should be retryable by default."""
        error = SandboxConnectionError("Connection failed")
        assert error.retryable is True


class TestSandboxResourceError:
    """Tests for SandboxResourceError."""

    def test_should_create_resource_error(self) -> None:
        """Should create resource error."""
        error = SandboxResourceError(
            message="No ports available",
            resource_type="port",
            available=0,
        )
        assert error.message == "No ports available"
        assert error.resource_type == "port"
        assert error.available == 0
        assert error.retryable is False  # Resource errors are not retryable


class TestSandboxTimeoutError:
    """Tests for SandboxTimeoutError."""

    def test_should_create_timeout_error(self) -> None:
        """Should create timeout error."""
        error = SandboxTimeoutError(
            message="Operation timed out",
            sandbox_id="sb-123",
            operation="execute_tool",
            timeout_seconds=30.0,
        )
        assert error.message == "Operation timed out"
        assert error.sandbox_id == "sb-123"
        assert error.operation == "execute_tool"
        assert error.timeout_seconds == 30.0
        assert error.retryable is True


class TestSandboxValidationError:
    """Tests for SandboxValidationError."""

    def test_should_create_validation_error(self) -> None:
        """Should create validation error."""
        error = SandboxValidationError(
            message="Invalid memory limit",
            field="memory_limit",
            value="unlimited",
        )
        assert error.message == "Invalid memory limit"
        assert error.field == "memory_limit"
        assert error.value == "unlimited"
        assert error.retryable is False


class TestSandboxStateTransitionError:
    """Tests for SandboxStateTransitionError."""

    def test_should_create_transition_error(self) -> None:
        """Should create state transition error."""
        error = SandboxStateTransitionError(
            sandbox_id="sb-123",
            current_state="RUNNING",
            target_state="STARTING",
        )
        assert "Invalid state transition" in error.message
        assert error.sandbox_id == "sb-123"
        assert error.current_state == "RUNNING"
        assert error.target_state == "STARTING"
        assert error.retryable is False

    def test_should_include_allowed_transitions(self) -> None:
        """Should include allowed transitions when provided."""
        allowed = {"RUNNING": {"ERROR", "TERMINATED"}}
        error = SandboxStateTransitionError(
            sandbox_id="sb-123",
            current_state="RUNNING",
            target_state="STARTING",
            allowed_transitions=allowed,
        )
        assert error.allowed_transitions == allowed


class TestSandboxHealthCheckError:
    """Tests for SandboxHealthCheckError."""

    def test_should_create_health_check_error(self) -> None:
        """Should create health check error."""
        error = SandboxHealthCheckError(
            message="Health check failed",
            sandbox_id="sb-123",
            health_check_type="container",
        )
        assert error.message == "Health check failed"
        assert error.sandbox_id == "sb-123"
        assert error.health_check_type == "container"
        assert error.retryable is True


class TestIsRetryableError:
    """Tests for is_retryable_error utility function."""

    def test_connection_error_is_retryable(self) -> None:
        """Should return True for connection errors."""
        error = SandboxConnectionError("Connection failed")
        assert is_retryable_error(error) is True

    def test_resource_error_is_not_retryable(self) -> None:
        """Should return False for resource errors."""
        error = SandboxResourceError("No ports available", "port")
        assert is_retryable_error(error) is False

    def test_timeout_error_is_retryable(self) -> None:
        """Should return True for timeout errors."""
        error = SandboxTimeoutError("Operation timed out")
        assert is_retryable_error(error) is True

    def test_validation_error_is_not_retryable(self) -> None:
        """Should return False for validation errors."""
        error = SandboxValidationError("Invalid config")
        assert is_retryable_error(error) is False

    def test_non_sandbox_error_is_not_retryable(self) -> None:
        """Should return False for non-sandbox errors."""
        error = ValueError("Some other error")
        assert is_retryable_error(error) is False

    def test_default_sandbox_error_is_not_retryable(self) -> None:
        """Should return False for base SandboxError without retryable flag."""
        error = SandboxError("Generic error")
        assert is_retryable_error(error) is False
