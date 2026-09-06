"""Plugin marketplace package API."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import cast

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
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
    MarketplacePackageUninstallRequest,
    MarketplacePackageUninstallResponse,
)
from src.application.services.plugin_marketplace_catalog_service import (
    PluginMarketplaceCatalogService,
)
from src.application.services.plugin_marketplace_desired_bundle_service_v2 import (
    PluginMarketplaceDesiredBundleServiceV2,
)
from src.application.services.plugin_marketplace_install_service import (
    PluginMarketplaceInstallService,
)
from src.application.services.plugin_marketplace_publication_service_v2 import (
    PluginMarketplacePublicationServiceV2,
)
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.primary.web.startup.http_route_publication_v2 import (
    HttpRoutePublicationCoordinatorV2,
)
from src.infrastructure.adapters.primary.web.startup.plugin_runtime_v2 import (
    plugin_publication_policy_v2_from_app,
)
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import (
    PlatformPluginPackageModel,
    User,
    UserTenant,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_desired_bundle_repository_v2 import (
    PlatformPluginDesiredBundleSetRepositoryV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_governance_repository import (
    PlatformPluginGovernanceRepository,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_profile_source_repository_v2 import (
    PlatformPluginProfileSourceRepositoryV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_repository_v2 import (
    PlatformPluginRepositoryV2,
)
from src.infrastructure.i18n import gettext as _
from src.infrastructure.plugins.package_registry import OciPluginArtifactClient
from src.infrastructure.plugins.v2.builtin_http_routes import BuiltinRouteGraphV2
from src.infrastructure.plugins.v2.production_bundle import (
    production_bundle_sources_v2,
)
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/plugin-marketplace", tags=["Plugin Marketplace"])


async def _republish_after_mutation(
    request: Request,
    db: AsyncSession,
) -> None:
    """Distribute the mutated desired state and reconcile the local data plane.

    A local NACK never rolls back the control-plane mutation; it is recorded as
    apply-state evidence so rollout readiness can evaluate the failure.
    """
    host = getattr(request.app.state, "platform_plugin_runtime_v2", None)
    if not isinstance(host, PlatformPluginRuntimeHostV2):
        raise RuntimeError("plugin runtime v2 is not initialized")
    coordinator = getattr(
        request.app.state,
        "platform_plugin_http_route_publication_v2",
        None,
    )
    if not isinstance(coordinator, HttpRoutePublicationCoordinatorV2):
        raise RuntimeError("plugin HTTP route publication v2 is not initialized")

    def commit_route_graph(graph: BuiltinRouteGraphV2) -> None:
        request.app.state.platform_plugin_route_graph_v2 = graph

    async with httpx.AsyncClient(timeout=15.0) as client:
        service = PluginMarketplacePublicationServiceV2(
            desired_repository=PlatformPluginDesiredBundleSetRepositoryV2(db),
            source_repository=PlatformPluginProfileSourceRepositoryV2(db),
            governance_repository=PlatformPluginGovernanceRepository(db),
            publication_repository=PlatformPluginRepositoryV2(db),
            artifact_client=OciPluginArtifactClient(client),
            production_sources=production_bundle_sources_v2(),
            trusted_public_keys=_trusted_public_keys(request),
            allowed_registries=getattr(
                request.app.state, "plugin_marketplace_allowed_registries_v2", None
            ),
            host=host,
            route_coordinator=coordinator,
            publication_policy=plugin_publication_policy_v2_from_app(request.app),
            on_route_commit=commit_route_graph,
        )
        result = await service.publish_current()
        if not result.publication.accepted:
            logger.warning(
                "Local platform plugin reconciliation NACKed version %s: %s",
                result.publication.envelope.version,
                result.publication.receipt.error_message,
            )


async def _service(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> AsyncIterator[PluginMarketplaceInstallService]:
    async with httpx.AsyncClient(timeout=15.0) as client:
        yield PluginMarketplaceInstallService(
            PlatformPluginGovernanceRepository(db),
            _desired_bundle_service(db),
            OciPluginArtifactClient(client),
            trusted_public_keys=_trusted_public_keys(request),
        )


def _catalog_service(
    db: AsyncSession = Depends(get_db),
) -> PluginMarketplaceCatalogService:
    return PluginMarketplaceCatalogService(
        PlatformPluginGovernanceRepository(db),
        _desired_bundle_service(db),
    )


def _desired_bundle_service(db: AsyncSession) -> PluginMarketplaceDesiredBundleServiceV2:
    return PluginMarketplaceDesiredBundleServiceV2(
        PlatformPluginDesiredBundleSetRepositoryV2(db),
        baseline=production_bundle_sources_v2().desired_set,
    )


def _trusted_public_keys(request: Request) -> tuple[str, ...]:
    value = getattr(request.app.state, "plugin_marketplace_trusted_public_keys_v2", ())
    if not isinstance(value, tuple):
        raise TypeError("plugin marketplace v2 trust keys must be a tuple of PEM strings")
    raw_keys = cast(tuple[object, ...], value)
    keys = tuple(key for key in raw_keys if isinstance(key, str))
    if len(keys) != len(raw_keys):
        raise TypeError("plugin marketplace v2 trust keys must be a tuple of PEM strings")
    return keys


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
    http_request: Request,
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
    if not _current_user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=_("Only a platform administrator may install a marketplace package"),
        )
    decision = await service.request_install(request=request, actor_id=_current_user.id)
    if decision.status == "approved":
        if decision.desired_changed:
            await _republish_after_mutation(http_request, db)
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
    http_request: Request,
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
            actor_id=current_user.id,
        )
    except LookupError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if result.desired_removed:
        await _republish_after_mutation(http_request, db)
    await db.commit()
    return MarketplacePackageRevocationResponse(
        plugin_id=result.plugin_id,
        revoked_versions=list(result.revoked_versions),
        revoked_permissions=result.revoked_permissions,
    )


@router.post(
    "/packages/{plugin_id}/uninstall",
    response_model=MarketplacePackageUninstallResponse,
)
async def uninstall_package(
    plugin_id: str,
    http_request: Request,
    request: MarketplacePackageUninstallRequest,
    current_user: User = Depends(get_current_user),
    service: PluginMarketplaceCatalogService = Depends(_catalog_service),
    db: AsyncSession = Depends(get_db),
) -> MarketplacePackageUninstallResponse:
    """Uninstall a package and remove it from the next desired snapshot."""
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=_("Only a platform administrator may uninstall a marketplace package"),
        )
    try:
        result = await service.uninstall(
            plugin_id=plugin_id,
            version=request.version,
            actor_id=current_user.id,
        )
    except LookupError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if result.desired_removed:
        await _republish_after_mutation(http_request, db)
    await db.commit()
    return MarketplacePackageUninstallResponse(
        plugin_id=result.plugin_id,
        version=result.version,
        status="uninstalled",
        desired_removed=result.desired_removed,
        revoked_permissions=result.revoked_permissions,
    )
