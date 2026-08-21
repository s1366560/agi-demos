"""DI sub-container for infrastructure services."""

from __future__ import annotations

from typing import Any

import redis.asyncio as redis

from src.configuration.config import Settings
from src.domain.ports.services.hitl_message_bus_port import HITLMessageBusPort


class InfraContainer:
    """Sub-container for infrastructure services.

    Provides factory methods for Redis, storage, distributed locks,
    sandbox adapters, and other cross-cutting infrastructure concerns.
    """

    def __init__(
        self,
        redis_client: redis.Redis | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._redis_client = redis_client
        self._settings = settings

    def redis(self) -> redis.Redis | None:
        """Get the Redis client for cache operations."""
        return self._redis_client

    def sequence_service(self) -> Any:
        """Get RedisSequenceService for atomic sequence number generation."""
        if not self._redis_client:
            return None
        from src.infrastructure.adapters.secondary.messaging.redis_sequence_service import (
            RedisSequenceService,
        )

        return RedisSequenceService(self._redis_client)

    def hitl_message_bus(self) -> HITLMessageBusPort | None:
        """Get the HITL message bus for cross-process communication.

        Returns the Redis Streams based message bus for HITL tools
        (decision, clarification, env_var).
        """
        if not self._redis_client:
            return None
        from src.infrastructure.adapters.secondary.messaging.redis_hitl_message_bus import (
            RedisHITLMessageBusAdapter,
        )

        return RedisHITLMessageBusAdapter(self._redis_client)

    def agent_message_bus(self) -> Any:
        """Get the inter-agent message bus for agent-to-agent communication."""
        if not self._redis_client:
            return None
        from src.infrastructure.adapters.secondary.messaging.redis_agent_message_bus import (
            RedisAgentMessageBusAdapter,
        )

        return RedisAgentMessageBusAdapter(self._redis_client)

    def storage_service(self) -> Any:
        """Get StorageServicePort for file storage operations (S3/MinIO)."""
        from src.infrastructure.adapters.secondary.storage.s3_storage_adapter import (
            S3StorageAdapter,
        )

        assert self._settings is not None
        return S3StorageAdapter(
            bucket_name=self._settings.s3_bucket_name,
            region=self._settings.aws_region,
            access_key_id=self._settings.aws_access_key_id,
            secret_access_key=self._settings.aws_secret_access_key,
            endpoint_url=self._settings.s3_endpoint_url,
            no_proxy=self._settings.s3_no_proxy,
        )

    def distributed_lock_adapter(self) -> Any:
        """Get Redis-based distributed lock adapter.

        Returns None if Redis client is not available.
        """
        if self._redis_client is None:
            return None

        from src.infrastructure.adapters.secondary.cache.redis_lock_adapter import (
            RedisDistributedLockAdapter,
        )

        return RedisDistributedLockAdapter(
            redis=self._redis_client,
            namespace="memstack:lock",
            default_ttl=120,
            retry_interval=0.1,
            max_retries=300,
        )
