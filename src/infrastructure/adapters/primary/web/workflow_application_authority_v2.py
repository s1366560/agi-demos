"""FastAPI dependency for the generation-owned workflow application service."""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import uuid4

from fastapi import Depends, Request

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.domain.ports.services.workflow_engine_port import WorkflowEnginePort
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.secondary.persistence.models import User
from src.infrastructure.plugins.v2.boundary import (
    OPERATION_IDENTITY_SERVICE_V2,
    OPERATION_METADATA_SERVICE_V2,
    current_generation_v2,
)
from src.infrastructure.plugins.v2.runtime import OperationContextV2, RuntimeV2Error
from src.infrastructure.plugins.v2.workflow_runtime import (
    WORKFLOW_APPLICATION_SERVICE_V2,
    WorkflowApplicationResolverProtocolV2,
)


async def workflow_engine_authority_dependency_v2(
    request: Request,
    current_user: User = Depends(get_current_user),
) -> AsyncIterator[WorkflowEnginePort]:
    """Yield the workflow engine resolved from the request's pinned generation."""
    scope = _request_scope_v2(request)
    operation = OperationContextV2(
        generation=current_generation_v2(),
        operation_id=f"http-workflow-application:{uuid4()}",
        scope=scope,
    )
    async with operation:
        _ = operation.provide(
            OPERATION_IDENTITY_SERVICE_V2,
            {"tenant_id": scope.tenant_id, "user_id": current_user.id},
        )
        _ = operation.provide(
            OPERATION_METADATA_SERVICE_V2,
            {"kind": "http-authority", "method": request.method, "path": request.url.path},
        )
        resolver = operation.require(WORKFLOW_APPLICATION_SERVICE_V2)
        if not isinstance(resolver, WorkflowApplicationResolverProtocolV2):
            raise RuntimeV2Error(
                "invalid_workflow_application_resolver",
                "workflow application service has an invalid implementation",
            )
        yield resolver.resolve(operation).engine


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


__all__ = ["workflow_engine_authority_dependency_v2"]
