"""Generation-owned construction seam for Agent recovery streaming."""

from __future__ import annotations

from collections.abc import Mapping
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

AGENT_RECOVERY_STREAM_REPOSITORY_PROVIDER_MODULE_V2 = (
    "builtin://memstack/persistence/agent-recovery-stream-repository-provider"
)
AGENT_RECOVERY_STREAM_REPOSITORY_PROVIDER_SERVICE_V2 = (
    "service:persistence.agent-recovery-stream-repository-provider"
)
AGENT_RECOVERY_STREAM_MODULE_V2 = "builtin://memstack/agent/recovery-stream"
AGENT_RECOVERY_STREAM_SERVICE_V2 = "service:agent.recovery-stream"
AGENT_RECOVERY_STREAM_REPOSITORIES_INJECT_V2 = "repositories"
AGENT_RECOVERY_STREAM_LLM_CLIENTS_INJECT_V2 = "llm_clients"
AGENT_RECOVERY_STREAM_REDIS_INJECT_V2 = "redis"
_OPERATION_DB_SESSION_SERVICE_V2 = "service:operation.db-session"
_OPERATION_IDENTITY_SERVICE_V2 = "service:operation.identity"


@dataclass(frozen=True, kw_only=True)
class AgentRecoveryStreamRepositoriesV2:
    """Repository adapters constructed from one operation-owned DB session."""

    conversation: ConversationRepository
    execution: AgentExecutionRepository
    tool_execution_record: ToolExecutionRecordRepository
    execution_event: AgentExecutionEventRepository


@runtime_checkable
class AgentRecoveryStreamRepositoryFactoryProtocolV2(Protocol):
    """Build all persistence adapters required by the recovery stream."""

    def build(self, operation: OperationContextV2) -> AgentRecoveryStreamRepositoriesV2: ...


@dataclass(frozen=True, kw_only=True)
class SqlAgentRecoveryStreamRepositoryFactoryV2:
    """Keep SQL implementation selection behind the persistence Provider seam."""

    strategy: str

    def build(self, operation: OperationContextV2) -> AgentRecoveryStreamRepositoriesV2:
        db = _operation_db_session_v2(operation)
        return AgentRecoveryStreamRepositoriesV2(
            conversation=SqlConversationRepository(db),
            execution=SqlAgentExecutionRepository(db),
            tool_execution_record=SqlToolExecutionRecordRepository(db),
            execution_event=SqlAgentExecutionEventRepository(db),
        )


class AgentRecoveryStreamServiceV2(AgentService):
    """Agent stream service whose title LLM remains generation injected."""

    @override
    async def _get_title_llm(self) -> LLMClient:
        return self._llm


@runtime_checkable
class AgentRecoveryStreamResolverProtocolV2(Protocol):
    """Resolve a recovery stream from one exact Agent operation."""

    async def resolve(self, operation: OperationContextV2) -> AgentRecoveryStreamServiceV2: ...


@dataclass(frozen=True, kw_only=True)
class AgentRecoveryStreamResolverV2:
    """Compose the recovery stream only from declared V2 Provider aliases."""

    repositories: AgentRecoveryStreamRepositoryFactoryProtocolV2
    llm_clients: TenantLlmClientFactoryProtocolV2
    redis: RedisRuntimeServiceV2

    async def resolve(self, operation: OperationContextV2) -> AgentRecoveryStreamServiceV2:
        db = _operation_db_session_v2(operation)
        tenant_id = _operation_tenant_id_v2(operation)
        redis_client = self.redis.client
        if redis_client is None:
            raise RuntimeV2Error(
                "agent_recovery_redis_unavailable",
                "Agent recovery stream requires the generation Redis runtime",
            )
        repositories = self.repositories.build(operation)
        llm = await self.llm_clients.create(db=db, tenant_id=tenant_id)
        return AgentRecoveryStreamServiceV2(
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
            "Agent recovery stream requires an AsyncSession operation service",
        )
    return db


def _operation_tenant_id_v2(operation: OperationContextV2) -> str:
    identity = operation.require(_OPERATION_IDENTITY_SERVICE_V2)
    if not isinstance(identity, Mapping):
        raise RuntimeV2Error(
            "invalid_operation_identity",
            "Agent recovery stream requires operation identity metadata",
        )
    tenant_id = cast(Mapping[str, object], identity).get("tenant_id")
    if not isinstance(tenant_id, str) or not tenant_id:
        raise RuntimeV2Error(
            "invalid_operation_identity",
            "Agent recovery stream requires a non-empty tenant identity",
        )
    scope_tenant_id = operation.context.scope.tenant_id
    if scope_tenant_id is not None and scope_tenant_id != tenant_id:
        raise RuntimeV2Error(
            "operation_identity_scope_mismatch",
            "Agent recovery stream tenant identity does not match its scope",
        )
    return tenant_id


