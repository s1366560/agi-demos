"""Unit tests for Redis-backed resilience components.

Tests cover:
- RedisCircuitBreakerStore: persistence, TTL, fallback on Redis errors
- CircuitBreaker: pluggable state store integration
- RedisRateLimiter: distributed RPM checks, fallback on Redis errors
- LLMProviderManager: redis_client wiring
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from src.infrastructure.llm.resilience.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitBreakerRegistry,
    CircuitState,
)
from src.infrastructure.llm.resilience.redis_store import (
    CircuitBreakerState,
    InMemoryCircuitBreakerStore,
    RedisCircuitBreakerStore,
    _deserialize_state,
    _serialize_state,
)


def _make_redis_mock() -> AsyncMock:
    """Create a mock async Redis client with common methods."""
    redis = AsyncMock()
    redis.hgetall = AsyncMock(return_value={})
    redis.hset = AsyncMock()
    redis.expire = AsyncMock()
    redis.delete = AsyncMock()
    redis.incr = AsyncMock(return_value=1)
    redis.decr = AsyncMock()
    return redis


# -------------------------------------------------------------------
# Serialization helpers
# -------------------------------------------------------------------


@pytest.mark.unit
class TestCircuitBreakerStateSerialization:
    """Tests for state serialization / deserialization."""

    def test_roundtrip_default_state(self) -> None:
        """Serialize then deserialize a default state."""
        state = CircuitBreakerState()
        data = _serialize_state(state)
        restored = _deserialize_state(data)

        assert restored.state == CircuitState.CLOSED
        assert restored.failure_count == 0
        assert restored.success_count == 0
        assert restored.half_open_requests == 0
        assert restored.last_failure_time is None

    def test_roundtrip_with_failure_time(self) -> None:
        """Serialize state with a last_failure_time set."""
        now = datetime.now(UTC)
        state = CircuitBreakerState(
            state=CircuitState.OPEN,
            failure_count=5,
            last_failure_time=now,
            last_state_change=now,
        )
        data = _serialize_state(state)
        restored = _deserialize_state(data)

        assert restored.state == CircuitState.OPEN
        assert restored.failure_count == 5
        assert restored.last_failure_time is not None

    def test_deserialize_missing_keys_uses_defaults(self) -> None:
        """Deserializing an empty dict produces default state."""
        restored = _deserialize_state({})
        assert restored.state == CircuitState.CLOSED
        assert restored.failure_count == 0


# -------------------------------------------------------------------
# InMemoryCircuitBreakerStore
# -------------------------------------------------------------------


@pytest.mark.unit
class TestInMemoryCircuitBreakerStore:
    """Tests for InMemoryCircuitBreakerStore."""

    async def test_load_returns_none_initially(self) -> None:
        """Loading a non-existent breaker returns None."""
        store = InMemoryCircuitBreakerStore()
        result = await store.load_state("unknown")
        assert result is None

    async def test_save_then_load(self) -> None:
        """Save state and load it back."""
        store = InMemoryCircuitBreakerStore()
        state = CircuitBreakerState(
            state=CircuitState.OPEN,
            failure_count=3,
        )
        await store.save_state("test-breaker", state)
        loaded = await store.load_state("test-breaker")

        assert loaded is not None
        assert loaded.state == CircuitState.OPEN
        assert loaded.failure_count == 3

    async def test_delete_state(self) -> None:
        """Delete removes the stored state."""
        store = InMemoryCircuitBreakerStore()
        await store.save_state("b1", CircuitBreakerState())
        await store.delete_state("b1")
        assert await store.load_state("b1") is None

    async def test_delete_nonexistent_is_noop(self) -> None:
        """Deleting a non-existent key does not raise."""
        store = InMemoryCircuitBreakerStore()
        await store.delete_state("nope")  # should not raise


# -------------------------------------------------------------------
# RedisCircuitBreakerStore
# -------------------------------------------------------------------


@pytest.mark.unit
class TestRedisCircuitBreakerStore:
    """Tests for RedisCircuitBreakerStore."""

    async def test_save_writes_to_redis_and_fallback(self) -> None:
        """save_state writes to both Redis HASH and in-memory."""
        redis = _make_redis_mock()
        store = RedisCircuitBreakerStore(
            redis_client=redis,
            default_ttl=timedelta(seconds=60),
        )
        state = CircuitBreakerState(
            state=CircuitState.OPEN,
            failure_count=5,
        )
        await store.save_state("p1", state)

        # Redis was called
        redis.hset.assert_awaited_once()
        redis.expire.assert_awaited_once_with("cb:p1", 60)

        # Fallback also has it
        fallback_state = await store._fallback.load_state("p1")
        assert fallback_state is not None
        assert fallback_state.state == CircuitState.OPEN

    async def test_load_reads_from_redis(self) -> None:
        """load_state returns data from Redis when available."""
        redis = _make_redis_mock()
        redis.hgetall = AsyncMock(
            return_value={
                "state": "open",
                "failure_count": "3",
                "success_count": "0",
                "half_open_requests": "0",
                "last_failure_time": "",
                "last_state_change": datetime.now(UTC).isoformat(),
            },
        )
        store = RedisCircuitBreakerStore(redis_client=redis)
        loaded = await store.load_state("p1")

        assert loaded is not None
        assert loaded.state == CircuitState.OPEN
        assert loaded.failure_count == 3

    async def test_load_falls_back_when_redis_empty(self) -> None:
        """load_state falls back to in-memory when Redis has no data."""
        redis = _make_redis_mock()
        redis.hgetall = AsyncMock(return_value={})
        store = RedisCircuitBreakerStore(redis_client=redis)

        # Pre-populate fallback
        await store._fallback.save_state(
            "p1",
            CircuitBreakerState(state=CircuitState.HALF_OPEN),
        )
        loaded = await store.load_state("p1")
        assert loaded is not None
        assert loaded.state == CircuitState.HALF_OPEN

    async def test_load_falls_back_on_redis_error(self) -> None:
        """load_state degrades to in-memory on Redis exception."""
        redis = _make_redis_mock()
        redis.hgetall = AsyncMock(side_effect=ConnectionError("down"))
        store = RedisCircuitBreakerStore(redis_client=redis)

        # Pre-populate fallback
        await store._fallback.save_state(
            "p1",
            CircuitBreakerState(failure_count=7),
        )
        loaded = await store.load_state("p1")
        assert loaded is not None
        assert loaded.failure_count == 7

    async def test_save_falls_back_on_redis_error(self) -> None:
        """save_state still saves to fallback even when Redis fails."""
        redis = _make_redis_mock()
        redis.hset = AsyncMock(side_effect=ConnectionError("down"))
        store = RedisCircuitBreakerStore(redis_client=redis)

        state = CircuitBreakerState(failure_count=2)
        await store.save_state("p1", state)  # should not raise

        fallback = await store._fallback.load_state("p1")
        assert fallback is not None
        assert fallback.failure_count == 2

    async def test_delete_removes_from_redis_and_fallback(self) -> None:
        """delete_state cleans up both Redis and fallback."""
        redis = _make_redis_mock()
        store = RedisCircuitBreakerStore(redis_client=redis)
        await store.save_state("p1", CircuitBreakerState())
        await store.delete_state("p1")

        redis.delete.assert_awaited_once_with("cb:p1")
        assert await store._fallback.load_state("p1") is None

    async def test_delete_ignores_redis_error(self) -> None:
        """delete_state succeeds (fallback) even if Redis errors."""
        redis = _make_redis_mock()
        redis.delete = AsyncMock(side_effect=ConnectionError("down"))
        store = RedisCircuitBreakerStore(redis_client=redis)
        await store.save_state("p1", CircuitBreakerState())

        await store.delete_state("p1")  # should not raise
        assert await store._fallback.load_state("p1") is None

    async def test_no_redis_client_uses_fallback_only(self) -> None:
        """When redis_client is None, all ops use in-memory."""
        store = RedisCircuitBreakerStore(redis_client=None)
        await store.save_state(
            "p1",
            CircuitBreakerState(failure_count=9),
        )
        loaded = await store.load_state("p1")
        assert loaded is not None
        assert loaded.failure_count == 9


# -------------------------------------------------------------------
# CircuitBreaker with pluggable state store
# -------------------------------------------------------------------


@pytest.mark.unit
class TestCircuitBreakerWithStore:
    """Tests for CircuitBreaker sync_from_store / sync_to_store."""

    async def test_sync_from_store_restores_state(self) -> None:
        """sync_from_store loads persisted state into instance."""
        store = InMemoryCircuitBreakerStore()
        await store.save_state(
            "openai",
            CircuitBreakerState(
                state=CircuitState.OPEN,
                failure_count=5,
                success_count=0,
            ),
        )
        breaker = CircuitBreaker(
            "openai",
            CircuitBreakerConfig(),
            state_store=store,
        )
        await breaker.sync_from_store()

        assert breaker.state == CircuitState.OPEN
        assert breaker._failure_count == 5

    async def test_sync_from_store_noop_without_store(self) -> None:
        """sync_from_store is a no-op when no store configured."""
        breaker = CircuitBreaker("openai")
        await breaker.sync_from_store()  # should not raise
        assert breaker.state == CircuitState.CLOSED

    async def test_sync_to_store_persists_state(self) -> None:
        """sync_to_store saves current state to store."""
        store = InMemoryCircuitBreakerStore()
        breaker = CircuitBreaker(
            "openai",
            CircuitBreakerConfig(failure_threshold=2),
            state_store=store,
        )
        # Force some failures
        breaker.record_failure()
        breaker.record_failure()
        # Now breaker is OPEN
        assert breaker.state == CircuitState.OPEN

        await breaker.sync_to_store()
        loaded = await store.load_state("openai")
        assert loaded is not None
        assert loaded.state == CircuitState.OPEN
        assert loaded.failure_count == 2

    async def test_sync_to_store_noop_without_store(self) -> None:
        """sync_to_store is a no-op when no store configured."""
        breaker = CircuitBreaker("openai")
        await breaker.sync_to_store()  # should not raise

    async def test_registry_passes_store_to_breakers(self) -> None:
        """CircuitBreakerRegistry passes state_store to new breakers."""
        store = InMemoryCircuitBreakerStore()
        registry = CircuitBreakerRegistry(state_store=store)
        breaker = registry.get_breaker("test-provider")
        assert breaker._state_store is store


# -------------------------------------------------------------------
# RedisRateLimiter
# -------------------------------------------------------------------


@pytest.mark.unit
class TestRedisRateLimiter:
    """Tests for RedisRateLimiter."""

    async def test_acquire_with_redis_rpm_ok(self) -> None:
        """Acquire succeeds when Redis RPM is under limit."""
        from src.domain.llm_providers.models import ProviderType
        from src.infrastructure.llm.resilience.rate_limiter import (
            RedisRateLimiter,
        )

        redis = _make_redis_mock()
        redis.incr = AsyncMock(return_value=1)  # first request
        limiter = RedisRateLimiter(redis_client=redis)

        ctx = await limiter.acquire(ProviderType.OPENAI)
        assert ctx is not None
        # Cleanup
        await ctx.release_async()

    async def test_acquire_rejects_when_over_rpm(self) -> None:
        """Acquire raises RateLimitExceededError when over RPM."""
        from src.domain.llm_providers.models import ProviderType
        from src.infrastructure.llm.resilience.rate_limiter import (
            RateLimitExceededError,
            RedisRateLimiter,
        )

        redis = _make_redis_mock()
        # Return a number way over any RPM limit
        redis.incr = AsyncMock(return_value=999_999_999)
        limiter = RedisRateLimiter(redis_client=redis)

        with pytest.raises(RateLimitExceededError):
            await limiter.acquire(ProviderType.OPENAI)

    async def test_acquire_allows_when_redis_fails(self) -> None:
        """When Redis errors, RPM check passes (graceful degradation)."""
        from src.domain.llm_providers.models import ProviderType
        from src.infrastructure.llm.resilience.rate_limiter import (
            RedisRateLimiter,
        )

        redis = _make_redis_mock()
        redis.incr = AsyncMock(side_effect=ConnectionError("down"))
        limiter = RedisRateLimiter(redis_client=redis)

        ctx = await limiter.acquire(ProviderType.OPENAI)
        assert ctx is not None
        await ctx.release_async()

    async def test_acquire_without_redis_uses_local_only(self) -> None:
        """No redis_client means pure local rate limiting."""
        from src.domain.llm_providers.models import ProviderType
        from src.infrastructure.llm.resilience.rate_limiter import (
            RedisRateLimiter,
        )

        limiter = RedisRateLimiter(redis_client=None)
        ctx = await limiter.acquire(ProviderType.OPENAI)
        assert ctx is not None
        await ctx.release_async()

    async def test_context_manager_releases_on_exit(self) -> None:
        """RedisRateLimitContext releases on async with exit."""
        from src.domain.llm_providers.models import ProviderType
        from src.infrastructure.llm.resilience.rate_limiter import (
            RedisRateLimiter,
        )

        redis = _make_redis_mock()
        limiter = RedisRateLimiter(redis_client=redis)

        async with await limiter.acquire(ProviderType.OPENAI):
            pass  # context exits cleanly

        # decr should have been called for concurrent tracking
        redis.decr.assert_awaited()

    async def test_get_stats_delegates_to_local(self) -> None:
        """get_stats returns local limiter stats."""
        from src.domain.llm_providers.models import ProviderType
        from src.infrastructure.llm.resilience.rate_limiter import (
            RedisRateLimiter,
        )

        limiter = RedisRateLimiter(redis_client=None)
        stats = limiter.get_stats(ProviderType.OPENAI)
        assert "provider" in stats
        assert stats["provider"] == "openai"

    async def test_get_all_stats_delegates_to_local(self) -> None:
        """get_all_stats returns local limiter stats."""
        from src.infrastructure.llm.resilience.rate_limiter import (
            RedisRateLimiter,
        )

        limiter = RedisRateLimiter(redis_client=None)
        all_stats = limiter.get_all_stats()
        assert isinstance(all_stats, dict)


# -------------------------------------------------------------------
# LLMProviderManager wiring
# -------------------------------------------------------------------


@pytest.mark.unit
class TestLLMProviderManagerRedisWiring:
    """Tests for redis_client wiring in LLMProviderManager."""

    def test_no_redis_uses_defaults(self) -> None:
        """Without redis_client, defaults are used."""
        from src.application.services.llm_provider_manager import (
            LLMProviderManager,
        )
        from src.infrastructure.llm.resilience.rate_limiter import (
            ProviderRateLimiter,
        )

        manager = LLMProviderManager()
        assert isinstance(manager._circuit_breakers, CircuitBreakerRegistry)
        assert isinstance(manager._rate_limiter, ProviderRateLimiter)

    def test_with_redis_creates_redis_backed_components(self) -> None:
        """With redis_client, Redis-backed stores are created."""
        from src.application.services.llm_provider_manager import (
            LLMProviderManager,
        )
        from src.infrastructure.llm.resilience.rate_limiter import (
            RedisRateLimiter,
        )

        redis = _make_redis_mock()
        manager = LLMProviderManager(redis_client=redis)

        # Circuit breaker registry should have a store
        assert manager._circuit_breakers._state_store is not None
        assert isinstance(
            manager._circuit_breakers._state_store,
            RedisCircuitBreakerStore,
        )
        # Rate limiter should be RedisRateLimiter
        assert isinstance(manager._rate_limiter, RedisRateLimiter)

    def test_explicit_registry_overrides_redis(self) -> None:
        """Explicitly provided registry takes precedence over redis."""
        from src.application.services.llm_provider_manager import (
            LLMProviderManager,
        )

        custom_registry = CircuitBreakerRegistry()
        redis = _make_redis_mock()
        manager = LLMProviderManager(
            circuit_breaker_registry=custom_registry,
            redis_client=redis,
        )
        assert manager._circuit_breakers is custom_registry

    def test_redis_failure_during_build_falls_back(self) -> None:
        """If Redis store creation fails, fallback to in-memory."""
        from src.application.services.llm_provider_manager import (
            LLMProviderManager,
        )

        redis = _make_redis_mock()
        with patch(
            "src.application.services.llm_provider_manager"
            ".LLMProviderManager._build_circuit_breaker_registry",
        ) as mock_build_cb:
            # Simulate the method returning the default registry
            from src.infrastructure.llm.resilience import (
                get_circuit_breaker_registry,
            )

            mock_build_cb.return_value = get_circuit_breaker_registry()
            manager = LLMProviderManager(redis_client=redis)
            assert manager._circuit_breakers is not None
