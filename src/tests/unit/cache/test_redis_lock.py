"""Unit tests for Redis distributed lock implementation."""

from unittest.mock import AsyncMock

import pytest

from src.domain.ports.services.distributed_lock_port import (
    LockHandle,
    LockInfo,
)
from src.infrastructure.adapters.secondary.cache.redis_lock import (
    RedisDistributedLock,
    RedisLockManager,
)
from src.infrastructure.adapters.secondary.cache.redis_lock_adapter import (
    RedisDistributedLockAdapter,
)


class TestRedisDistributedLock:
    """Test cases for RedisDistributedLock class."""

    @pytest.fixture
    def mock_redis(self):
        """Create a mock Redis client."""
        redis = AsyncMock()
        return redis

    @pytest.fixture
    def lock(self, mock_redis):
        """Create a RedisDistributedLock instance."""
        return RedisDistributedLock(
            redis=mock_redis,
            key="test-key",
            ttl=60,
            retry_interval=0.01,
            max_retries=3,
        )

    @pytest.mark.asyncio
    async def test_acquire_success(self, lock, mock_redis):
        """Test successful lock acquisition."""
        mock_redis.set.return_value = True  # SET NX EX succeeds

        result = await lock.acquire(blocking=False)

        assert result is True
        assert lock.acquired is True
        mock_redis.set.assert_called_once()
        call_args = mock_redis.set.call_args
        assert call_args.kwargs["nx"] is True
        assert call_args.kwargs["ex"] == 60

    @pytest.mark.asyncio
    async def test_acquire_failure_non_blocking(self, lock, mock_redis):
        """Test failed lock acquisition in non-blocking mode."""
        mock_redis.set.return_value = None  # Lock held by another process

        result = await lock.acquire(blocking=False)

        assert result is False
        assert lock.acquired is False

    @pytest.mark.asyncio
    async def test_acquire_with_retry(self, lock, mock_redis):
        """Test lock acquisition with retry."""
        # First two attempts fail, third succeeds
        mock_redis.set.side_effect = [None, None, True]

        result = await lock.acquire(blocking=True)

        assert result is True
        assert lock.acquired is True
        assert mock_redis.set.call_count == 3

    @pytest.mark.asyncio
    async def test_acquire_timeout(self, lock, mock_redis):
        """Test lock acquisition timeout."""
        mock_redis.set.return_value = None  # Always fail

        result = await lock.acquire(blocking=True, timeout=0.05)

        assert result is False
        assert lock.acquired is False

    @pytest.mark.asyncio
    async def test_release_success(self, lock, mock_redis):
        """Test successful lock release."""
        mock_redis.set.return_value = True
        mock_redis.eval.return_value = 1  # DEL succeeded

        await lock.acquire()
        result = await lock.release()

        assert result is True
        assert lock.acquired is False
        mock_redis.eval.assert_called_once()

    @pytest.mark.asyncio
    async def test_release_not_owner(self, lock, mock_redis):
        """Test release when not the owner."""
        mock_redis.set.return_value = True
        mock_redis.eval.return_value = 0  # Not owner

        await lock.acquire()
        result = await lock.release()

        assert result is False
        assert lock.acquired is False

    @pytest.mark.asyncio
    async def test_release_not_acquired(self, lock, mock_redis):
        """Test release when lock not acquired."""
        result = await lock.release()

        assert result is False
        mock_redis.eval.assert_not_called()

    @pytest.mark.asyncio
    async def test_extend_success(self, lock, mock_redis):
        """Test successful lock extension."""
        mock_redis.set.return_value = True
        mock_redis.eval.return_value = 1  # EXPIRE succeeded

        await lock.acquire()
        result = await lock.extend(additional_ttl=120)

        assert result is True
        assert mock_redis.eval.call_count == 1

    @pytest.mark.asyncio
    async def test_extend_not_owner(self, lock, mock_redis):
        """Test extend when not the owner."""
        mock_redis.set.return_value = True
        mock_redis.eval.return_value = 0  # Not owner

        await lock.acquire()
        result = await lock.extend()

        assert result is False

    @pytest.mark.asyncio
    async def test_is_locked(self, lock, mock_redis):
        """Test checking if lock is held."""
        mock_redis.get.return_value = "some-owner"

        result = await lock.is_locked()

        assert result is True

    @pytest.mark.asyncio
    async def test_is_not_locked(self, lock, mock_redis):
        """Test checking if lock is not held."""
        mock_redis.get.return_value = None

        result = await lock.is_locked()

        assert result is False

    @pytest.mark.asyncio
    async def test_context_manager(self, lock, mock_redis):
        """Test using lock as async context manager."""
        mock_redis.set.return_value = True
        mock_redis.eval.return_value = 1

        async with lock:
            assert lock.acquired is True

        assert lock.acquired is False
        mock_redis.eval.assert_called_once()

    @pytest.mark.asyncio
    async def test_time_remaining(self, lock, mock_redis):
        """Test getting remaining TTL."""
        mock_redis.ttl.return_value = 45

        result = await lock.time_remaining()

        assert result == 45

    def test_stats_tracking(self, mock_redis):
        """Test that stats are tracked correctly."""
        RedisDistributedLock.reset_stats()
        stats = RedisDistributedLock.get_stats()

        assert stats.acquisitions == 0
        assert stats.releases == 0


