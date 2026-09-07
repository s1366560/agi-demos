# pyright: reportImportCycles=false
"""FastAPI authorities for generation-owned instance and deploy services."""

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
    get_current_user_from_header_or_query,
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
from src.infrastructure.plugins.v2.instance_deploy_services import (
    INSTANCE_DEPLOY_APPLICATION_SERVICE_V2,
    InstanceDeployApplicationResolverProtocolV2,
    InstanceDeployApplicationServicesV2,
)
from src.infrastructure.plugins.v2.runtime import OperationContextV2, RuntimeV2Error


@dataclass(frozen=True, kw_only=True)
class InstanceDeployApplicationAuthorityV2:
    """Request's immutable generation lease and instance/deploy services."""

    operation: OperationContextV2
    db: AsyncSession
    current_user: User
    tenant_id: str | None
    services: InstanceDeployApplicationServicesV2

    def require_tenant_id(self) -> str:
        """Return the tenant bound by the tenant-scoped authority dependency."""
        if self.tenant_id is None:
            raise RuntimeV2Error(
                "tenant_scope_required",
                "instance application authority requires a tenant scope",
            )
        return self.tenant_id


@asynccontextmanager
async def _authority_context_v2(
    *,
    request: Request,
    current_user: User,
    db: AsyncSession,
    tenant_id: str | None,
    operation_kind: str,
) -> AsyncIterator[InstanceDeployApplicationAuthorityV2]:
    scope = (
        ScopeV2(kind=ScopeKindV2.TENANT, tenant_id=tenant_id)
        if tenant_id is not None
        else ScopeV2(kind=ScopeKindV2.ROOT)
    )
    operation = OperationContextV2(
        generation=current_generation_v2(),
        operation_id=f"{operation_kind}:{uuid4()}",
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
        resolver = operation.require(INSTANCE_DEPLOY_APPLICATION_SERVICE_V2)
        if not isinstance(resolver, InstanceDeployApplicationResolverProtocolV2):
            raise RuntimeV2Error(
                "invalid_instance_deploy_application_resolver",
                "instance/deploy application service has an invalid implementation",
            )
        yield InstanceDeployApplicationAuthorityV2(
            operation=operation,
            db=db,
            current_user=current_user,
            tenant_id=tenant_id,
            services=resolver.resolve(operation),
        )


async def instance_application_authority_dependency_v2(
    request: Request,
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> AsyncIterator[InstanceDeployApplicationAuthorityV2]:
    """Yield tenant-scoped instance services from the pinned request generation."""
    async with _authority_context_v2(
        request=request,
        current_user=current_user,
        db=db,
        tenant_id=tenant_id,
        operation_kind="http-instances",
    ) as authority:
        yield authority


async def deploy_application_authority_dependency_v2(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AsyncIterator[InstanceDeployApplicationAuthorityV2]:
    """Yield root-scoped deploy services until the resource tenant is resolved."""
    async with _authority_context_v2(
        request=request,
        current_user=current_user,
        db=db,
        tenant_id=None,
        operation_kind="http-deploy",
    ) as authority:
        yield authority


async def deploy_progress_application_authority_dependency_v2(
    request: Request,
    current_user: User = Depends(get_current_user_from_header_or_query),
    db: AsyncSession = Depends(get_db),
) -> AsyncIterator[InstanceDeployApplicationAuthorityV2]:
    """Keep the root generation lease for the complete deploy SSE response."""
    async with _authority_context_v2(
        request=request,
        current_user=current_user,
        db=db,
        tenant_id=None,
        operation_kind="http-deploy-progress",
    ) as authority:
        yield authority


__all__ = [
    "InstanceDeployApplicationAuthorityV2",
    "deploy_application_authority_dependency_v2",
    "deploy_progress_application_authority_dependency_v2",
    "instance_application_authority_dependency_v2",
]
