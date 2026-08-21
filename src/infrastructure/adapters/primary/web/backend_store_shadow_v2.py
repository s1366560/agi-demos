"""FastAPI shadow boundary for graph/retrieval store V2 composition."""

from __future__ import annotations

import logging
from uuid import uuid4

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.graph_store_service import GraphStoreService
from src.application.services.retrieval_store_service import RetrievalStoreService
from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.domain.model.plugins.runtime import PluginGenerationDescriptorV2
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import User
from src.infrastructure.adapters.secondary.persistence.sql_graph_store_repository import (
    SqlGraphStoreRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_retrieval_store_repository import (
    SqlRetrievalStoreRepository,
)
from src.infrastructure.graph.backend_factory import build_default_factory
from src.infrastructure.graph.registry import get_graph_backend_registry
from src.infrastructure.plugins.v2.backend_store_services import (
    BACKEND_STORE_SHADOW_SERVICE_V2,
    BackendStoreServicesV2,
    BackendStoreShadowEvidenceV2,
    BackendStoreShadowProtocolV2,
)
from src.infrastructure.plugins.v2.boundary import (
    OPERATION_DB_SESSION_SERVICE_V2,
    OPERATION_IDENTITY_SERVICE_V2,
    OPERATION_METADATA_SERVICE_V2,
    current_generation_v2,
)
from src.infrastructure.plugins.v2.runtime import OperationContextV2, RuntimeV2Error
from src.infrastructure.retrieval.backend_factory import build_default_retrieval_factory
from src.infrastructure.retrieval.registry import get_retrieval_backend_registry

logger = logging.getLogger(__name__)

BACKEND_STORE_SHADOW_STATE_V2 = "backend_store_shadow_v2"


async def backend_store_shadow_dependency_v2(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BackendStoreShadowEvidenceV2:
    """Record objective V2/static parity while static composition remains authoritative."""
    scope = _request_scope_v2(request)
    operation_id = f"http-backend-store-shadow:{uuid4()}"
    descriptor: PluginGenerationDescriptorV2 | None = None
    operation: OperationContextV2 | None = None
    evidence: BackendStoreShadowEvidenceV2 | None = None
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
            {"tenant_id": scope.tenant_id, "user_id": current_user.id},
        )
        _ = operation.provide(
            OPERATION_METADATA_SERVICE_V2,
            {"kind": "http-shadow", "method": request.method, "path": request.url.path},
        )
        comparator = operation.require(BACKEND_STORE_SHADOW_SERVICE_V2)
        if not isinstance(comparator, BackendStoreShadowProtocolV2):
            raise RuntimeV2Error(
                "invalid_backend_store_shadow",
                "backend store shadow service has an invalid implementation",
            )
        evidence = comparator.compare(
            operation=operation,
            legacy=_legacy_backend_store_services_v2(db),
            expected_scope=scope,
        )
    except Exception as exc:
        evidence = BackendStoreShadowEvidenceV2.failed(
            operation_id=operation_id,
            scope=scope,
            descriptor=descriptor,
            error_code=_shadow_error_code_v2(exc),
            difference="shadow_execution",
        )
        logger.warning(
            "Backend store V2 shadow comparison failed error_code=%s",
            evidence.error_code,
        )
    finally:
        if operation is not None:
            try:
                await operation.dispose()
            except Exception as exc:
                evidence = BackendStoreShadowEvidenceV2.failed(
                    operation_id=operation_id,
                    scope=scope,
                    descriptor=descriptor,
                    error_code=_shadow_error_code_v2(exc),
                    difference="shadow_disposal",
                )
                logger.warning(
                    "Backend store V2 shadow disposal failed error_code=%s",
                    evidence.error_code,
                )

    setattr(request.state, BACKEND_STORE_SHADOW_STATE_V2, evidence)
    return evidence


def _legacy_backend_store_services_v2(db: AsyncSession) -> BackendStoreServicesV2:
    return BackendStoreServicesV2(
        graph_service=GraphStoreService(
            repo=SqlGraphStoreRepository(db),
            registry=get_graph_backend_registry(),
            factory=build_default_factory(),
        ),
        retrieval_service=RetrievalStoreService(
            repo=SqlRetrievalStoreRepository(db),
            registry=get_retrieval_backend_registry(),
            factory=build_default_retrieval_factory(),
        ),
    )


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
    "BACKEND_STORE_SHADOW_STATE_V2",
    "backend_store_shadow_dependency_v2",
]
