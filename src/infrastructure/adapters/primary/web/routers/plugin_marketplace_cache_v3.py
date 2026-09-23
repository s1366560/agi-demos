"""Explicit, scoped cache accounting and cleanup routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.primary.web.mcp_application_authority_v2 import (
    mcp_application_authority_dependency_v2,
)
from src.infrastructure.adapters.primary.web.routers.plugin_marketplace_v3 import (
    MarketplaceMutationRequest,
    authorize_scope,
)
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import User
from src.infrastructure.i18n import gettext as _
from src.infrastructure.plugins.marketplace_snapshot_cache import MarketplaceSnapshotCache
from src.infrastructure.plugins.v2.sandbox_operation_services import (
    SANDBOX_OPERATION_APPLICATION_SERVICE_V2,
    SandboxOperationApplicationResolverProtocolV2,
)

router = APIRouter()


@router.get("/cache")
async def cache_stats(
    tenant_id: str,
    project_id: str | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, int]:
    await authorize_scope(db, user, tenant_id, project_id)
    return await MarketplaceSnapshotCache(db, tenant_id, project_id).stats()


@router.post("/cache/cleanup")
async def cache_cleanup(
    data: MarketplaceMutationRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await authorize_scope(db, user, data.tenant_id, data.project_id)
    try:
        if data.project_id:
            db.info["marketplace_transaction_owned"] = True
            async for authority in mcp_application_authority_dependency_v2(
                request, user, data.tenant_id, db
            ):
                resolver = authority.operation.require(SANDBOX_OPERATION_APPLICATION_SERVICE_V2)
                if not isinstance(resolver, SandboxOperationApplicationResolverProtocolV2):
                    raise TypeError("Sandbox cache cleanup service is unavailable")
                sandbox = resolver.resolve(authority.operation).sandbox_resource
                result = await MarketplaceSnapshotCache(
                    db, data.tenant_id, data.project_id, sandbox
                ).cleanup(data.idempotency_key)
                await db.commit()
                return result
            raise ValueError("Project sandbox is unavailable for cache cleanup")
        result = await MarketplaceSnapshotCache(db, data.tenant_id, None).cleanup(
            data.idempotency_key
        )
        await db.commit()
        return result
    except ValueError as exc:
        # Keep failed registrations recoverable and never claim removal succeeded.
        await db.commit()
        raise HTTPException(400, _(str(exc))) from exc
