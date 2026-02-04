"""
Circuit Breaker implementation for LLM providers.

Provides automatic failure detection and recovery for LLM provider calls.
When a provider fails repeatedly, the circuit "opens" to prevent further
calls and allow the provider to recover.

States:
- CLOSED: Normal operation, requests pass through
- OPEN: Provider failing, requests rejected immediately
- HALF_OPEN: Testing if provider recovered

Example:
    breaker = CircuitBreaker("openai", CircuitBreakerConfig())

    if breaker.can_execute():
        try:
            result = await llm_client.generate(...)
            breaker.record_success()
        except Exception:
            breaker.record_failure()
            raise
    else:
        # Circuit is open, use fallback provider
        pass
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Callable, Optional

logger = logging.getLogger(__name__)


class CircuitState(str, Enum):
    """Circuit breaker states."""

    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Failing, rejecting requests
    HALF_OPEN = "half_open"  # Testing recovery


@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker behavior."""

    # Number of consecutive failures before opening circuit
    failure_threshold: int = 5

    # Number of consecutive successes needed to close circuit from half-open
    success_threshold: int = 2

    # How long to wait before testing recovery (half-open state)
    recovery_timeout: timedelta = timedelta(seconds=60)

    # Maximum number of test requests allowed in half-open state
    half_open_max_requests: int = 3

    # Optional callback when state changes
    on_state_change: Optional[Callable[[str, CircuitState, CircuitState], None]] = None


@dataclass
class CircuitBreakerStats:
    """Statistics for circuit breaker monitoring."""

    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    rejected_requests: int = 0
    state_changes: int = 0
    last_failure_time: Optional[datetime] = None
    last_success_time: Optional[datetime] = None
    last_state_change: Optional[datetime] = None


class CircuitBreaker:
    """
    Circuit breaker for LLM provider fault tolerance.

    Implements the circuit breaker pattern to prevent cascading failures
    and allow providers time to recover from transient issues.
    """

    def __init__(
        self,
        provider_id: str,
        config: Optional[CircuitBreakerConfig] = None,
    ):
        """
        Initialize circuit breaker for a provider.

        Args:
            provider_id: Unique identifier for the provider
            config: Circuit breaker configuration
        """
        self.provider_id = provider_id
        self.config = config or CircuitBreakerConfig()

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._half_open_requests = 0
        self._last_failure_time: Optional[datetime] = None
        self._last_state_change = datetime.utcnow()
        self._stats = CircuitBreakerStats()
        self._lock = asyncio.Lock()

    @property
    def state(self) -> CircuitState:
        """Get current circuit state."""
        return self._state

    @property
    def stats(self) -> CircuitBreakerStats:
        """Get circuit breaker statistics."""
        return self._stats

    def can_execute(self) -> bool:
        """
        Check if a request can be executed.

        Returns:
            True if request should proceed, False if circuit is open
        """
        self._check_state_transition()

        if self._state == CircuitState.CLOSED:
            return True

        if self._state == CircuitState.HALF_OPEN:
            # Allow limited requests in half-open state
            if self._half_open_requests < self.config.half_open_max_requests:
                return True
            self._stats.rejected_requests += 1
            return False

        # Circuit is OPEN
        self._stats.rejected_requests += 1
        return False

    async def can_execute_async(self) -> bool:
        """Thread-safe version of can_execute."""
        async with self._lock:
            return self.can_execute()

    def record_success(self) -> None:
        """Record a successful request."""
        self._stats.total_requests += 1
        self._stats.successful_requests += 1
        self._stats.last_success_time = datetime.utcnow()

        if self._state == CircuitState.HALF_OPEN:
            self._success_count += 1
            if self._success_count >= self.config.success_threshold:
                self._transition_to(CircuitState.CLOSED)
        elif self._state == CircuitState.CLOSED:
            # Reset failure count on success
            self._failure_count = 0

    async def record_success_async(self) -> None:
        """Thread-safe version of record_success."""
        async with self._lock:
            self.record_success()

    def record_failure(self, error: Optional[Exception] = None) -> None:
        """
        Record a failed request.

        Args:
            error: Optional exception that caused the failure
        """
        self._stats.total_requests += 1
        self._stats.failed_requests += 1
        self._stats.last_failure_time = datetime.utcnow()
        self._last_failure_time = datetime.utcnow()

        if self._state == CircuitState.HALF_OPEN:
            # Any failure in half-open immediately opens circuit
            self._transition_to(CircuitState.OPEN)
        elif self._state == CircuitState.CLOSED:
            self._failure_count += 1
            if self._failure_count >= self.config.failure_threshold:
                self._transition_to(CircuitState.OPEN)
                logger.warning(
                    f"Circuit breaker OPENED for provider '{self.provider_id}' "
                    f"after {self._failure_count} consecutive failures"
                )

    async def record_failure_async(self, error: Optional[Exception] = None) -> None:
        """Thread-safe version of record_failure."""
        async with self._lock:
            self.record_failure(error)

    def reset(self) -> None:
        """Manually reset the circuit breaker to closed state."""
        self._transition_to(CircuitState.CLOSED)
        self._failure_count = 0
        self._success_count = 0
        self._half_open_requests = 0
        logger.info(f"Circuit breaker manually reset for provider '{self.provider_id}'")

    async def reset_async(self) -> None:
        """Thread-safe version of reset."""
        async with self._lock:
            self.reset()

    def _check_state_transition(self) -> None:
        """Check if state should transition based on timeouts."""
        if self._state == CircuitState.OPEN:
            if self._last_failure_time:
                time_since_failure = datetime.utcnow() - self._last_failure_time
                if time_since_failure >= self.config.recovery_timeout:
                    self._transition_to(CircuitState.HALF_OPEN)
                    logger.info(
                        f"Circuit breaker HALF-OPEN for provider '{self.provider_id}' "
                        f"(testing recovery after {time_since_failure.total_seconds():.1f}s)"
                    )

    def _transition_to(self, new_state: CircuitState) -> None:
        """Transition to a new state."""
        old_state = self._state
        if old_state == new_state:
            return

        self._state = new_state
        self._last_state_change = datetime.utcnow()
        self._stats.state_changes += 1
        self._stats.last_state_change = self._last_state_change

        # Reset counters on state change
        if new_state == CircuitState.CLOSED:
            self._failure_count = 0
            self._success_count = 0
            self._half_open_requests = 0
        elif new_state == CircuitState.HALF_OPEN:
            self._success_count = 0
            self._half_open_requests = 0
        elif new_state == CircuitState.OPEN:
            self._success_count = 0

        # Notify callback if configured
        if self.config.on_state_change:
            try:
                self.config.on_state_change(self.provider_id, old_state, new_state)
            except Exception as e:
                logger.error(f"Error in circuit breaker state change callback: {e}")

        logger.debug(
            f"Circuit breaker state changed for '{self.provider_id}': "
            f"{old_state.value} -> {new_state.value}"
        )

    def get_status(self) -> dict:
        """Get current circuit breaker status as dict."""
        return {
            "provider_id": self.provider_id,
            "state": self._state.value,
            "failure_count": self._failure_count,
            "success_count": self._success_count,
            "last_failure_time": (
                self._last_failure_time.isoformat() if self._last_failure_time else None
            ),
            "last_state_change": (
                self._last_state_change.isoformat() if self._last_state_change else None
            ),
            "stats": {
                "total_requests": self._stats.total_requests,
                "successful_requests": self._stats.successful_requests,
                "failed_requests": self._stats.failed_requests,
                "rejected_requests": self._stats.rejected_requests,
                "state_changes": self._stats.state_changes,
            },
        }


