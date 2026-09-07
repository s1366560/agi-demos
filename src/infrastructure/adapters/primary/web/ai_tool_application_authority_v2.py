# pyright: reportImportCycles=false
"""FastAPI authority dependency for generation-owned lightweight AI tools."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from uuid import uuid4

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import User
from src.infrastructure.plugins.v2.ai_tool_services import (
    AI_TOOL_APPLICATION_SERVICE_V2,
    AiToolApplicationResolverProtocolV2,
    AiToolApplicationServicesV2,
)
from src.infrastructure.plugins.v2.boundary import (
    OPERATION_DB_SESSION_SERVICE_V2,
    OPERATION_IDENTITY_SERVICE_V2,
    OPERATION_METADATA_SERVICE_V2,
    current_generation_v2,
)
from src.infrastructure.plugins.v2.runtime import OperationContextV2, RuntimeV2Error


@dataclass(frozen=True, kw_only=True)
class AiToolApplicationAuthorityV2:
    """Request-owned AI-tool services and their disposable operation boundary."""

    operation: OperationContextV2
    db: AsyncSession
    user_id: str
    tenant_id: str | None
    services: AiToolApplicationServicesV2


async def ai_tool_application_authority_dependency_v2(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AsyncIterator[AiToolApplicationAuthorityV2]:
    """Yield AI-tool services from the generation pinned to this request."""
    tenant_id = _tenant_id_v2(getattr(current_user, "tenant_id", None))
    user_id = str(current_user.id)
    scope = (
        ScopeV2(kind=ScopeKindV2.TENANT, tenant_id=tenant_id)
        if tenant_id is not None
        else ScopeV2(kind=ScopeKindV2.ROOT)
    )
    operation = OperationContextV2(
        generation=current_generation_v2(),
        operation_id=f"http-ai-tool-application:{uuid4()}",
        scope=scope,
    )
    async with operation:
        _ = operation.provide(OPERATION_DB_SESSION_SERVICE_V2, db)
        _ = operation.provide(
            OPERATION_IDENTITY_SERVICE_V2,
            {
                "tenant_id": tenant_id,
                "user_id": user_id,
                "is_superuser": bool(current_user.is_superuser),
            },
        )
        _ = operation.provide(
            OPERATION_METADATA_SERVICE_V2,
            {"kind": "http-authority", "method": request.method, "path": request.url.path},
        )
        resolver = operation.require(AI_TOOL_APPLICATION_SERVICE_V2)
        if not isinstance(resolver, AiToolApplicationResolverProtocolV2):
            raise RuntimeV2Error(
                "invalid_ai_tool_application_resolver",
                "ai-tool application service has an invalid implementation",
            )
        yield AiToolApplicationAuthorityV2(
            operation=operation,
            db=db,
            user_id=user_id,
            tenant_id=tenant_id,
            services=resolver.resolve(operation),
        )


def _tenant_id_v2(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


__all__ = [
    "AiToolApplicationAuthorityV2",
    "ai_tool_application_authority_dependency_v2",
]