class TestRedisLockManager:
    """Test cases for RedisLockManager class."""

    @pytest.fixture
    def mock_redis(self):
        """Create a mock Redis client."""
        return AsyncMock()

    @pytest.fixture
    def manager(self, mock_redis):
        """Create a RedisLockManager instance."""
        return RedisLockManager(
            redis=mock_redis,
            namespace="test",
            default_ttl=60,
        )

    def test_create_lock(self, manager):
        """Test creating a lock."""
        lock = manager.create_lock("my-key")

        assert lock.key == "test:my-key"
        assert lock._ttl == 60

    def test_create_lock_with_override(self, manager):
        """Test creating a lock with TTL override."""
        lock = manager.create_lock("my-key", ttl=120)

        assert lock._ttl == 120

    @pytest.mark.asyncio
    async def test_lock_context_manager(self, manager, mock_redis):
        """Test using manager's lock context manager."""
        mock_redis.set.return_value = True
        mock_redis.eval.return_value = 1

        async with manager.lock("my-key") as lock:
            assert lock.acquired is True

        mock_redis.eval.assert_called_once()

    @pytest.mark.asyncio
    async def test_is_locked(self, manager, mock_redis):
        """Test checking if a key is locked."""
        mock_redis.get.return_value = "owner"

        result = await manager.is_locked("my-key")

        assert result is True
        mock_redis.get.assert_called_with("test:my-key")

    @pytest.mark.asyncio
    async def test_force_release(self, manager, mock_redis):
        """Test force releasing a lock."""
        mock_redis.delete.return_value = 1

        result = await manager.force_release("my-key")

        assert result is True
        mock_redis.delete.assert_called_with("test:my-key")


