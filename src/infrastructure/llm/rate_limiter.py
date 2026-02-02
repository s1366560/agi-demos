"""
LLM Rate Limiter - Centralized concurrency control for LLM API calls.

Prevents exceeding provider-specific concurrent request limits.

Features:
- Per-provider semaphores
- Queue or reject strategy
- Timeout protection
- Metrics tracking
"""

import asyncio
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class RateLimitStrategy(str, Enum):
    """Rate limiting strategy when limit is reached."""

    REJECT = "reject"  # Immediately reject with RateLimitError
    QUEUE = "queue"  # Wait in queue until slot available


class ProviderType(str, Enum):
    """LLM provider types."""

    QWEN = "qwen"
    OPENAI = "openai"
    GEMINI = "gemini"
    DEEPSEEK = "deepseek"
    ZHIPU = "zhipu"
    KIMI = "kimi"
    LITELLM = "litellm"


@dataclass
class ProviderConfig:
    """Rate limit configuration for a provider."""

    max_concurrent: int  # Maximum concurrent requests
    timeout: float = 300.0  # Max wait time in queue (seconds)


# Default provider limits (can be overridden via environment)
DEFAULT_PROVIDER_LIMITS: Dict[ProviderType, ProviderConfig] = {
    ProviderType.QWEN: ProviderConfig(max_concurrent=10, timeout=300.0),  # Increased for HITL
    ProviderType.OPENAI: ProviderConfig(max_concurrent=10, timeout=300.0),
    ProviderType.GEMINI: ProviderConfig(max_concurrent=10, timeout=300.0),
    ProviderType.DEEPSEEK: ProviderConfig(max_concurrent=10, timeout=300.0),
    ProviderType.ZHIPU: ProviderConfig(max_concurrent=10, timeout=300.0),
    ProviderType.KIMI: ProviderConfig(max_concurrent=10, timeout=300.0),
    ProviderType.LITELLM: ProviderConfig(max_concurrent=10, timeout=300.0),  # Increased for HITL
}


@dataclass
class RateLimiterMetrics:
    """Metrics for rate limiter monitoring."""

    active_requests: int = 0
    queued_requests: int = 0
    total_accepted: int = 0
    total_rejected: int = 0
    total_completed: int = 0


class RateLimitError(Exception):
    """Raised when request is rejected due to rate limit."""

    def __init__(self, provider: ProviderType, message: str):
        self.provider = provider
        super().__init__(message)


