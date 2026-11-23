"""Signed project marketplace shared by the empty kernel and the full API."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from typing import Any, Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.schemas.plugin_marketplace import (
    MarketplaceMutationRequest,
    MarketplacePackageCatalogEntry,
    MarketplacePackageDetailResponse,
    MarketplacePackageRequest,
    MarketplacePackageResponse,
)
from src.application.services.plugin_marketplace_install_service import (
    PluginMarketplaceInstallService,
)
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.primary.web.routers.optional_business_http_v2 import (
    _authorize_write,
    _service as project_packages,
    list_project_packages,
)
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import (
    PlatformPluginPackageModel,
    User,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_governance_repository import (
    PlatformPluginGovernanceRepository,
)
from src.infrastructure.i18n import gettext as _
from src.infrastructure.plugins.package_registry import OciPluginArtifactClient
from src.infrastructure.plugins.v2.signed_optional_business_v2 import OptionalBusinessError

kernel_marketplace_router = APIRouter(
    prefix="/api/v1/plugin-marketplace", tags=["Plugin Marketplace"]
)
kernel_marketplace_router.add_api_route("/v3/installations", list_project_packages, methods=["GET"])


def has_project_contributions(manifest: Mapping[str, object]) -> bool:
    artifacts = manifest.get("artifacts")
    return isinstance(artifacts, list) and any(
        isinstance(item, dict) and item.get("path") == "contributions.json" for item in artifacts
    )


def catalog_entry(package: PlatformPluginPackageModel) -> MarketplacePackageCatalogEntry:
    return MarketplacePackageCatalogEntry(
        plugin_id=package.plugin_id,
        version=package.version,
        publisher=package.publisher,
        artifact_digest=package.artifact_digest,
        artifact_registry=package.artifact_registry,
        artifact_repository=package.artifact_repository,
        oci_manifest_digest=package.oci_manifest_digest,
        install_status=package.install_status,
        manifest=package.manifest,
        signature=package.signature,
        provenance=package.provenance,
        security_scan_status=package.security_scan_status,
        revoked=package.revoked,
        revocation_reason=package.revocation_reason,
    )


async def kernel_market_service(
    request: Request, db: AsyncSession = Depends(get_db)
) -> AsyncIterator[PluginMarketplaceInstallService]:
    async with httpx.AsyncClient(timeout=15.0) as client:
        yield PluginMarketplaceInstallService(
            PlatformPluginGovernanceRepository(db),
            None,
            OciPluginArtifactClient(client),
            trusted_public_keys=tuple(
                getattr(request.app.state, "plugin_marketplace_trusted_public_keys_v2", ())
            ),
            allowed_registries=getattr(
                request.app.state, "plugin_marketplace_allowed_registries_v2", frozenset()
            ),
        )


@kernel_marketplace_router.get("/packages")
async def list_project_catalog(
    include_revoked: bool = False,
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[MarketplacePackageCatalogEntry]:
    rows = await PlatformPluginGovernanceRepository(db).list_packages(
        include_revoked=include_revoked
    )
    return [catalog_entry(row) for row in rows if has_project_contributions(row.manifest)]


@kernel_marketplace_router.get("/packages/{plugin_id}")
async def get_project_catalog_package(
    plugin_id: str,
    include_revoked: bool = False,
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MarketplacePackageDetailResponse:
    rows = await PlatformPluginGovernanceRepository(db).get_package(plugin_id)
    versions = [
        catalog_entry(row)
        for row in rows
        if (include_revoked or not row.revoked) and has_project_contributions(row.manifest)
    ]
    if not versions:
        raise HTTPException(404, _("Marketplace package was not found"))
    return MarketplacePackageDetailResponse(plugin_id=plugin_id, versions=versions)


@kernel_marketplace_router.post("/packages/{plugin_id}/install", status_code=202)
async def install_verified_project_package(
    plugin_id: str,
    http_request: Request,
    request: MarketplacePackageRequest,
    _current_user: User = Depends(get_current_user),
    service: PluginMarketplaceInstallService = Depends(kernel_market_service),
    db: AsyncSession = Depends(get_db),
) -> MarketplacePackageResponse:
    if request.plugin_id != plugin_id:
        raise HTTPException(400, _("Plugin path and request body must identify the same package"))
    if not has_project_contributions(request.manifest):
        raise HTTPException(422, _("A project business package is required"))
    if not request.project_id:
        raise HTTPException(422, _("A project is required for a business package"))
    await _authorize_write(db, _current_user, request.tenant_id, request.project_id)
    decision = await service.request_install(request=request, actor_id=_current_user.id)
    if decision.project_archive is None:
        await db.rollback()
        return MarketplacePackageResponse(
            plugin_id=plugin_id,
            version=request.version,
            status="quarantined",
            reason=decision.reason,
        )
    scoped = project_packages(
        http_request, db, request.tenant_id, request.project_id, actor_id=_current_user.id
    )
    try:
        await scoped.record(
            decision.project_archive, request.approved_permissions, _current_user.id
        )
        await scoped.mutate(plugin_id, "enable", expected_version=request.version)
    except (ValueError, OptionalBusinessError) as error:
        raise HTTPException(409, _(str(error))) from error
    return MarketplacePackageResponse(
        plugin_id=plugin_id,
        version=request.version,
        status="approved",
        reason="Signed project package enabled",
    )


@kernel_marketplace_router.post("/v3/installations/{installation_id}/{action}")
async def mutate_project_installation(
    installation_id: str,
    action: Literal["enable", "disable", "update", "uninstall", "configure", "verify"],
    data: MarketplaceMutationRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    if not data.project_id or not installation_id.startswith("project-package:"):
        raise HTTPException(404, _("Signed installation not found in selected scope"))
    await _authorize_write(db, user, data.tenant_id, data.project_id)
    scoped = project_packages(request, db, data.tenant_id, data.project_id, actor_id=user.id)
    plugin_id = installation_id.removeprefix("project-package:")
    if not await scoped.is_installed(plugin_id):
        raise HTTPException(404, _("Signed installation not found in selected scope"))
    try:
        if action in {"enable", "disable", "uninstall"}:
            await scoped.mutate(plugin_id, action, expected_revision=data.expected_revision)
        elif action != "verify":
            raise HTTPException(409, _("Install a signed version to update this package"))
        item = await scoped.marketplace_item(plugin_id)
        return {"status": item["status"], "installation": item}
    except (ValueError, OptionalBusinessError) as exc:
        raise HTTPException(409, _(str(exc))) from exc
