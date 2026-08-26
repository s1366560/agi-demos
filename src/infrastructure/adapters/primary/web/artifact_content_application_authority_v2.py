# pyright: reportImportCycles=false
"""FastAPI authority dependency for generation-owned Artifact content services."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from uuid import uuid4

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import User
from src.infrastructure.plugins.v2.artifact_content_services import (
    ARTIFACT_CONTENT_APPLICATION_SERVICE_V2,
    ArtifactContentApplicationResolverProtocolV2,
    ArtifactContentApplicationServicesV2,
)
from src.infrastructure.plugins.v2.boundary import (
    OPERATION_DB_SESSION_SERVICE_V2,
    OPERATION_IDENTITY_SERVICE_V2,
    OPERATION_METADATA_SERVICE_V2,
    current_generation_v2,
)
from src.infrastructure.plugins.v2.runtime import OperationContextV2, RuntimeV2Error


@dataclass(frozen=True, kw_only=True)
class ArtifactContentApplicationAuthorityV2:
    """Request-owned Artifact content services and operation boundary."""

    operation: OperationContextV2
    db: AsyncSession
    services: ArtifactContentApplicationServicesV2


def _route_template(request: Request) -> str:
    route = request.scope.get("route")
    route_path = getattr(route, "path", None)
    return route_path if isinstance(route_path, str) else "-"


async def artifact_content_application_authority_dependency_v2(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AsyncIterator[ArtifactContentApplicationAuthorityV2]:
    """Yield content services from the generation pinned to this request."""
    operation = OperationContextV2(
        generation=current_generation_v2(),
        operation_id=f"http-artifact-content-application:{uuid4()}",
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
            {
                "kind": "http-authority",
                "method": request.method,
                "path": _route_template(request),
            },
        )
        resolver = operation.require(ARTIFACT_CONTENT_APPLICATION_SERVICE_V2)
        if not isinstance(resolver, ArtifactContentApplicationResolverProtocolV2):
            raise RuntimeV2Error(
                "invalid_artifact_content_application_resolver",
                "Artifact content application service has an invalid implementation",
            )
        yield ArtifactContentApplicationAuthorityV2(
            operation=operation,
            db=db,
            services=resolver.resolve(operation),
        )


__all__ = [
    "ArtifactContentApplicationAuthorityV2",
    "artifact_content_application_authority_dependency_v2",
]
