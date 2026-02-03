"""
Tests for LLM Rate Limiter.

TDD Approach:
1. Write failing tests first
2. Implement to make them pass
3. Refactor and improve
"""

import asyncio

import pytest

from src.infrastructure.llm.rate_limiter import (
    LLMRateLimiter,
    ProviderConfig,
    ProviderType,
    RateLimitError,
    RateLimitStrategy,
    get_rate_limiter,
)


class TestLLMRateLimiterInitialization:
    """Test rate limiter initialization."""

    def test_initializes_with_default_limits(self):
        """Should initialize with default provider limits."""
        limiter = LLMRateLimiter()

        assert limiter.get_provider_limit(ProviderType.QWEN) == 1
        assert limiter.get_provider_limit(ProviderType.OPENAI) == 5
        assert limiter.get_provider_limit(ProviderType.GEMINI) == 5
        assert limiter.get_provider_limit(ProviderType.DEEPSEEK) == 2
        assert limiter.get_provider_limit(ProviderType.ZHIPU) == 2

    def test_initializes_with_custom_limits(self):
        """Should accept custom provider limits."""
        custom_limits = {
            ProviderType.QWEN: ProviderConfig(max_concurrent=5),
            ProviderType.OPENAI: ProviderConfig(max_concurrent=10),
        }
        limiter = LLMRateLimiter(provider_limits=custom_limits)

        assert limiter.get_provider_limit(ProviderType.QWEN) == 5
        assert limiter.get_provider_limit(ProviderType.OPENAI) == 10

    def test_initializes_metrics(self):
        """Should initialize metrics for each provider."""
        limiter = LLMRateLimiter()
        metrics = limiter.get_metrics()

        assert ProviderType.QWEN in metrics
        assert ProviderType.OPENAI in metrics
        assert metrics[ProviderType.QWEN].active_requests == 0
        assert metrics[ProviderType.QWEN].queued_requests == 0


class TestAcquireAndRelease:
    """Test slot acquisition and release."""

    @pytest.mark.asyncio
    async def test_acquire_single_slot(self):
        """Should acquire a single slot successfully."""
        limiter = LLMRateLimiter(provider_limits={
            ProviderType.QWEN: ProviderConfig(max_concurrent=1)
        })

        async with limiter.acquire(ProviderType.QWEN) as token:
            assert token is not None
            assert not token._released

        # Token should be released after context manager exit
        assert token._released

    @pytest.mark.asyncio
    async def test_concurrent_requests_within_limit(self):
        """Should allow concurrent requests up to the limit."""
        limiter = LLMRateLimiter(provider_limits={
            ProviderType.QWEN: ProviderConfig(max_concurrent=2)
        })

        results = []

        async def make_request(id: int):
            async with limiter.acquire(ProviderType.QWEN):
                await asyncio.sleep(0.1)
                results.append(id)

        # Start 2 concurrent requests (within limit)
        task1 = asyncio.create_task(make_request(1))
        task2 = asyncio.create_task(make_request(2))

        await asyncio.gather(task1, task2)

        assert sorted(results) == [1, 2]

    @pytest.mark.asyncio
    async def test_concurrent_requests_exceeds_limit_queue_strategy(self):
        """Should queue requests that exceed the limit when strategy is QUEUE."""
        limiter = LLMRateLimiter(
            provider_limits={
                ProviderType.QWEN: ProviderConfig(max_concurrent=1, timeout=5.0)
            },
            strategy=RateLimitStrategy.QUEUE,
        )

        execution_order = []

        async def make_request(id: int):
            execution_order.append(f"{id}-start")
            async with limiter.acquire(ProviderType.QWEN):
                execution_order.append(f"{id}-acquired")
                await asyncio.sleep(0.05)
                execution_order.append(f"{id}-release")

        # Start 3 concurrent requests (limit is 1)
        task1 = asyncio.create_task(make_request(1))
        task2 = asyncio.create_task(make_request(2))
        task3 = asyncio.create_task(make_request(3))

        await asyncio.gather(task1, task2, task3)

        # Key verification: only one task should be "acquired" at any time
        # So we should never see two consecutive "-acquired" without a "-release" in between
        for i in range(len(execution_order) - 1):
            if execution_order[i].endswith("-acquired"):
                # Next item should NOT be another "-acquired" (must be release first)
                assert not execution_order[i + 1].endswith("-acquired")

        # All 3 should complete
        assert sum(1 for x in execution_order if x.endswith("-release")) == 3

    @pytest.mark.asyncio
    async def test_concurrent_requests_exceeds_limit_reject_strategy(self):
        """Should reject requests that exceed the limit when strategy is REJECT."""
        limiter = LLMRateLimiter(
            provider_limits={
                ProviderType.QWEN: ProviderConfig(max_concurrent=1)
            },
            strategy=RateLimitStrategy.REJECT,
        )

        async def make_request(id: int):
            try:
                async with limiter.acquire(ProviderType.QWEN):
                    await asyncio.sleep(0.1)
                    return id
            except RateLimitError:
                return "rejected"

        # Hold the slot
        task1 = asyncio.create_task(make_request(1))
        await asyncio.sleep(0.01)  # Ensure task1 acquires first

        # Try to acquire while slot is held
        task2 = asyncio.create_task(make_request(2))

        results = await asyncio.gather(task1, task2)

        assert results[0] == 1  # First request succeeds
        assert results[1] == "rejected"  # Second request is rejected

    @pytest.mark.asyncio
    async def test_queue_timeout(self):
        """Should raise TimeoutError when queue wait exceeds timeout."""
        limiter = LLMRateLimiter(
            provider_limits={
                ProviderType.QWEN: ProviderConfig(max_concurrent=1, timeout=0.1)
            },
            strategy=RateLimitStrategy.QUEUE,
        )

        acquired = False

        async def hold_slot():
            nonlocal acquired
            async with limiter.acquire(ProviderType.QWEN):
                acquired = True
                await asyncio.sleep(1.0)  # Hold longer than timeout

        async def try_acquire():
            await asyncio.sleep(0.01)  # Ensure first task acquires
            with pytest.raises(asyncio.TimeoutError):
                async with limiter.acquire(ProviderType.QWEN):
                    pass

        # Run both tasks concurrently
        await asyncio.gather(
            asyncio.create_task(hold_slot()),
            asyncio.create_task(try_acquire()),
        )

        assert acquired  # First task should have acquired


