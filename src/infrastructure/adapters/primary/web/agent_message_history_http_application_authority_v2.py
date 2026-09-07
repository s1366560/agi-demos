# pyright: reportImportCycles=false
"""FastAPI authority for generation-owned Agent message history queries."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from uuid import uuid4

from fastapi import Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.adapters.primary.web.dependencies import (
    get_current_user,
    get_current_user_tenant,
)
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import User
from src.infrastructure.i18n import gettext as _
from src.infrastructure.plugins.v2.agent_message_history_services import (
    AGENT_MESSAGE_HISTORY_SERVICE_V2,
    AgentMessageHistoryAccessDeniedV2,
    AgentMessageHistoryConversationNotFoundV2,
    AgentMessageHistoryResolverProtocolV2,
    AgentMessageHistoryServiceV2,
)
from src.infrastructure.plugins.v2.boundary import (
    OPERATION_DB_SESSION_SERVICE_V2,
    OPERATION_IDENTITY_SERVICE_V2,
    OPERATION_METADATA_SERVICE_V2,
    current_generation_v2,
)
from src.infrastructure.plugins.v2.runtime import OperationContextV2, RuntimeV2Error


@dataclass(frozen=True, kw_only=True)
class AgentMessageHistoryHttpApplicationAuthorityV2:
    """Request-owned history query service and disposable operation."""

    operation: OperationContextV2
    service: AgentMessageHistoryServiceV2


async def agent_message_history_http_application_authority_dependency_v2(
    conversation_id: str,
    request: Request,
    project_id: str = Query(..., description="Project ID for authorization"),
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> AsyncIterator[AgentMessageHistoryHttpApplicationAuthorityV2]:
    """Authorize and yield history queries from the request's pinned generation."""
    operation = OperationContextV2(
        generation=current_generation_v2(),
        operation_id=f"http-agent-message-history:{uuid4()}",
        scope=ScopeV2(
            kind=ScopeKindV2.PROJECT,
            tenant_id=tenant_id,
            project_id=project_id,
        ),
    )
    async with operation:
        _db_effect = operation.provide(OPERATION_DB_SESSION_SERVICE_V2, db)
        _identity_effect = operation.provide(
            OPERATION_IDENTITY_SERVICE_V2,
            {
                "tenant_id": tenant_id,
                "project_id": project_id,
                "user_id": str(current_user.id),
            },
        )
        _metadata_effect = operation.provide(
            OPERATION_METADATA_SERVICE_V2,
            {"kind": "http-authority", "method": request.method, "path": request.url.path},
        )
        resolver = operation.require(AGENT_MESSAGE_HISTORY_SERVICE_V2)
        if not isinstance(resolver, AgentMessageHistoryResolverProtocolV2):
            raise RuntimeV2Error(
                "invalid_agent_message_history_resolver",
                "Agent message history service has an invalid resolver",
            )
        service = resolver.resolve(operation)
        try:
            _conversation = await service.require_conversation_access(
                conversation_id=conversation_id,
                tenant_id=tenant_id,
                project_id=project_id,
                user_id=str(current_user.id),
            )
        except AgentMessageHistoryConversationNotFoundV2 as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=_("Conversation not found"),
            ) from exc
        except AgentMessageHistoryAccessDeniedV2 as exc:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=_("Access denied"),
            ) from exc
        yield AgentMessageHistoryHttpApplicationAuthorityV2(
            operation=operation,
            service=service,
        )


__all__ = [
    "AgentMessageHistoryHttpApplicationAuthorityV2",
    "agent_message_history_http_application_authority_dependency_v2",
]
