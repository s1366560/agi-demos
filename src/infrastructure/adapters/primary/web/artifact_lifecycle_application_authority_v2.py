# pyright: reportImportCycles=false
"""FastAPI authority for generation-owned Artifact lifecycle services."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from uuid import uuid4

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.artifact_service import ArtifactService
from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import User
from src.infrastructure.plugins.v2.artifact_lifecycle_services import (
    ARTIFACT_LIFECYCLE_APPLICATION_SERVICE_V2,
    ArtifactLifecycleApplicationServiceV2,
)
from src.infrastructure.plugins.v2.boundary import (
    OPERATION_DB_SESSION_SERVICE_V2,
    OPERATION_IDENTITY_SERVICE_V2,
    OPERATION_METADATA_SERVICE_V2,
    current_generation_v2,
)
from src.infrastructure.plugins.v2.runtime import OperationContextV2, RuntimeV2Error


@dataclass(frozen=True, kw_only=True)
class ArtifactLifecycleApplicationAuthorityV2:
    """Request-owned generation lease and Artifact lifecycle service."""

    operation: OperationContextV2
    db: AsyncSession
    artifact: ArtifactService


async def artifact_lifecycle_application_authority_dependency_v2(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AsyncIterator[ArtifactLifecycleApplicationAuthorityV2]:
    """Yield the Artifact service from the generation pinned to this request."""
    operation = OperationContextV2(
        generation=current_generation_v2(),
        operation_id=f"http-artifact-lifecycle-application:{uuid4()}",
        scope=ScopeV2(kind=ScopeKindV2.ROOT),
    )
    async with operation:
        _ = operation.provide(OPERATION_DB_SESSION_SERVICE_V2, db)
        _ = operation.provide(
            OPERATION_IDENTITY_SERVICE_V2,
            {"tenant_id": None, "user_id": str(current_user.id)},
        )
        _ = operation.provide(
            OPERATION_METADATA_SERVICE_V2,
            {"kind": "http-authority", "method": request.method, "path": request.url.path},
        )
        service = operation.require(ARTIFACT_LIFECYCLE_APPLICATION_SERVICE_V2)
        if not isinstance(service, ArtifactLifecycleApplicationServiceV2):
            raise RuntimeV2Error(
                "invalid_artifact_lifecycle_application_service",
                "Artifact lifecycle application service has an invalid implementation",
            )
        yield ArtifactLifecycleApplicationAuthorityV2(
            operation=operation,
            db=db,
            artifact=service.artifact,
        )


__all__ = [
    "ArtifactLifecycleApplicationAuthorityV2",
    "artifact_lifecycle_application_authority_dependency_v2",
]
