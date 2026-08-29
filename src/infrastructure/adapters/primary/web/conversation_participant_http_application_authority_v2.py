# pyright: reportImportCycles=false
"""FastAPI authority for generation-owned conversation participant services."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from uuid import uuid4

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.adapters.primary.web.dependencies import (
    get_current_user,
    get_current_user_tenant,
)
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import User
from src.infrastructure.plugins.v2.boundary import (
    OPERATION_DB_SESSION_SERVICE_V2,
    OPERATION_IDENTITY_SERVICE_V2,
    OPERATION_METADATA_SERVICE_V2,
    bind_operation_context_v2,
    current_generation_v2,
)
from src.infrastructure.plugins.v2.conversation_participant_services import (
    CONVERSATION_PARTICIPANT_SERVICE_V2,
    ConversationParticipantResolverProtocolV2,
    ConversationParticipantServiceV2,
)
from src.infrastructure.plugins.v2.runtime import OperationContextV2, RuntimeV2Error


@dataclass(frozen=True, kw_only=True)
class ConversationParticipantHttpApplicationAuthorityV2:
    """Request-owned participant service and disposable tenant operation."""

    operation: OperationContextV2
    db: AsyncSession
    service: ConversationParticipantServiceV2


@asynccontextmanager
async def conversation_participant_http_application_authority_v2(
    *,
    request: Request,
    current_user: User,
    tenant_id: str,
    db: AsyncSession,
) -> AsyncIterator[ConversationParticipantHttpApplicationAuthorityV2]:
    """Resolve participant authority before the conversation's project is known."""
    operation = OperationContextV2(
        generation=current_generation_v2(),
        operation_id=f"http-conversation-participants:{uuid4()}",
        scope=ScopeV2(kind=ScopeKindV2.TENANT, tenant_id=tenant_id),
    )
    async with operation:
        _ = operation.provide(OPERATION_DB_SESSION_SERVICE_V2, db)
        _ = operation.provide(
            OPERATION_IDENTITY_SERVICE_V2,
            {"tenant_id": tenant_id, "user_id": str(current_user.id)},
        )
        _ = operation.provide(
            OPERATION_METADATA_SERVICE_V2,
            {"kind": "http-authority", "method": request.method, "path": request.url.path},
        )
        resolver = operation.require(CONVERSATION_PARTICIPANT_SERVICE_V2)
        if not isinstance(resolver, ConversationParticipantResolverProtocolV2):
            raise RuntimeV2Error(
                "invalid_conversation_participant_resolver",
                "conversation participant service has an invalid implementation",
            )
        with bind_operation_context_v2(operation):
            yield ConversationParticipantHttpApplicationAuthorityV2(
                operation=operation,
                db=db,
                service=resolver.resolve(operation),
            )


async def conversation_participant_http_application_authority_dependency_v2(
    request: Request,
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> AsyncIterator[ConversationParticipantHttpApplicationAuthorityV2]:
    async with conversation_participant_http_application_authority_v2(
        request=request,
        current_user=current_user,
        tenant_id=tenant_id,
        db=db,
    ) as authority:
        yield authority


__all__ = [
    "ConversationParticipantHttpApplicationAuthorityV2",
    "conversation_participant_http_application_authority_dependency_v2",
    "conversation_participant_http_application_authority_v2",
]
