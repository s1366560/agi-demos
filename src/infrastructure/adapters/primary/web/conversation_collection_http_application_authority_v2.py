# pyright: reportImportCycles=false
"""FastAPI authority for generation-owned conversation create/list services."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
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
from src.infrastructure.plugins.v2.boundary import (
    OPERATION_DB_SESSION_SERVICE_V2,
    OPERATION_IDENTITY_SERVICE_V2,
    OPERATION_METADATA_SERVICE_V2,
    bind_operation_context_v2,
    current_generation_v2,
)
from src.infrastructure.plugins.v2.conversation_collection_services import (
    CONVERSATION_COLLECTION_SERVICE_V2,
    ConversationCollectionResolverProtocolV2,
    ConversationCollectionServiceV2,
)
from src.infrastructure.plugins.v2.runtime import OperationContextV2, RuntimeV2Error


@dataclass(frozen=True, kw_only=True)
class ConversationCollectionHttpApplicationAuthorityV2:
    """Request-owned collection service and disposable operation boundary."""

    operation: OperationContextV2
    db: AsyncSession
    service: ConversationCollectionServiceV2


@asynccontextmanager
async def conversation_collection_http_application_authority_v2(
    *,
    request: Request,
    project_id: str,
    current_user: User,
    tenant_id: str,
    db: AsyncSession,
) -> AsyncIterator[ConversationCollectionHttpApplicationAuthorityV2]:
    operation = OperationContextV2(
        generation=current_generation_v2(),
        operation_id=f"http-conversation-collection:{uuid4()}",
        scope=ScopeV2(
            kind=ScopeKindV2.PROJECT,
            tenant_id=tenant_id,
            project_id=project_id,
        ),
    )
    async with operation:
        _ = operation.provide(OPERATION_DB_SESSION_SERVICE_V2, db)
        _ = operation.provide(
            OPERATION_IDENTITY_SERVICE_V2,
            {
                "tenant_id": tenant_id,
                "user_id": str(current_user.id),
                "project_id": project_id,
            },
        )
        _ = operation.provide(
            OPERATION_METADATA_SERVICE_V2,
            {"kind": "http-authority", "method": request.method, "path": request.url.path},
        )
        resolver = operation.require(CONVERSATION_COLLECTION_SERVICE_V2)
        if not isinstance(resolver, ConversationCollectionResolverProtocolV2):
            raise RuntimeV2Error(
                "invalid_conversation_collection_resolver",
                "conversation collection service has an invalid implementation",
            )
        with bind_operation_context_v2(operation):
            yield ConversationCollectionHttpApplicationAuthorityV2(
                operation=operation,
                db=db,
                service=resolver.resolve(operation),
            )


async def conversation_create_http_application_authority_dependency_v2(
    request: Request,
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> AsyncIterator[ConversationCollectionHttpApplicationAuthorityV2]:
    """Yield create authority using the project carried by the request body."""
    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=_("Invalid request"),
        ) from exc
    project_id = payload.get("project_id") if isinstance(payload, Mapping) else None
    if not isinstance(project_id, str):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=_("Invalid request"),
        )
    async with conversation_collection_http_application_authority_v2(
        request=request,
        project_id=project_id,
        current_user=current_user,
        tenant_id=tenant_id,
        db=db,
    ) as authority:
        yield authority


async def conversation_list_http_application_authority_dependency_v2(
    request: Request,
    project_id: str = Query(..., description="Project ID to filter by"),
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> AsyncIterator[ConversationCollectionHttpApplicationAuthorityV2]:
    """Yield list authority using the project carried by the query string."""
    async with conversation_collection_http_application_authority_v2(
        request=request,
        project_id=project_id,
        current_user=current_user,
        tenant_id=tenant_id,
        db=db,
    ) as authority:
        yield authority


__all__ = [
    "ConversationCollectionHttpApplicationAuthorityV2",
    "conversation_collection_http_application_authority_v2",
    "conversation_create_http_application_authority_dependency_v2",
    "conversation_list_http_application_authority_dependency_v2",
]
