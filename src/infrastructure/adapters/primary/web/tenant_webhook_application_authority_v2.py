# pyright: reportImportCycles=false
"""FastAPI authority for generation-owned tenant webhook services."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from uuid import uuid4

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.auth.user import User
from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.plugins.v2.boundary import (
    OPERATION_DB_SESSION_SERVICE_V2,
    OPERATION_IDENTITY_SERVICE_V2,
    OPERATION_METADATA_SERVICE_V2,
    current_generation_v2,
)
from src.infrastructure.plugins.v2.runtime import OperationContextV2, RuntimeV2Error
from src.infrastructure.plugins.v2.tenant_webhook_services import (
    TENANT_WEBHOOK_APPLICATION_SERVICE_V2,
    TenantWebhookApplicationResolverProtocolV2,
    TenantWebhookApplicationServicesV2,
)


@dataclass(frozen=True, kw_only=True)
class TenantWebhookApplicationAuthorityV2:
    """Request's immutable generation lease and tenant webhook services."""

    operation: OperationContextV2
    db: AsyncSession
    current_user: User
    tenant_id: str | None
    services: TenantWebhookApplicationServicesV2


@asynccontextmanager
async def tenant_webhook_application_authority_context_v2(
    *,
    request: Request,
    current_user: User,
    db: AsyncSession,
    tenant_id: str | None,
) -> AsyncIterator[TenantWebhookApplicationAuthorityV2]:
    """Pin one generation and resolve operation-scoped webhook services."""
    scope = (
        ScopeV2(kind=ScopeKindV2.ROOT)
        if tenant_id is None
        else ScopeV2(kind=ScopeKindV2.TENANT, tenant_id=tenant_id)
    )
    operation = OperationContextV2(
        generation=current_generation_v2(),
        operation_id=f"http-tenant-webhooks:{uuid4()}",
        scope=scope,
    )
    async with operation:
        _ = operation.provide(OPERATION_DB_SESSION_SERVICE_V2, db)
        identity = {"user_id": str(current_user.id)}
        if tenant_id is not None:
            identity["tenant_id"] = tenant_id
        _ = operation.provide(OPERATION_IDENTITY_SERVICE_V2, identity)
        _ = operation.provide(
            OPERATION_METADATA_SERVICE_V2,
            {"kind": "http-authority", "method": request.method, "path": request.url.path},
        )
        resolver = operation.require(TENANT_WEBHOOK_APPLICATION_SERVICE_V2)
        if not isinstance(resolver, TenantWebhookApplicationResolverProtocolV2):
            raise RuntimeV2Error(
                "invalid_tenant_webhook_application_resolver",
                "tenant webhook application service has an invalid implementation",
            )
        yield TenantWebhookApplicationAuthorityV2(
            operation=operation,
            db=db,
            current_user=current_user,
            tenant_id=tenant_id,
            services=resolver.resolve(operation),
        )


__all__ = [
    "TenantWebhookApplicationAuthorityV2",
    "tenant_webhook_application_authority_context_v2",
]
