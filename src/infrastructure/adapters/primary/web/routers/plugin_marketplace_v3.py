"""Unified marketplace endpoints; public discovery and authenticated scoped mutations."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.marketplace_signed_scope_v2 import (
    SignedMarketplaceScopeV2,
    signed_installations,
)
from src.application.services.plugin_marketplace_v3 import (
    PUBLIC_TENANT,
    MarketplaceV3Error,
    PluginMarketplaceV3,
)
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.primary.web.mcp_application_authority_v2 import (
    mcp_application_authority_dependency_v2,
)
from src.infrastructure.adapters.primary.web.routers.plugin_marketplace import _require_tenant_admin
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import Project, User, UserProject
from src.infrastructure.adapters.secondary.persistence.plugin_marketplace_models_v3 import (
    MarketplaceRecordV3,
)
from src.infrastructure.i18n import gettext as _
from src.infrastructure.plugins.marketplace_snapshot_cache import reclaim_marketplace_cache

router = APIRouter(prefix="/api/v1/plugin-marketplace/v3", tags=["Plugin Marketplace"])


class MarketplaceScope(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=64)
    project_id: str | None = Field(default=None, max_length=64)


class MarketplaceSourceRequest(MarketplaceScope):
    name: str = Field(min_length=1, max_length=200)
    kind: Literal["https", "git", "local"]
    location: str = Field(min_length=1, max_length=2048)
    trusted: bool = False


class MarketplacePreflightRequest(MarketplaceScope):
    source_id: str
    plugin_id: str
    version: str | None = None


class MarketplaceInstallRequest(MarketplaceScope):
    preflight_id: str
    approved_permissions: list[str] = Field(default_factory=list)
    idempotency_key: str = Field(min_length=1, max_length=128)


class MarketplaceMutationRequest(MarketplaceScope):
    idempotency_key: str = Field(min_length=1, max_length=128)
    preflight_id: str | None = None
    approved_permissions: list[str] = Field(default_factory=list)
    credentials: dict[str, str] = Field(default_factory=dict)


async def authorize_scope(
    db: AsyncSession, user: User, tenant_id: str, project_id: str | None
) -> None:
    await _require_tenant_admin(db, user, tenant_id)
    if project_id:
        project = await db.scalar(
            select(Project).where(Project.id == project_id, Project.tenant_id == tenant_id)
        )
        if project is None:
            raise HTTPException(404, _("Project not found"))
        if not user.is_superuser:
            membership = await db.scalar(
                select(UserProject).where(
                    UserProject.user_id == user.id, UserProject.project_id == project_id
                )
            )
            if membership is None or membership.role not in {"owner", "admin"}:
                raise HTTPException(403, _("Project administrator approval is required"))


@router.get("/catalog")
async def public_catalog(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    return await PluginMarketplaceV3(db, PUBLIC_TENANT).catalog()


@router.get("/catalog/scoped")
async def scoped_catalog(
    tenant_id: str,
    project_id: str | None = None,
    source_id: str | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await authorize_scope(db, user, tenant_id, project_id)
    return await PluginMarketplaceV3(db, tenant_id, project_id).catalog(source_id)


@router.get("/sources")
async def list_sources(
    tenant_id: str,
    project_id: str | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await authorize_scope(db, user, tenant_id, project_id)
    sources = await PluginMarketplaceV3(db, tenant_id, project_id).sources()
    # Deployment filesystem paths are never disclosed to clients.
    return {
        "items": [
            {**source, "location": "" if source["kind"] == "local" else source["location"]}
            for source in sources
        ]
    }


@router.post("/sources", status_code=201)
async def create_source(
    data: MarketplaceSourceRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await authorize_scope(db, user, data.tenant_id, data.project_id)
    try:
        result = await PluginMarketplaceV3(db, data.tenant_id, data.project_id).add_source(
            data.model_dump()
        )
        await db.commit()
        return result
    except MarketplaceV3Error as exc:
        raise HTTPException(400, _(str(exc))) from exc


@router.delete("/sources/{source_id}", status_code=204)
async def delete_source(
    source_id: str,
    tenant_id: str,
    project_id: str | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    await authorize_scope(db, user, tenant_id, project_id)
    try:
        await PluginMarketplaceV3(db, tenant_id, project_id).remove_source(source_id)
        await db.commit()
    except MarketplaceV3Error as exc:
        raise HTTPException(400, _(str(exc))) from exc


@router.post("/preflight")
async def preflight(
    data: MarketplacePreflightRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await authorize_scope(db, user, data.tenant_id, data.project_id)
    try:
        result = await PluginMarketplaceV3(db, data.tenant_id, data.project_id).preflight(
            data.source_id, data.plugin_id, data.version
        )
        await db.commit()
        return result
    except MarketplaceV3Error as exc:
        raise HTTPException(400, _(str(exc))) from exc


@router.get("/installations")
async def list_installations(
    tenant_id: str,
    project_id: str | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await authorize_scope(db, user, tenant_id, project_id)
    service = PluginMarketplaceV3(db, tenant_id, project_id)
    return {
        "items": [
            service.installation_view(row.payload) for row in await service.records("installation")
        ]
        + await signed_installations(db, tenant_id, project_id)
    }


@router.post("/installations", status_code=201)
async def install(
    data: MarketplaceInstallRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await authorize_scope(db, user, data.tenant_id, data.project_id)
    try:
        result = await PluginMarketplaceV3(db, data.tenant_id, data.project_id).install(
            data.preflight_id, data.approved_permissions, data.idempotency_key
        )
        await db.commit()
        return result
    except MarketplaceV3Error as exc:
        raise HTTPException(400, _(str(exc))) from exc


@router.post("/installations/{installation_id}/{action}")
async def mutate(
    installation_id: str,
    action: Literal["enable", "disable", "update", "uninstall", "configure", "verify"],
    data: MarketplaceMutationRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await authorize_scope(db, user, data.tenant_id, data.project_id)
    service = PluginMarketplaceV3(db, data.tenant_id, data.project_id)
    signed = await db.scalar(
        select(MarketplaceRecordV3).where(
            MarketplaceRecordV3.id == installation_id,
            MarketplaceRecordV3.kind == "signed_installation",
            MarketplaceRecordV3.tenant_id == data.tenant_id,
            MarketplaceRecordV3.project_id == (data.project_id or ""),
        )
    )
    if signed is not None:
        runtime = getattr(request.app.state, "scoped_profile_runtime_v2", None)
        if runtime is None:
            raise HTTPException(503, _("Scoped plugin runtime is unavailable"))
        try:
            return await SignedMarketplaceScopeV2(
                db, runtime, data.tenant_id, data.project_id
            ).mutate(
                signed.record_key,
                action,
                user.id,
                data.model_dump(),
            )
        except (ValueError, LookupError) as exc:
            raise HTTPException(400, _(str(exc))) from exc
    try:
        row = await service.record(installation_id, "installation")
        if set(row.payload["capabilities"]) & {"mcp", "apps", "hooks"}:
            db.info["marketplace_transaction_owned"] = True
            async for authority in mcp_application_authority_dependency_v2(
                request, user, data.tenant_id, db
            ):
                service.mcp = authority.services
                result = await service.mutate(installation_id, action, data.model_dump())
                await db.commit()
                await reclaim_marketplace_cache(
                    db,
                    data.tenant_id,
                    data.project_id or "",
                    authority.services.sandbox_manager._sandbox_resource,
                )
                return result
            raise MarketplaceV3Error("MCP runtime unavailable")
        result = await service.mutate(installation_id, action, data.model_dump())
        await db.commit()
        await reclaim_marketplace_cache(db, data.tenant_id, data.project_id or "")
        return result
    except MarketplaceV3Error as exc:
        # Persist compensation and the failed job instead of rolling back its cleanup.
        await db.commit()
        raise HTTPException(400, _(str(exc))) from exc


@router.get("/jobs/{job_id}")
async def get_job(
    job_id: str,
    tenant_id: str,
    project_id: str | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await authorize_scope(db, user, tenant_id, project_id)
    try:
        row = await PluginMarketplaceV3(db, tenant_id, project_id).record(job_id, "operation")
        return {
            key: row.payload[key]
            for key in (
                "id",
                "installation_id",
                "action",
                "status",
                "stage",
                "stages",
                "error",
                "created_at",
            )
            if key in row.payload
        }
    except MarketplaceV3Error as exc:
        raise HTTPException(404, _(str(exc))) from exc


@router.get("/jobs")
async def list_jobs(
    tenant_id: str,
    project_id: str | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await authorize_scope(db, user, tenant_id, project_id)
    records = await PluginMarketplaceV3(db, tenant_id, project_id).records("operation")
    return {
        "items": [
            {
                key: row.payload[key]
                for key in (
                    "id",
                    "installation_id",
                    "action",
                    "status",
                    "stage",
                    "stages",
                    "error",
                    "created_at",
                )
                if key in row.payload
            }
            for row in records
        ]
    }


from .marketplace_oauth import router as oauth_router  # noqa: E402

router.include_router(oauth_router)

# Imported after scope dependencies to avoid a router construction cycle.
from .plugin_marketplace_cache_v3 import router as cache_router  # noqa: E402

router.include_router(cache_router)
