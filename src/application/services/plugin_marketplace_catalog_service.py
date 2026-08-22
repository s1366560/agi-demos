"""Marketplace catalog listing, tenant approval, and revocation workflows."""

from __future__ import annotations

from dataclasses import dataclass

from src.application.services.plugin_marketplace_desired_bundle_service_v2 import (
    PluginMarketplaceDesiredBundleServiceV2,
)
from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.adapters.secondary.persistence.models import (
    PlatformPluginPackageModel,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_governance_repository import (
    PlatformPluginGovernanceRepository,
)
from src.infrastructure.plugins.v2.protocol import parse_bundle_manifest_v2


@dataclass(frozen=True)
class MarketplaceApprovalResult:
    plugin_id: str
    version: str
    granted_permissions: tuple[str, ...]


@dataclass(frozen=True)
class MarketplaceRevocationResult:
    plugin_id: str
    revoked_versions: tuple[str, ...]
    revoked_permissions: int
    desired_removed: bool


@dataclass(frozen=True)
class MarketplaceUninstallResult:
    plugin_id: str
    version: str
    desired_removed: bool
    revoked_permissions: int


class PluginMarketplaceCatalogService:
    """Read and govern packages without exposing signed secrets."""

    def __init__(  # pyright: ignore[reportMissingSuperCall]
        self,
        repository: PlatformPluginGovernanceRepository,
        desired_bundles: PluginMarketplaceDesiredBundleServiceV2,
    ) -> None:
        self._repository = repository
        self._desired_bundles = desired_bundles

    async def list_packages(
        self,
        *,
        include_revoked: bool = False,
    ) -> list[PlatformPluginPackageModel]:
        """Return deterministic catalog rows."""
        return await self._repository.list_packages(include_revoked=include_revoked)

    async def get_package(
        self,
        plugin_id: str,
        *,
        include_revoked: bool = False,
    ) -> list[PlatformPluginPackageModel]:
        """Return deterministic package versions."""
        rows = await self._repository.get_package(plugin_id)
        if not include_revoked:
            rows = [row for row in rows if not row.revoked]
        return rows

    async def approve(
        self,
        *,
        plugin_id: str,
        version: str,
        tenant_id: str,
        approved_permissions: frozenset[str],
        actor_id: str | None,
    ) -> MarketplaceApprovalResult:
        """Grant only permissions requested by the verified package manifest."""
        package = await self._repository.get_package_version(plugin_id, version)
        if package is None:
            raise LookupError("marketplace package version was not found")
        if package.revoked:
            raise PermissionError("marketplace package version is revoked")
        if package.security_scan_status != "passed":
            raise PermissionError("marketplace package has not passed its security scan")

        bundle = parse_bundle_manifest_v2(package.manifest)
        declared_permissions = {
            permission for manifest in bundle.manifests for permission in manifest.permissions
        }
        undeclared = sorted(approved_permissions - declared_permissions)
        if undeclared:
            raise PermissionError(
                f"permissions not declared by protocol v2 Bundle: {', '.join(undeclared)}"
            )
        for permission in sorted(approved_permissions):
            _ = await self._repository.grant_permission(
                plugin_id=plugin_id,
                permission=permission,
                scope_type="tenant",
                scope_id=tenant_id,
                granted_by=actor_id,
            )
        return MarketplaceApprovalResult(
            plugin_id=plugin_id,
            version=version,
            granted_permissions=tuple(sorted(approved_permissions)),
        )

    async def revoke(
        self,
        *,
        plugin_id: str,
        reason: str,
        version: str | None = None,
        actor_id: str | None = None,
    ) -> MarketplaceRevocationResult:
        """Revoke package versions and fail closed on every permission grant."""
        rows = await self._repository.revoke_packages(plugin_id, reason, version=version)
        if not rows:
            raise LookupError("marketplace package version was not found")
        mutation = await self._desired_bundles.uninstall(
            scope=ScopeV2(kind=ScopeKindV2.ROOT),
            bundle_id=plugin_id,
            version=version,
            actor_id=actor_id,
        )
        revoked_permissions = await self._repository.revoke_permissions(plugin_id)
        return MarketplaceRevocationResult(
            plugin_id=plugin_id,
            revoked_versions=tuple(row.version for row in rows),
            revoked_permissions=revoked_permissions,
            desired_removed=mutation.changed,
        )

    async def uninstall(
        self,
        *,
        plugin_id: str,
        version: str,
        actor_id: str | None = None,
    ) -> MarketplaceUninstallResult:
        """Uninstall one package and remove it from the next desired snapshot."""
        package = await self._repository.uninstall_package(plugin_id, version)
        if package is None:
            raise LookupError("marketplace package version was not found")
        mutation = await self._desired_bundles.uninstall(
            scope=ScopeV2(kind=ScopeKindV2.ROOT),
            bundle_id=plugin_id,
            version=version,
            actor_id=actor_id,
        )
        revoked_permissions = (
            await self._repository.revoke_permissions(plugin_id) if mutation.changed else 0
        )
        return MarketplaceUninstallResult(
            plugin_id=plugin_id,
            version=version,
            desired_removed=mutation.changed,
            revoked_permissions=revoked_permissions,
        )
