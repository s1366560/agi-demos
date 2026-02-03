"""
Connection Retry Logic with exponential backoff.

Provides:
- Exponential backoff for retries
- Transient error detection
- Max retry configuration
- Jitter for thundering herd prevention
"""

import asyncio
import functools
import logging
import random
from typing import Any, Callable, Coroutine, Optional, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class TransientError(Exception):
    """
    Base exception for transient errors.

    Transient errors are temporary failures that may succeed
    if retried after a delay.
    """

    def __init__(self, message: str, code: Optional[int] = None, retry_after: Optional[int] = None):
        super().__init__(message)
        self.code = code
        self.retry_after = retry_after


class MaxRetriesExceededError(Exception):
    """
    Raised when max retries are exhausted.

    Attributes:
        message: Error message
        last_error: The last error that occurred
        attempts: Total number of attempts made
    """

    def __init__(
        self,
        message: str = "Max retries exceeded",
        last_error: Optional[Exception] = None,
        attempts: int = 0,
    ):
        super().__init__(message)
        self.last_error = last_error
        self.attempts = attempts
        if last_error:
            self.__cause__ = last_error


def is_transient_error(error: Exception) -> bool:
    """
    Determine if an error is transient (should be retried).

    Transient errors include:
    - ConnectionError: Network connection issues
    - TimeoutError: Operation timeouts
    - OSError with EINTR: Interrupted system calls
    - ConnectionResetError / ConnectionRefusedError: Connection issues
    - RuntimeError with connection-related messages
    - TransientError: Custom transient errors

    Args:
        error: The exception to check

    Returns:
        True if error is transient, False otherwise
    """
    # Built-in transient error types
    if isinstance(error, TransientError):
        return True

    if isinstance(error, (ConnectionError, TimeoutError)):
        return True

    if isinstance(error, (ConnectionResetError, ConnectionRefusedError)):
        return True

    if isinstance(error, OSError):
        # EINTR (4) - Interrupted system call
        # ECONNRESET (104) - Connection reset
        # ECONNREFUSED (111) - Connection refused
        if error.errno in {4, 104, 111}:
            return True

    if isinstance(error, RuntimeError):
        error_msg = str(error).lower()
        transient_keywords = [
            "connection",
            "timeout",
            "pool",
            "deadlock",
            "temporary",
            "unavailable",
            "overloaded",
        ]
        if any(keyword in error_msg for keyword in transient_keywords):
            return True

    if isinstance(error, ValueError):
        # Deadlock-related errors
        error_msg = str(error).lower()
        if "deadlock" in error_msg or "lock" in error_msg:
            return True

    # Non-transient errors
    if isinstance(error, (NotImplementedError, AttributeError, ImportError)):
        return False

    # Default to non-transient for unknown error types
    return False


def _calculate_delay(
    attempt: int,
    base_delay: float,
    max_delay: float,
    jitter: bool = True,
) -> float:
    """
    Calculate delay for retry attempt with exponential backoff.

    Formula: min(base_delay * 2^attempt, max_delay)

    Args:
        attempt: Retry attempt number (0-indexed)
        base_delay: Base delay in seconds
        max_delay: Maximum delay in seconds
        jitter: Whether to add random jitter

    Returns:
        Delay in seconds
    """
    # Exponential backoff: base_delay * 2^attempt
    delay = base_delay * (2**attempt)

    # Cap at max_delay
    delay = min(delay, max_delay)

    # Add jitter to prevent thundering herd
    # Jitter is +/- 25% of the delay
    if jitter:
        jitter_amount = delay * 0.25
        delay += random.uniform(-jitter_amount, jitter_amount)

    # Ensure non-negative
    return max(0, delay)


