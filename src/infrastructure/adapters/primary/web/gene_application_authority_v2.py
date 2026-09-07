# pyright: reportImportCycles=false
"""FastAPI authority for generation-owned Gene marketplace services."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from uuid import uuid4

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.adapters.secondary.persistence.models import User
from src.infrastructure.plugins.v2.boundary import (
    OPERATION_DB_SESSION_SERVICE_V2,
    OPERATION_IDENTITY_SERVICE_V2,
    OPERATION_METADATA_SERVICE_V2,
    current_generation_v2,
)
from src.infrastructure.plugins.v2.gene_services import (
    GENE_APPLICATION_SERVICE_V2,
    GeneApplicationResolverProtocolV2,
    GeneApplicationServicesV2,
)
from src.infrastructure.plugins.v2.runtime import OperationContextV2, RuntimeV2Error


@dataclass(frozen=True, kw_only=True)
class GeneApplicationAuthorityV2:
    """Tenant request's immutable generation lease and Gene services."""

    operation: OperationContextV2
    db: AsyncSession
    current_user: User
    tenant_id: str
    services: GeneApplicationServicesV2


@asynccontextmanager
async def gene_application_authority_context_v2(
    *,
    request: Request,
    current_user: User,
    tenant_id: str,
    db: AsyncSession,
) -> AsyncIterator[GeneApplicationAuthorityV2]:
    """Pin one generation and resolve operation-scoped Gene services."""
    operation = OperationContextV2(
        generation=current_generation_v2(),
        operation_id=f"http-genes:{uuid4()}",
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
        resolver = operation.require(GENE_APPLICATION_SERVICE_V2)
        if not isinstance(resolver, GeneApplicationResolverProtocolV2):
            raise RuntimeV2Error(
                "invalid_gene_application_resolver",
                "Gene application service has an invalid implementation",
            )
        yield GeneApplicationAuthorityV2(
            operation=operation,
            db=db,
            current_user=current_user,
            tenant_id=tenant_id,
            services=resolver.resolve(operation),
        )


__all__ = [
    "GeneApplicationAuthorityV2",
    "gene_application_authority_context_v2",
]