class CircuitBreakerRegistry:
    """
    Registry for managing circuit breakers across providers.

    Provides a centralized way to get/create circuit breakers for providers.
    """

    def __init__(self, default_config: Optional[CircuitBreakerConfig] = None):
        """
        Initialize the registry.

        Args:
            default_config: Default configuration for new circuit breakers
        """
        self._breakers: dict[str, CircuitBreaker] = {}
        self._default_config = default_config or CircuitBreakerConfig()
        self._lock = asyncio.Lock()

    def get(
        self,
        provider_type,
        config: Optional[CircuitBreakerConfig] = None,
    ) -> CircuitBreaker:
        """
        Get or create a circuit breaker for a provider type.

        Args:
            provider_type: Provider type (ProviderType enum or string)
            config: Optional custom configuration

        Returns:
            CircuitBreaker instance for the provider
        """
        # Handle both ProviderType enum and string
        if hasattr(provider_type, "value"):
            provider_id = provider_type.value
        else:
            provider_id = str(provider_type)
        return self.get_breaker(provider_id, config)

    def get_breaker(
        self,
        provider_id: str,
        config: Optional[CircuitBreakerConfig] = None,
    ) -> CircuitBreaker:
        """
        Get or create a circuit breaker for a provider.

        Args:
            provider_id: Provider identifier (string)
            config: Optional custom configuration

        Returns:
            CircuitBreaker instance for the provider
        """
        if provider_id not in self._breakers:
            self._breakers[provider_id] = CircuitBreaker(
                provider_id=provider_id,
                config=config or self._default_config,
            )
        return self._breakers[provider_id]

    async def get_breaker_async(
        self,
        provider_id: str,
        config: Optional[CircuitBreakerConfig] = None,
    ) -> CircuitBreaker:
        """Thread-safe version of get_breaker."""
        async with self._lock:
            return self.get_breaker(provider_id, config)

    def get_all_statuses(self) -> dict[str, dict]:
        """Get status of all circuit breakers."""
        return {pid: breaker.get_status() for pid, breaker in self._breakers.items()}

    def reset_all(self) -> None:
        """Reset all circuit breakers."""
        for breaker in self._breakers.values():
            breaker.reset()


# Global registry instance
_circuit_breaker_registry: Optional[CircuitBreakerRegistry] = None


def get_circuit_breaker_registry() -> CircuitBreakerRegistry:
    """Get the global circuit breaker registry."""
    global _circuit_breaker_registry
    if _circuit_breaker_registry is None:
        _circuit_breaker_registry = CircuitBreakerRegistry()
    return _circuit_breaker_registry
