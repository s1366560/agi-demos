"""Retry Policy with exponential backoff for sandbox operations.

This module provides retry logic with configurable backoff strategies
for transient sandbox operations.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from src.domain.model.sandbox.exceptions import (
    SandboxConnectionError,
    is_retryable_error as sandbox_is_retryable,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")


class RetryPolicy:
    """
    Retry policy with exponential backoff for sandbox operations.

    Provides configurable retry logic for transient failures in sandbox
    operations, with exponential backoff to avoid overwhelming
    the system.

    Attributes:
        max_attempts: Maximum number of attempts (including first)
        base_delay: Initial delay in seconds before first retry
        max_delay: Maximum delay between retries
        backoff_factor: Multiplier for delay after each attempt
    """

    def __init__(
        self,
        max_attempts: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 30.0,
        backoff_factor: float = 2.0,
        should_retry: Callable[[Exception], bool] | None = None,
    ) -> None:
        """Initialize the retry policy.

        Args:
            max_attempts: Maximum number of attempts (1-10)
            base_delay: Initial delay in seconds (0.1-60)
            max_delay: Maximum delay in seconds (1-300)
            backoff_factor: Multiplier for exponential backoff (1.1-10)
            should_retry: Optional custom retry predicate

        Raises:
            ValueError: If parameters are out of valid range
        """
        # Validate max_attempts
        if not 1 <= max_attempts <= 10:
            raise ValueError(f"max_attempts must be between 1 and 10, got {max_attempts}")

        # Validate base_delay
        if not 0.1 <= base_delay <= 60:
            raise ValueError(f"base_delay must be between 0.1 and 60, got {base_delay}")

        # Validate max_delay
        if not 1.0 <= max_delay <= 300:
            raise ValueError(f"max_delay must be between 1 and 300, got {max_delay}")

        # Validate backoff_factor
        if not 1.1 <= backoff_factor <= 10:
            raise ValueError(f"backoff_factor must be between 1.1 and 10, got {backoff_factor}")

        self.max_attempts = max_attempts
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.backoff_factor = backoff_factor
        self._should_retry = should_retry or sandbox_is_retryable

    def _calculate_delay(self, attempt: int) -> float:
        """Calculate delay for a given retry attempt.

        Args:
            attempt: The attempt number (0-indexed, so 1 = first retry)

        Returns:
            Delay in seconds, capped at max_delay
        """
        if attempt == 0:
            return self.base_delay

        delay = self.base_delay * (self.backoff_factor**attempt)
        return min(delay, self.max_delay)

    async def execute(
        self,
        operation: Callable[[], Awaitable[T]],
        on_retry: Callable[[Exception, int, float], None] | None = None,
    ) -> T:
        """
        Execute an operation with retry logic.

        Args:
            operation: A callable that returns the async operation to execute
            on_retry: Optional callback called after each failed attempt
                Receives (error, attempt_number, delay_seconds)

        Returns:
            The result of the operation

        Raises:
            Exception: The last exception if all attempts fail
        """
        last_exception: Exception | None = None

        for attempt in range(self.max_attempts):
            try:
                return await operation()
            except Exception as error:
                last_exception = error

                # Check if we should retry
                is_last_attempt = attempt >= self.max_attempts - 1
                should_retry = not is_last_attempt and self._should_retry(error)

                if not should_retry:
                    logger.debug(f"Operation failed with non-retryable error: {error}")
                    raise

                if on_retry:
                    delay = self._calculate_delay(attempt)
                    try:
                        on_retry(error, attempt + 1, delay)
                    except Exception as callback_error:
                        logger.warning(f"on_retry callback failed: {callback_error}")

                if not is_last_attempt:
                    delay = self._calculate_delay(attempt)
                    logger.info(
                        f"Operation failed (attempt {attempt + 1}/{self.max_attempts}), "
                        f"retrying in {delay:.1f}s: {error}"
                    )
                    await asyncio.sleep(delay)

        # All attempts failed
        assert last_exception is not None
        raise last_exception


def is_retryable_error(error: Exception) -> bool:
    """Check if an error is retryable for sandbox operations.

    This is the default retry predicate used by RetryPolicy.
    Connection errors and timeouts are retryable.
    Resource exhaustion and validation errors are not.

    Args:
        error: The exception to check

    Returns:
        True if the error should be retried, False otherwise
    """
    return sandbox_is_retryable(error)


def max_retries_exceeded(
    policy: RetryPolicy,
    operation_name: str,
) -> SandboxConnectionError:
    """Create a retry exceeded error from policy context.

    Args:
        policy: The retry policy that was exhausted
        operation_name: Name of the operation that failed

    Returns:
        A SandboxConnectionError with retry information
    """
    return SandboxConnectionError(
        message=(f"Operation '{operation_name}' failed after {policy.max_attempts} attempts"),
        retryable=False,  # Don't retry a retry policy failure
        operation=operation_name,
    )


def RetryableError(
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    backoff_factor: float = 2.0,
    should_retry: Callable[[Exception], bool] | None = None,
) -> Callable[..., Any]:
    """
    Decorator to add retry logic to async functions.

    Usage:
        @RetryableError(max_attempts=3)
        async def connect_to_sandbox(sandbox_id: str) -> bool:
            # Connection logic that might fail
            return await sandbox.connect()

    Args:
        max_attempts: Maximum retry attempts
        base_delay: Initial delay before first retry
        max_delay: Maximum delay between retries
        backoff_factor: Exponential backoff multiplier
        should_retry: Optional custom retry predicate

    Returns:
        Decorator function
    """

    def decorator(func: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        policy = RetryPolicy(
            max_attempts=max_attempts,
            base_delay=base_delay,
            max_delay=max_delay,
            backoff_factor=backoff_factor,
            should_retry=should_retry,
        )

        async def wrapper(*args: Any, **kwargs: Any) -> T:
            async def bound_operation() -> None:
                return await func(*args, **kwargs)

            return await policy.execute(bound_operation)

        return wrapper

    return decorator
