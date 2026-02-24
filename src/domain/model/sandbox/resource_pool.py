"""Resource Pool Manager for sandbox resources.

This module provides a pool-based resource management system for sandbox
resources like ports, containers, and connections to prevent resource leaks
and enable efficient reuse.
"""

import asyncio
import logging
from collections.abc import Callable
from contextlib import asynccontextmanager
from typing import TypeVar

from src.domain.model.sandbox.exceptions import (
    SandboxResourceError,
    SandboxTimeoutError,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")


class PoolConfig:
    """Configuration for a resource pool."""

    def __init__(
        self,
        min_size: int = 0,
        max_size: int = 10,
        acquire_timeout: float = 30.0,
        idle_timeout: float = 300.0,
        max_lifetime: float = 3600.0,
    ) -> None:
        """Initialize pool configuration.

        Args:
            min_size: Minimum number of resources to maintain
            max_size: Maximum number of resources allowed
            acquire_timeout: Seconds to wait for resource acquisition
            idle_timeout: Seconds before idle resources are cleaned up
            max_lifetime: Maximum seconds a resource can exist

        Raises:
            ValueError: If configuration is invalid
        """
        if min_size < 0:
            raise ValueError(f"min_size must be >= 0, got {min_size}")
        if max_size < 1:
            raise ValueError(f"max_size must be >= 1, got {max_size}")
        if min_size > max_size:
            raise ValueError(f"min_size ({min_size}) cannot exceed max_size ({max_size})")
        if acquire_timeout <= 0:
            raise ValueError(f"acquire_timeout must be > 0, got {acquire_timeout}")

        self.min_size = min_size
        self.max_size = max_size
        self.acquire_timeout = acquire_timeout
        self.idle_timeout = idle_timeout
        self.max_lifetime = max_lifetime


class ResourcePool[T]:
    """
    Generic resource pool for managing reusable resources.

    Provides connection pooling semantics for any type of resource,
    with automatic cleanup and timeout handling.
    """

    def __init__(
        self,
        factory: Callable[[], T],
        config: PoolConfig | None = None,
        cleanup: Callable[[T], None] | None = None,
        validate: Callable[[T], bool] | None = None,
        pool_name: str = "resource",
    ) -> None:
        """Initialize the resource pool.

        Args:
            factory: Function that creates new resources
            config: Pool configuration
            cleanup: Optional function to cleanup resources when removed
            validate: Optional function to validate if resource is healthy
            pool_name: Name for logging/debugging
        """
        self._factory = factory
        self._config = config or PoolConfig()
        self._cleanup = cleanup
        self._validate = validate or (lambda r: True)
        self._pool_name = pool_name

        self._resources: dict[str, T] = {}  # All resources by ID
        self._available: set[str] = set()   # IDs of available resources
        self._in_use: set[str] = set()      # IDs of in-use resources
        self._created_at: dict[str, float] = {}
        self._last_used: dict[str, float] = {}
        self._lock = asyncio.Lock()
        self._cond = asyncio.Condition(self._lock)
        self._is_closed = False

    async def acquire(self, resource_id: str | None = None, timeout: float | None = None) -> str:
        """
        Acquire a resource from the pool.

        Args:
            resource_id: Optional specific resource ID to acquire
            timeout: Override default acquire timeout

        Returns:
            The resource ID that was acquired

        Raises:
            SandboxResourceError: If pool is at capacity
            SandboxTimeoutError: If acquisition times out
        """
        timeout = timeout or self._config.acquire_timeout

        async with self._cond:
            if self._is_closed:
                raise SandboxResourceError(
                    f"Pool '{self._pool_name}' is closed",
                    resource_type="pool",
                )

            # If specific resource requested, try to find it
            if resource_id:
                if resource_id in self._available:
                    self._available.remove(resource_id)
                    self._in_use.add(resource_id)
                    self._last_used[resource_id] = asyncio.get_event_loop().time()
                    return resource_id
                if resource_id in self._in_use:
                    raise SandboxResourceError(
                        f"Resource '{resource_id}' is already in use",
                        resource_type="resource",
                    )
                # Resource doesn't exist, create it
                if len(self._resources) >= self._config.max_size:
                    raise SandboxResourceError(
                        f"Pool '{self._pool_name}' is at max capacity",
                        resource_type="pool",
                    )
                return await self._create_resource(resource_id)

            # Wait for available resource or create new one
            deadline = asyncio.get_event_loop().time() + timeout
            while True:
                # Try to get an available resource
                if self._available:
                    rid = next(iter(self._available))
                    resource = self._resources.get(rid)
                    self._available.remove(rid)
                    # Validate resource
                    if resource and self._validate(resource):
                        self._in_use.add(rid)
                        self._last_used[rid] = asyncio.get_event_loop().time()
                        return rid
                    # Resource failed validation, cleanup and remove
                    self._remove_resource_metadata(rid)
                    if resource and self._cleanup:
                        try:
                            self._cleanup(resource)
                        except Exception as e:
                            logger.warning(f"Cleanup failed for {rid}: {e}")
                    # Also remove from resources dict
                    self._resources.pop(rid, None)

                # Check if we can create a new resource
                if len(self._resources) < self._config.max_size:
                    return await self._create_resource()

                # Wait for a resource to become available
                remaining = deadline - asyncio.get_event_loop().time()
                if remaining <= 0:
                    raise SandboxTimeoutError(
                        f"Acquire timeout for pool '{self._pool_name}'",
                        timeout_seconds=timeout,
                    )
                try:
                    await asyncio.wait_for(
                        self._cond.wait(),
                        timeout=remaining,
                    )
                except TimeoutError:
                    raise SandboxTimeoutError(
                        f"Acquire timeout for pool '{self._pool_name}'",
                        timeout_seconds=timeout,
                    )

    async def release(self, resource_id: str) -> None:
        """
        Release a resource back to the pool.

        Args:
            resource_id: The resource ID to release
        """
        async with self._lock:
            if resource_id not in self._in_use:
                logger.warning(f"Resource '{resource_id}' not in use")
                return

            self._in_use.remove(resource_id)
            self._available.add(resource_id)
            self._last_used[resource_id] = asyncio.get_event_loop().time()
            self._cond.notify(1)

    async def remove(self, resource_id: str) -> None:
        """
        Remove a resource from the pool.

        Args:
            resource_id: The resource ID to remove
        """
        async with self._lock:
            resource = self._resources.get(resource_id)

            # Remove from tracking sets
            self._available.discard(resource_id)
            self._in_use.discard(resource_id)
            self._resources.pop(resource_id, None)
            self._remove_resource_metadata(resource_id)

            if resource and self._cleanup:
                try:
                    self._cleanup(resource)
                except Exception as e:
                    logger.warning(f"Cleanup failed for {resource_id}: {e}")

    async def close(self) -> None:
        """Close the pool and cleanup all resources."""
        async with self._lock:
            if self._is_closed:
                return

            self._is_closed = True

            # Cleanup all resources
            for rid in list(self._resources.keys()):
                resource = self._resources.pop(rid, None)
                self._available.discard(rid)
                self._in_use.discard(rid)
                self._remove_resource_metadata(rid)

                if resource and self._cleanup:
                    try:
                        self._cleanup(resource)
                    except Exception as e:
                        logger.warning(f"Cleanup failed for {rid}: {e}")

            self._cond.notify_all()

    @asynccontextmanager
    async def resource(self):
        """Context manager for automatic resource acquisition and release."""
        resource_id = await self.acquire()
        try:
            yield resource_id
        finally:
            await self.release(resource_id)

    def get_resource(self, resource_id: str) -> T | None:
        """Get a resource by ID (doesn't acquire)."""
        return self._resources.get(resource_id)

    @property
    def size(self) -> int:
        """Total number of resources in the pool."""
        return len(self._available) + len(self._in_use)

    @property
    def available_count(self) -> int:
        """Number of available resources."""
        return len(self._available)

    @property
    def in_use_count(self) -> int:
        """Number of resources in use."""
        return len(self._in_use)

    @property
    def is_closed(self) -> bool:
        """Whether the pool is closed."""
        return self._is_closed

    async def _create_resource(self, resource_id: str | None = None) -> str:
        """Create a new resource and add to pool."""
        if resource_id is None:
            import uuid
            resource_id = str(uuid.uuid4())[:8]

        resource = self._factory()
        self._resources[resource_id] = resource
        self._created_at[resource_id] = asyncio.get_event_loop().time()
        self._last_used[resource_id] = asyncio.get_event_loop().time()
        self._in_use.add(resource_id)
        return resource_id

    def _remove_resource_metadata(self, resource_id: str) -> None:
        """Remove metadata for a resource."""
        self._created_at.pop(resource_id, None)
        self._last_used.pop(resource_id, None)