async def retry_with_backoff(
    func: Callable[[], Coroutine[Any, Any, T]],
    max_retries: int = 3,
    base_delay: float = 0.1,
    max_delay: float = 60.0,
    is_transient_fn: Optional[Callable[[Exception], bool]] = None,
    on_retry: Optional[Callable[[Exception, int, float], Any]] = None,
    jitter: bool = True,
) -> T:
    """
    Execute async function with exponential backoff retry.

    Args:
        func: Async function to execute
        max_retries: Maximum number of retry attempts
        base_delay: Base delay between retries in seconds
        max_delay: Maximum delay between retries in seconds
        is_transient_fn: Custom function to determine if error is transient
        on_retry: Callback called before each retry (error, attempt, delay)
        jitter: Whether to add random jitter to delays

    Returns:
        Result from successful function execution

    Raises:
        MaxRetriesExceededError: If all retries are exhausted
        Exception: If a non-transient error occurs
    """
    if is_transient_fn is None:
        is_transient_fn = is_transient_error

    last_error: Optional[Exception] = None

    for attempt in range(max_retries + 1):
        try:
            return await func()

        except Exception as e:
            last_error = e

            # Check if error is transient
            if not is_transient_fn(e):
                # Non-transient error - fail immediately
                raise

            # Check if we have retries left
            if attempt >= max_retries:
                # Max retries exhausted
                raise MaxRetriesExceededError(
                    message=f"Max retries ({max_retries}) exceeded",
                    last_error=e,
                    attempts=attempt + 1,
                )

            # Calculate delay for next retry
            delay = _calculate_delay(attempt, base_delay, max_delay, jitter)

            logger.debug(f"Retry {attempt + 1}/{max_retries} after {delay:.2f}s due to error: {e}")

            # Call on_retry callback if provided
            if on_retry:
                try:
                    await on_retry(e, attempt + 1, delay)
                except Exception as callback_error:
                    logger.warning(f"on_retry callback failed: {callback_error}")

            # Wait before retry
            await asyncio.sleep(delay)

    # Should never reach here, but for type safety
    raise MaxRetriesExceededError(
        message="Max retries exceeded",
        last_error=last_error,
        attempts=max_retries + 1,
    )


def retry_decorator(
    max_retries: int = 3,
    base_delay: float = 0.1,
    max_delay: float = 60.0,
    is_transient_fn: Optional[Callable[[Exception], bool]] = None,
    jitter: bool = True,
):
    """
    Decorator to add retry logic to async functions.

    Args:
        max_retries: Maximum number of retry attempts
        base_delay: Base delay between retries in seconds
        max_delay: Maximum delay between retries in seconds
        is_transient_fn: Custom function to determine if error is transient
        jitter: Whether to add random jitter to delays

    Returns:
        Decorator function

    Example:
        @retry_decorator(max_retries=3, base_delay=0.1)
        async def my_function():
            return await risky_operation()
    """

    def decorator(
        func: Callable[..., Coroutine[Any, Any, T]],
    ) -> Callable[..., Coroutine[Any, Any, T]]:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> T:
            async def bound_func() -> T:
                return await func(*args, **kwargs)

            return await retry_with_backoff(
                bound_func,
                max_retries=max_retries,
                base_delay=base_delay,
                max_delay=max_delay,
                is_transient_fn=is_transient_fn,
                jitter=jitter,
            )

        return wrapper

    return decorator


class RetryTracker:
    """
    Track retry statistics for monitoring and debugging.

    Attributes:
        total_attempts: Total number of attempts
        successful_retries: Number of successful retries
        failed_retries: Number of failed retries
        last_error: Most recent error
    """

    def __init__(self) -> None:
        self.total_attempts: int = 0
        self.successful_retries: int = 0
        self.failed_retries: int = 0
        self.last_error: Optional[Exception] = None

    def record_attempt(self) -> None:
        """Record a retry attempt."""
        self.total_attempts += 1

    def record_success(self) -> None:
        """Record a successful retry."""
        self.successful_retries += 1

    def record_failure(self, error: Exception) -> None:
        """Record a failed retry."""
        self.failed_retries += 1
        self.last_error = error

    def reset(self) -> None:
        """Reset all statistics."""
        self.total_attempts = 0
        self.successful_retries = 0
        self.failed_retries = 0
        self.last_error = None

    def to_dict(self) -> dict[str, Any]:
        """Convert statistics to dictionary."""
        return {
            "total_attempts": self.total_attempts,
            "successful_retries": self.successful_retries,
            "failed_retries": self.failed_retries,
            "last_error": str(self.last_error) if self.last_error else None,
        }


# Global retry tracker for monitoring
_global_tracker = RetryTracker()


def get_global_retry_tracker() -> RetryTracker:
    """Get the global retry tracker."""
    return _global_tracker


def reset_global_retry_tracker() -> None:
    """Reset the global retry tracker."""
    _global_tracker.reset()
