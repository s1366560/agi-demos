"""Resolve authenticated project scope through the request's pinned generation."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.knowledge_sync_service import KnowledgeSyncApplication
from src.domain.model.knowledge_sync.contracts import KnowledgeSyncError
from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.domain.model.plugins.runtime import PluginGenerationDescriptorV2
from src.infrastructure.adapters.primary.web.cloud_knowledge_sync_generation_v2 import (
    observe_cloud_knowledge_sync_generation_v2,
    require_cloud_knowledge_sync_generation_v2,
)
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import User
from src.infrastructure.i18n import gettext as _
from src.infrastructure.plugins.v2.boundary import (
    OPERATION_DB_SESSION_SERVICE_V2,
    OPERATION_IDENTITY_SERVICE_V2,
    OPERATION_METADATA_SERVICE_V2,
    current_generation_v2,
)
from src.infrastructure.plugins.v2.cloud_knowledge_sync_services import (
    CLOUD_KNOWLEDGE_SYNC_APPLICATION_SERVICE_V2,
    CloudKnowledgeSyncResolverProtocolV2,
    CloudKnowledgeSyncServicesV2,
)
from src.infrastructure.plugins.v2.runtime import OperationContextV2, RuntimeV2Error


def _provide(
    operation: OperationContextV2,
    db: AsyncSession,
    actor_id: str,
    request: Request,
    tenant_id: str | None,
) -> CloudKnowledgeSyncResolverProtocolV2:
    _ = operation.provide(OPERATION_DB_SESSION_SERVICE_V2, db)
    _ = operation.provide(
        OPERATION_IDENTITY_SERVICE_V2, {"user_id": actor_id, "tenant_id": tenant_id}
    )
    _ = operation.provide(
        OPERATION_METADATA_SERVICE_V2,
        {"kind": "cloud-knowledge-sync", "method": request.method, "path": request.url.path},
    )
    resolver = operation.require(CLOUD_KNOWLEDGE_SYNC_APPLICATION_SERVICE_V2)
    if not isinstance(resolver, CloudKnowledgeSyncResolverProtocolV2):
        raise RuntimeV2Error("invalid_cloud_sync_resolver", "cloud sync service is invalid")
    return resolver


async def cloud_knowledge_sync_authority_dependency_v2(
    project_id: str,
    request: Request,
    generation: PluginGenerationDescriptorV2 = Depends(require_cloud_knowledge_sync_generation_v2),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AsyncIterator[CloudKnowledgeSyncServicesV2]:
    del generation  # The HTTP precondition runs before identity or repository dependencies.
    async with _scoped_authority(project_id, request, user, db) as authority:
        yield authority


async def cloud_knowledge_sync_observation_dependency_v2(
    project_id: str,
    request: Request,
    generation: PluginGenerationDescriptorV2 = Depends(observe_cloud_knowledge_sync_generation_v2),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AsyncIterator[CloudKnowledgeSyncServicesV2]:
    del generation
    async with _scoped_authority(project_id, request, user, db) as authority:
        yield authority


@asynccontextmanager
async def _scoped_authority(
    project_id: str, request: Request, user: User, db: AsyncSession
) -> AsyncIterator[CloudKnowledgeSyncServicesV2]:
    generation = current_generation_v2()
    async with OperationContextV2(
        generation=generation,
        operation_id=f"cloud-knowledge-sync-scope:{uuid4()}",
        scope=ScopeV2(kind=ScopeKindV2.ROOT),
    ) as discovery:
        resolver = _provide(discovery, db, user.id, request, None)
        try:
            scope = await resolver.discover_scope(discovery, project_id)
        except KnowledgeSyncError as error:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": error.code,
                    "message": _("Knowledge synchronization access denied"),
                },
            ) from error
    async with OperationContextV2(
        generation=generation,
        operation_id=f"cloud-knowledge-sync:{uuid4()}",
        scope=ScopeV2(
            kind=ScopeKindV2.PROJECT, tenant_id=scope.tenant_id, project_id=scope.project_id
        ),
    ) as operation:
        resolver = _provide(operation, db, user.id, request, scope.tenant_id)
        yield resolver.resolve(operation)


async def cloud_knowledge_sync_application_dependency_v2(
    authority: CloudKnowledgeSyncServicesV2 = Depends(cloud_knowledge_sync_authority_dependency_v2),
) -> KnowledgeSyncApplication:
    return authority.sync
