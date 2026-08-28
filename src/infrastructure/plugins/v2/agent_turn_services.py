"""Generation-owned construction seam for native Agent turns."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from typing import Any, Protocol, cast, override, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.agent_service import AgentService
from src.domain.llm_providers.llm_types import LLMClient
from src.domain.ports.repositories.agent_repository import (
    AgentExecutionEventRepository,
    AgentExecutionRepository,
    ConversationRepository,
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
from src.infrastructure.adapters.secondary.persistence.sql_tool_execution_record_repository import (
    SqlToolExecutionRecordRepository,
)

from .llm_client_service import TenantLlmClientFactoryProtocolV2
from .redis_runtime import RedisRuntimeServiceV2
from .runtime import (
    ContextV2,
    OperationContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

AGENT_TURN_REPOSITORY_PROVIDER_MODULE_V2 = (
    "builtin://memstack/persistence/agent-turn-repository-provider"
)
AGENT_TURN_REPOSITORY_PROVIDER_SERVICE_V2 = "service:persistence.agent-turn-repository-provider"
AGENT_TURN_MODULE_V2 = "builtin://memstack/agent/turn-service"
AGENT_TURN_SERVICE_V2 = "service:agent.turn-service"
AGENT_TURN_REPOSITORIES_INJECT_V2 = "repositories"
AGENT_TURN_LLM_CLIENTS_INJECT_V2 = "llm_clients"
AGENT_TURN_REDIS_INJECT_V2 = "redis"
_OPERATION_DB_SESSION_SERVICE_V2 = "service:operation.db-session"
_OPERATION_IDENTITY_SERVICE_V2 = "service:operation.identity"


@dataclass(frozen=True, kw_only=True)
class AgentTurnRepositoriesV2:
    """Repository adapters constructed from one operation-owned DB session."""

    conversation: ConversationRepository
    execution: AgentExecutionRepository
    tool_execution_record: ToolExecutionRecordRepository
    execution_event: AgentExecutionEventRepository


@runtime_checkable
class AgentTurnRepositoryFactoryProtocolV2(Protocol):
    """Build persistence adapters required by one native Agent turn."""

    def build(self, operation: OperationContextV2) -> AgentTurnRepositoriesV2: ...


@dataclass(frozen=True, kw_only=True)
class SqlAgentTurnRepositoryFactoryV2:
    """Keep SQL implementation selection behind the persistence Provider seam."""

    strategy: str

    def build(self, operation: OperationContextV2) -> AgentTurnRepositoriesV2:
        db = _operation_db_session_v2(operation)
        return AgentTurnRepositoriesV2(
            conversation=SqlConversationRepository(db),
            execution=SqlAgentExecutionRepository(db),
            tool_execution_record=SqlToolExecutionRecordRepository(db),
            execution_event=SqlAgentExecutionEventRepository(db),
        )


class AgentTurnServiceV2(AgentService):
    """Native turn service whose title LLM remains generation injected."""

    @override
    async def _get_title_llm(self) -> LLMClient:
        return self._llm


@runtime_checkable
class AgentTurnStreamProtocolV2(Protocol):
    """Minimum native stream surface consumed by channel adapters."""

    def stream_chat_v2(  # noqa: PLR0913
        self,
        conversation_id: str,
        user_message: str,
        project_id: str,
        user_id: str,
        tenant_id: str,
        preferred_language: str | None = None,
        attachment_ids: list[str] | None = None,
        file_metadata: list[dict[str, Any]] | None = None,
        forced_skill_name: str | None = None,
        app_model_context: dict[str, Any] | None = None,
        image_attachments: list[str] | None = None,
        agent_id: str | None = None,
        mentions: list[str] | None = None,
        api_auth_token: str | None = None,
        execution_message_id: str | None = None,
        canonical_run_id: str | None = None,
    ) -> AsyncIterator[dict[str, Any]]: ...


@runtime_checkable
class AgentTurnResolverProtocolV2(Protocol):
    """Resolve one native turn service from an exact Agent operation."""

    async def resolve(self, operation: OperationContextV2) -> object: ...


@dataclass(frozen=True, kw_only=True)
class AgentTurnResolverV2:
    """Compose a native turn only from declared V2 Provider aliases."""

    repositories: AgentTurnRepositoryFactoryProtocolV2
    llm_clients: TenantLlmClientFactoryProtocolV2
    redis: RedisRuntimeServiceV2

    async def resolve(self, operation: OperationContextV2) -> AgentTurnServiceV2:
        db = _operation_db_session_v2(operation)
        tenant_id = _operation_tenant_id_v2(operation)
        redis_client = self.redis.client
        if redis_client is None:
            raise RuntimeV2Error(
                "agent_turn_redis_unavailable",
                "Native Agent turns require the generation Redis runtime",
            )
        repositories = self.repositories.build(operation)
        llm = await self.llm_clients.create(db=db, tenant_id=tenant_id)
        return AgentTurnServiceV2(
            conversation_repository=repositories.conversation,
            execution_repository=repositories.execution,
            llm=llm,
            redis_client=redis_client,
            tool_execution_record_repository=repositories.tool_execution_record,
            agent_execution_event_repository=repositories.execution_event,
            db_session=db,
        )


def _operation_db_session_v2(operation: OperationContextV2) -> AsyncSession:
    db = operation.require(_OPERATION_DB_SESSION_SERVICE_V2)
    if not isinstance(db, AsyncSession):
        raise RuntimeV2Error(
            "invalid_operation_db_session",
            "Native Agent turns require an AsyncSession operation service",
        )
    return db


def _operation_tenant_id_v2(operation: OperationContextV2) -> str:
    identity = operation.require(_OPERATION_IDENTITY_SERVICE_V2)
    if not isinstance(identity, Mapping):
        raise RuntimeV2Error(
            "invalid_operation_identity",
            "Native Agent turns require operation identity metadata",
        )
    tenant_id = cast(Mapping[str, object], identity).get("tenant_id")
    if not isinstance(tenant_id, str) or not tenant_id:
        raise RuntimeV2Error(
            "invalid_operation_identity",
            "Native Agent turns require a non-empty tenant identity",
        )
    scope_tenant_id = operation.context.scope.tenant_id
    if scope_tenant_id is not None and scope_tenant_id != tenant_id:
        raise RuntimeV2Error(
            "operation_identity_scope_mismatch",
            "Native Agent turn tenant identity does not match its scope",
        )
    return tenant_id


def _apply_agent_turn_repository_provider_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    strategy = config.get("strategy")
    if strategy != "request-async-session":
        raise ValueError("Agent turn repository provider requires strategy request-async-session")
    _ = context.provide(
        AGENT_TURN_REPOSITORY_PROVIDER_SERVICE_V2,
        SqlAgentTurnRepositoryFactoryV2(strategy=strategy),
        label="agent-turn-repository-provider",
    )


def _apply_agent_turn_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    if config.get("strategy") != "operation-scoped-agent-service":
        raise ValueError("Agent turn service requires strategy operation-scoped-agent-service")
    repositories = context.require(AGENT_TURN_REPOSITORIES_INJECT_V2)
    if not isinstance(repositories, AgentTurnRepositoryFactoryProtocolV2):
        raise RuntimeV2Error(
            "invalid_agent_turn_repository_provider",
            "Agent turn repository Provider has an invalid implementation",
        )
    llm_clients = context.require(AGENT_TURN_LLM_CLIENTS_INJECT_V2)
    if not isinstance(llm_clients, TenantLlmClientFactoryProtocolV2):
        raise RuntimeV2Error(
            "invalid_agent_turn_llm_provider",
            "Agent turn LLM Provider has an invalid implementation",
        )
    redis = context.require(AGENT_TURN_REDIS_INJECT_V2)
    if not isinstance(redis, RedisRuntimeServiceV2):
        raise RuntimeV2Error(
            "invalid_agent_turn_redis_provider",
            "Agent turn Redis Provider has an invalid implementation",
        )
    _ = context.provide(
        AGENT_TURN_SERVICE_V2,
        AgentTurnResolverV2(
            repositories=repositories,
            llm_clients=llm_clients,
            redis=redis,
        ),
        label="agent-turn-service",
    )


def agent_turn_service_definitions_v2() -> tuple[PluginDefinitionV2, ...]:
    """Return the persistence Provider and native Agent turn Consumer definitions."""
    return (
        PluginDefinitionV2(
            module_ref=AGENT_TURN_REPOSITORY_PROVIDER_MODULE_V2,
            contract_digest=generated_contract_digest_v2(AGENT_TURN_REPOSITORY_PROVIDER_MODULE_V2),
            apply=_apply_agent_turn_repository_provider_v2,
        ),
        PluginDefinitionV2(
            module_ref=AGENT_TURN_MODULE_V2,
            contract_digest=generated_contract_digest_v2(AGENT_TURN_MODULE_V2),
            apply=_apply_agent_turn_v2,
        ),
    )


__all__ = [
    "AGENT_TURN_LLM_CLIENTS_INJECT_V2",
    "AGENT_TURN_MODULE_V2",
    "AGENT_TURN_REDIS_INJECT_V2",
    "AGENT_TURN_REPOSITORIES_INJECT_V2",
    "AGENT_TURN_REPOSITORY_PROVIDER_MODULE_V2",
    "AGENT_TURN_REPOSITORY_PROVIDER_SERVICE_V2",
    "AGENT_TURN_SERVICE_V2",
    "AgentTurnRepositoriesV2",
    "AgentTurnRepositoryFactoryProtocolV2",
    "AgentTurnResolverProtocolV2",
    "AgentTurnResolverV2",
    "AgentTurnServiceV2",
    "AgentTurnStreamProtocolV2",
    "SqlAgentTurnRepositoryFactoryV2",
    "agent_turn_service_definitions_v2",
]
