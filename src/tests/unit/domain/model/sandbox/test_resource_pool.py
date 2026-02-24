"""Tests for Resource Pool Manager.

Tests the pool-based resource management system for sandbox resources.
"""

import asyncio

import pytest

from src.domain.model.sandbox.exceptions import (
    SandboxResourceError,
    SandboxTimeoutError,
)
from src.domain.model.sandbox.resource_pool import (
    PoolConfig,
    ResourcePool,
)


class TestPoolConfig:
    """Tests for PoolConfig."""

    def test_default_config(self) -> None:
        """Should have default values."""
        config = PoolConfig()
        assert config.min_size == 0
        assert config.max_size == 10
        assert config.acquire_timeout == 30.0

    def test_custom_config(self) -> None:
        """Should accept custom configuration."""
        config = PoolConfig(
            min_size=2,
            max_size=20,
            acquire_timeout=60.0,
        )
        assert config.min_size == 2
        assert config.max_size == 20
        assert config.acquire_timeout == 60.0

    def test_invalid_min_size(self) -> None:
        """Should raise error for negative min_size."""
        with pytest.raises(ValueError, match="min_size"):
            PoolConfig(min_size=-1)

    def test_invalid_max_size(self) -> None:
        """Should raise error for max_size < 1."""
        with pytest.raises(ValueError, match="max_size"):
            PoolConfig(max_size=0)

    def test_min_exceeds_max(self) -> None:
        """Should raise error when min_size > max_size."""
        with pytest.raises(ValueError, match="min_size.*max_size"):
            PoolConfig(min_size=10, max_size=5)

    def test_invalid_acquire_timeout(self) -> None:
        """Should raise error for non-positive timeout."""
        with pytest.raises(ValueError, match="acquire_timeout"):
            PoolConfig(acquire_timeout=0)


