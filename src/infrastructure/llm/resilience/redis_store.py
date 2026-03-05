"""Redis-backed state stores for circuit breaker and rate limiter.

Provides pluggable state persistence for circuit breaker state,
with graceful degradation to in-memory when Redis is unavailable.

Key patterns:
- CircuitBreakerStateStore: Abstract interface for state persistence
- InMemoryCircuitBreakerStore: Default in-process store
- RedisCircuitBreakerStore: Distributed store via Redis HASH

Redis key format: cb:{breaker_id}
TTL: 2x recovery_timeout (auto-expires stale breakers)
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, override

from src.infrastructure.llm.resilience.circuit_breaker import CircuitState

if TYPE_CHECKING:
    from redis.asyncio import Redis

logger = logging.getLogger(__name__)


@dataclass
class CircuitBreakerState:
    """Value object representing circuit breaker state.

    Attributes:
        state: Current circuit state (CLOSED, OPEN, HALF_OPEN).
        failure_count: Consecutive failure count.
        success_count: Consecutive success count in half-open.
        half_open_requests: Number of requests allowed in half-open.
        last_failure_time: Timestamp of last failure.
        last_state_change: Timestamp of last state transition.
    """

    state: CircuitState = CircuitState.CLOSED
    failure_count: int = 0
    success_count: int = 0
    half_open_requests: int = 0
    last_failure_time: datetime | None = None
    last_state_change: datetime = field(
        default_factory=lambda: datetime.now(UTC),
    )


class CircuitBreakerStateStore(ABC):
    """Abstract interface for circuit breaker state persistence."""

    @abstractmethod
    async def load_state(
        self,
        breaker_id: str,
    ) -> CircuitBreakerState | None:
        """Load state for a circuit breaker.

        Args:
            breaker_id: Unique identifier for the circuit breaker.

        Returns:
            The persisted state, or None if not found.
        """

    @abstractmethod
    async def save_state(
        self,
        breaker_id: str,
        state: CircuitBreakerState,
    ) -> None:
        """Persist state for a circuit breaker.

        Args:
            breaker_id: Unique identifier for the circuit breaker.
            state: The state to persist.
        """

    @abstractmethod
    async def delete_state(self, breaker_id: str) -> None:
        """Delete persisted state for a circuit breaker.

        Args:
            breaker_id: Unique identifier for the circuit breaker.
        """


class InMemoryCircuitBreakerStore(CircuitBreakerStateStore):
    """In-memory circuit breaker state store.

    Suitable for single-process deployments or as fallback
    when Redis is unavailable.
    """

    def __init__(self) -> None:
        self._states: dict[str, CircuitBreakerState] = {}

    @override
    async def load_state(
        self,
        breaker_id: str,
    ) -> CircuitBreakerState | None:
        """Load state from in-memory dict."""
        return self._states.get(breaker_id)

    @override
    async def save_state(
        self,
        breaker_id: str,
        state: CircuitBreakerState,
    ) -> None:
        """Save state to in-memory dict."""
        self._states[breaker_id] = state

    @override
    async def delete_state(self, breaker_id: str) -> None:
        """Delete state from in-memory dict."""
        self._states.pop(breaker_id, None)


def _serialize_state(state: CircuitBreakerState) -> dict[str, str]:
    """Serialize CircuitBreakerState to a Redis HASH-compatible dict.

    All values are strings for Redis HSET compatibility.
    """
    return {
        "state": state.state.value,
        "failure_count": str(state.failure_count),
        "success_count": str(state.success_count),
        "half_open_requests": str(state.half_open_requests),
        "last_failure_time": (
            state.last_failure_time.isoformat() if state.last_failure_time else ""
        ),
        "last_state_change": state.last_state_change.isoformat(),
    }


def _deserialize_state(
    data: dict[str, str],
) -> CircuitBreakerState:
    """Deserialize a Redis HASH dict into CircuitBreakerState."""
    last_failure_raw = data.get("last_failure_time", "")
    last_failure_time: datetime | None = None
    if last_failure_raw:
        last_failure_time = datetime.fromisoformat(last_failure_raw)

    last_state_raw = data.get("last_state_change", "")
    last_state_change = (
        datetime.fromisoformat(last_state_raw) if last_state_raw else datetime.now(UTC)
    )

    return CircuitBreakerState(
        state=CircuitState(data.get("state", "closed")),
        failure_count=int(data.get("failure_count", "0")),
        success_count=int(data.get("success_count", "0")),
        half_open_requests=int(
            data.get("half_open_requests", "0"),
        ),
        last_failure_time=last_failure_time,
        last_state_change=last_state_change,
    )


class RedisCircuitBreakerStore(CircuitBreakerStateStore):
    """Redis-backed circuit breaker state store.

    Stores state in Redis HASHes at key ``cb:{breaker_id}``.
    TTL is set to 2x recovery_timeout so stale breakers expire.

    Falls back to an in-memory store on any Redis error, ensuring
    the circuit breaker continues to function even without Redis.
    """

    _KEY_PREFIX = "cb:"

    def __init__(
        self,
        redis_client: Redis | None = None,
        default_ttl: timedelta = timedelta(seconds=120),
    ) -> None:
        """Initialize the Redis circuit breaker store.

        Args:
            redis_client: Async Redis client. None = in-memory only.
            default_ttl: TTL for Redis keys (2x recovery_timeout).
        """
        self._redis = redis_client
        self._ttl_seconds = int(default_ttl.total_seconds())
        self._fallback = InMemoryCircuitBreakerStore()

    def _key(self, breaker_id: str) -> str:
        """Build the Redis key for a breaker."""
        return f"{self._KEY_PREFIX}{breaker_id}"

    @override
    async def load_state(
        self,
        breaker_id: str,
    ) -> CircuitBreakerState | None:
        """Load state from Redis, falling back to in-memory."""
        if not self._redis:
            return await self._fallback.load_state(breaker_id)

        try:
            data = await self._redis.hgetall(self._key(breaker_id))  # type: ignore[misc]
            if not data:
                # Try fallback in case it was written there
                return await self._fallback.load_state(breaker_id)
            return _deserialize_state(data)
        except Exception:
            logger.warning(
                "Redis load failed for cb:%s, using fallback",
                breaker_id,
                exc_info=True,
            )
            return await self._fallback.load_state(breaker_id)

    @override
    async def save_state(
        self,
        breaker_id: str,
        state: CircuitBreakerState,
    ) -> None:
        """Save state to Redis and in-memory fallback."""
        # Always keep fallback in sync
        await self._fallback.save_state(breaker_id, state)

        if not self._redis:
            return

        try:
            key = self._key(breaker_id)
            mapping = _serialize_state(state)
            await self._redis.hset(key, mapping=mapping)  # type: ignore[misc]
            await self._redis.expire(key, self._ttl_seconds)
        except Exception:
            logger.warning(
                "Redis save failed for cb:%s, using fallback",
                breaker_id,
                exc_info=True,
            )

    @override
    async def delete_state(self, breaker_id: str) -> None:
        """Delete state from Redis and in-memory fallback."""
        await self._fallback.delete_state(breaker_id)

        if not self._redis:
            return

        try:
            await self._redis.delete(self._key(breaker_id))
        except Exception:
            logger.warning(
                "Redis delete failed for cb:%s",
                breaker_id,
                exc_info=True,
            )
