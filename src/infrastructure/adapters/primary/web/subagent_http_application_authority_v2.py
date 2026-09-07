# pyright: reportImportCycles=false, reportUnnecessaryIsInstance=false
"""FastAPI authority for generation-owned SubAgent management."""

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
from src.infrastructure.plugins.v2.runtime import OperationContextV2, RuntimeV2Error
from src.infrastructure.plugins.v2.subagent_management_services import (
    SUBAGENT_MANAGEMENT_SERVICE_V2,
    SubAgentManagementResolverProtocolV2,
    SubAgentManagementServiceProtocolV2,
)


@dataclass(frozen=True, kw_only=True)
class SubAgentHttpApplicationAuthorityV2:
    """Request-owned SubAgent service and disposable operation."""

    operation: OperationContextV2
    service: SubAgentManagementServiceProtocolV2


@asynccontextmanager
async def subagent_http_application_authority_v2(
    *,
    request: Request,
    tenant_id: str,
    current_user: User,
    db: AsyncSession,
) -> AsyncIterator[SubAgentHttpApplicationAuthorityV2]:
    """Yield SubAgent management from the generation pinned to this request."""
    operation = OperationContextV2(
        generation=current_generation_v2(),
        operation_id=f"http-subagent-management:{uuid4()}",
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
        resolver = operation.require(SUBAGENT_MANAGEMENT_SERVICE_V2)
        if not isinstance(resolver, SubAgentManagementResolverProtocolV2):
            raise RuntimeV2Error(
                "invalid_subagent_management_resolver",
                "SubAgent management service has an invalid resolver",
            )
        service = resolver.resolve(operation)
        if not isinstance(service, SubAgentManagementServiceProtocolV2):
            raise RuntimeV2Error(
                "invalid_subagent_management_service",
                "SubAgent management resolver returned an invalid service",
            )
        yield SubAgentHttpApplicationAuthorityV2(
            operation=operation,
            service=service,
        )


__all__ = [
    "SubAgentHttpApplicationAuthorityV2",
    "subagent_http_application_authority_v2",
]
