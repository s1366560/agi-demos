"""
Circuit Breaker pattern implementation.

Prevents cascading failures by:
- Opening circuit after N failures
- Enting half-open state to test recovery
- Closing circuit after successful recovery
"""

import asyncio
import logging
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class CircuitState(str, Enum):
    """Circuit breaker states."""

    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Circuit is open, blocking calls
    HALF_OPEN = "half_open"  # Testing if service has recovered


@dataclass(frozen=True)
class CircuitBreakerConfig:
    """
    Configuration for circuit breaker.

    Attributes:
        failure_threshold: Number of failures before opening circuit
        success_threshold: Number of successes needed to close from half-open
        timeout: Time to wait before transitioning from OPEN to HALF_OPEN
        half_open_max_calls: Max calls allowed in HALF_OPEN state
        exceptions: Tuple of exception types to track (None = all)
    """

    failure_threshold: int = 5
    success_threshold: int = 2
    timeout: timedelta = timedelta(seconds=60)
    half_open_max_calls: int = 3
    exceptions: tuple[type[Exception], ...] | None = None


class CircuitBreakerOpenError(Exception):
    """
    Raised when circuit breaker is open.

    Attributes:
        breaker_name: Name of the circuit breaker
        opened_at: When the circuit was opened
        timeout: Timeout duration for the circuit
    """

    def __init__(
        self,
        breaker_name: str = "unknown",
        opened_at: datetime | None = None,
        timeout: timedelta | None = None,
    ) -> None:
        self.breaker_name = breaker_name
        self.opened_at = opened_at or datetime.now(UTC)
        self.timeout = timeout or timedelta(seconds=60)
        super().__init__(
            f"Circuit breaker '{breaker_name}' is open. "
            f"Opened at {self.opened_at.isoformat()}. "
            f"Try again after {self.retry_after()} seconds."
        )

    def retry_after(self) -> float:
        """Calculate seconds until retry should be attempted."""
        elapsed = datetime.now(UTC) - self.opened_at
        remaining = self.timeout.total_seconds() - elapsed.total_seconds()
        return max(0, remaining)


@dataclass
class CircuitBreakerState:
    """
    Current state of the circuit breaker.

    Attributes:
        state: Current circuit state (CLOSED, OPEN, HALF_OPEN)
        failure_count: Number of failures in current window
        success_count: Number of successes in current window
        opened_at: When the circuit was last opened
        last_failure_time: When the last failure occurred
        half_open_call_count: Number of calls made in HALF_OPEN state
    """

    state: CircuitState = CircuitState.CLOSED
    failure_count: int = 0
    success_count: int = 0
    opened_at: datetime | None = None
    last_failure_time: datetime | None = None
    half_open_call_count: int = 0


@dataclass
class CircuitBreakerStats:
    """
    Statistics for circuit breaker.

    Attributes:
        total_calls: Total number of calls
        successful_calls: Number of successful calls
        failed_calls: Number of failed calls
        rejected_calls: Number of calls rejected (circuit open)
        open_count: Number of times circuit was opened
    """

    total_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    rejected_calls: int = 0
    open_count: int = 0


