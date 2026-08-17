"""Plugin marketplace package API."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.schemas.plugin_marketplace import (
    MarketplacePackageApprovalRequest,
    MarketplacePackageApprovalResponse,
    MarketplacePackageCatalogEntry,
    MarketplacePackageDetailResponse,
    MarketplacePackageRequest,
    MarketplacePackageResponse,
    MarketplacePackageRevocationRequest,
    MarketplacePackageRevocationResponse,
)
from src.application.services.plugin_marketplace_catalog_service import (
    PluginMarketplaceCatalogService,
)
from src.application.services.plugin_marketplace_install_service import (
    PluginMarketplaceInstallService,
)
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import (
    PlatformPluginPackageModel,
    User,
    UserTenant,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_governance_repository import (
    PlatformPluginGovernanceRepository,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_repository import (
    PlatformPluginRepository,
)
from src.infrastructure.i18n import gettext as _
from src.infrastructure.plugins.package_registry import OciPluginArtifactClient

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/plugin-marketplace", tags=["Plugin Marketplace"])


async def _service(
    db: AsyncSession = Depends(get_db),
) -> AsyncIterator[PluginMarketplaceInstallService]:
    async with httpx.AsyncClient(timeout=15.0) as client:
        yield PluginMarketplaceInstallService(
            PlatformPluginGovernanceRepository(db),
            PlatformPluginRepository(db),
            OciPluginArtifactClient(client),
        )


def _catalog_service(
    db: AsyncSession = Depends(get_db),
) -> PluginMarketplaceCatalogService:
    return PluginMarketplaceCatalogService(
        PlatformPluginGovernanceRepository(db),
    )


async def _require_tenant_admin(
    db: AsyncSession,
    current_user: User,
    tenant_id: str,
) -> None:
    """Require superuser or an admin/owner membership in the target tenant."""
    if current_user.is_superuser:
        return
    result = await db.execute(
        refresh_select_statement(
            select(UserTenant).where(
                UserTenant.user_id == current_user.id,
                UserTenant.tenant_id == tenant_id,
            )
        )
    )
    membership = result.scalar_one_or_none()
    if membership is None or membership.role not in {"admin", "owner"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=_("Tenant administrator approval is required"),
        )


def _catalog_entry(package: PlatformPluginPackageModel) -> MarketplacePackageCatalogEntry:
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


@router.get("/packages", response_model=list[MarketplacePackageCatalogEntry])
async def list_packages(
    include_revoked: bool = False,
    _current_user: User = Depends(get_current_user),
    service: PluginMarketplaceCatalogService = Depends(_catalog_service),
) -> list[MarketplacePackageCatalogEntry]:
    """List verified marketplace packages without signature secrets."""
    packages = await service.list_packages(include_revoked=include_revoked)
    return [_catalog_entry(package) for package in packages]


@router.get("/packages/{plugin_id}", response_model=MarketplacePackageDetailResponse)
async def get_package(
    plugin_id: str,
    include_revoked: bool = False,
    _current_user: User = Depends(get_current_user),
    service: PluginMarketplaceCatalogService = Depends(_catalog_service),
) -> MarketplacePackageDetailResponse:
    """Return all visible versions for one marketplace package."""
    packages = await service.get_package(plugin_id, include_revoked=include_revoked)
    if not packages:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_("Marketplace package was not found"),
        )
    return MarketplacePackageDetailResponse(
        plugin_id=plugin_id,
        versions=[_catalog_entry(package) for package in packages],
    )


@router.post(
    "/packages/{plugin_id}/install",
    response_model=MarketplacePackageResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def install_package(
    plugin_id: str,
    request: MarketplacePackageRequest,
    _current_user: User = Depends(get_current_user),
    service: PluginMarketplaceInstallService = Depends(_service),
    db: AsyncSession = Depends(get_db),
) -> MarketplacePackageResponse:
    """Verify and request one package installation without exposing secrets."""
    if request.plugin_id != plugin_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_("Plugin path and request body must identify the same package"),
        )
    await _require_tenant_admin(db, _current_user, request.tenant_id)
    decision = await service.request_install(request=request)
    if decision.status == "approved":
        await db.commit()
    else:
        await db.rollback()
    return MarketplacePackageResponse(
        plugin_id=decision.plugin_id,
        version=decision.version,
        status=decision.status,
        reason=decision.reason,
    )


@router.post(
    "/packages/{plugin_id}/approve",
    response_model=MarketplacePackageApprovalResponse,
)
async def approve_package(
    plugin_id: str,
    request: MarketplacePackageApprovalRequest,
    current_user: User = Depends(get_current_user),
    service: PluginMarketplaceCatalogService = Depends(_catalog_service),
    db: AsyncSession = Depends(get_db),
) -> MarketplacePackageApprovalResponse:
    """Approve only a subset of permissions requested by a verified package."""
    await _require_tenant_admin(db, current_user, request.tenant_id)
    try:
        result = await service.approve(
            plugin_id=plugin_id,
            version=request.version,
            tenant_id=request.tenant_id,
            approved_permissions=request.approved_permissions,
            actor_id=current_user.id,
        )
    except LookupError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PermissionError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    await db.commit()
    return MarketplacePackageApprovalResponse(
        plugin_id=result.plugin_id,
        version=result.version,
        status="approved",
        granted_permissions=list(result.granted_permissions),
    )


@router.post(
    "/packages/{plugin_id}/revoke",
    response_model=MarketplacePackageRevocationResponse,
)
async def revoke_package(
    plugin_id: str,
    request: MarketplacePackageRevocationRequest,
    current_user: User = Depends(get_current_user),
    service: PluginMarketplaceCatalogService = Depends(_catalog_service),
    db: AsyncSession = Depends(get_db),
) -> MarketplacePackageRevocationResponse:
    """Revoke a package version and all active plugin permission grants."""
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=_("Only a platform administrator may revoke a marketplace package"),
        )
    try:
        result = await service.revoke(
            plugin_id=plugin_id,
            reason=request.reason,
            version=request.version,
        )
    except LookupError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    await db.commit()
    return MarketplacePackageRevocationResponse(
        plugin_id=result.plugin_id,
        revoked_versions=list(result.revoked_versions),
        revoked_permissions=result.revoked_permissions,
    )
