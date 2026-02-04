"""
Unit tests for LLM resilience components.

Tests CircuitBreaker, ProviderRateLimiter, and related utilities.
"""

import asyncio
import time
from datetime import timedelta

import pytest

from src.domain.llm_providers.models import ProviderType
from src.infrastructure.llm.resilience import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitState,
    ProviderRateLimiter,
    RateLimitConfig,
    get_circuit_breaker_registry,
    get_provider_rate_limiter,
)


class TestCircuitBreaker:
    """Tests for CircuitBreaker."""

    def test_initial_state_is_closed(self):
        """Circuit breaker starts in closed state."""
        breaker = CircuitBreaker("test", CircuitBreakerConfig())
        assert breaker.state == CircuitState.CLOSED
        assert breaker.can_execute()

    def test_opens_after_failure_threshold(self):
        """Circuit opens after reaching failure threshold."""
        config = CircuitBreakerConfig(failure_threshold=3)
        breaker = CircuitBreaker("test", config)

        # Record failures up to threshold
        for _ in range(3):
            breaker.record_failure()

        assert breaker.state == CircuitState.OPEN
        assert not breaker.can_execute()

    def test_success_resets_failure_count(self):
        """Successful request resets failure counter."""
        config = CircuitBreakerConfig(failure_threshold=3)
        breaker = CircuitBreaker("test", config)

        # Record some failures
        breaker.record_failure()
        breaker.record_failure()

        # Success resets
        breaker.record_success()

        # More failures needed to open
        breaker.record_failure()
        breaker.record_failure()
        assert breaker.state == CircuitState.CLOSED

    def test_half_open_after_recovery_timeout(self):
        """Circuit transitions to half-open after recovery timeout."""
        config = CircuitBreakerConfig(
            failure_threshold=1,
            recovery_timeout=timedelta(seconds=0.1),  # Short timeout for testing
        )
        breaker = CircuitBreaker("test", config)

        breaker.record_failure()
        assert breaker.state == CircuitState.OPEN

        # Wait for recovery timeout
        time.sleep(0.15)

        # Should transition to half-open
        assert breaker.can_execute()
        assert breaker.state == CircuitState.HALF_OPEN

    def test_closes_after_success_in_half_open(self):
        """Circuit closes after success threshold in half-open."""
        config = CircuitBreakerConfig(
            failure_threshold=1,
            success_threshold=2,
            recovery_timeout=timedelta(seconds=0.1),
        )
        breaker = CircuitBreaker("test", config)

        # Open the circuit
        breaker.record_failure()
        time.sleep(0.15)
        breaker.can_execute()  # Transition to half-open

        # Record successes
        breaker.record_success()
        breaker.record_success()

        assert breaker.state == CircuitState.CLOSED

    def test_reopens_on_failure_in_half_open(self):
        """Circuit reopens immediately on failure in half-open."""
        config = CircuitBreakerConfig(
            failure_threshold=1,
            recovery_timeout=timedelta(seconds=0.1),
        )
        breaker = CircuitBreaker("test", config)

        # Open and transition to half-open
        breaker.record_failure()
        time.sleep(0.15)
        breaker.can_execute()
        assert breaker.state == CircuitState.HALF_OPEN

        # Failure reopens circuit
        breaker.record_failure()
        assert breaker.state == CircuitState.OPEN

    def test_get_status(self):
        """Status returns correct information."""
        breaker = CircuitBreaker("test-provider", CircuitBreakerConfig())
        breaker.record_success()
        breaker.record_failure()

        status = breaker.get_status()
        assert status["provider_id"] == "test-provider"
        assert status["state"] == "closed"
        assert status["stats"]["total_requests"] == 2
        assert status["stats"]["successful_requests"] == 1
        assert status["stats"]["failed_requests"] == 1


class TestCircuitBreakerRegistry:
    """Tests for CircuitBreakerRegistry."""

    def test_get_creates_breaker(self):
        """Registry creates breaker on first access."""
        from src.infrastructure.llm.resilience.circuit_breaker import (
            CircuitBreakerRegistry,
        )

        registry = CircuitBreakerRegistry()
        breaker = registry.get(ProviderType.OPENAI)

        assert breaker is not None
        assert breaker.provider_id == "openai"

    def test_get_returns_same_instance(self):
        """Registry returns same breaker for same provider."""
        from src.infrastructure.llm.resilience.circuit_breaker import (
            CircuitBreakerRegistry,
        )

        registry = CircuitBreakerRegistry()
        breaker1 = registry.get(ProviderType.OPENAI)
        breaker2 = registry.get(ProviderType.OPENAI)

        assert breaker1 is breaker2

    def test_get_works_with_string(self):
        """Registry works with string provider ID."""
        from src.infrastructure.llm.resilience.circuit_breaker import (
            CircuitBreakerRegistry,
        )

        registry = CircuitBreakerRegistry()
        breaker = registry.get("custom-provider")

        assert breaker.provider_id == "custom-provider"


class TestProviderRateLimiter:
    """Tests for ProviderRateLimiter."""

    @pytest.mark.asyncio
    async def test_acquire_and_release(self):
        """Basic acquire and release works."""
        limiter = ProviderRateLimiter()

        async with await limiter.acquire(ProviderType.OPENAI):
            pass  # Request executed

        stats = limiter.get_stats(ProviderType.OPENAI)
        assert stats["stats"]["total_requests"] == 1

    @pytest.mark.asyncio
    async def test_concurrent_limit(self):
        """Respects concurrent request limit."""
        config = {ProviderType.OPENAI: RateLimitConfig(max_concurrent=2)}
        limiter = ProviderRateLimiter(configs=config)

        active = 0
        max_active = 0

        async def make_request():
            nonlocal active, max_active
            async with await limiter.acquire(ProviderType.OPENAI):
                active += 1
                max_active = max(max_active, active)
                await asyncio.sleep(0.1)
                active -= 1

        # Start 5 concurrent requests with limit of 2
        await asyncio.gather(*[make_request() for _ in range(5)])

        assert max_active <= 2

    def test_get_stats(self):
        """Stats are correctly tracked."""
        limiter = ProviderRateLimiter()

        stats = limiter.get_stats(ProviderType.OPENAI)
        assert stats["provider"] == "openai"
        assert "config" in stats
        assert "stats" in stats

    def test_default_configs(self):
        """Default configs are applied."""
        limiter = ProviderRateLimiter()

        openai_config = limiter._get_config(ProviderType.OPENAI)
        assert openai_config.max_concurrent == 50

        gemini_config = limiter._get_config(ProviderType.GEMINI)
        assert gemini_config.max_concurrent == 100


class TestGlobalInstances:
    """Tests for global singleton instances."""

    def test_circuit_breaker_registry_singleton(self):
        """Global registry is singleton."""
        registry1 = get_circuit_breaker_registry()
        registry2 = get_circuit_breaker_registry()
        assert registry1 is registry2

    def test_rate_limiter_singleton(self):
        """Global rate limiter is singleton."""
        limiter1 = get_provider_rate_limiter()
        limiter2 = get_provider_rate_limiter()
        assert limiter1 is limiter2
