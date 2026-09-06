"""Leased V2 persistence for trusted Workspace Runtime transport operations.

This is not session execution admission. Callers retain their existing authorization
checks and acquire an independent scoped reservation before executing an Agent turn.
"""

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.domain.ports.repositories.agent_repository import (
    AgentExecutionEventRepository,
    ConversationRepository,
)

from .agent_event_query_services import (
    AGENT_EVENT_QUERY_REPOSITORY_PROVIDER_SERVICE_V2,
    AgentEventQueryRepositoryFactoryProtocolV2,
)
from .conversation_access_services import (
    CONVERSATION_REPOSITORY_PROVIDER_SERVICE_V2,
    ConversationRepositoryFactoryProtocolV2,
)
from .runtime import OperationContextV2, RuntimeV2Error
from .scope import validate_scope_v2


@dataclass(frozen=True, kw_only=True)
class WorkspaceRuntimeRepositoriesV2:
    """Persistence adapters valid only while their operation lease remains open."""

    conversation: ConversationRepository
    execution_event: AgentExecutionEventRepository
    operation: OperationContextV2


type RepositoryLeaseV2 = Callable[..., AbstractAsyncContextManager[WorkspaceRuntimeRepositoriesV2]]


@asynccontextmanager
async def lease_workspace_runtime_repositories_v2(
    *, db: AsyncSession, tenant_id: str, project_id: str, conversation_id: str
) -> AsyncIterator[WorkspaceRuntimeRepositoriesV2]:
    """Hold an admitted ROOT provider generation throughout transport persistence.

    Identity validation is structural, not an authorization grant. No ContextVar
    is rebound: an inner scoped Agent turn must retain its own execution authority.
    """
    identity = validate_scope_v2(
        ScopeV2(
            kind=ScopeKindV2.SESSION,
            tenant_id=tenant_id,
            project_id=project_id,
            session_id=conversation_id,
        )
    )
    # boundary imports builtins, so resolve the process host at the operation edge.
    from .boundary import (
        OPERATION_DB_SESSION_SERVICE_V2,
        OPERATION_IDENTITY_SERVICE_V2,
        current_process_generation_host_v2,
    )

    host = current_process_generation_host_v2()
    lease = await host.acquire()
    async with lease as generation, OperationContextV2(
        generation=generation,
        operation_id=f"workspace-runtime-persistence:{uuid4().hex}",
        scope=ScopeV2(kind=ScopeKindV2.ROOT),
    ) as operation:
        _ = operation.provide(OPERATION_DB_SESSION_SERVICE_V2, db)
        _ = operation.provide(
            OPERATION_IDENTITY_SERVICE_V2,
            {
                "tenant_id": identity.tenant_id,
                "project_id": identity.project_id,
                "session_id": identity.session_id,
            },
        )
        conversations = operation.require(CONVERSATION_REPOSITORY_PROVIDER_SERVICE_V2)
        events = operation.require(AGENT_EVENT_QUERY_REPOSITORY_PROVIDER_SERVICE_V2)
        if not isinstance(conversations, ConversationRepositoryFactoryProtocolV2):
            raise RuntimeV2Error(
                "invalid_conversation_repository_provider",
                "Workspace persistence requires a conversation repository provider",
            )
        if not isinstance(events, AgentEventQueryRepositoryFactoryProtocolV2):
            raise RuntimeV2Error(
                "invalid_agent_event_query_repository_provider",
                "Workspace persistence requires an execution event repository provider",
            )
        yield WorkspaceRuntimeRepositoriesV2(
            conversation=conversations.build(operation),
            execution_event=events.build(operation),
            operation=operation,
        )


__all__ = [
    "RepositoryLeaseV2",
    "WorkspaceRuntimeRepositoriesV2",
    "lease_workspace_runtime_repositories_v2",
]
