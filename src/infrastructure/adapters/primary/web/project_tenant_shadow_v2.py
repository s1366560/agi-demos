"""FastAPI shadow dependency for the first persistence/project/tenant V2 cutover batch."""

from __future__ import annotations

import logging
from uuid import uuid4

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.configuration.di_container import DIContainer
from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import User
from src.infrastructure.plugins.v2.boundary import (
    OPERATION_DB_SESSION_SERVICE_V2,
    OPERATION_IDENTITY_SERVICE_V2,
    OPERATION_METADATA_SERVICE_V2,
    current_generation_v2,
)
from src.infrastructure.plugins.v2.project_tenant_services import (
    PROJECT_TENANT_SHADOW_SERVICE_V2,
    ProjectTenantServicesV2,
    ProjectTenantShadowEvidenceV2,
    ProjectTenantShadowProtocolV2,
)
from src.infrastructure.plugins.v2.runtime import OperationContextV2, RuntimeV2Error

logger = logging.getLogger(__name__)

PROJECT_TENANT_SHADOW_STATE_V2 = "project_tenant_shadow_v2"


async def project_tenant_shadow_dependency_v2(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProjectTenantShadowEvidenceV2:
    """Record objective V2/legacy parity while leaving the legacy route authoritative."""
    scope = _request_scope_v2(request)
    operation_id = f"http-shadow:{uuid4()}"
    descriptor = None
    operation: OperationContextV2 | None = None
    evidence: ProjectTenantShadowEvidenceV2 | None = None
    try:
        generation = current_generation_v2()
        descriptor = generation.descriptor
        operation = OperationContextV2(
            generation=generation,
            operation_id=operation_id,
            scope=scope,
        )
        _ = await operation.__aenter__()
        _ = operation.provide(OPERATION_DB_SESSION_SERVICE_V2, db)
        _ = operation.provide(
            OPERATION_IDENTITY_SERVICE_V2,
            {"user_id": current_user.id, "tenant_id": scope.tenant_id},
        )
        _ = operation.provide(
            OPERATION_METADATA_SERVICE_V2,
            {"kind": "http-shadow", "method": request.method, "path": request.url.path},
        )
        comparator = operation.require(PROJECT_TENANT_SHADOW_SERVICE_V2)
        if not isinstance(comparator, ProjectTenantShadowProtocolV2):
            raise RuntimeV2Error(
                "invalid_project_tenant_shadow",
                "project/tenant shadow service has an invalid implementation",
            )
        container = _request_container_with_db(request, db)
        evidence = comparator.compare(
            operation=operation,
            legacy=ProjectTenantServicesV2(
                project_repository=container.project_repository(),
                project_service=container.project_service(),
                tenant_service=container.tenant_service(),
            ),
            expected_scope=scope,
        )
    except Exception as exc:
        evidence = ProjectTenantShadowEvidenceV2.failed(
            operation_id=operation_id,
            scope=scope,
            descriptor=descriptor,
            error_code=_shadow_error_code_v2(exc),
            difference="shadow_execution",
        )
        logger.warning(
            "Project/tenant V2 shadow comparison failed error_code=%s",
            evidence.error_code,
        )
    finally:
        if operation is not None:
            try:
                await operation.dispose()
            except Exception as exc:
                evidence = ProjectTenantShadowEvidenceV2.failed(
                    operation_id=operation_id,
                    scope=scope,
                    descriptor=descriptor,
                    error_code=_shadow_error_code_v2(exc),
                    difference="shadow_disposal",
                )
                logger.warning(
                    "Project/tenant V2 shadow disposal failed error_code=%s",
                    evidence.error_code,
                )

    setattr(request.state, PROJECT_TENANT_SHADOW_STATE_V2, evidence)
    return evidence


def _request_container_with_db(request: Request, db: AsyncSession) -> DIContainer:
    container = request.app.state.container
    if not isinstance(container, DIContainer):
        raise RuntimeV2Error(
            "invalid_legacy_di_container",
            "project/tenant shadow requires the application DIContainer",
        )
    return container.with_db(db)


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


def _shadow_error_code_v2(exc: Exception) -> str:
    if isinstance(exc, RuntimeV2Error):
        return exc.code
    return f"shadow_{type(exc).__name__}"


__all__ = [
    "PROJECT_TENANT_SHADOW_STATE_V2",
    "project_tenant_shadow_dependency_v2",
]
