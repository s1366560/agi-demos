"""DI sub-container for infrastructure services."""

from typing import TYPE_CHECKING, Optional

import redis.asyncio as redis

from src.domain.ports.services.hitl_message_bus_port import HITLMessageBusPort
from src.domain.ports.services.workflow_engine_port import WorkflowEnginePort
from src.infrastructure.adapters.secondary.temporal.mcp.adapter import MCPTemporalAdapter

if TYPE_CHECKING:
    from temporalio.client import Client as TemporalClient


class InfraContainer:
    """Sub-container for infrastructure services.

    Provides factory methods for Redis, Temporal, storage, distributed locks,
    sandbox adapters, and other cross-cutting infrastructure concerns.
    """

    def __init__(
        self,
        redis_client: Optional[redis.Redis] = None,
        workflow_engine: Optional[WorkflowEnginePort] = None,
        temporal_client: Optional["TemporalClient"] = None,
        mcp_temporal_adapter: Optional[MCPTemporalAdapter] = None,
        settings=None,
    ) -> None:
        self._redis_client = redis_client
        self._workflow_engine = workflow_engine
        self._temporal_client = temporal_client
        self._mcp_temporal_adapter = mcp_temporal_adapter
        self._settings = settings

    def redis(self) -> Optional[redis.Redis]:
        """Get the Redis client for cache operations."""
        return self._redis_client

    def sequence_service(self):
        """Get RedisSequenceService for atomic sequence number generation."""
        if not self._redis_client:
            return None
        from src.infrastructure.adapters.secondary.messaging.redis_sequence_service import (
            RedisSequenceService,
        )

        return RedisSequenceService(self._redis_client)

    def hitl_message_bus(self) -> Optional[HITLMessageBusPort]:
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

    def storage_service(self):
        """Get StorageServicePort for file storage operations (S3/MinIO)."""
        from src.infrastructure.adapters.secondary.storage.s3_storage_adapter import (
            S3StorageAdapter,
        )

        return S3StorageAdapter(
            bucket_name=self._settings.s3_bucket_name,
            region=self._settings.aws_region,
            access_key_id=self._settings.aws_access_key_id,
            secret_access_key=self._settings.aws_secret_access_key,
            endpoint_url=self._settings.s3_endpoint_url,
        )

    def distributed_lock_adapter(self):
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

    def workflow_engine_port(self) -> Optional[WorkflowEnginePort]:
        """Get WorkflowEnginePort for workflow orchestration (Temporal)."""
        return self._workflow_engine

    async def temporal_client(self) -> Optional["TemporalClient"]:
        """Get Temporal client for direct workflow operations.

        Returns the cached client if available, otherwise creates a new connection.
        """
        if self._temporal_client is not None:
            return self._temporal_client

        from src.infrastructure.adapters.secondary.temporal.client import TemporalClientFactory

        try:
            self._temporal_client = await TemporalClientFactory.get_client()
            return self._temporal_client
        except Exception:
            return None

    async def mcp_temporal_adapter(self) -> Optional[MCPTemporalAdapter]:
        """Get MCPTemporalAdapter for Temporal-based MCP server management."""
        if self._mcp_temporal_adapter is not None:
            return self._mcp_temporal_adapter

        client = await self.temporal_client()
        if client is None:
            return None
        self._mcp_temporal_adapter = MCPTemporalAdapter(client)
        return self._mcp_temporal_adapter

    def get_mcp_temporal_adapter_sync(self) -> Optional[MCPTemporalAdapter]:
        """Get cached MCPTemporalAdapter synchronously.

        Returns the cached adapter instance without async initialization.
        """
        return self._mcp_temporal_adapter

    def sandbox_adapter(self):
        """Get the MCP Sandbox adapter for desktop and terminal management."""
        from src.configuration.config import get_settings
        from src.infrastructure.adapters.secondary.sandbox.mcp_sandbox_adapter import (
            MCPSandboxAdapter,
        )

        settings = get_settings()
        return MCPSandboxAdapter(
            mcp_image=settings.sandbox_default_image,
            default_timeout=settings.sandbox_timeout_seconds,
            default_memory_limit=settings.sandbox_memory_limit,
            default_cpu_limit=settings.sandbox_cpu_limit,
        )

    def sandbox_event_publisher(self):
        """Get SandboxEventPublisher for SSE event emission."""
        from src.application.services.sandbox_event_service import SandboxEventPublisher

        event_bus = None
        if self._redis_client:
            try:
                from src.infrastructure.adapters.secondary.event.redis_event_bus import (
                    RedisEventBusAdapter,
                )

                event_bus = RedisEventBusAdapter(self._redis_client)
            except Exception as e:
                import logging

                logging.getLogger(__name__).warning(f"Could not create event bus: {e}")

        return SandboxEventPublisher(event_bus=event_bus)