def _apply_agent_recovery_stream_repository_provider_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    strategy = config.get("strategy")
    if strategy != "request-async-session":
        raise ValueError(
            "Agent recovery stream repository provider requires strategy request-async-session"
        )
    _ = context.provide(
        AGENT_RECOVERY_STREAM_REPOSITORY_PROVIDER_SERVICE_V2,
        SqlAgentRecoveryStreamRepositoryFactoryV2(strategy=strategy),
        label="agent-recovery-stream-repository-provider",
    )


def _apply_agent_recovery_stream_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    if config.get("strategy") != "operation-scoped-agent-service":
        raise ValueError("Agent recovery stream requires strategy operation-scoped-agent-service")
    repositories = context.require(AGENT_RECOVERY_STREAM_REPOSITORIES_INJECT_V2)
    if not isinstance(repositories, AgentRecoveryStreamRepositoryFactoryProtocolV2):
        raise RuntimeV2Error(
            "invalid_agent_recovery_repository_provider",
            "Agent recovery repository Provider has an invalid implementation",
        )
    llm_clients = context.require(AGENT_RECOVERY_STREAM_LLM_CLIENTS_INJECT_V2)
    if not isinstance(llm_clients, TenantLlmClientFactoryProtocolV2):
        raise RuntimeV2Error(
            "invalid_agent_recovery_llm_provider",
            "Agent recovery LLM Provider has an invalid implementation",
        )
    redis = context.require(AGENT_RECOVERY_STREAM_REDIS_INJECT_V2)
    if not isinstance(redis, RedisRuntimeServiceV2):
        raise RuntimeV2Error(
            "invalid_agent_recovery_redis_provider",
            "Agent recovery Redis Provider has an invalid implementation",
        )
    _ = context.provide(
        AGENT_RECOVERY_STREAM_SERVICE_V2,
        AgentRecoveryStreamResolverV2(
            repositories=repositories,
            llm_clients=llm_clients,
            redis=redis,
        ),
        label="agent-recovery-stream",
    )


def agent_recovery_stream_service_definitions_v2() -> tuple[PluginDefinitionV2, ...]:
    """Return the persistence Provider and Agent recovery Consumer definitions."""
    return (
        PluginDefinitionV2(
            module_ref=AGENT_RECOVERY_STREAM_REPOSITORY_PROVIDER_MODULE_V2,
            contract_digest=generated_contract_digest_v2(
                AGENT_RECOVERY_STREAM_REPOSITORY_PROVIDER_MODULE_V2
            ),
            apply=_apply_agent_recovery_stream_repository_provider_v2,
        ),
        PluginDefinitionV2(
            module_ref=AGENT_RECOVERY_STREAM_MODULE_V2,
            contract_digest=generated_contract_digest_v2(AGENT_RECOVERY_STREAM_MODULE_V2),
            apply=_apply_agent_recovery_stream_v2,
        ),
    )


__all__ = [
    "AGENT_RECOVERY_STREAM_LLM_CLIENTS_INJECT_V2",
    "AGENT_RECOVERY_STREAM_MODULE_V2",
    "AGENT_RECOVERY_STREAM_REDIS_INJECT_V2",
    "AGENT_RECOVERY_STREAM_REPOSITORIES_INJECT_V2",
    "AGENT_RECOVERY_STREAM_REPOSITORY_PROVIDER_MODULE_V2",
    "AGENT_RECOVERY_STREAM_REPOSITORY_PROVIDER_SERVICE_V2",
    "AGENT_RECOVERY_STREAM_SERVICE_V2",
    "AgentRecoveryStreamRepositoriesV2",
    "AgentRecoveryStreamRepositoryFactoryProtocolV2",
    "AgentRecoveryStreamResolverProtocolV2",
    "AgentRecoveryStreamResolverV2",
    "AgentRecoveryStreamServiceV2",
    "SqlAgentRecoveryStreamRepositoryFactoryV2",
    "agent_recovery_stream_service_definitions_v2",
]
