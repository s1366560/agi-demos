"""Generation-owned application and typed events for conversation collections."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol, TypeGuard, cast, runtime_checkable

from src.application.services.conversation_events import build_conversation_created_payload
from src.domain.events.envelope import EventEnvelope
from src.domain.model.agent import Conversation, ConversationStatus
from src.domain.model.agent.conversation.agent_config import (
    normalize_agent_config,
    selected_agent_id_from_config,
)
from src.infrastructure.adapters.secondary.messaging.redis_unified_event_bus import (
    RedisUnifiedEventBusAdapter,
)

from .agent_definition import AgentDefinitionResolverProtocolV2
from .conversation_access_services import (
    ConversationCacheClientProtocolV2,
    ConversationCacheInvalidatorProtocolV2,
    RedisConversationCacheInvalidatorV2,
)
from .conversation_collection_repository import (
    ConversationCollectionRepositoryFactoryProtocolV2,
    ConversationCollectionRepositoryProtocolV2,
)
from .redis_runtime import RedisRuntimeServiceV2
from .runtime import (
    ContextV2,
    OperationContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

CONVERSATION_COLLECTION_MODULE_V2 = "builtin://memstack/application/conversation-collection"
CONVERSATION_COLLECTION_SERVICE_V2 = "service:application.conversation-collection"
CONVERSATION_COLLECTION_REPOSITORY_INJECT_V2 = "repository"
CONVERSATION_COLLECTION_AGENT_DEFINITIONS_INJECT_V2 = "agent_definitions"
CONVERSATION_COLLECTION_REDIS_INJECT_V2 = "redis"

CONVERSATION_CREATED_EVENT_V2 = "conversation.created"
CONVERSATION_CREATED_REDIS_PUBLISHER_MODULE_V2 = (
    "builtin://memstack/events/conversation-created-redis-publisher"
)
CONVERSATION_CREATED_REDIS_PUBLISHER_REDIS_INJECT_V2 = "redis"

logger = logging.getLogger(__name__)

type _ConversationCreatedDispatchV2 = Callable[[Conversation], Awaitable[None]]


class InvalidConversationAgentSelectionV2(ValueError):
    """The requested selected agent is absent from the pinned generation."""


@runtime_checkable
class ConversationCreatedRedisClientProtocolV2(Protocol):
    """Redis subset required by the unified event bus publisher."""

    async def xadd(self, *_args: object, **_kwargs: object) -> object: ...


@dataclass(frozen=True, kw_only=True)
class ConversationCollectionServiceV2:
    """Operation-owned create/list authority with no static DI or LLM dependency."""

    repository: ConversationCollectionRepositoryProtocolV2
    agent_definitions: AgentDefinitionResolverProtocolV2
    cache: ConversationCacheInvalidatorProtocolV2
    dispatch_created: _ConversationCreatedDispatchV2

    async def create_conversation(
        self,
        *,
        project_id: str,
        tenant_id: str,
        user_id: str,
        title: str | None = None,
        agent_config: dict[str, Any] | None = None,
        workspace_id: str | None = None,
    ) -> Conversation:
        if not project_id.strip():
            raise ValueError("project_id must be non-empty")
        if not tenant_id.strip():
            raise ValueError("tenant_id must be non-empty")
        if not user_id.strip():
            raise ValueError("user_id must be non-empty")

        selected_agent_id = selected_agent_id_from_config(agent_config)
        if selected_agent_id is not None:
            agent = await self.agent_definitions.resolve(
                agent_id=selected_agent_id,
                tenant_id=tenant_id,
                project_id=project_id,
            )
            if agent is None:
                raise InvalidConversationAgentSelectionV2(selected_agent_id)

        now = datetime.now(UTC)
        conversation = Conversation(
            id=str(uuid.uuid4()),
            project_id=project_id,
            tenant_id=tenant_id,
            user_id=user_id,
            title=title or "New Conversation",
            status=ConversationStatus.ACTIVE,
            agent_config=normalize_agent_config(agent_config),
            metadata={"created_at": now.isoformat()},
            message_count=0,
            created_at=now,
            workspace_id=workspace_id,
        )
        return await self.repository.save(conversation)

    async def list_conversations(
        self,
        *,
        project_id: str,
        tenant_id: str,
        status: ConversationStatus | None,
        limit: int,
        offset: int,
    ) -> list[Conversation]:
        return await self.repository.list_default(
            project_id=project_id,
            tenant_id=tenant_id,
            status=status,
            limit=limit,
            offset=offset,
        )

    async def count_conversations(
        self,
        *,
        project_id: str,
        tenant_id: str,
        status: ConversationStatus | None,
    ) -> int:
        return await self.repository.count_default(
            project_id=project_id,
            tenant_id=tenant_id,
            status=status,
        )

    async def list_workspace_conversations(
        self,
        *,
        project_id: str,
        tenant_id: str,
        workspace_ids: set[str],
        status: ConversationStatus | None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[Conversation]:
        return await self.repository.list_workspace(
            project_id=project_id,
            tenant_id=tenant_id,
            workspace_ids=workspace_ids,
            status=status,
            limit=limit,
            offset=offset,
        )

    async def count_workspace_conversations(
        self,
        *,
        project_id: str,
        tenant_id: str,
        workspace_id: str,
        status: ConversationStatus | None,
    ) -> int:
        return await self.repository.count_workspace(
            project_id=project_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            status=status,
        )

    async def list_unbound_conversations(
        self,
        *,
        project_id: str,
        tenant_id: str,
        user_id: str,
        status: ConversationStatus | None,
        limit: int,
        offset: int,
    ) -> list[Conversation]:
        return await self.repository.list_unbound(
            project_id=project_id,
            tenant_id=tenant_id,
            user_id=user_id,
            status=status,
            limit=limit,
            offset=offset,
        )

    async def count_unbound_conversations(
        self,
        *,
        project_id: str,
        tenant_id: str,
        user_id: str,
        status: ConversationStatus | None,
    ) -> int:
        return await self.repository.count_unbound(
            project_id=project_id,
            tenant_id=tenant_id,
            user_id=user_id,
            status=status,
        )

    async def after_create_committed(self, conversation: Conversation) -> None:
        """Run post-commit cache coherence and the declared typed event."""
        await self.cache.invalidate(conversation.project_id)
        await self.dispatch_created(conversation)


@runtime_checkable
class ConversationCollectionResolverProtocolV2(Protocol):
    def resolve(self, operation: OperationContextV2) -> ConversationCollectionServiceV2: ...


@dataclass(frozen=True, kw_only=True)
class ConversationCollectionResolverV2:
    repository_provider: ConversationCollectionRepositoryFactoryProtocolV2
    agent_definitions: AgentDefinitionResolverProtocolV2
    redis: RedisRuntimeServiceV2
    dispatch_created: _ConversationCreatedDispatchV2

    def resolve(self, operation: OperationContextV2) -> ConversationCollectionServiceV2:
        return ConversationCollectionServiceV2(
            repository=self.repository_provider.build(operation),
            agent_definitions=self.agent_definitions,
            cache=RedisConversationCacheInvalidatorV2(redis=self.redis),
            dispatch_created=self.dispatch_created,
        )


def _is_string_mapping(value: object) -> TypeGuard[Mapping[str, object]]:
    return isinstance(value, Mapping)


async def _publish_conversation_created_to_redis(
    redis: RedisRuntimeServiceV2,
    payload: object,
) -> None:
    if not _is_string_mapping(payload):
        raise RuntimeV2Error(
            "invalid_conversation_created_payload",
            "conversation.created payload must be an object",
        )
    required = ("conversation_id", "project_id", "tenant_id", "title", "status", "created_at")
    if any(not isinstance(payload.get(field), str) for field in required):
        raise RuntimeV2Error(
            "invalid_conversation_created_payload",
            "conversation.created payload has invalid fields",
        )
    client = redis.client
    if client is None:
        return
    if not isinstance(client, ConversationCreatedRedisClientProtocolV2):
        raise RuntimeV2Error(
            "invalid_conversation_created_redis_client",
            "conversation.created publisher requires Redis xadd",
        )

    project_id = cast("str", payload["project_id"])
    envelope = EventEnvelope(event_type="conversation_created", payload=dict(payload))
    routing_key = f"project:{project_id}:conversation_created"
    try:
        bus = RedisUnifiedEventBusAdapter(cast(Any, client))
        _ = await bus.publish(envelope, routing_key)
    except Exception:
        logger.exception(
            "Failed to publish conversation.created",
            extra={
                "conversation_id": payload["conversation_id"],
                "project_id": project_id,
            },
        )


def _apply_conversation_collection_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    if config.get("strategy") != "operation-scoped-provider":
        raise ValueError("conversation collection requires strategy operation-scoped-provider")
    repository_provider = context.require(CONVERSATION_COLLECTION_REPOSITORY_INJECT_V2)
    if not isinstance(repository_provider, ConversationCollectionRepositoryFactoryProtocolV2):
        raise RuntimeV2Error(
            "invalid_conversation_collection_repository_provider",
            "conversation collection repository Provider has an invalid implementation",
        )
    agent_definitions = context.require(CONVERSATION_COLLECTION_AGENT_DEFINITIONS_INJECT_V2)
    if not isinstance(agent_definitions, AgentDefinitionResolverProtocolV2):
        raise RuntimeV2Error(
            "invalid_conversation_collection_agent_definitions",
            "conversation collection agent definition resolver has an invalid implementation",
        )
    redis = context.require(CONVERSATION_COLLECTION_REDIS_INJECT_V2)
    if not isinstance(redis, RedisRuntimeServiceV2):
        raise RuntimeV2Error(
            "invalid_conversation_collection_redis",
            "conversation collection Redis inject has an invalid implementation",
        )
    if redis.client is not None and not isinstance(redis.client, ConversationCacheClientProtocolV2):
        raise RuntimeV2Error(
            "invalid_conversation_cache_client",
            "conversation cache invalidation requires Redis scan_iter/delete",
        )

    async def dispatch_created(conversation: Conversation) -> None:
        payload = build_conversation_created_payload(conversation)
        _ = await context.dispatch(CONVERSATION_CREATED_EVENT_V2, payload)

    _ = context.provide(
        CONVERSATION_COLLECTION_SERVICE_V2,
        ConversationCollectionResolverV2(
            repository_provider=repository_provider,
            agent_definitions=agent_definitions,
            redis=redis,
            dispatch_created=dispatch_created,
        ),
        label="conversation-collection",
    )


def _apply_conversation_created_redis_publisher_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    if config.get("strategy") != "redis-project-stream":
        raise ValueError(
            "conversation.created Redis publisher requires strategy redis-project-stream"
        )
    redis = context.require(CONVERSATION_CREATED_REDIS_PUBLISHER_REDIS_INJECT_V2)
    if not isinstance(redis, RedisRuntimeServiceV2):
        raise RuntimeV2Error(
            "invalid_conversation_created_redis",
            "conversation.created publisher Redis inject has an invalid implementation",
        )
    if redis.client is not None and not isinstance(
        redis.client,
        ConversationCreatedRedisClientProtocolV2,
    ):
        raise RuntimeV2Error(
            "invalid_conversation_created_redis_client",
            "conversation.created publisher requires Redis xadd",
        )

    async def publish(payload: object) -> None:
        await _publish_conversation_created_to_redis(redis, payload)

    _ = context.on(CONVERSATION_CREATED_EVENT_V2, publish)


def conversation_collection_service_definitions_v2() -> tuple[PluginDefinitionV2, ...]:
    return (
        PluginDefinitionV2(
            module_ref=CONVERSATION_COLLECTION_MODULE_V2,
            contract_digest=generated_contract_digest_v2(CONVERSATION_COLLECTION_MODULE_V2),
            apply=_apply_conversation_collection_v2,
        ),
        PluginDefinitionV2(
            module_ref=CONVERSATION_CREATED_REDIS_PUBLISHER_MODULE_V2,
            contract_digest=generated_contract_digest_v2(
                CONVERSATION_CREATED_REDIS_PUBLISHER_MODULE_V2
            ),
            apply=_apply_conversation_created_redis_publisher_v2,
        ),
    )


__all__ = [
    "CONVERSATION_COLLECTION_AGENT_DEFINITIONS_INJECT_V2",
    "CONVERSATION_COLLECTION_MODULE_V2",
    "CONVERSATION_COLLECTION_REDIS_INJECT_V2",
    "CONVERSATION_COLLECTION_REPOSITORY_INJECT_V2",
    "CONVERSATION_COLLECTION_SERVICE_V2",
    "CONVERSATION_CREATED_EVENT_V2",
    "CONVERSATION_CREATED_REDIS_PUBLISHER_MODULE_V2",
    "CONVERSATION_CREATED_REDIS_PUBLISHER_REDIS_INJECT_V2",
    "ConversationCollectionResolverProtocolV2",
    "ConversationCollectionResolverV2",
    "ConversationCollectionServiceV2",
    "ConversationCreatedRedisClientProtocolV2",
    "InvalidConversationAgentSelectionV2",
    "conversation_collection_service_definitions_v2",
]