class CircuitBreaker:
    """
    Circuit Breaker implementation.

    Prevents cascading failures by opening the circuit when
    failures exceed a threshold. Automatically closes after
    successful recovery attempts.

    Example:
        breaker = CircuitBreaker(name="database", config=config)

        try:
            result = await breaker.call(risky_function)
        except CircuitBreakerOpenError:
            # Circuit is open, use fallback
            result = await fallback_function()

    Thread Safety:
        This class uses asyncio locks for thread safety in async contexts.
    """

    def __init__(
        self,
        name: str,
        config: CircuitBreakerConfig | None = None,
    ) -> None:
        """
        Initialize circuit breaker.

        Args:
            name: Name of the circuit breaker (for logging/debugging)
            config: Circuit breaker configuration
        """
        self._name = name
        self._config = config or CircuitBreakerConfig()
        self._state = CircuitBreakerState()
        self._stats = CircuitBreakerStats()
        self._lock = asyncio.Lock()

    @property
    def name(self) -> str:
        """Get circuit breaker name."""
        return self._name

    @property
    def state(self) -> CircuitState:
        """Get current circuit state."""
        return self._state.state

    @property
    def failure_count(self) -> int:
        """Get current failure count."""
        return self._state.failure_count

    @property
    def success_count(self) -> int:
        """Get current success count."""
        return self._state.success_count

    @property
    def half_open_call_count(self) -> int:
        """Get half-open call count."""
        return self._state.half_open_call_count

    async def call(
        self,
        func: Callable[[], Coroutine[Any, Any, T]],
        fallback: Callable[[], Coroutine[Any, Any, T]] | None = None,
        fallback_on_exception: type[Exception] | None = None,
    ) -> T:
        """
        Execute function with circuit breaker protection.

        Args:
            func: Async function to execute
            fallback: Fallback function if circuit is open
            fallback_on_exception: Use fallback for specific exception type

        Returns:
            Result from function or fallback

        Raises:
            CircuitBreakerOpenError: If circuit is open and no fallback
            Exception: If function raises an exception
        """
        async with self._lock:
            # Check if circuit is open and should transition to half-open
            if self._state.state == CircuitState.OPEN:
                if self._should_attempt_reset():
                    self._transition_to_half_open()
                else:
                    self._stats.rejected_calls += 1
                    if fallback:
                        return await fallback()
                    raise CircuitBreakerOpenError(
                        breaker_name=self._name,
                        opened_at=self._state.opened_at,
                        timeout=self._config.timeout,
                    )

            # Check if half-open and max calls reached
            if self._state.state == CircuitState.HALF_OPEN:
                if self._state.half_open_call_count >= self._config.half_open_max_calls:
                    self._stats.rejected_calls += 1
                    if fallback:
                        return await fallback()
                    raise CircuitBreakerOpenError(
                        breaker_name=self._name,
                        opened_at=self._state.opened_at,
                        timeout=self._config.timeout,
                    )

        # Execute the function
        try:
            self._stats.total_calls += 1
            result = await func()
            await self._on_success()
            return result

        except Exception as e:
            # Check if we should use fallback for this exception
            if fallback_on_exception and isinstance(e, fallback_on_exception):
                if fallback:
                    return await fallback(e)

            await self._on_failure(e)
            raise

    async def _on_success(self) -> None:
        """Handle successful function execution."""
        async with self._lock:
            self._stats.successful_calls += 1

            if self._state.state == CircuitState.HALF_OPEN:
                self._state.success_count += 1
                self._state.half_open_call_count += 1

                # Close circuit if success threshold reached
                if self._state.success_count >= self._config.success_threshold:
                    self._transition_to_closed()

            elif self._state.state == CircuitState.CLOSED:
                # Reset failure count on success in closed state
                self._state.failure_count = 0
                self._state.success_count += 1

    async def _on_failure(self, error: Exception) -> None:
        """Handle failed function execution."""
        async with self._lock:
            self._stats.failed_calls += 1
            self._state.last_failure_time = datetime.now(UTC)

            # Check if error should be tracked
            if self._config.exceptions and not isinstance(error, self._config.exceptions):
                # Not tracking this exception type
                return

            if self._state.state == CircuitState.HALF_OPEN:
                # Failure in half-open reopens the circuit
                self._transition_to_open()

            elif self._state.state == CircuitState.CLOSED:
                self._state.failure_count += 1

                # Open circuit if threshold exceeded
                if self._state.failure_count >= self._config.failure_threshold:
                    self._transition_to_open()

    def _should_attempt_reset(self) -> bool:
        """Check if enough time has passed to attempt reset."""
        if self._state.opened_at is None:
            return True

        elapsed = datetime.now(UTC) - self._state.opened_at
        return elapsed >= self._config.timeout

    def _transition_to_open(self) -> None:
        """Transition circuit to OPEN state."""
        self._state.state = CircuitState.OPEN
        self._state.opened_at = datetime.now(UTC)
        self._state.half_open_call_count = 0
        self._stats.open_count += 1
        logger.warning(
            f"Circuit breaker '{self._name}' opened after {self._state.failure_count} failures"
        )

    def _transition_to_half_open(self) -> None:
        """Transition circuit to HALF_OPEN state."""
        self._state.state = CircuitState.HALF_OPEN
        self._state.failure_count = 1  # Reset to 1 for tracking half-open failures
        self._state.success_count = 0
        self._state.half_open_call_count = 0
        logger.info(f"Circuit breaker '{self._name}' transitioned to HALF_OPEN")

    def _transition_to_half_open(self) -> None:
        """Transition circuit to HALF_OPEN state."""
        self._state.state = CircuitState.HALF_OPEN
        self._state.failure_count = 0
        self._state.success_count = 0
        self._state.half_open_call_count = 0
        logger.info(f"Circuit breaker '{self._name}' transitioned to HALF_OPEN")

    def _transition_to_closed(self) -> None:
        """Transition circuit to CLOSED state."""
        self._state.state = CircuitState.CLOSED
        self._state.failure_count = 0
        self._state.success_count = 0
        self._state.half_open_call_count = 0
        self._state.opened_at = None
        logger.info(f"Circuit breaker '{self._name}' closed after successful recovery")

    def reset(self) -> None:
        """Reset circuit breaker to initial CLOSED state."""
        self._state = CircuitBreakerState()
        logger.info(f"Circuit breaker '{self._name}' reset to CLOSED state")

    def get_state(self) -> dict[str, Any]:
        """Get current circuit state as dictionary."""
        return {
            "name": self._name,
            "state": self._state.state.value,
            "failure_count": self._state.failure_count,
            "success_count": self._state.success_count,
            "half_open_call_count": self._state.half_open_call_count,
            "opened_at": self._state.opened_at.isoformat() if self._state.opened_at else None,
            "last_failure_time": (
                self._state.last_failure_time.isoformat() if self._state.last_failure_time else None
            ),
        }

    def get_statistics(self) -> dict[str, Any]:
        """Get circuit breaker statistics."""
        return {
            "name": self._name,
            "total_calls": self._stats.total_calls,
            "successful_calls": self._stats.successful_calls,
            "failed_calls": self._stats.failed_calls,
            "rejected_calls": self._stats.rejected_calls,
            "open_count": self._stats.open_count,
            "success_rate": (
                self._stats.successful_calls / self._stats.total_calls
                if self._stats.total_calls > 0
                else 0
            ),
        }

    async def __aenter__(self) -> "CircuitBreaker":
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        if exc_type is not None:
            await self._on_failure(exc_val)
        else:
            await self._on_success()


