# pyright: reportImportCycles=false
"""FastAPI authority for generation-owned cluster services."""

from __future__ import annotations

from collections.abc import AsyncIterator
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
    current_generation_v2,
)
from src.infrastructure.plugins.v2.cluster_services import (
    CLUSTER_APPLICATION_SERVICE_V2,
    ClusterApplicationResolverProtocolV2,
    ClusterApplicationServicesV2,
)
from src.infrastructure.plugins.v2.runtime import OperationContextV2, RuntimeV2Error


@dataclass(frozen=True, kw_only=True)
class ClusterApplicationAuthorityV2:
    """Tenant request's immutable generation lease and cluster services."""

    operation: OperationContextV2
    db: AsyncSession
    current_user: User
    tenant_id: str
    services: ClusterApplicationServicesV2


async def cluster_application_authority_dependency_v2(
    request: Request,
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> AsyncIterator[ClusterApplicationAuthorityV2]:
    """Yield cluster services from the generation pinned to this request."""
    operation = OperationContextV2(
        generation=current_generation_v2(),
        operation_id=f"http-clusters:{uuid4()}",
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
        resolver = operation.require(CLUSTER_APPLICATION_SERVICE_V2)
        if not isinstance(resolver, ClusterApplicationResolverProtocolV2):
            raise RuntimeV2Error(
                "invalid_cluster_application_resolver",
                "cluster application service has an invalid implementation",
            )
        yield ClusterApplicationAuthorityV2(
            operation=operation,
            db=db,
            current_user=current_user,
            tenant_id=tenant_id,
            services=resolver.resolve(operation),
        )


__all__ = [
    "ClusterApplicationAuthorityV2",
    "cluster_application_authority_dependency_v2",
]
