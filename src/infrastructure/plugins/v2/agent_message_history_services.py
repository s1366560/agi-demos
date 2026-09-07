"""Generation-owned persistence and application seams for Agent message history."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.agent import Conversation
from src.domain.model.agent.execution.agent_execution_event import AgentExecutionEvent
from src.domain.model.agent.hitl_request import HITLRequest
from src.domain.model.agent.skill.tool_execution_record import ToolExecutionRecord
from src.domain.ports.repositories.agent_repository import (
    AgentExecutionEventRepository,
    ToolExecutionRecordRepository,
)
from src.domain.ports.repositories.hitl_request_repository import HITLRequestRepositoryPort
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.models import UserTenant
from src.infrastructure.adapters.secondary.persistence.sql_agent_execution_event_repository import (
    SqlAgentExecutionEventRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_hitl_request_repository import (
    SqlHITLRequestRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_tool_execution_record_repository import (
    SqlToolExecutionRecordRepository,
)

from .conversation_access_services import (
    ConversationAccessResolverProtocolV2,
    ConversationAccessServiceV2,
)
from .project_access_services import (
    ProjectAccessDeniedV2,
    ProjectAccessResolverProtocolV2,
    ProjectAccessServiceV2,
)
from .runtime import (
    ContextV2,
    OperationContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

AGENT_MESSAGE_HISTORY_REPOSITORY_PROVIDER_MODULE_V2 = (
    "builtin://memstack/persistence/agent-message-history-repository-provider"
)
AGENT_MESSAGE_HISTORY_REPOSITORY_PROVIDER_SERVICE_V2 = (
    "service:persistence.agent-message-history-repository-provider"
)
AGENT_MESSAGE_HISTORY_MODULE_V2 = "builtin://memstack/application/agent-message-history"
AGENT_MESSAGE_HISTORY_SERVICE_V2 = "service:application.agent-message-history"
AGENT_MESSAGE_HISTORY_REPOSITORIES_INJECT_V2 = "repositories"
AGENT_MESSAGE_HISTORY_CONVERSATION_ACCESS_INJECT_V2 = "conversation_access"
AGENT_MESSAGE_HISTORY_PROJECT_ACCESS_INJECT_V2 = "project_access"
_OPERATION_DB_SESSION_SERVICE_V2 = "service:operation.db-session"


class AgentMessageHistoryErrorV2(RuntimeError):
    """Base failure for the Agent message-history application seam."""


class AgentMessageHistoryConversationNotFoundV2(AgentMessageHistoryErrorV2):
    """The requested conversation is absent from the exact tenant scope."""


class AgentMessageHistoryAccessDeniedV2(AgentMessageHistoryErrorV2):
    """The current identity cannot read the requested conversation history."""


@dataclass(frozen=True, kw_only=True)
class AgentMessageHistoryRepositoriesV2:
    """Persistence ports used by one operation-owned history query service."""

    event: AgentExecutionEventRepository
    tool_execution: ToolExecutionRecordRepository
    hitl_request: HITLRequestRepositoryPort
    tenant_membership: AgentMessageHistoryTenantMembershipProtocolV2


@runtime_checkable
class AgentMessageHistoryTenantMembershipProtocolV2(Protocol):
    """Structural tenant-membership lookup required by message-history reads."""

    async def contains(self, *, tenant_id: str, user_id: str) -> bool: ...


@dataclass(frozen=True, kw_only=True)
class SqlAgentMessageHistoryTenantMembershipV2:
    """Check one exact UserTenant tuple through the operation-owned session."""

    db: AsyncSession

    async def contains(self, *, tenant_id: str, user_id: str) -> bool:
        result = await self.db.execute(
            refresh_select_statement(
                select(UserTenant.id)
                .where(
                    UserTenant.user_id == user_id,
                    UserTenant.tenant_id == tenant_id,
                )
                .limit(1)
            )
        )
        return result.scalar_one_or_none() is not None


@runtime_checkable
class AgentMessageHistoryRepositoryFactoryProtocolV2(Protocol):
    """Build message-history repositories from an operation-owned DB session."""

    def build(self, operation: OperationContextV2) -> AgentMessageHistoryRepositoriesV2: ...


@dataclass(frozen=True, kw_only=True)
class SqlAgentMessageHistoryRepositoryFactoryV2:
    """Hide SQL repository implementations behind an explicit Provider seam."""

    strategy: str

    def build(self, operation: OperationContextV2) -> AgentMessageHistoryRepositoriesV2:
        db = operation.require(_OPERATION_DB_SESSION_SERVICE_V2)
        if not isinstance(db, AsyncSession):
            raise RuntimeV2Error(
                "invalid_operation_db_session",
                "Agent message history requires an AsyncSession operation service",
            )
        return AgentMessageHistoryRepositoriesV2(
            event=SqlAgentExecutionEventRepository(db),
            tool_execution=SqlToolExecutionRecordRepository(db),
            hitl_request=SqlHITLRequestRepository(db),
            tenant_membership=SqlAgentMessageHistoryTenantMembershipV2(db=db),
        )


def _require_identifier(value: str, *, field_name: str) -> None:
    if not value.strip():
        raise ValueError(f"{field_name} must be non-empty")


@dataclass(frozen=True, kw_only=True)
class AgentMessageHistoryServiceV2:
    """Operation-owned authorization and history query surface."""

    repositories: AgentMessageHistoryRepositoriesV2
    conversation_access: ConversationAccessServiceV2
    project_access: ProjectAccessServiceV2

    async def require_conversation_access(
        self,
        *,
        conversation_id: str,
        tenant_id: str,
        project_id: str,
        user_id: str,
    ) -> Conversation:
        """Authorize exact conversation ownership before any history read."""
        _require_identifier(conversation_id, field_name="conversation_id")
        _require_identifier(tenant_id, field_name="tenant_id")
        _require_identifier(project_id, field_name="project_id")
        _require_identifier(user_id, field_name="user_id")
        conversation = await self.conversation_access.find_by_id(conversation_id)
        if conversation is None or conversation.tenant_id != tenant_id:
            raise AgentMessageHistoryConversationNotFoundV2(conversation_id)
        if conversation.project_id != project_id or conversation.user_id != user_id:
            raise AgentMessageHistoryAccessDeniedV2(conversation_id)
        if not await self.repositories.tenant_membership.contains(
            tenant_id=tenant_id,
            user_id=user_id,
        ):
            raise AgentMessageHistoryAccessDeniedV2(conversation_id)
        try:
            _grant = await self.project_access.require_access(
                project_id=project_id,
                tenant_id=tenant_id,
                user_id=user_id,
            )
        except ProjectAccessDeniedV2 as exc:
            raise AgentMessageHistoryAccessDeniedV2(conversation_id) from exc
        return conversation

    async def get_last_event_time(self, conversation_id: str) -> tuple[int, int]:
        _require_identifier(conversation_id, field_name="conversation_id")
        return await self.repositories.event.get_last_event_time(conversation_id)

    async def get_events(
        self,
        conversation_id: str,
        from_time_us: int = 0,
        from_counter: int = 0,
        limit: int = 1000,
        event_types: set[str] | None = None,
        before_time_us: int | None = None,
        before_counter: int | None = None,
    ) -> list[AgentExecutionEvent]:
        _require_identifier(conversation_id, field_name="conversation_id")
        return await self.repositories.event.get_events(
            conversation_id=conversation_id,
            from_time_us=from_time_us,
            from_counter=from_counter,
            limit=limit,
            event_types=event_types,
            before_time_us=before_time_us,
            before_counter=before_counter,
        )

    async def get_events_by_message_ids(
        self,
        conversation_id: str,
        message_ids: set[str],
    ) -> dict[str, list[AgentExecutionEvent]]:
        _require_identifier(conversation_id, field_name="conversation_id")
        return await self.repositories.event.get_events_by_message_ids(
            conversation_id,
            message_ids,
        )

    async def list_tool_executions(
        self,
        *,
        conversation_id: str,
        message_id: str | None,
        limit: int = 100,
    ) -> list[ToolExecutionRecord]:
        _require_identifier(conversation_id, field_name="conversation_id")
        if message_id is None:
            return await self.repositories.tool_execution.list_by_conversation(
                conversation_id,
                limit=limit,
            )
        _require_identifier(message_id, field_name="message_id")
        records = await self.repositories.tool_execution.list_by_message(message_id, limit=limit)
        return [record for record in records if record.conversation_id == conversation_id]

    async def list_hitl_requests(self, conversation_id: str) -> list[HITLRequest]:
        _require_identifier(conversation_id, field_name="conversation_id")
        return await self.repositories.hitl_request.get_by_conversation(conversation_id)


@runtime_checkable
class AgentMessageHistoryResolverProtocolV2(Protocol):
    """Resolve one operation-owned history service from declared aliases."""

    def resolve(self, operation: OperationContextV2) -> AgentMessageHistoryServiceV2: ...


@dataclass(frozen=True, kw_only=True)
class AgentMessageHistoryResolverV2:
    """Compose history queries from repository and authorization Providers."""

    repositories: AgentMessageHistoryRepositoryFactoryProtocolV2
    conversation_access: ConversationAccessResolverProtocolV2
    project_access: ProjectAccessResolverProtocolV2

    def resolve(self, operation: OperationContextV2) -> AgentMessageHistoryServiceV2:
        return AgentMessageHistoryServiceV2(
            repositories=self.repositories.build(operation),
            conversation_access=self.conversation_access.resolve(operation),
            project_access=self.project_access.resolve(operation),
        )


def _apply_agent_message_history_repository_provider_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    strategy = config.get("strategy")
    if strategy != "request-async-session":
        raise ValueError(
            "Agent message history repository Provider requires strategy request-async-session"
        )
    _ = context.provide(
        AGENT_MESSAGE_HISTORY_REPOSITORY_PROVIDER_SERVICE_V2,
        SqlAgentMessageHistoryRepositoryFactoryV2(strategy=strategy),
        label="agent-message-history-repository-provider",
    )


def _apply_agent_message_history_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    if config.get("strategy") != "operation-scoped-providers":
        raise ValueError("Agent message history requires strategy operation-scoped-providers")
    repositories = context.require(AGENT_MESSAGE_HISTORY_REPOSITORIES_INJECT_V2)
    if not isinstance(repositories, AgentMessageHistoryRepositoryFactoryProtocolV2):
        raise RuntimeV2Error(
            "invalid_agent_message_history_repository_provider",
            "Agent message history repository Provider has an invalid implementation",
        )
    conversation_access = context.require(AGENT_MESSAGE_HISTORY_CONVERSATION_ACCESS_INJECT_V2)
    if not isinstance(conversation_access, ConversationAccessResolverProtocolV2):
        raise RuntimeV2Error(
            "invalid_agent_message_history_conversation_access",
            "Agent message history conversation access has an invalid implementation",
        )
    project_access = context.require(AGENT_MESSAGE_HISTORY_PROJECT_ACCESS_INJECT_V2)
    if not isinstance(project_access, ProjectAccessResolverProtocolV2):
        raise RuntimeV2Error(
            "invalid_agent_message_history_project_access",
            "Agent message history project access has an invalid implementation",
        )
    _ = context.provide(
        AGENT_MESSAGE_HISTORY_SERVICE_V2,
        AgentMessageHistoryResolverV2(
            repositories=repositories,
            conversation_access=conversation_access,
            project_access=project_access,
        ),
        label="agent-message-history",
    )


def agent_message_history_service_definitions_v2() -> tuple[PluginDefinitionV2, ...]:
    """Return the history persistence Provider and application Consumer."""
    return (
        PluginDefinitionV2(
            module_ref=AGENT_MESSAGE_HISTORY_REPOSITORY_PROVIDER_MODULE_V2,
            contract_digest=generated_contract_digest_v2(
                AGENT_MESSAGE_HISTORY_REPOSITORY_PROVIDER_MODULE_V2
            ),
            apply=_apply_agent_message_history_repository_provider_v2,
        ),
        PluginDefinitionV2(
            module_ref=AGENT_MESSAGE_HISTORY_MODULE_V2,
            contract_digest=generated_contract_digest_v2(AGENT_MESSAGE_HISTORY_MODULE_V2),
            apply=_apply_agent_message_history_v2,
        ),
    )


__all__ = [
    "AGENT_MESSAGE_HISTORY_CONVERSATION_ACCESS_INJECT_V2",
    "AGENT_MESSAGE_HISTORY_MODULE_V2",
    "AGENT_MESSAGE_HISTORY_PROJECT_ACCESS_INJECT_V2",
    "AGENT_MESSAGE_HISTORY_REPOSITORIES_INJECT_V2",
    "AGENT_MESSAGE_HISTORY_REPOSITORY_PROVIDER_MODULE_V2",
    "AGENT_MESSAGE_HISTORY_REPOSITORY_PROVIDER_SERVICE_V2",
    "AGENT_MESSAGE_HISTORY_SERVICE_V2",
    "AgentMessageHistoryAccessDeniedV2",
    "AgentMessageHistoryConversationNotFoundV2",
    "AgentMessageHistoryErrorV2",
    "AgentMessageHistoryRepositoriesV2",
    "AgentMessageHistoryRepositoryFactoryProtocolV2",
    "AgentMessageHistoryResolverProtocolV2",
    "AgentMessageHistoryResolverV2",
    "AgentMessageHistoryServiceV2",
    "AgentMessageHistoryTenantMembershipProtocolV2",
    "SqlAgentMessageHistoryRepositoryFactoryV2",
    "SqlAgentMessageHistoryTenantMembershipV2",
    "agent_message_history_service_definitions_v2",
]
