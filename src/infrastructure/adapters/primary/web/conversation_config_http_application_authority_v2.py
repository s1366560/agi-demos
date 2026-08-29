# pyright: reportImportCycles=false
"""FastAPI authority for generation-owned conversation configuration."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from uuid import uuid4

from fastapi import Depends, Query, Request
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
    current_generation_v2,
)
from src.infrastructure.plugins.v2.conversation_config_services import (
    CONVERSATION_CONFIG_SERVICE_V2,
    ConversationConfigResolverProtocolV2,
    ConversationConfigServiceV2,
)
from src.infrastructure.plugins.v2.runtime import OperationContextV2, RuntimeV2Error


@dataclass(frozen=True, kw_only=True)
class ConversationConfigHttpApplicationAuthorityV2:
    """Request-owned config service and disposable operation boundary."""

    operation: OperationContextV2
    db: AsyncSession
    service: ConversationConfigServiceV2


async def conversation_config_http_application_authority_dependency_v2(
    request: Request,
    project_id: str = Query(..., description="Project ID for authorization"),
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> AsyncIterator[ConversationConfigHttpApplicationAuthorityV2]:
    """Yield config mutation services from the generation pinned to this request."""
    operation = OperationContextV2(
        generation=current_generation_v2(),
        operation_id=f"http-conversation-config:{uuid4()}",
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
        resolver = operation.require(CONVERSATION_CONFIG_SERVICE_V2)
        if not isinstance(resolver, ConversationConfigResolverProtocolV2):
            raise RuntimeV2Error(
                "invalid_conversation_config_resolver",
                "conversation config service has an invalid implementation",
            )
        yield ConversationConfigHttpApplicationAuthorityV2(
            operation=operation,
            db=db,
            service=resolver.resolve(operation),
        )


__all__ = [
    "ConversationConfigHttpApplicationAuthorityV2",
    "conversation_config_http_application_authority_dependency_v2",
]
