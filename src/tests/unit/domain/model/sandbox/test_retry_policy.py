"""Tests for RetryPolicy with exponential backoff.

Tests the retry logic with exponential backoff for sandbox operations.
"""


import pytest

from src.domain.model.sandbox.exceptions import (
    SandboxConnectionError,
    SandboxResourceError,
    SandboxTimeoutError,
    SandboxValidationError,
)
from src.domain.model.sandbox.retry_policy import (
    RetryableError,
    RetryPolicy,
    is_retryable_error,
    max_retries_exceeded,
)


class TestRetryPolicyConfig:
    """Tests for RetryPolicy configuration."""

    def test_default_config(self) -> None:
        """Should have default values."""
        policy = RetryPolicy()
        assert policy.max_attempts == 3
        assert policy.base_delay == 1.0
        assert policy.max_delay == 30.0
        assert policy.backoff_factor == 2.0

    def test_custom_config(self) -> None:
        """Should accept custom configuration."""
        policy = RetryPolicy(
            max_attempts=5,
            base_delay=0.5,
            max_delay=60.0,
            backoff_factor=3.0,
        )
        assert policy.max_attempts == 5
        assert policy.base_delay == 0.5
        assert policy.max_delay == 60.0
        assert policy.backoff_factor == 3.0

    def test_invalid_max_attempts(self) -> None:
        """Should raise error for invalid max_attempts."""
        with pytest.raises(ValueError, match="max_attempts"):
            RetryPolicy(max_attempts=0)

        with pytest.raises(ValueError, match="max_attempts"):
            RetryPolicy(max_attempts=-1)

    def test_invalid_delays(self) -> None:
        """Should raise error for invalid delay values."""
        with pytest.raises(ValueError, match="base_delay"):
            RetryPolicy(base_delay=0)

        with pytest.raises(ValueError, match="base_delay"):
            RetryPolicy(base_delay=-1)

        with pytest.raises(ValueError, match="max_delay"):
            RetryPolicy(max_delay=0)

        with pytest.raises(ValueError, match="backoff_factor"):
            RetryPolicy(backoff_factor=0.5)

        with pytest.raises(ValueError, match="backoff_factor"):
            RetryPolicy(backoff_factor=1.0)


class TestRetryPolicyCalculateDelay:
    """Tests for delay calculation."""

    def test_first_attempt_delay(self) -> None:
        """Should return base_delay for first attempt."""
        policy = RetryPolicy(base_delay=1.0)
        assert policy._calculate_delay(0) == 1.0

    def test_second_attempt_delay(self) -> None:
        """Should apply backoff for second attempt."""
        policy = RetryPolicy(base_delay=1.0, backoff_factor=2.0)
        assert policy._calculate_delay(1) == 2.0

    def test_third_attempt_delay(self) -> None:
        """Should apply backoff twice for third attempt."""
        policy = RetryPolicy(base_delay=1.0, backoff_factor=2.0)
        assert policy._calculate_delay(2) == 4.0

    def test_delay_capped_at_max(self) -> None:
        """Should cap delay at max_delay."""
        policy = RetryPolicy(
            base_delay=10.0,
            backoff_factor=3.0,
            max_delay=50.0,
        )
        # 10, 30, 50 (capped), 50 (capped)
        assert policy._calculate_delay(0) == 10.0
        assert policy._calculate_delay(1) == 30.0
        assert policy._calculate_delay(2) == 50.0
        assert policy._calculate_delay(3) == 50.0