class LLMRateLimiter:
    """
    Centralized rate limiter for LLM API calls.

    Usage:
        limiter = LLMRateLimiter()

        async with limiter.acquire(ProviderType.QWEN):
            # Make LLM call
            response = await qwen_client.generate(...)
    """

    def __init__(
        self,
        provider_limits: Optional[Dict[ProviderType, ProviderConfig]] = None,
        strategy: RateLimitStrategy = RateLimitStrategy.QUEUE,
    ):
        """
        Initialize rate limiter.

        Args:
            provider_limits: Per-provider concurrency limits
            strategy: What to do when limit is reached
        """
        self._limits = provider_limits or DEFAULT_PROVIDER_LIMITS.copy()
        self._strategy = strategy
        self._semaphores: Dict[ProviderType, asyncio.Semaphore] = {}
        self._metrics: Dict[ProviderType, RateLimiterMetrics] = {}
        self._lock = asyncio.Lock()
        self._waiters: Dict[ProviderType, int] = {}  # Track waiting requests

        # Initialize semaphores and metrics for each provider
        for provider, config in self._limits.items():
            self._semaphores[provider] = asyncio.Semaphore(config.max_concurrent)
            self._metrics[provider] = RateLimiterMetrics()
            self._waiters[provider] = 0

    def acquire(self, provider: ProviderType) -> "RateLimiterToken":
        """
        Acquire a slot for the provider.

        Args:
            provider: LLM provider type

        Returns:
            RateLimiterToken that acts as an async context manager

        Raises:
            RateLimitError: If strategy is REJECT and limit is reached
            asyncio.TimeoutError: If queue wait exceeds timeout (during __aenter__)
        """
        if provider not in self._semaphores:
            # Default to limit 1 for unknown providers
            self._semaphores[provider] = asyncio.Semaphore(1)
            self._metrics[provider] = RateLimiterMetrics()
            self._waiters[provider] = 0
            self._limits[provider] = ProviderConfig(max_concurrent=1)

        return RateLimiterToken(self, provider)

    def _update_queued_metrics(self):
        """Update queued metrics based on waiters count."""
        for provider, count in self._waiters.items():
            self._metrics[provider].queued_requests = count

    async def _release(self, provider: ProviderType):
        """Internal release method."""
        semaphore = self._semaphores[provider]
        metrics = self._metrics[provider]

        semaphore.release()

        async with self._lock:
            metrics.active_requests = max(0, metrics.active_requests - 1)
            metrics.total_completed += 1

    def get_metrics(self, provider: Optional[ProviderType] = None) -> Dict[str, RateLimiterMetrics]:
        """
        Get metrics for one or all providers.

        Args:
            provider: If specified, return metrics for this provider only.
                     Otherwise return metrics for all providers.

        Returns:
            Dictionary mapping provider names to their metrics
        """
        if provider:
            # Return dict with single provider (to maintain consistent API)
            # The value can be accessed with .values()[0] or by key
            return {provider.value: self._metrics.get(provider, RateLimiterMetrics())}

        return {p.value: m for p, m in self._metrics.items()}

    def get_provider_limit(self, provider: ProviderType) -> int:
        """Get the concurrency limit for a provider."""
        if provider in self._limits:
            return self._limits[provider].max_concurrent
        return 1  # Default limit


class RateLimiterToken:
    """Token returned by acquire(), acts as async context manager."""

    def __init__(self, limiter: LLMRateLimiter, provider: ProviderType):
        self._limiter = limiter
        self._provider = provider
        self._released = False
        self._acquired = False

    async def __aenter__(self):
        """Acquire the semaphore when entering context."""
        if self._acquired:
            return self

        semaphore = self._limiter._semaphores[self._provider]
        config = self._limiter._limits[self._provider]
        metrics = self._limiter._metrics[self._provider]

        # Check if we can acquire immediately
        if semaphore.locked():
            # Semaphore is at capacity
            if self._limiter._strategy == RateLimitStrategy.REJECT:
                metrics.total_rejected += 1
                raise RateLimitError(
                    self._provider,
                    f"Rate limit exceeded for {self._provider.value}. "
                    f"Max concurrent: {config.max_concurrent}",
                )
            else:  # QUEUE strategy
                # Wait with timeout
                async with self._limiter._lock:
                    self._limiter._waiters[self._provider] += 1
                    self._limiter._update_queued_metrics()

                try:
                    await asyncio.wait_for(semaphore.acquire(), timeout=config.timeout)
                except asyncio.TimeoutError:
                    metrics.total_rejected += 1
                    raise
                finally:
                    async with self._limiter._lock:
                        self._limiter._waiters[self._provider] -= 1
                        self._limiter._update_queued_metrics()
        else:
            # Acquire immediately
            await semaphore.acquire()

        self._acquired = True

        # Update metrics
        async with self._limiter._lock:
            metrics.total_accepted += 1
            metrics.active_requests += 1

        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.release()

    async def release(self):
        """Release the slot back to the pool."""
        if self._released or not self._acquired:
            return
        self._released = True
        await self._limiter._release(self._provider)


# Global singleton
_global_limiter: Optional[LLMRateLimiter] = None


def get_rate_limiter() -> LLMRateLimiter:
    """Get the global rate limiter instance."""
    global _global_limiter
    if _global_limiter is None:
        _global_limiter = LLMRateLimiter()
    return _global_limiter