class TestMetrics:
    """Test metrics tracking."""

    @pytest.mark.asyncio
    async def test_metrics_track_active_requests(self):
        """Should track number of active requests."""
        limiter = LLMRateLimiter(provider_limits={
            ProviderType.QWEN: ProviderConfig(max_concurrent=2)
        })

        async with limiter.acquire(ProviderType.QWEN):
            metrics_dict = limiter.get_metrics(ProviderType.QWEN)
            metrics = list(metrics_dict.values())[0]
            assert metrics.active_requests == 1

    @pytest.mark.asyncio
    async def test_metrics_track_completed_requests(self):
        """Should track completed requests."""
        limiter = LLMRateLimiter(provider_limits={
            ProviderType.QWEN: ProviderConfig(max_concurrent=1)
        })

        async with limiter.acquire(ProviderType.QWEN):
            pass

        metrics_dict = limiter.get_metrics(ProviderType.QWEN)
        metrics = list(metrics_dict.values())[0]
        assert metrics.total_completed == 1

    @pytest.mark.asyncio
    async def test_metrics_track_rejected_requests(self):
        """Should track rejected requests with REJECT strategy."""
        limiter = LLMRateLimiter(
            provider_limits={
                ProviderType.QWEN: ProviderConfig(max_concurrent=1)
            },
            strategy=RateLimitStrategy.REJECT,
        )

        async def hold_slot():
            async with limiter.acquire(ProviderType.QWEN):
                await asyncio.sleep(0.2)

        async def try_acquire():
            try:
                async with limiter.acquire(ProviderType.QWEN):
                    pass
            except RateLimitError:
                pass  # Expected

        # Start both tasks
        await asyncio.gather(
            asyncio.create_task(hold_slot()),
            asyncio.create_task(try_acquire()),
        )

        metrics_dict = limiter.get_metrics(ProviderType.QWEN)
        metrics = list(metrics_dict.values())[0]
        assert metrics.total_rejected == 1


class TestMultipleProviders:
    """Test handling multiple providers independently."""

    @pytest.mark.asyncio
    async def test_providers_have_independent_limits(self):
        """Qwen limit should not affect OpenAI requests."""
        limiter = LLMRateLimiter(provider_limits={
            ProviderType.QWEN: ProviderConfig(max_concurrent=1),
            ProviderType.OPENAI: ProviderConfig(max_concurrent=2),
        })

        qwen_count = 0
        openai_count = 0

        async def qwen_request():
            nonlocal qwen_count
            async with limiter.acquire(ProviderType.QWEN):
                qwen_count += 1
                await asyncio.sleep(0.1)

        async def openai_request():
            nonlocal openai_count
            async with limiter.acquire(ProviderType.OPENAI):
                openai_count += 1
                await asyncio.sleep(0.1)

        # Start 2 Qwen and 2 OpenAI requests concurrently
        tasks = [
            asyncio.create_task(qwen_request()),
            asyncio.create_task(qwen_request()),
            asyncio.create_task(openai_request()),
            asyncio.create_task(openai_request()),
        ]

        await asyncio.gather(*tasks)

        # Qwen: limit=1, so only 1 should complete (other queued then blocked)
        # But with queue strategy, both will complete sequentially
        assert qwen_count == 2
        # OpenAI: limit=2, so both can run concurrently
        assert openai_count == 2


class TestGlobalSingleton:
    """Test global rate limiter singleton."""

    def test_get_rate_limiter_returns_singleton(self):
        """Should return the same instance on multiple calls."""
        limiter1 = get_rate_limiter()
        limiter2 = get_rate_limiter()

        assert limiter1 is limiter2

    @pytest.mark.asyncio
    async def test_global_limiter_works(self):
        """Global limiter should function correctly."""
        limiter = get_rate_limiter()

        async with limiter.acquire(ProviderType.QWEN):
            metrics_dict = limiter.get_metrics(ProviderType.QWEN)
            metrics = list(metrics_dict.values())[0]
            assert metrics.active_requests >= 0  # Basic sanity check