class TestRetryPolicyExecute:
    """Tests for execute method."""

    @pytest.mark.asyncio
    async def test_success_on_first_attempt(self) -> None:
        """Should return result on first attempt."""
        policy = RetryPolicy()

        async def operation():
            return "success"

        result = await policy.execute(operation)
        assert result == "success"

    @pytest.mark.asyncio
    async def test_success_on_retry(self) -> None:
        """Should retry on failure then succeed."""
        policy = RetryPolicy(max_attempts=3, base_delay=0.1)
        attempt_count = 0

        async def operation():
            nonlocal attempt_count
            attempt_count += 1
            if attempt_count < 2:
                raise SandboxConnectionError("Temporary failure")
            return "success"

        result = await policy.execute(operation)
        assert result == "success"
        assert attempt_count == 2

    @pytest.mark.asyncio
    async def test_exhausted_retries(self) -> None:
        """Should raise exception after max attempts."""
        policy = RetryPolicy(max_attempts=2, base_delay=0.1)

        async def operation():
            raise SandboxConnectionError("Persistent failure")

        with pytest.raises(SandboxConnectionError) as exc_info:
            await policy.execute(operation)

        assert "Persistent failure" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_non_retryable_error_fails_immediately(self) -> None:
        """Should not retry non-retryable errors."""
        policy = RetryPolicy(max_attempts=5)

        async def operation():
            raise SandboxResourceError("No ports available", "port")

        with pytest.raises(SandboxResourceError):
            await policy.execute(operation)

    @pytest.mark.asyncio
    async def test_custom_error_classifier(self) -> None:
        """Should use custom error classifier."""
        policy = RetryPolicy(
            max_attempts=3,
            base_delay=0.1,
            should_retry=lambda e: isinstance(e, SandboxConnectionError),
        )

        async def operation():
            raise SandboxTimeoutError("Timeout")

        # Timeout errors are retryable by default but custom classifier says no
        with pytest.raises(SandboxTimeoutError):
            await policy.execute(operation)

    @pytest.mark.asyncio
    async def test_on_retry_callback(self) -> None:
        """Should call on_retry callback between attempts."""
        policy = RetryPolicy(max_attempts=3, base_delay=0.1)
        attempts = []

        def on_retry(error, attempt, delay):
            attempts.append((attempt, delay))

        async def operation():
            if len(attempts) < 2:
                raise SandboxConnectionError("Temporary failure")
            return "success"

        result = await policy.execute(operation, on_retry=on_retry)
        assert result == "success"
        assert len(attempts) == 2
        assert attempts[0][0] == 1  # First retry
        assert attempts[1][0] == 2  # Second retry


class TestIsRetryableError:
    """Tests for is_retryable_error utility."""

    def test_connection_error_is_retryable(self) -> None:
        """Should return True for connection errors."""
        error = SandboxConnectionError("Connection failed")
        assert is_retryable_error(error) is True

    def test_resource_error_is_not_retryable(self) -> None:
        """Should return False for resource errors."""
        error = SandboxResourceError("No ports", "port")
        assert is_retryable_error(error) is False

    def test_timeout_error_is_retryable(self) -> None:
        """Should return True for timeout errors."""
        error = SandboxTimeoutError("Timeout")
        assert is_retryable_error(error) is True

    def test_validation_error_is_not_retryable(self) -> None:
        """Should return False for validation errors."""
        error = SandboxValidationError("Invalid config")
        assert is_retryable_error(error) is False

    def test_generic_exception_is_not_retryable(self) -> None:
        """Should return False for generic exceptions."""
        assert is_retryable_error(ValueError("Some error")) is False
        assert is_retryable_error(RuntimeError("Error")) is False


class TestMaxRetriesExceeded:
    """Tests for max_retries_exceeded utility."""

    def test_create_error_from_policy(self) -> None:
        """Should create error from policy context."""
        policy = RetryPolicy(max_attempts=3)
        error = max_retries_exceeded(policy, "test_operation")

        assert isinstance(error, SandboxConnectionError)
        assert "failed after" in str(error).lower()
        assert error.operation == "test_operation"


class TestRetryableError:
    """Tests for RetryableError decorator."""

    @pytest.mark.asyncio
    async def test_decorator_marks_function_as_retryable(self) -> None:
        """Should mark function as retryable."""
        @RetryableError(max_attempts=2, base_delay=0.1)
        async def failing_operation():
            if not getattr(failing_operation, "called", False):
                failing_operation.called = True
                raise SandboxConnectionError("First failure")
            return "success"

        result = await failing_operation()
        assert result == "success"

    @pytest.mark.asyncio
    async def test_decorator_with_custom_classifier(self) -> None:
        """Should use custom error classifier."""
        called = False

        def custom_classifier(error):
            return called  # Only retry after first call

        @RetryableError(max_attempts=3, should_retry=custom_classifier, base_delay=0.1)
        async def operation():
            nonlocal called
            called = True
            raise SandboxConnectionError("Failure")

        with pytest.raises(SandboxConnectionError):
            await operation()