class CircuitBreakerRegistry:
    """
    Registry for managing multiple circuit breakers.

    Provides centralized access to circuit breakers by name.
    """

    def __init__(self) -> None:
        self._breakers: dict[str, CircuitBreaker] = {}
        self._lock = asyncio.Lock()

    async def get_or_create(
        self,
        name: str,
        config: CircuitBreakerConfig | None = None,
    ) -> CircuitBreaker:
        """
        Get existing circuit breaker or create new one.

        Args:
            name: Circuit breaker name
            config: Configuration for new breaker

        Returns:
            CircuitBreaker instance
        """
        async with self._lock:
            if name not in self._breakers:
                self._breakers[name] = CircuitBreaker(name, config)
            return self._breakers[name]

    async def get(self, name: str) -> CircuitBreaker | None:
        """
        Get circuit breaker by name.

        Args:
            name: Circuit breaker name

        Returns:
            CircuitBreaker instance or None
        """
        async with self._lock:
            return self._breakers.get(name)

    async def reset_all(self) -> None:
        """Reset all circuit breakers."""
        async with self._lock:
            for breaker in self._breakers.values():
                breaker.reset()

    async def get_all_states(self) -> dict[str, dict[str, Any]]:
        """Get state of all circuit breakers."""
        async with self._lock:
            return {name: breaker.get_state() for name, breaker in self._breakers.items()}


# Global circuit breaker registry
_global_registry = CircuitBreakerRegistry()


async def get_circuit_breaker(
    name: str,
    config: CircuitBreakerConfig | None = None,
) -> CircuitBreaker:
    """Get or create circuit breaker from global registry."""
    return await _global_registry.get_or_create(name, config)
