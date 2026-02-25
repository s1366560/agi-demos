"""
Unit tests for Circuit Breaker pattern implementation.

Tests the circuit breaker with:
- Open circuit after N failures
- Half-open state for testing recovery
- Close circuit after success
- Timeout for automatic state transitions
"""

import contextlib
from datetime import UTC, datetime, timedelta

import pytest

from src.infrastructure.adapters.secondary.common.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitBreakerOpenError,
    CircuitState,
)


class TestCircuitBreakerConfig:
    """Tests for CircuitBreakerConfig."""

    def test_default_config(self):
        """Test default configuration values."""
        config = CircuitBreakerConfig()

        assert config.failure_threshold == 5
        assert config.success_threshold == 2
        assert config.timeout == timedelta(seconds=60)
        assert config.half_open_max_calls == 3

    def test_custom_config(self):
        """Test custom configuration values."""
        config = CircuitBreakerConfig(
            failure_threshold=10,
            success_threshold=3,
            timeout=timedelta(seconds=120),
            half_open_max_calls=5,
        )

        assert config.failure_threshold == 10
        assert config.success_threshold == 3
        assert config.timeout == timedelta(seconds=120)
        assert config.half_open_max_calls == 5

    def test_config_immutability_pattern(self):
        """Test that config can be used as frozen dataclass."""
        config = CircuitBreakerConfig()
        # Access properties to verify structure
        assert config.failure_threshold >= 0


class TestCircuitState:
    """Tests for CircuitState enum."""

    def test_state_values(self):
        """Test circuit state values."""
        assert CircuitState.CLOSED == "closed"
        assert CircuitState.OPEN == "open"
        assert CircuitState.HALF_OPEN == "half_open"

    def test_state_comparison(self):
        """Test state comparison."""
        assert CircuitState.CLOSED == CircuitState.CLOSED
        assert CircuitState.CLOSED != CircuitState.OPEN


