# pyright: reportImportCycles=false
"""FastAPI authority for generation-owned workflow-pattern services."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from uuid import uuid4

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.auth.user import User
from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.plugins.v2.boundary import (
    OPERATION_DB_SESSION_SERVICE_V2,
    OPERATION_IDENTITY_SERVICE_V2,
    OPERATION_METADATA_SERVICE_V2,
    current_generation_v2,
)
from src.infrastructure.plugins.v2.runtime import OperationContextV2, RuntimeV2Error
from src.infrastructure.plugins.v2.workflow_pattern_services import (
    WORKFLOW_PATTERN_APPLICATION_SERVICE_V2,
    WorkflowPatternApplicationResolverProtocolV2,
    WorkflowPatternApplicationServicesV2,
)


@dataclass(frozen=True, kw_only=True)
class WorkflowPatternApplicationAuthorityV2:
    """Request-owned services and their immutable generation boundary."""

    operation: OperationContextV2
    db: AsyncSession
    current_user: User
    services: WorkflowPatternApplicationServicesV2


async def workflow_pattern_application_authority_dependency_v2(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AsyncIterator[WorkflowPatternApplicationAuthorityV2]:
    """Yield workflow-pattern services from the generation pinned to this request."""
    tenant_id = _scope_id_v2(request.query_params.get("tenant_id"))
    scope = (
        ScopeV2(kind=ScopeKindV2.TENANT, tenant_id=tenant_id)
        if tenant_id is not None
        else ScopeV2(kind=ScopeKindV2.ROOT)
    )
    operation = OperationContextV2(
        generation=current_generation_v2(),
        operation_id=f"http-workflow-pattern:{uuid4()}",
        scope=scope,
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
        resolver = operation.require(WORKFLOW_PATTERN_APPLICATION_SERVICE_V2)
        if not isinstance(resolver, WorkflowPatternApplicationResolverProtocolV2):
            raise RuntimeV2Error(
                "invalid_workflow_pattern_application_resolver",
                "workflow-pattern application service has an invalid implementation",
            )
        yield WorkflowPatternApplicationAuthorityV2(
            operation=operation,
            db=db,
            current_user=current_user,
            services=resolver.resolve(operation),
        )


def _scope_id_v2(value: object) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


__all__ = [
    "WorkflowPatternApplicationAuthorityV2",
    "workflow_pattern_application_authority_dependency_v2",
]