class TestRedisDistributedLockAdapter:
    """Test cases for RedisDistributedLockAdapter (port implementation)."""

    @pytest.fixture
    def mock_redis(self):
        """Create a mock Redis client."""
        return AsyncMock()

    @pytest.fixture
    def adapter(self, mock_redis):
        """Create a RedisDistributedLockAdapter instance."""
        return RedisDistributedLockAdapter(
            redis=mock_redis,
            namespace="test:lock",
            default_ttl=60,
        )

    @pytest.mark.asyncio
    async def test_acquire_returns_handle(self, adapter, mock_redis):
        """Test that acquire returns a LockHandle."""
        mock_redis.set.return_value = True

        handle = await adapter.acquire("my-resource")

        assert handle is not None
        assert isinstance(handle, LockHandle)
        assert handle.key == "my-resource"
        assert handle.ttl == 60

    @pytest.mark.asyncio
    async def test_acquire_returns_none_on_failure(self, adapter, mock_redis):
        """Test that acquire returns None on failure."""
        mock_redis.set.return_value = None

        handle = await adapter.acquire("my-resource", blocking=False)

        assert handle is None

    @pytest.mark.asyncio
    async def test_release_with_handle(self, adapter, mock_redis):
        """Test releasing with a handle."""
        mock_redis.set.return_value = True
        mock_redis.eval.return_value = 1

        handle = await adapter.acquire("my-resource")
        result = await adapter.release(handle)

        assert result is True

    @pytest.mark.asyncio
    async def test_extend_with_handle(self, adapter, mock_redis):
        """Test extending with a handle."""
        mock_redis.set.return_value = True
        mock_redis.eval.return_value = 1

        handle = await adapter.acquire("my-resource")
        result = await adapter.extend(handle, additional_ttl=120)

        assert result is True

    @pytest.mark.asyncio
    async def test_is_locked(self, adapter, mock_redis):
        """Test checking if resource is locked."""
        mock_redis.get.return_value = "owner"

        result = await adapter.is_locked("my-resource")

        assert result is True

    @pytest.mark.asyncio
    async def test_get_lock_info(self, adapter, mock_redis):
        """Test getting lock info."""
        mock_redis.get.return_value = "owner-token"
        mock_redis.ttl.return_value = 45

        info = await adapter.get_lock_info("my-resource")

        assert isinstance(info, LockInfo)
        assert info.key == "my-resource"
        assert info.owner == "owner-token"
        assert info.ttl_remaining == 45
        assert info.is_locked is True

    @pytest.mark.asyncio
    async def test_get_lock_info_not_locked(self, adapter, mock_redis):
        """Test getting lock info when not locked."""
        mock_redis.get.return_value = None
        mock_redis.ttl.return_value = -2

        info = await adapter.get_lock_info("my-resource")

        assert info.is_locked is False
        assert info.owner is None

    @pytest.mark.asyncio
    async def test_acquire_lock_context_manager(self, adapter, mock_redis):
        """Test using acquire_lock context manager."""
        mock_redis.set.return_value = True
        mock_redis.eval.return_value = 1

        async with adapter.acquire_lock("my-resource") as lock:
            assert lock.acquired is True
            assert lock.handle is not None

        # Lock should be released
        mock_redis.eval.assert_called()

    @pytest.mark.asyncio
    async def test_cleanup(self, adapter, mock_redis):
        """Test cleanup releases all locks."""
        mock_redis.set.return_value = True
        mock_redis.eval.return_value = 1

        # Acquire multiple locks
        await adapter.acquire("resource-1")
        await adapter.acquire("resource-2")

        # Cleanup
        await adapter.cleanup()

        # Should have released both
        assert mock_redis.eval.call_count == 2


class TestConcurrentLocking:
    """Test concurrent lock scenarios."""

    @pytest.fixture
    def mock_redis(self):
        """Create a mock Redis client with realistic behavior."""
        redis = AsyncMock()
        # Track lock state
        redis._lock_owner = None

        async def set_lock(key, value, nx=False, ex=None):
            if nx and redis._lock_owner is not None:
                return None  # Lock held
            redis._lock_owner = value
            return True

        async def eval_script(script, keys_count, *args):
            if "DEL" in script:
                if redis._lock_owner == args[1]:  # Owner matches
                    redis._lock_owner = None
                    return 1
                return 0
            if "EXPIRE" in script:
                if redis._lock_owner == args[1]:
                    return 1
                return 0
            return 0

        async def get_lock(key):
            return redis._lock_owner

        redis.set = set_lock
        redis.eval = eval_script
        redis.get = get_lock

        return redis

    @pytest.mark.asyncio
    async def test_sequential_acquire_release(self, mock_redis):
        """Test sequential acquire and release."""
        manager = RedisLockManager(mock_redis, "test")

        async with manager.lock("resource") as lock1:
            assert lock1.acquired is True

            # Try to acquire same lock (should fail)
            lock2 = manager.create_lock("resource")
            result = await lock2.acquire(blocking=False)
            assert result is False

        # After release, should be able to acquire
        async with manager.lock("resource") as lock3:
            assert lock3.acquired is True

    @pytest.mark.asyncio
    async def test_different_resources(self, mock_redis):
        """Test locking different resources."""
        # Each resource has its own lock state
        redis1 = AsyncMock()
        redis1.set.return_value = True
        redis1.eval.return_value = 1

        manager = RedisLockManager(redis1, "test")

        lock1 = manager.create_lock("resource-1")
        lock2 = manager.create_lock("resource-2")

        await lock1.acquire()
        await lock2.acquire()

        assert lock1.acquired is True
        assert lock2.acquired is True

        await lock1.release()
        await lock2.release()