class TestResourcePool:
    """Tests for ResourcePool."""

    @pytest.mark.asyncio
    async def test_acquire_and_release(self) -> None:
        """Should acquire and release resources."""
        pool = ResourcePool(factory=lambda: {"data": "value"})

        rid = await pool.acquire()
        assert rid is not None
        assert pool.in_use_count == 1
        assert pool.available_count == 0

        await pool.release(rid)
        assert pool.in_use_count == 0
        # After release, the resource is still in pool and available
        assert pool.available_count == 1

    @pytest.mark.asyncio
    async def test_acquire_specific_resource(self) -> None:
        """Should acquire specific resource by ID."""
        pool = ResourcePool(factory=lambda: {"data": "value"})

        # First create a resource
        rid1 = await pool.acquire("specific-123")
        assert rid1 == "specific-123"

        # Release it
        await pool.release(rid1)

        # Acquire the same resource again
        rid2 = await pool.acquire("specific-123")
        assert rid2 == "specific-123"

    @pytest.mark.asyncio
    async def test_acquire_in_use_resource_raises_error(self) -> None:
        """Should raise error when acquiring resource in use."""
        pool = ResourcePool(factory=lambda: {"data": "value"})

        _rid = await pool.acquire("specific-123")

        with pytest.raises(SandboxResourceError, match="already in use"):
            await pool.acquire("specific-123")

    @pytest.mark.asyncio
    async def test_acquire_blocks_when_pool_full(self) -> None:
        """Should block when pool is at max capacity."""
        pool = ResourcePool(
            factory=lambda: {"data": "value"},
            config=PoolConfig(max_size=2),
        )

        # Acquire all resources
        _rid1 = await pool.acquire()
        _rid2 = await pool.acquire()

        assert pool.size == 2
        assert pool.in_use_count == 2

        # This should block until a resource is released
        acquire_task = asyncio.create_task(pool.acquire(timeout=1.0))

        # Wait a bit
        await asyncio.sleep(0.1)

        # Release one resource
        await pool.release(_rid1)

        # Now the acquire should complete
        rid3 = await acquire_task
        assert rid3 is not None

    @pytest.mark.asyncio
    async def test_acquire_timeout(self) -> None:
        """Should timeout when waiting for resource."""
        pool = ResourcePool(
            factory=lambda: {"data": "value"},
            config=PoolConfig(max_size=1),
        )

        # Acquire the only resource
        _rid = await pool.acquire()

        # Try to acquire another - should timeout
        with pytest.raises(SandboxTimeoutError, match="timeout"):
            await pool.acquire(timeout=0.1)

    @pytest.mark.asyncio
    async def test_pool_at_capacity_error(self) -> None:
        """Should raise error when trying to acquire specific ID at capacity."""
        pool = ResourcePool(
            factory=lambda: {"data": "value"},
            config=PoolConfig(max_size=1),
        )

        # Fill the pool
        _rid = await pool.acquire()

        # Try to create new specific resource - should fail
        with pytest.raises(SandboxResourceError, match="max capacity"):
            await pool.acquire("new-resource")

    @pytest.mark.asyncio
    async def test_remove_resource(self) -> None:
        """Should remove a resource from the pool."""
        cleanup_called = []

        def cleanup(r):
            cleanup_called.append(r)

        pool = ResourcePool(
            factory=lambda: {"data": "value"},
            cleanup=cleanup,
        )

        rid = await pool.acquire()
        await pool.release(rid)

        assert pool.available_count == 1

        await pool.remove(rid)

        assert pool.available_count == 0
        assert len(cleanup_called) == 1

    @pytest.mark.asyncio
    async def test_remove_in_use_resource(self) -> None:
        """Should remove resource even if in use."""
        cleanup_called = []

        def cleanup(r):
            cleanup_called.append(r)

        pool = ResourcePool(
            factory=lambda: {"data": "value"},
            cleanup=cleanup,
        )

        rid = await pool.acquire()
        assert pool.in_use_count == 1

        await pool.remove(rid)

        # Resource is removed from pool (both in_use and resources dict)
        assert pool.in_use_count == 0
        assert pool.size == 0
        assert len(cleanup_called) == 1

    @pytest.mark.asyncio
    async def test_close_pool(self) -> None:
        """Should close pool and cleanup all resources."""
        cleanup_called = []

        def cleanup(r):
            cleanup_called.append(r)

        pool = ResourcePool(
            factory=lambda: {"data": "value"},
            cleanup=cleanup,
        )

        _rid1 = await pool.acquire()
        _rid2 = await pool.acquire()

        await pool.close()

        assert pool.is_closed
        assert pool.size == 0
        assert len(cleanup_called) == 2

    @pytest.mark.asyncio
    async def test_acquire_after_close_raises_error(self) -> None:
        """Should raise error when acquiring from closed pool."""
        pool = ResourcePool(factory=lambda: {"data": "value"})

        await pool.close()

        with pytest.raises(SandboxResourceError, match="closed"):
            await pool.acquire()

    @pytest.mark.asyncio
    async def test_double_close_is_idempotent(self) -> None:
        """Should handle double close gracefully."""
        pool = ResourcePool(factory=lambda: {"data": "value"})

        await pool.close()
        await pool.close()  # Should not raise

        assert pool.is_closed

    @pytest.mark.asyncio
    async def test_resource_context_manager(self) -> None:
        """Should automatically release with context manager."""
        pool = ResourcePool(factory=lambda: {"data": "value"})

        async with pool.resource() as _rid:
            assert pool.in_use_count == 1

        assert pool.in_use_count == 0
        assert pool.available_count == 1

    @pytest.mark.asyncio
    async def test_validate_unhealthy_resource(self) -> None:
        """Should recreate unhealthy resources."""
        create_count = [0]

        def factory():
            create_count[0] += 1
            return {"data": "value", "id": create_count[0]}

        healthy = [True]

        def validate(r):
            return healthy[0]

        pool = ResourcePool(
            factory=factory,
            validate=validate,
        )

        # Create and release a resource
        rid1 = await pool.acquire()
        initial_id = pool.get_resource(rid1)["id"]
        await pool.release(rid1)

        # Mark as unhealthy
        healthy[0] = False

        # Acquire again - should validate old resource, fail, and create new one
        rid2 = await pool.acquire()
        # ID will be different since old resource was removed
        assert rid2 != rid1  # Different ID because unhealthy resource was removed
        assert pool.get_resource(rid2)["id"] != initial_id  # New resource

    @pytest.mark.asyncio
    async def test_get_resource(self) -> None:
        """Should get resource without acquiring."""
        pool = ResourcePool(factory=lambda: {"data": "value"})

        rid = await pool.acquire()
        await pool.release(rid)

        resource = pool.get_resource(rid)
        assert resource is not None
        assert resource["data"] == "value"

    @pytest.mark.asyncio
    async def test_get_nonexistent_resource(self) -> None:
        """Should return None for nonexistent resource."""
        pool = ResourcePool(factory=lambda: {"data": "value"})

        resource = pool.get_resource("nonexistent")
        assert resource is None

    @pytest.mark.asyncio
    async def test_release_nonexistent_resource(self) -> None:
        """Should handle releasing nonexistent resource gracefully."""
        pool = ResourcePool(factory=lambda: {"data": "value"})

        # Should not raise
        await pool.release("nonexistent")

    @pytest.mark.asyncio
    async def test_cleanup_exception_logged(self) -> None:
        """Should log cleanup exceptions without raising."""

        def bad_cleanup(r):
            raise RuntimeError("Cleanup failed!")

        pool = ResourcePool(
            factory=lambda: {"data": "value"},
            cleanup=bad_cleanup,
        )

        rid = await pool.acquire()
        await pool.release(rid)

        # Should not raise despite cleanup error
        await pool.remove(rid)

        assert pool.available_count == 0


class TestResourcePoolConcurrency:
    """Tests for concurrent access."""

    @pytest.mark.asyncio
    async def test_concurrent_acquires(self) -> None:
        """Should handle concurrent acquire requests."""
        pool = ResourcePool(
            factory=lambda: {"data": "value"},
            config=PoolConfig(max_size=5),
        )

        # Acquire 3 resources concurrently
        results = await asyncio.gather(
            pool.acquire(),
            pool.acquire(),
            pool.acquire(),
        )

        assert len(set(results)) == 3  # All unique
        assert pool.in_use_count == 3

    @pytest.mark.asyncio
    async def test_concurrent_acquire_release(self) -> None:
        """Should handle concurrent acquire and release."""
        pool = ResourcePool(
            factory=lambda: {"data": "value"},
            config=PoolConfig(max_size=2),
        )

        async def worker():
            async with pool.resource():
                await asyncio.sleep(0.1)

        # Run 5 workers but only 2 can use pool at once
        await asyncio.gather(*[worker() for _ in range(5)])

        assert pool.size <= 2
