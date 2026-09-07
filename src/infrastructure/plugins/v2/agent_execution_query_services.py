"""Generation-owned persistence and application seams for Agent execution queries."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.agent.conversation_manager import ConversationManager
from src.domain.ports.repositories.agent_repository import AgentExecutionRepository
from src.infrastructure.adapters.secondary.persistence.sql_agent_execution_repository import (
    SqlAgentExecutionRepository,
)

from .conversation_access_services import ConversationRepositoryFactoryProtocolV2
from .runtime import (
    ContextV2,
    OperationContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

AGENT_EXECUTION_REPOSITORY_PROVIDER_MODULE_V2 = (
    "builtin://memstack/persistence/agent-execution-repository-provider"
)
AGENT_EXECUTION_REPOSITORY_PROVIDER_SERVICE_V2 = (
    "service:persistence.agent-execution-repository-provider"
)
AGENT_EXECUTION_QUERY_MODULE_V2 = "builtin://memstack/application/agent-execution-query"
AGENT_EXECUTION_QUERY_SERVICE_V2 = "service:application.agent-execution-query"
AGENT_EXECUTION_CONVERSATION_REPOSITORY_INJECT_V2 = "conversation_repository_provider"
AGENT_EXECUTION_REPOSITORY_INJECT_V2 = "execution_repository_provider"
_OPERATION_DB_SESSION_SERVICE_V2 = "service:operation.db-session"


@runtime_checkable
class AgentExecutionRepositoryFactoryProtocolV2(Protocol):
    """Build an execution repository from one operation-owned DB session."""

    def build(self, operation: OperationContextV2) -> AgentExecutionRepository: ...


@dataclass(frozen=True, kw_only=True)
class SqlAgentExecutionRepositoryFactoryV2:
    """Hide the SQL execution repository behind an explicit Provider seam."""

    strategy: str

    def build(self, operation: OperationContextV2) -> AgentExecutionRepository:
        db = operation.require(_OPERATION_DB_SESSION_SERVICE_V2)
        if not isinstance(db, AsyncSession):
            raise RuntimeV2Error(
                "invalid_operation_db_session",
                "Agent execution queries require an AsyncSession operation service",
            )
        return SqlAgentExecutionRepository(db)


@dataclass(frozen=True, kw_only=True)
class AgentExecutionQueryApplicationServicesV2:
    """Operation-owned read surface for persisted Agent executions."""

    manager: ConversationManager

    async def get_execution_history(
        self,
        *,
        conversation_id: str,
        project_id: str,
        user_id: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        return await self.manager.get_execution_history(
            conversation_id=conversation_id,
            project_id=project_id,
            user_id=user_id,
            limit=limit,
        )


@runtime_checkable
class AgentExecutionQueryResolverProtocolV2(Protocol):
    """Resolve one read-only execution query service from declared Provider aliases."""

    def resolve(
        self, operation: OperationContextV2
    ) -> AgentExecutionQueryApplicationServicesV2: ...


@dataclass(frozen=True, kw_only=True)
class AgentExecutionQueryResolverV2:
    """Compose execution queries without constructing an LLM or Agent turn service."""

    conversation_repository_provider: ConversationRepositoryFactoryProtocolV2
    execution_repository_provider: AgentExecutionRepositoryFactoryProtocolV2

    def resolve(self, operation: OperationContextV2) -> AgentExecutionQueryApplicationServicesV2:
        return AgentExecutionQueryApplicationServicesV2(
            manager=ConversationManager(
                conversation_repo=self.conversation_repository_provider.build(operation),
                execution_repo=self.execution_repository_provider.build(operation),
            )
        )


def _apply_agent_execution_repository_provider_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    strategy = config.get("strategy")
    if strategy != "request-async-session":
        raise ValueError(
            "Agent execution repository provider requires strategy request-async-session"
        )
    _ = context.provide(
        AGENT_EXECUTION_REPOSITORY_PROVIDER_SERVICE_V2,
        SqlAgentExecutionRepositoryFactoryV2(strategy=strategy),
        label="agent-execution-repository-provider",
    )


def _apply_agent_execution_query_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    if config.get("strategy") != "operation-scoped-providers":
        raise ValueError("Agent execution query requires strategy operation-scoped-providers")
    conversation_provider = context.require(AGENT_EXECUTION_CONVERSATION_REPOSITORY_INJECT_V2)
    if not isinstance(conversation_provider, ConversationRepositoryFactoryProtocolV2):
        raise RuntimeV2Error(
            "invalid_conversation_repository_provider",
            "Agent execution query conversation Provider has an invalid implementation",
        )
    execution_provider = context.require(AGENT_EXECUTION_REPOSITORY_INJECT_V2)
    if not isinstance(execution_provider, AgentExecutionRepositoryFactoryProtocolV2):
        raise RuntimeV2Error(
            "invalid_agent_execution_repository_provider",
            "Agent execution query repository Provider has an invalid implementation",
        )
    _ = context.provide(
        AGENT_EXECUTION_QUERY_SERVICE_V2,
        AgentExecutionQueryResolverV2(
            conversation_repository_provider=conversation_provider,
            execution_repository_provider=execution_provider,
        ),
        label="agent-execution-query",
    )


def agent_execution_query_service_definitions_v2() -> tuple[PluginDefinitionV2, ...]:
    """Return the execution persistence Provider and application Consumer."""
    return (
        PluginDefinitionV2(
            module_ref=AGENT_EXECUTION_REPOSITORY_PROVIDER_MODULE_V2,
            contract_digest=generated_contract_digest_v2(
                AGENT_EXECUTION_REPOSITORY_PROVIDER_MODULE_V2
            ),
            apply=_apply_agent_execution_repository_provider_v2,
        ),
        PluginDefinitionV2(
            module_ref=AGENT_EXECUTION_QUERY_MODULE_V2,
            contract_digest=generated_contract_digest_v2(AGENT_EXECUTION_QUERY_MODULE_V2),
            apply=_apply_agent_execution_query_v2,
        ),
    )


__all__ = [
    "AGENT_EXECUTION_CONVERSATION_REPOSITORY_INJECT_V2",
    "AGENT_EXECUTION_QUERY_MODULE_V2",
    "AGENT_EXECUTION_QUERY_SERVICE_V2",
    "AGENT_EXECUTION_REPOSITORY_INJECT_V2",
    "AGENT_EXECUTION_REPOSITORY_PROVIDER_MODULE_V2",
    "AGENT_EXECUTION_REPOSITORY_PROVIDER_SERVICE_V2",
    "AgentExecutionQueryApplicationServicesV2",
    "AgentExecutionQueryResolverProtocolV2",
    "AgentExecutionQueryResolverV2",
    "AgentExecutionRepositoryFactoryProtocolV2",
    "SqlAgentExecutionRepositoryFactoryV2",
    "agent_execution_query_service_definitions_v2",
]
