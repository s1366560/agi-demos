"""FastAPI authority for generation-owned MCP application services."""

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
from src.infrastructure.plugins.v2.mcp_services import (
    MCP_APPLICATION_SERVICE_V2,
    MCPApplicationResolverProtocolV2,
    MCPApplicationServicesV2,
)
from src.infrastructure.plugins.v2.runtime import OperationContextV2, RuntimeV2Error


@dataclass(frozen=True, kw_only=True)
class MCPApplicationAuthorityV2:
    """Request-owned MCP services and their disposable operation boundary."""

    operation: OperationContextV2
    db: AsyncSession
    tenant_id: str
    user_id: str
    services: MCPApplicationServicesV2


async def mcp_application_authority_dependency_v2(
    request: Request,
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> AsyncIterator[MCPApplicationAuthorityV2]:
    """Yield tenant-scoped MCP services from the generation pinned to this request."""
    scope = ScopeV2(kind=ScopeKindV2.TENANT, tenant_id=tenant_id)
    operation = OperationContextV2(
        generation=current_generation_v2(),
        operation_id=f"http-mcp-application:{uuid4()}",
        scope=scope,
    )
    async with operation:
        _ = operation.provide(OPERATION_DB_SESSION_SERVICE_V2, db)
        _ = operation.provide(
            OPERATION_IDENTITY_SERVICE_V2,
            {"tenant_id": tenant_id, "user_id": current_user.id},
        )
        _ = operation.provide(
            OPERATION_METADATA_SERVICE_V2,
            {
                "kind": "http-mcp-authority",
                "method": request.method,
                "path": request.url.path,
            },
        )
        resolver = operation.require(MCP_APPLICATION_SERVICE_V2)
        if not isinstance(resolver, MCPApplicationResolverProtocolV2):
            raise RuntimeV2Error(
                "invalid_mcp_application_resolver",
                "MCP application service has an invalid implementation",
            )
        yield MCPApplicationAuthorityV2(
            operation=operation,
            db=db,
            tenant_id=tenant_id,
            user_id=current_user.id,
            services=resolver.resolve(operation),
        )


__all__ = [
    "MCPApplicationAuthorityV2",
    "mcp_application_authority_dependency_v2",
]
