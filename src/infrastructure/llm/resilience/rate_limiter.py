"""
Per-provider rate limiter for LLM API calls.

Provides independent rate limiting for each LLM provider, preventing
one provider's limits from affecting others.

Features:
- Per-provider semaphores for concurrent request limiting
- Configurable limits per provider type
- RPM (requests per minute) tracking
- Token bucket algorithm for smooth rate limiting

Example:
    limiter = get_provider_rate_limiter()

    async with limiter.acquire(ProviderType.OPENAI):
        result = await llm_client.generate(...)
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from types import TracebackType
from typing import TYPE_CHECKING, Any

from src.domain.llm_providers.models import ProviderType

if TYPE_CHECKING:
    from redis.asyncio import Redis

logger = logging.getLogger(__name__)


@dataclass
class RateLimitConfig:
    """Configuration for rate limiting a provider."""

    # Maximum concurrent requests
    max_concurrent: int = 20

    # Requests per minute limit (0 = unlimited)
    rpm: int = 0

    # Tokens per minute limit (0 = unlimited, for future token-based limiting)
    tpm: int = 0

    # Burst allowance (extra requests allowed in short bursts)
    burst_allowance: int = 5

    # Time window for RPM calculation (seconds)
    window_seconds: int = 60


@dataclass
class RateLimitStats:
    """Statistics for rate limiting."""

    total_requests: int = 0
    waiting_requests: int = 0
    rejected_requests: int = 0
    total_wait_time_ms: float = 0
    requests_in_window: int = 0
    window_start: float = field(default_factory=time.time)


class RateLimitExceededError(Exception):
    """Raised when rate limit is exceeded and cannot be waited for."""

    def __init__(self, provider_type: ProviderType, message: str = "") -> None:
        self.provider_type = provider_type
        super().__init__(message or f"Rate limit exceeded for {provider_type.value}")


# Default rate limit configurations per provider
# Based on documented API limits from each provider
DEFAULT_RATE_LIMITS: dict[ProviderType, RateLimitConfig] = {
    ProviderType.OPENAI: RateLimitConfig(
        max_concurrent=50,
        rpm=10000,  # Tier 3 limit
        tpm=2000000,
    ),
    ProviderType.OPENROUTER: RateLimitConfig(
        max_concurrent=50,
        rpm=10000,
        tpm=2000000,
    ),
    ProviderType.GEMINI: RateLimitConfig(
        max_concurrent=100,
        rpm=60000,  # Very generous limits
        tpm=4000000,
    ),
    ProviderType.DASHSCOPE: RateLimitConfig(
        max_concurrent=30,
        rpm=6000,
        tpm=300000,
    ),
    ProviderType.DEEPSEEK: RateLimitConfig(
        max_concurrent=20,
        rpm=2000,
        tpm=100000,
    ),
    ProviderType.ZAI: RateLimitConfig(
        max_concurrent=30,
        rpm=5000,
        tpm=200000,
    ),
    ProviderType.ANTHROPIC: RateLimitConfig(
        max_concurrent=40,
        rpm=4000,
        tpm=400000,
    ),
    ProviderType.KIMI: RateLimitConfig(
        max_concurrent=20,
        rpm=3000,
        tpm=100000,
    ),
    ProviderType.GROQ: RateLimitConfig(
        max_concurrent=30,
        rpm=30000,  # Very fast inference
        tpm=500000,
    ),
    ProviderType.MISTRAL: RateLimitConfig(
        max_concurrent=30,
        rpm=5000,
        tpm=200000,
    ),
    ProviderType.COHERE: RateLimitConfig(
        max_concurrent=20,
        rpm=10000,
        tpm=200000,
    ),
    ProviderType.OLLAMA: RateLimitConfig(
        max_concurrent=10,
        rpm=0,  # Local provider
        tpm=0,
    ),
    ProviderType.LMSTUDIO: RateLimitConfig(
        max_concurrent=10,
        rpm=0,  # Local provider
        tpm=0,
    ),
}

# Fallback config for unknown providers
DEFAULT_FALLBACK_CONFIG = RateLimitConfig(
    max_concurrent=10,
    rpm=1000,
    tpm=50000,
)


class ProviderRateLimiter:
    """
    Rate limiter with per-provider isolation.

    Each provider gets its own semaphore and rate tracking,
    preventing one provider's limits from affecting others.
    """

    def __init__(
        self,
        configs: dict[ProviderType, RateLimitConfig] | None = None,
    ) -> None:
        """
        Initialize the rate limiter.

        Args:
            configs: Optional custom configurations per provider
        """
        self._configs: dict[ProviderType, RateLimitConfig] = (
            configs if configs is not None else DEFAULT_RATE_LIMITS.copy()
        )
        self._semaphores: dict[ProviderType, asyncio.Semaphore] = {}
        self._stats: dict[ProviderType, RateLimitStats] = {}
        self._request_times: dict[ProviderType, list[float]] = {}
        self._lock = asyncio.Lock()

    def get_config(self, provider_type: ProviderType) -> RateLimitConfig:
        """Get configuration for a provider."""
        return self._configs.get(provider_type, DEFAULT_FALLBACK_CONFIG)

    def _get_semaphore(self, provider_type: ProviderType) -> asyncio.Semaphore:
        """Get or create semaphore for a provider."""
        if provider_type not in self._semaphores:
            config = self.get_config(provider_type)
            self._semaphores[provider_type] = asyncio.Semaphore(config.max_concurrent)
            self._stats[provider_type] = RateLimitStats()
            self._request_times[provider_type] = []
        return self._semaphores[provider_type]

    def get_stats_obj(self, provider_type: ProviderType) -> RateLimitStats:
        """Get or create stats for a provider."""
        if provider_type not in self._stats:
            self._get_semaphore(provider_type)  # Initialize if needed
        return self._stats[provider_type]

    def _check_rpm_limit(self, provider_type: ProviderType) -> bool:
        """
        Check if RPM limit allows a new request.

        Returns:
            True if request is allowed, False if RPM limit exceeded
        """
        config = self.get_config(provider_type)
        if config.rpm <= 0:
            return True  # No RPM limit

        current_time = time.time()
        request_times = self._request_times.get(provider_type, [])

        # Remove requests outside the window
        window_start = current_time - config.window_seconds
        request_times = [t for t in request_times if t > window_start]
        self._request_times[provider_type] = request_times

        # Check if under limit (with burst allowance)
        max_requests = config.rpm + config.burst_allowance
        return len(request_times) < max_requests

    def _record_request(self, provider_type: ProviderType) -> None:
        """Record a request for RPM tracking."""
        if provider_type not in self._request_times:
            self._request_times[provider_type] = []
        self._request_times[provider_type].append(time.time())

    async def acquire(self, provider_type: ProviderType) -> RateLimitContext:
        """
        Acquire rate limit permission for a provider.

        Usage:
            async with limiter.acquire(ProviderType.OPENAI):
                # Make API call
                pass

        Args:
            provider_type: The provider type to acquire limit for

        Returns:
            Context manager that releases the semaphore on exit
        """
        semaphore = self._get_semaphore(provider_type)
        stats = self.get_stats_obj(provider_type)

        stats.total_requests += 1
        stats.waiting_requests += 1

        start_time = time.time()

        # Wait for semaphore
        await semaphore.acquire()

        # Check RPM limit
        while not self._check_rpm_limit(provider_type):
            # Release and wait a bit before retrying
            semaphore.release()
            logger.debug(f"RPM limit reached for {provider_type.value}, waiting 1s...")
            await asyncio.sleep(1.0)
            await semaphore.acquire()

        wait_time = (time.time() - start_time) * 1000
        stats.waiting_requests -= 1
        stats.total_wait_time_ms += wait_time

        if wait_time > 100:  # Log if waited more than 100ms
            logger.debug(f"Rate limiter: waited {wait_time:.1f}ms for {provider_type.value}")

        self._record_request(provider_type)

        return RateLimitContext(semaphore, provider_type, self)

    def get_stats(self, provider_type: ProviderType) -> dict[str, Any]:
        """Get rate limiting statistics for a provider."""
        stats = self.get_stats_obj(provider_type)
        config = self.get_config(provider_type)

        # Calculate current RPM
        current_time = time.time()
        window_start = current_time - config.window_seconds
        request_times = self._request_times.get(provider_type, [])
        current_rpm = len([t for t in request_times if t > window_start])

        return {
            "provider": provider_type.value,
            "config": {
                "max_concurrent": config.max_concurrent,
                "rpm": config.rpm,
                "tpm": config.tpm,
            },
            "stats": {
                "total_requests": stats.total_requests,
                "waiting_requests": stats.waiting_requests,
                "rejected_requests": stats.rejected_requests,
                "avg_wait_time_ms": (
                    stats.total_wait_time_ms / stats.total_requests
                    if stats.total_requests > 0
                    else 0
                ),
                "current_rpm": current_rpm,
            },
        }

    def get_all_stats(self) -> dict[str, dict[str, Any]]:
        """Get statistics for all providers."""
        return {
            provider_type.value: self.get_stats(provider_type)
            for provider_type in self._stats.keys()
        }

    def update_config(
        self,
        provider_type: ProviderType,
        config: RateLimitConfig,
    ) -> None:
        """
        Update configuration for a provider.

        Note: Changes to max_concurrent require recreating the semaphore.
        """
        old_config = self._configs.get(provider_type)
        self._configs[provider_type] = config

        # Recreate semaphore if max_concurrent changed
        if old_config and old_config.max_concurrent != config.max_concurrent:
            if provider_type in self._semaphores:
                # Note: This doesn't wait for in-flight requests
                self._semaphores[provider_type] = asyncio.Semaphore(config.max_concurrent)
                logger.info(
                    f"Recreated semaphore for {provider_type.value} "
                    f"with max_concurrent={config.max_concurrent}"
                )


class RateLimitContext:
    """Context manager for rate limit acquisition."""

    def __init__(
        self,
        semaphore: asyncio.Semaphore,
        provider_type: ProviderType,
        limiter: ProviderRateLimiter,
    ) -> None:
        self._semaphore = semaphore
        self._provider_type = provider_type
        self._limiter = limiter
        self._released = False

    async def __aenter__(self) -> RateLimitContext:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        if not self._released:
            self._semaphore.release()
            self._released = True

    def release(self) -> None:
        """Manually release the rate limit."""
        if not self._released:
            self._semaphore.release()
            self._released = True


class RedisRateLimiter:
    """Distributed rate limiter backed by Redis.

    Wraps a local ``ProviderRateLimiter`` and augments it with
    Redis-based RPM/TPM tracking using atomic INCR + EXPIRE.
    Falls back to the local limiter on any Redis error.

    Redis key format:
        ``rl:{provider}:rpm:{minute_bucket}``
        ``rl:{provider}:concurrent``

    Concurrent requests are tracked via Redis INCR/DECR so all
    workers share the same concurrency count.
    """

    _KEY_PREFIX = "rl:"

    def __init__(
        self,
        redis_client: Redis | None = None,
        configs: dict[ProviderType, RateLimitConfig] | None = None,
    ) -> None:
        """Initialize distributed rate limiter.

        Args:
            redis_client: Async Redis client. None = local-only.
            configs: Per-provider rate limit configs.
        """
        self._redis = redis_client
        self._local = ProviderRateLimiter(configs)

    def _rpm_key(self, provider_type: ProviderType) -> str:
        """Build Redis key for RPM tracking."""
        minute = int(time.time() // 60)
        return f"{self._KEY_PREFIX}{provider_type.value}:rpm:{minute}"

    def _concurrent_key(
        self,
        provider_type: ProviderType,
    ) -> str:
        """Build Redis key for concurrent request count."""
        return f"{self._KEY_PREFIX}{provider_type.value}:concurrent"

    async def _check_rpm_redis(
        self,
        provider_type: ProviderType,
    ) -> bool:
        """Check RPM limit via Redis INCR.

        Returns:
            True if request is allowed, False if over limit.
        """
        if not self._redis:
            return True

        config = self._local.get_config(provider_type)
        if config.rpm <= 0:
            return True

        key = self._rpm_key(provider_type)
        try:
            current: int = await self._redis.incr(key)
            if current == 1:
                # First request this minute -- set 70s expiry
                await self._redis.expire(key, 70)
            max_rpm = config.rpm + config.burst_allowance
            return current <= max_rpm
        except Exception:
            logger.warning(
                "Redis RPM check failed for %s, allowing",
                provider_type.value,
                exc_info=True,
            )
            return True

    async def _incr_concurrent(
        self,
        provider_type: ProviderType,
    ) -> int:
        """Increment concurrent request counter in Redis."""
        if not self._redis:
            return 0
        key = self._concurrent_key(provider_type)
        try:
            val: int = await self._redis.incr(key)
            # Set a safety TTL so counters don't leak
            await self._redis.expire(key, 120)
            return val
        except Exception:
            logger.warning(
                "Redis concurrent INCR failed for %s",
                provider_type.value,
                exc_info=True,
            )
            return 0

    async def decr_concurrent(
        self,
        provider_type: ProviderType,
    ) -> None:
        """Decrement concurrent request counter in Redis."""
        if not self._redis:
            return
        key = self._concurrent_key(provider_type)
        try:
            await self._redis.decr(key)
        except Exception:
            logger.warning(
                "Redis concurrent DECR failed for %s",
                provider_type.value,
                exc_info=True,
            )

    async def acquire(
        self,
        provider_type: ProviderType,
    ) -> RedisRateLimitContext:
        """Acquire rate limit with distributed checks.

        Uses the local limiter for semaphore-based concurrency,
        then layers Redis RPM and concurrency tracking on top.
        Falls back to local-only on Redis failure.
        """
        # Acquire local semaphore first
        local_ctx = await self._local.acquire(provider_type)

        # Layer on Redis RPM check
        rpm_ok = await self._check_rpm_redis(provider_type)
        if not rpm_ok:
            local_ctx.release()
            stats = self._local.get_stats_obj(provider_type)
            stats.rejected_requests += 1
            raise RateLimitExceededError(
                provider_type,
                f"Distributed RPM limit exceeded for {provider_type.value}",
            )

        # Track distributed concurrency
        await self._incr_concurrent(provider_type)

        return RedisRateLimitContext(
            local_ctx=local_ctx,
            provider_type=provider_type,
            redis_limiter=self,
        )

    def get_stats(
        self,
        provider_type: ProviderType,
    ) -> dict[str, Any]:
        """Delegate stats to local limiter."""
        return self._local.get_stats(provider_type)

    def get_all_stats(self) -> dict[str, dict[str, Any]]:
        """Delegate all stats to local limiter."""
        return self._local.get_all_stats()

    def update_config(
        self,
        provider_type: ProviderType,
        config: RateLimitConfig,
    ) -> None:
        """Delegate config update to local limiter."""
        self._local.update_config(provider_type, config)


class RedisRateLimitContext:
    """Context manager for distributed rate limit acquisition."""

    def __init__(
        self,
        local_ctx: RateLimitContext,
        provider_type: ProviderType,
        redis_limiter: RedisRateLimiter,
    ) -> None:
        self._local_ctx = local_ctx
        self._provider_type = provider_type
        self._redis_limiter = redis_limiter
        self._released = False

    async def __aenter__(self) -> RedisRateLimitContext:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        if not self._released:
            await self.release_async()

    async def release_async(self) -> None:
        """Release both local and distributed resources."""
        if self._released:
            return
        self._released = True
        self._local_ctx.release()
        await self._redis_limiter.decr_concurrent(
            self._provider_type,
        )

    def release(self) -> None:
        """Synchronous release -- local only.

        Redis decrement is best-effort; use release_async()
        when possible.
        """
        if not self._released:
            self._released = True
            self._local_ctx.release()


# Global rate limiter instance
_provider_rate_limiter: ProviderRateLimiter | None = None


def get_provider_rate_limiter() -> ProviderRateLimiter:
    """Get the global provider rate limiter."""
    global _provider_rate_limiter
    if _provider_rate_limiter is None:
        _provider_rate_limiter = ProviderRateLimiter()
    return _provider_rate_limiter


def reset_rate_limiter() -> None:
    """Reset the global rate limiter (for testing)."""
    global _provider_rate_limiter
    _provider_rate_limiter = None
