"""Generation-owned persistence and application seams for conversation access."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.agent import Conversation
from src.domain.ports.repositories.agent_repository import ConversationRepository
from src.infrastructure.adapters.secondary.persistence.sql_conversation_repository import (
    SqlConversationRepository,
)

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
CONVERSATION_ACCESS_MODULE_V2 = "builtin://memstack/application/conversation-access"
CONVERSATION_ACCESS_SERVICE_V2 = "service:application.conversation-access"
CONVERSATION_REPOSITORY_INJECT_V2 = "repository_provider"
_OPERATION_DB_SESSION_SERVICE_V2 = "service:operation.db-session"


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
class ConversationAccessServiceV2:
    """Operation-owned query surface for persisted conversation authority."""

    repository: ConversationRepository

    async def find_by_id(self, conversation_id: str) -> Conversation | None:
        if not conversation_id.strip():
            raise ValueError("conversation_id must be non-empty")
        return await self.repository.find_by_id(conversation_id)


@runtime_checkable
class ConversationAccessResolverProtocolV2(Protocol):
    """Resolve the application query surface from a declared Provider alias."""

    def resolve(self, operation: OperationContextV2) -> ConversationAccessServiceV2: ...


@dataclass(frozen=True, kw_only=True)
class ConversationAccessResolverV2:
    """Bind the injected repository Provider to one operation boundary."""

    repository_provider: ConversationRepositoryFactoryProtocolV2

    def resolve(self, operation: OperationContextV2) -> ConversationAccessServiceV2:
        return ConversationAccessServiceV2(
            repository=self.repository_provider.build(operation),
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
    repository_provider = context.require(CONVERSATION_REPOSITORY_INJECT_V2)
    if not isinstance(repository_provider, ConversationRepositoryFactoryProtocolV2):
        raise RuntimeV2Error(
            "invalid_conversation_repository_provider",
            "conversation repository provider inject has an invalid implementation",
        )
    _ = context.provide(
        CONVERSATION_ACCESS_SERVICE_V2,
        ConversationAccessResolverV2(repository_provider=repository_provider),
        label="conversation-access",
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
            module_ref=CONVERSATION_ACCESS_MODULE_V2,
            contract_digest=generated_contract_digest_v2(CONVERSATION_ACCESS_MODULE_V2),
            apply=_apply_conversation_access_v2,
        ),
    )


__all__ = [
    "CONVERSATION_ACCESS_MODULE_V2",
    "CONVERSATION_ACCESS_SERVICE_V2",
    "CONVERSATION_REPOSITORY_INJECT_V2",
    "CONVERSATION_REPOSITORY_PROVIDER_MODULE_V2",
    "CONVERSATION_REPOSITORY_PROVIDER_SERVICE_V2",
    "ConversationAccessResolverProtocolV2",
    "ConversationAccessResolverV2",
    "ConversationAccessServiceV2",
    "ConversationRepositoryFactoryProtocolV2",
    "SqlConversationRepositoryFactoryV2",
    "conversation_access_service_definitions_v2",
]
