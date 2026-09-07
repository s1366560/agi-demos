# pyright: reportImportCycles=false
"""FastAPI authority dependency for generation-owned notification services."""

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
from src.infrastructure.plugins.v2.boundary import (
    OPERATION_DB_SESSION_SERVICE_V2,
    OPERATION_IDENTITY_SERVICE_V2,
    OPERATION_METADATA_SERVICE_V2,
    current_generation_v2,
)
from src.infrastructure.plugins.v2.notification_services import (
    NOTIFICATION_APPLICATION_SERVICE_V2,
    NotificationApplicationResolverProtocolV2,
    NotificationApplicationServicesV2,
)
from src.infrastructure.plugins.v2.runtime import OperationContextV2, RuntimeV2Error


@dataclass(frozen=True, kw_only=True)
class NotificationApplicationAuthorityV2:
    """Request-owned notification services and their disposable operation boundary."""

    operation: OperationContextV2
    db: AsyncSession
    services: NotificationApplicationServicesV2


async def notification_application_authority_dependency_v2(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AsyncIterator[NotificationApplicationAuthorityV2]:
    """Yield notification services from the generation pinned to this HTTP request."""
    scope = _request_scope_v2(request)
    operation = OperationContextV2(
        generation=current_generation_v2(),
        operation_id=f"http-notification-application:{uuid4()}",
        scope=scope,
    )
    async with operation:
        _ = operation.provide(OPERATION_DB_SESSION_SERVICE_V2, db)
        _ = operation.provide(
            OPERATION_IDENTITY_SERVICE_V2,
            {"tenant_id": scope.tenant_id, "user_id": current_user.id},
        )
        _ = operation.provide(
            OPERATION_METADATA_SERVICE_V2,
            {"kind": "http-authority", "method": request.method, "path": request.url.path},
        )
        resolver = operation.require(NOTIFICATION_APPLICATION_SERVICE_V2)
        if not isinstance(resolver, NotificationApplicationResolverProtocolV2):
            raise RuntimeV2Error(
                "invalid_notification_application_resolver",
                "notification application service has an invalid implementation",
            )
        yield NotificationApplicationAuthorityV2(
            operation=operation,
            db=db,
            services=resolver.resolve(operation),
        )


def _request_scope_v2(request: Request) -> ScopeV2:
    tenant_id = _scope_id_v2(
        request.path_params.get("tenant_id") or request.query_params.get("tenant_id")
    )
    project_id = _scope_id_v2(
        request.path_params.get("project_id") or request.query_params.get("project_id")
    )
    if tenant_id is not None and project_id is not None:
        return ScopeV2(
            kind=ScopeKindV2.PROJECT,
            tenant_id=tenant_id,
            project_id=project_id,
        )
    if tenant_id is not None:
        return ScopeV2(kind=ScopeKindV2.TENANT, tenant_id=tenant_id)
    return ScopeV2(kind=ScopeKindV2.ROOT)


def _scope_id_v2(value: object) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


__all__ = [
    "NotificationApplicationAuthorityV2",
    "notification_application_authority_dependency_v2",
]
