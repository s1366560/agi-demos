"""DI sub-container for infrastructure services."""

from __future__ import annotations

from typing import Any, cast

import redis.asyncio as redis

from src.configuration.config import Settings
from src.domain.ports.services.hitl_message_bus_port import HITLMessageBusPort
from src.domain.ports.services.workflow_engine_port import WorkflowEnginePort


def _validate_workflow_engine(implementation: object) -> None:
    """Assert a workflow engine row exposes the port surface."""
    if not callable(getattr(implementation, "start_workflow", None)):
        raise TypeError("workflow_engine capability must expose the WorkflowEnginePort surface")


class InfraContainer:
    """Sub-container for infrastructure services.

    Provides factory methods for Redis, storage, distributed locks,
    sandbox adapters, and other cross-cutting infrastructure concerns.
    """

    def __init__(
        self,
        redis_client: redis.Redis | None = None,
        workflow_engine: WorkflowEnginePort | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._redis_client = redis_client
        self._workflow_engine = workflow_engine
        self._settings = settings
        self._sandbox_adapter_instance: Any = None

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

    def workflow_engine_port(self) -> WorkflowEnginePort | None:
        """Get WorkflowEnginePort for workflow orchestration.

        R3c seam: an active plugin ``workflow_engine`` capability row wins
        (validated for the port surface); otherwise the engine injected at
        construction is returned, which may legitimately be None
        (builtin-absent semantics preserved).
        """
        from src.domain.model.plugins import CapabilityKind
        from src.infrastructure.plugins.backend_runtime import (
            BackendResolutionError,
            resolve_backend,
        )
        from src.infrastructure.plugins.runtime_host import (
            get_platform_plugin_runtime_host,
        )

        try:
            selection = resolve_backend(
                get_platform_plugin_runtime_host().capabilities,
                CapabilityKind.WORKFLOW_ENGINE,
                validator=_validate_workflow_engine,
            )
        except BackendResolutionError:
            return self._workflow_engine
        return cast(WorkflowEnginePort, selection.implementation)

    def _legacy_workflow_engine_port(self) -> WorkflowEnginePort | None:
        """Return the constructor-injected engine without the plugin seam."""
        return self._workflow_engine

    def sandbox_adapter(self) -> Any:
        """Get the MCP Sandbox adapter for desktop and terminal management.

        Returns a cached singleton instance per InfraContainer to avoid
        re-creating the adapter (and triggering Docker recovery) on every call.
        """
        if self._sandbox_adapter_instance is not None:
            return self._sandbox_adapter_instance

        from src.configuration.config import get_settings
        from src.infrastructure.adapters.secondary.sandbox.mcp_sandbox_adapter import (
            MCPSandboxAdapter,
        )

        settings = get_settings()
        self._sandbox_adapter_instance = MCPSandboxAdapter(
            mcp_image=settings.sandbox_default_image,
            default_timeout=settings.sandbox_timeout_seconds,
            default_memory_limit=settings.sandbox_memory_limit,
            default_cpu_limit=settings.sandbox_cpu_limit,
            workspace_base=settings.sandbox_workspace_base,
            redis_client=self._redis_client,
        )
        return self._sandbox_adapter_instance

    def sandbox_event_publisher(self) -> Any:
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
