"""Generation-owned persistence and application seams for conversation access."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.agent import Conversation
from src.domain.ports.repositories.agent_repository import (
    AgentExecutionEventRepository,
    AgentExecutionRepository,
    ConversationRepository,
    ExecutionCheckpointRepository,
    ToolExecutionRecordRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_agent_execution_event_repository import (
    SqlAgentExecutionEventRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_agent_execution_repository import (
    SqlAgentExecutionRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_conversation_repository import (
    SqlConversationRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_execution_checkpoint_repository import (
    SqlExecutionCheckpointRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_tool_execution_record_repository import (
    SqlToolExecutionRecordRepository,
)

from .redis_runtime import RedisRuntimeServiceV2
from .runtime import (
    ContextV2,
    OperationContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

CONVERSATION_REPOSITORY_PROVIDER_MODULE_V2 = (
    "builtin://memstack/persistence/conversation-repository-provider"
)
CONVERSATION_REPOSITORY_PROVIDER_SERVICE_V2 = "service:persistence.conversation-repository-provider"
CONVERSATION_CRUD_REPOSITORY_PROVIDER_MODULE_V2 = (
    "builtin://memstack/persistence/conversation-crud-repository-provider"
)
CONVERSATION_CRUD_REPOSITORY_PROVIDER_SERVICE_V2 = (
    "service:persistence.conversation-crud-repository-provider"
)
CONVERSATION_ACCESS_MODULE_V2 = "builtin://memstack/application/conversation-access"
CONVERSATION_ACCESS_SERVICE_V2 = "service:application.conversation-access"
CONVERSATION_CRUD_REPOSITORIES_INJECT_V2 = "crud_repositories"
CONVERSATION_CACHE_REDIS_INJECT_V2 = "redis"
_OPERATION_DB_SESSION_SERVICE_V2 = "service:operation.db-session"

logger = logging.getLogger(__name__)


@runtime_checkable
class ConversationRepositoryFactoryProtocolV2(Protocol):
    """Build a conversation repository from one operation-owned DB session."""

    def build(self, operation: OperationContextV2) -> ConversationRepository: ...


@dataclass(frozen=True, kw_only=True)
class SqlConversationRepositoryFactoryV2:
    """Construct the SQL adapter without exposing it to service Consumers."""

    strategy: str

    def build(self, operation: OperationContextV2) -> ConversationRepository:
        db = operation.require(_OPERATION_DB_SESSION_SERVICE_V2)
        if not isinstance(db, AsyncSession):
            raise RuntimeV2Error(
                "invalid_operation_db_session",
                "conversation access requires an AsyncSession operation service",
            )
        return SqlConversationRepository(db)


@dataclass(frozen=True, kw_only=True)
class ConversationCrudRepositoriesV2:
    """Persistence adapters required for complete conversation CRUD semantics."""

    conversation: ConversationRepository
    execution: AgentExecutionRepository
    execution_event: AgentExecutionEventRepository
    tool_execution_record: ToolExecutionRecordRepository
    execution_checkpoint: ExecutionCheckpointRepository


@runtime_checkable
class ConversationCrudRepositoryFactoryProtocolV2(Protocol):
    """Build all conversation CRUD repositories from one operation session."""

    def build_crud(self, operation: OperationContextV2) -> ConversationCrudRepositoriesV2: ...


@runtime_checkable
class ConversationCacheClientProtocolV2(Protocol):
    """Redis subset used to invalidate transitional conversation list caches."""

    def scan_iter(
        self,
        *,
        match: str,
        count: int,
    ) -> AsyncIterator[str | bytes]: ...

    async def delete(self, *keys: str | bytes) -> object: ...


@runtime_checkable
class ConversationCacheInvalidatorProtocolV2(Protocol):
    """Invalidate cached conversation lists after a committed mutation."""

    async def invalidate(self, project_id: str) -> None: ...


@dataclass(frozen=True, kw_only=True)
class RedisConversationCacheInvalidatorV2:
    """Keep V1 list/count caches coherent during the staged V2 cutover."""

    redis: RedisRuntimeServiceV2

    async def invalidate(self, project_id: str) -> None:
        if not project_id.strip():
            raise ValueError("project_id must be non-empty")
        client = self.redis.client
        if client is None:
            return
        if not isinstance(client, ConversationCacheClientProtocolV2):
            raise RuntimeV2Error(
                "invalid_conversation_cache_client",
                "conversation cache invalidation requires Redis scan_iter/delete",
            )
        try:
            for prefix in ("conv_list:", "conv_count:"):
                batch: list[str | bytes] = []
                async for key in client.scan_iter(
                    match=f"{prefix}{project_id}:*",
                    count=100,
                ):
                    batch.append(key)
                    if len(batch) >= 100:
                        _ = await client.delete(*batch)
                        batch.clear()
                if batch:
                    _ = await client.delete(*batch)
        except Exception:
            logger.debug(
                "conversation cache invalidation failed",
                extra={"project_id": project_id},
                exc_info=True,
            )


@dataclass(frozen=True, kw_only=True)
class SqlConversationCrudRepositoryFactoryV2:
    """Keep the complete SQL deletion set behind one explicit Provider seam."""

    strategy: str

    def build_crud(self, operation: OperationContextV2) -> ConversationCrudRepositoriesV2:
        db = operation.require(_OPERATION_DB_SESSION_SERVICE_V2)
        if not isinstance(db, AsyncSession):
            raise RuntimeV2Error(
                "invalid_operation_db_session",
                "conversation CRUD requires an AsyncSession operation service",
            )
        return ConversationCrudRepositoriesV2(
            conversation=SqlConversationRepository(db),
            execution=SqlAgentExecutionRepository(db),
            execution_event=SqlAgentExecutionEventRepository(db),
            tool_execution_record=SqlToolExecutionRecordRepository(db),
            execution_checkpoint=SqlExecutionCheckpointRepository(db),
        )


@dataclass(frozen=True, kw_only=True)
class ConversationAccessServiceV2:
    """Operation-owned CRUD surface for persisted conversation authority."""

    repositories: ConversationCrudRepositoriesV2
    cache: ConversationCacheInvalidatorProtocolV2

    @property
    def repository(self) -> ConversationRepository:
        """Preserve the narrow read surface used by WebSocket Consumers."""
        return self.repositories.conversation

    async def find_by_id(self, conversation_id: str) -> Conversation | None:
        if not conversation_id.strip():
            raise ValueError("conversation_id must be non-empty")
        return await self.repository.find_by_id(conversation_id)

    async def get_conversation(
        self,
        *,
        conversation_id: str,
        project_id: str,
        user_id: str,
    ) -> Conversation | None:
        """Return a conversation only when its full request scope matches."""
        if not project_id.strip():
            raise ValueError("project_id must be non-empty")
        if not user_id.strip():
            raise ValueError("user_id must be non-empty")
        conversation = await self.find_by_id(conversation_id)
        if conversation is None:
            return None
        if conversation.project_id != project_id or conversation.user_id != user_id:
            return None
        return conversation

    async def delete_conversation(
        self,
        *,
        conversation_id: str,
        project_id: str,
        user_id: str,
    ) -> bool:
        """Delete one exact scoped conversation without owning the transaction."""
        conversation = await self.get_conversation(
            conversation_id=conversation_id,
            project_id=project_id,
            user_id=user_id,
        )
        if conversation is None:
            return False
        await self.repositories.tool_execution_record.delete_by_conversation(conversation.id)
        await self.repositories.execution_event.delete_by_conversation(conversation.id)
        await self.repositories.execution_checkpoint.delete_by_conversation(conversation.id)
        await self.repositories.execution.delete_by_conversation(conversation.id)
        return await self.repository.delete(conversation.id)

    async def update_conversation_title(
        self,
        *,
        conversation_id: str,
        project_id: str,
        user_id: str,
        title: str,
    ) -> Conversation | None:
        """Persist a title change while leaving commit authority to the request."""
        conversation = await self.get_conversation(
            conversation_id=conversation_id,
            project_id=project_id,
            user_id=user_id,
        )
        if conversation is None:
            return None
        conversation.update_title(title)
        return await self.repository.save(conversation)


@runtime_checkable
class ConversationAccessResolverProtocolV2(Protocol):
    """Resolve the application query surface from a declared Provider alias."""

    def resolve(self, operation: OperationContextV2) -> ConversationAccessServiceV2: ...


@dataclass(frozen=True, kw_only=True)
class ConversationAccessResolverV2:
    """Bind the injected repository Provider to one operation boundary."""

    crud_repository_provider: ConversationCrudRepositoryFactoryProtocolV2
    redis: RedisRuntimeServiceV2

    def resolve(self, operation: OperationContextV2) -> ConversationAccessServiceV2:
        return ConversationAccessServiceV2(
            repositories=self.crud_repository_provider.build_crud(operation),
            cache=RedisConversationCacheInvalidatorV2(redis=self.redis),
        )


def _apply_conversation_repository_provider_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    strategy = config.get("strategy")
    if strategy != "request-async-session":
        raise ValueError("conversation repository provider requires strategy request-async-session")
    _ = context.provide(
        CONVERSATION_REPOSITORY_PROVIDER_SERVICE_V2,
        SqlConversationRepositoryFactoryV2(strategy=strategy),
        label="conversation-repository-provider",
    )


def _apply_conversation_access_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    if config.get("strategy") != "operation-scoped-provider":
        raise ValueError("conversation access requires strategy operation-scoped-provider")
    crud_repository_provider = context.require(CONVERSATION_CRUD_REPOSITORIES_INJECT_V2)
    if not isinstance(crud_repository_provider, ConversationCrudRepositoryFactoryProtocolV2):
        raise RuntimeV2Error(
            "invalid_conversation_crud_repository_provider",
            "conversation CRUD repository Provider has an invalid implementation",
        )
    redis = context.require(CONVERSATION_CACHE_REDIS_INJECT_V2)
    if not isinstance(redis, RedisRuntimeServiceV2):
        raise RuntimeV2Error(
            "invalid_conversation_cache_redis",
            "conversation access Redis inject has an invalid implementation",
        )
    if redis.client is not None and not isinstance(
        redis.client,
        ConversationCacheClientProtocolV2,
    ):
        raise RuntimeV2Error(
            "invalid_conversation_cache_client",
            "conversation cache invalidation requires Redis scan_iter/delete",
        )
    _ = context.provide(
        CONVERSATION_ACCESS_SERVICE_V2,
        ConversationAccessResolverV2(
            crud_repository_provider=crud_repository_provider,
            redis=redis,
        ),
        label="conversation-access",
    )


def _apply_conversation_crud_repository_provider_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    strategy = config.get("strategy")
    if strategy != "request-async-session":
        raise ValueError(
            "conversation CRUD repository provider requires strategy request-async-session"
        )
    _ = context.provide(
        CONVERSATION_CRUD_REPOSITORY_PROVIDER_SERVICE_V2,
        SqlConversationCrudRepositoryFactoryV2(strategy=strategy),
        label="conversation-crud-repository-provider",
    )


def conversation_access_service_definitions_v2() -> tuple[PluginDefinitionV2, ...]:
    """Return the persistence Provider and explicit application Consumer."""
    return (
        PluginDefinitionV2(
            module_ref=CONVERSATION_REPOSITORY_PROVIDER_MODULE_V2,
            contract_digest=generated_contract_digest_v2(
                CONVERSATION_REPOSITORY_PROVIDER_MODULE_V2
            ),
            apply=_apply_conversation_repository_provider_v2,
        ),
        PluginDefinitionV2(
            module_ref=CONVERSATION_CRUD_REPOSITORY_PROVIDER_MODULE_V2,
            contract_digest=generated_contract_digest_v2(
                CONVERSATION_CRUD_REPOSITORY_PROVIDER_MODULE_V2
            ),
            apply=_apply_conversation_crud_repository_provider_v2,
        ),
        PluginDefinitionV2(
            module_ref=CONVERSATION_ACCESS_MODULE_V2,
            contract_digest=generated_contract_digest_v2(CONVERSATION_ACCESS_MODULE_V2),
            apply=_apply_conversation_access_v2,
        ),
    )


__all__ = [
    "CONVERSATION_ACCESS_MODULE_V2",
    "CONVERSATION_ACCESS_SERVICE_V2",
    "CONVERSATION_CACHE_REDIS_INJECT_V2",
    "CONVERSATION_CRUD_REPOSITORIES_INJECT_V2",
    "CONVERSATION_CRUD_REPOSITORY_PROVIDER_MODULE_V2",
    "CONVERSATION_CRUD_REPOSITORY_PROVIDER_SERVICE_V2",
    "CONVERSATION_REPOSITORY_PROVIDER_MODULE_V2",
    "CONVERSATION_REPOSITORY_PROVIDER_SERVICE_V2",
    "ConversationAccessResolverProtocolV2",
    "ConversationAccessResolverV2",
    "ConversationAccessServiceV2",
    "ConversationCacheClientProtocolV2",
    "ConversationCacheInvalidatorProtocolV2",
    "ConversationCrudRepositoriesV2",
    "ConversationCrudRepositoryFactoryProtocolV2",
    "ConversationRepositoryFactoryProtocolV2",
    "RedisConversationCacheInvalidatorV2",
    "SqlConversationCrudRepositoryFactoryV2",
    "SqlConversationRepositoryFactoryV2",
    "conversation_access_service_definitions_v2",
]
