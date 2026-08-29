# pyright: reportImportCycles=false
"""FastAPI authority for generation-owned project membership checks."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import cast
from uuid import uuid4

from fastapi import Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.adapters.primary.web.dependencies import (
    get_current_user,
    get_current_user_tenant,
)
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import User
from src.infrastructure.i18n import gettext as _
from src.infrastructure.plugins.v2.boundary import (
    OPERATION_DB_SESSION_SERVICE_V2,
    OPERATION_IDENTITY_SERVICE_V2,
    OPERATION_METADATA_SERVICE_V2,
    current_generation_v2,
)
from src.infrastructure.plugins.v2.project_access_services import (
    PROJECT_ACCESS_APPLICATION_SERVICE_V2,
    ProjectAccessResolverProtocolV2,
    ProjectAccessServiceV2,
)
from src.infrastructure.plugins.v2.runtime import OperationContextV2, RuntimeV2Error


@dataclass(frozen=True, kw_only=True)
class ProjectAccessHttpApplicationAuthorityV2:
    operation: OperationContextV2
    db: AsyncSession
    service: ProjectAccessServiceV2


@asynccontextmanager
async def project_access_http_application_authority_v2(
    *,
    request: Request,
    project_id: str,
    current_user: User,
    tenant_id: str,
    db: AsyncSession,
) -> AsyncIterator[ProjectAccessHttpApplicationAuthorityV2]:
    operation = OperationContextV2(
        generation=current_generation_v2(),
        operation_id=f"http-project-access:{uuid4()}",
        scope=ScopeV2(
            kind=ScopeKindV2.PROJECT,
            tenant_id=tenant_id,
            project_id=project_id,
        ),
    )
    async with operation:
        _ = operation.provide(OPERATION_DB_SESSION_SERVICE_V2, db)
        _ = operation.provide(
            OPERATION_IDENTITY_SERVICE_V2,
            {
                "tenant_id": tenant_id,
                "project_id": project_id,
                "user_id": str(current_user.id),
            },
        )
        _ = operation.provide(
            OPERATION_METADATA_SERVICE_V2,
            {"kind": "http-authority", "method": request.method, "path": request.url.path},
        )
        resolver = operation.require(PROJECT_ACCESS_APPLICATION_SERVICE_V2)
        if not isinstance(resolver, ProjectAccessResolverProtocolV2):
            raise RuntimeV2Error(
                "invalid_project_access_resolver",
                "project access service has an invalid implementation",
            )
        yield ProjectAccessHttpApplicationAuthorityV2(
            operation=operation,
            db=db,
            service=resolver.resolve(operation),
        )


async def project_access_query_http_application_authority_dependency_v2(
    request: Request,
    project_id: str = Query(..., description="Project ID for authorization"),
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> AsyncIterator[ProjectAccessHttpApplicationAuthorityV2]:
    async with project_access_http_application_authority_v2(
        request=request,
        project_id=project_id,
        current_user=current_user,
        tenant_id=tenant_id,
        db=db,
    ) as authority:
        yield authority


async def project_access_create_http_application_authority_dependency_v2(
    request: Request,
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> AsyncIterator[ProjectAccessHttpApplicationAuthorityV2]:
    try:
        payload = cast("object", await request.json())
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=_("Invalid request"),
        ) from exc
    payload_mapping: Mapping[str, object]
    if isinstance(payload, Mapping):
        payload_mapping = cast("Mapping[str, object]", payload)
    else:
        payload_mapping = {}
    project_id: object | None = payload_mapping.get("project_id")
    if not isinstance(project_id, str) or not project_id.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=_("Invalid request"),
        )
    async with project_access_http_application_authority_v2(
        request=request,
        project_id=project_id,
        current_user=current_user,
        tenant_id=tenant_id,
        db=db,
    ) as authority:
        yield authority


__all__ = [
    "ProjectAccessHttpApplicationAuthorityV2",
    "project_access_create_http_application_authority_dependency_v2",
    "project_access_http_application_authority_v2",
    "project_access_query_http_application_authority_dependency_v2",
]
