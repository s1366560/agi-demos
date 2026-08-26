# pyright: reportImportCycles=false
"""FastAPI authority dependency for generation-owned attachment services."""

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
from src.infrastructure.plugins.v2.attachment_services import (
    ATTACHMENT_APPLICATION_SERVICE_V2,
    AttachmentApplicationResolverProtocolV2,
    AttachmentApplicationServicesV2,
)
from src.infrastructure.plugins.v2.boundary import (
    OPERATION_DB_SESSION_SERVICE_V2,
    OPERATION_IDENTITY_SERVICE_V2,
    OPERATION_METADATA_SERVICE_V2,
    current_generation_v2,
)
from src.infrastructure.plugins.v2.runtime import OperationContextV2, RuntimeV2Error


@dataclass(frozen=True, kw_only=True)
class AttachmentApplicationAuthorityV2:
    """Request-owned attachment services and their disposable operation boundary."""

    operation: OperationContextV2
    db: AsyncSession
    current_user: User
    services: AttachmentApplicationServicesV2


def _route_template(request: Request) -> str:
    route = request.scope.get("route")
    route_path = getattr(route, "path", None)
    return route_path if isinstance(route_path, str) else "-"


async def attachment_application_authority_dependency_v2(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AsyncIterator[AttachmentApplicationAuthorityV2]:
    """Yield attachment services from the generation pinned to this HTTP request."""
    operation = OperationContextV2(
        generation=current_generation_v2(),
        operation_id=f"http-attachment-application:{uuid4()}",
        scope=ScopeV2(kind=ScopeKindV2.ROOT),
    )
    async with operation:
        _ = operation.provide(OPERATION_DB_SESSION_SERVICE_V2, db)
        _ = operation.provide(
            OPERATION_IDENTITY_SERVICE_V2,
            {
                "tenant_id": None,
                "user_id": str(current_user.id),
                "is_superuser": bool(current_user.is_superuser),
            },
        )
        _ = operation.provide(
            OPERATION_METADATA_SERVICE_V2,
            {
                "kind": "http-authority",
                "method": request.method,
                "path": _route_template(request),
            },
        )
        resolver = operation.require(ATTACHMENT_APPLICATION_SERVICE_V2)
        if not isinstance(resolver, AttachmentApplicationResolverProtocolV2):
            raise RuntimeV2Error(
                "invalid_attachment_application_resolver",
                "attachment application service has an invalid implementation",
            )
        yield AttachmentApplicationAuthorityV2(
            operation=operation,
            db=db,
            current_user=current_user,
            services=resolver.resolve(operation),
        )


__all__ = [
    "AttachmentApplicationAuthorityV2",
    "attachment_application_authority_dependency_v2",
]