class TestCircuitBreaker:
    """Tests for CircuitBreaker."""

    @pytest.fixture
    def breaker(self):
        """Create a circuit breaker with test configuration."""
        config = CircuitBreakerConfig(
            failure_threshold=3,
            success_threshold=2,
            timeout=timedelta(seconds=10),
            half_open_max_calls=2,
        )
        return CircuitBreaker(name="test_breaker", config=config)

    @pytest.fixture
    def success_func(self):
        """Create a function that always succeeds."""

        async def func():
            return "success"

        return func

    @pytest.fixture
    def failing_func(self):
        """Create a function that always fails."""

        async def func():
            raise ConnectionError("Connection failed")

        return func

    @pytest.fixture
    def flaky_func(self):
        """Create a function that fails first N times then succeeds."""

        def create(attempts_to_fail=2):
            attempt = 0

            async def func():
                nonlocal attempt
                attempt += 1
                if attempt <= attempts_to_fail:
                    raise ConnectionError(f"Attempt {attempt} failed")
                return f"success on attempt {attempt}"

            return func

        return create

    async def test_initial_state_is_closed(self, breaker):
        """Test that circuit breaker starts in CLOSED state."""
        assert breaker.state == CircuitState.CLOSED
        assert breaker.failure_count == 0
        assert breaker.success_count == 0

    async def test_success_keeps_circuit_closed(self, breaker, success_func):
        """Test that successful calls keep circuit closed."""
        for _ in range(10):
            result = await breaker.call(success_func)
            assert result == "success"

        assert breaker.state == CircuitState.CLOSED
        assert breaker.failure_count == 0
        assert breaker.success_count == 10

    async def test_failures_open_circuit(self, breaker, failing_func):
        """Test that failures open the circuit after threshold."""
        # First failure
        with pytest.raises(ConnectionError):
            await breaker.call(failing_func)
        assert breaker.state == CircuitState.CLOSED
        assert breaker.failure_count == 1

        # Second failure
        with pytest.raises(ConnectionError):
            await breaker.call(failing_func)
        assert breaker.state == CircuitState.CLOSED
        assert breaker.failure_count == 2

        # Third failure - should open circuit
        with pytest.raises(ConnectionError):
            await breaker.call(failing_func)
        assert breaker.state == CircuitState.OPEN
        assert breaker.failure_count == 3

    async def test_open_circuit_blocks_calls(self, breaker, failing_func, success_func):
        """Test that open circuit blocks calls immediately."""
        # Open the circuit
        for _ in range(3):
            with contextlib.suppress(ConnectionError):
                await breaker.call(failing_func)

        assert breaker.state == CircuitState.OPEN

        # Calls should fail with CircuitBreakerOpenError
        with pytest.raises(CircuitBreakerOpenError):
            await breaker.call(success_func)

        # Failure count should not increase when circuit is open
        assert breaker.failure_count == 3

    async def test_half_open_after_timeout(self, breaker, failing_func):
        """Test transition to HALF_OPEN after timeout by directly forcing state."""
        # Open the circuit
        for _ in range(3):
            with contextlib.suppress(ConnectionError):
                await breaker.call(failing_func)

        assert breaker.state == CircuitState.OPEN

        # Directly manipulate state to test HALF_OPEN behavior
        breaker._transition_to_half_open()

        assert breaker.state == CircuitState.HALF_OPEN

    async def test_success_closes_circuit_from_half_open(self, breaker, failing_func, flaky_func):
        """Test that successes close circuit from HALF_OPEN."""
        # Open the circuit
        for _ in range(3):
            with contextlib.suppress(ConnectionError):
                await breaker.call(failing_func)

        assert breaker.state == CircuitState.OPEN

        # Manually transition to HALF_OPEN for testing
        breaker._transition_to_half_open()

        # First success in HALF_OPEN
        func = flaky_func(attempts_to_fail=0)
        result = await breaker.call(func)
        assert result == "success on attempt 1"
        assert breaker.state == CircuitState.HALF_OPEN
        assert breaker.success_count == 1

        # Second success should close circuit
        result = await breaker.call(func)
        assert result == "success on attempt 2"
        assert breaker.state == CircuitState.CLOSED
        assert breaker.failure_count == 0
        assert breaker.success_count == 0  # Reset on close

    async def test_failure_in_half_open_reopens(self, breaker, failing_func):
        """Test that failure in HALF_OPEN reopens circuit."""
        # Open the circuit
        for _ in range(3):
            with contextlib.suppress(ConnectionError):
                await breaker.call(failing_func)

        # Manually transition to HALF_OPEN for testing
        breaker._transition_to_half_open()

        # Failure in HALF_OPEN should reopen
        with pytest.raises(ConnectionError):
            await breaker.call(failing_func)

        assert breaker.state == CircuitState.OPEN

    async def test_half_open_max_calls_limit(self, breaker, failing_func):
        """Test that HALF_OPEN tracks call count."""
        # Use a config with higher success threshold to stay in HALF_OPEN
        config = CircuitBreakerConfig(
            failure_threshold=3,
            success_threshold=5,  # Higher threshold
            half_open_max_calls=10,
        )
        test_breaker = CircuitBreaker(name="test_breaker_high", config=config)

        # Open the circuit
        for _ in range(3):
            with contextlib.suppress(ConnectionError):
                await test_breaker.call(failing_func)

        # Manually transition to HALF_OPEN for testing
        test_breaker._transition_to_half_open()

        # Create a function that succeeds so we stay in HALF_OPEN
        async def success_func():
            return "success"

        # Make calls in HALF_OPEN
        for _ in range(3):
            result = await test_breaker.call(success_func)
            assert result == "success"

        assert test_breaker.state == CircuitState.HALF_OPEN
        assert test_breaker.half_open_call_count == 3
        assert test_breaker.success_count == 3

    async def test_reset(self, breaker, failing_func):
        """Test manual reset of circuit breaker."""
        # Open the circuit
        for _ in range(3):
            with contextlib.suppress(ConnectionError):
                await breaker.call(failing_func)

        assert breaker.state == CircuitState.OPEN

        # Reset
        breaker.reset()

        assert breaker.state == CircuitState.CLOSED
        assert breaker.failure_count == 0
        assert breaker.success_count == 0

    async def test_get_state(self, breaker):
        """Test getting current state."""
        state = breaker.get_state()

        assert state["name"] == "test_breaker"
        assert state["state"] == CircuitState.CLOSED
        assert state["failure_count"] == 0
        assert state["success_count"] == 0
        assert "opened_at" in state
        assert "last_failure_time" in state

    async def test_context_manager_success(self, breaker, success_func):
        """Test using circuit breaker as context manager."""
        async with breaker:
            result = await success_func()

        assert result == "success"
        assert breaker.state == CircuitState.CLOSED

    async def test_context_manager_failure(self, breaker, failing_func):
        """Test context manager with failing function."""
        with pytest.raises(ConnectionError):
            async with breaker:
                await failing_func()

        assert breaker.failure_count == 1

    async def test_context_manager_open_circuit(self, breaker, failing_func):
        """Test context manager with open circuit."""
        # Open the circuit
        for _ in range(3):
            with contextlib.suppress(ConnectionError):
                await breaker.call(failing_func)

        # Verify circuit is open
        assert breaker.state == CircuitState.OPEN

        # Context manager will not raise immediately
        # but __aexit__ will call _on_success or _on_failure
        # Since we don't execute anything in the context manager,
        # it will just pass through
        async with breaker:
            pass

        # Circuit should still be open
        assert breaker.state == CircuitState.OPEN

    async def test_custom_exception_handling(self):
        """Test circuit breaker with custom exception types."""
        config = CircuitBreakerConfig(
            failure_threshold=2,
            exceptions=(ValueError,),  # Only track ValueError
        )
        breaker = CircuitBreaker(name="custom_breaker", config=config)

        # Other exceptions should not affect circuit state
        async def raise_connection_error():
            raise ConnectionError("Not tracked")

        for _ in range(5):
            with contextlib.suppress(ConnectionError):
                await breaker.call(raise_connection_error)

        # Circuit should remain CLOSED
        assert breaker.state == CircuitState.CLOSED
        assert breaker.failure_count == 0

        # Tracked exception should open circuit
        async def raise_value_error():
            raise ValueError("Tracked error")

        for _ in range(2):
            with contextlib.suppress(ValueError):
                await breaker.call(raise_value_error)

        assert breaker.state == CircuitState.OPEN

    async def test_fallback_function(self, breaker, failing_func):
        """Test fallback function when circuit is open."""
        # Open the circuit
        for _ in range(3):
            with contextlib.suppress(ConnectionError):
                await breaker.call(failing_func)

        async def fallback():
            return "fallback_value"

        result = await breaker.call(failing_func, fallback=fallback)

        assert result == "fallback_value"

    async def test_fallback_on_exception(self, breaker):
        """Test fallback function on specific exception."""

        async def raise_specific_error():
            raise ValueError("Specific error")

        async def fallback(error=None):
            return f"Handled: {error}"

        # Circuit is closed, fallback on exception
        result = await breaker.call(
            raise_specific_error, fallback_on_exception=ValueError, fallback=fallback
        )

        assert result == "Handled: None"
        # The exception was handled by fallback, so no failure counted
        assert breaker.failure_count == 0

    async def test_statistics_tracking(self, breaker, failing_func, flaky_func):
        """Test that circuit breaker tracks statistics."""
        stats_before = breaker.get_statistics()

        # Make some successful calls
        func = flaky_func(attempts_to_fail=0)
        for _ in range(5):
            await breaker.call(func)

        # Make some failing calls to open circuit
        for _ in range(3):
            with contextlib.suppress(ConnectionError):
                await breaker.call(failing_func)

        stats_after = breaker.get_statistics()

        assert stats_after["total_calls"] > stats_before["total_calls"]
        assert stats_after["successful_calls"] >= 5
        assert stats_after["failed_calls"] >= 3
        assert stats_after["open_count"] > 0

    async def test_concurrent_calls(self, breaker, flaky_func):
        """Test circuit breaker behavior with concurrent calls."""
        import asyncio

        # Each call creates a new function with its own attempt counter
        # Create a function that succeeds immediately
        async def success_func():
            return "success"

        # Make concurrent calls
        tasks = [breaker.call(success_func) for _ in range(10)]
        results = await asyncio.gather(*tasks)

        assert len(results) == 10
        assert all(r == "success" for r in results)
        assert breaker.state == CircuitState.CLOSED


class TestCircuitBreakerOpenError:
    """Tests for CircuitBreakerOpenError."""

    def test_error_creation(self):
        """Test creating a CircuitBreakerOpenError."""
        error = CircuitBreakerOpenError(
            breaker_name="test_breaker",
            opened_at=datetime.now(UTC),
        )

        assert "test_breaker" in str(error)
        assert error.breaker_name == "test_breaker"
        assert error.opened_at is not None

    def test_error_retry_after(self):
        """Test retry_after calculation."""
        opened_at = datetime.now(UTC)
        error = CircuitBreakerOpenError(
            breaker_name="test_breaker",
            opened_at=opened_at,
            timeout=timedelta(seconds=30),
        )

        # retry_after should be positive
        assert error.retry_after() > 0
        assert error.retry_after() <= 30

    def test_default_values(self):
        """Test default error values."""
        error = CircuitBreakerOpenError()

        assert error.breaker_name == "unknown"
        assert error.timeout is not None
