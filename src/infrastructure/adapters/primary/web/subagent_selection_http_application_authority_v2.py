# pyright: reportImportCycles=false, reportUnnecessaryIsInstance=false
"""FastAPI authority for generation-owned SubAgent selection."""

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
from src.infrastructure.plugins.v2.subagent_selection_services import (
    SUBAGENT_SELECTION_APPLICATION_SERVICE_V2,
    SubAgentSelectionApplicationResolverProtocolV2,
    SubAgentSelectionApplicationServiceProtocolV2,
)


@dataclass(frozen=True, kw_only=True)
class SubAgentSelectionHttpApplicationAuthorityV2:
    """Request-owned SubAgent selection service and disposable operation."""

    operation: OperationContextV2
    service: SubAgentSelectionApplicationServiceProtocolV2


@asynccontextmanager
async def subagent_selection_http_application_authority_v2(
    *,
    request: Request,
    tenant_id: str,
    current_user: User,
    db: AsyncSession,
) -> AsyncIterator[SubAgentSelectionHttpApplicationAuthorityV2]:
    """Yield selection from the generation pinned to this request."""
    operation = OperationContextV2(
        generation=current_generation_v2(),
        operation_id=f"http-subagent-selection:{uuid4()}",
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
        resolver = operation.require(SUBAGENT_SELECTION_APPLICATION_SERVICE_V2)
        if not isinstance(resolver, SubAgentSelectionApplicationResolverProtocolV2):
            raise RuntimeV2Error(
                "invalid_subagent_selection_resolver",
                "SubAgent selection service has an invalid resolver",
            )
        service = resolver.resolve(operation)
        if not isinstance(service, SubAgentSelectionApplicationServiceProtocolV2):
            raise RuntimeV2Error(
                "invalid_subagent_selection_service",
                "SubAgent selection resolver returned an invalid service",
            )
        yield SubAgentSelectionHttpApplicationAuthorityV2(
            operation=operation,
            service=service,
        )


__all__ = [
    "SubAgentSelectionHttpApplicationAuthorityV2",
    "subagent_selection_http_application_authority_v2",
]
