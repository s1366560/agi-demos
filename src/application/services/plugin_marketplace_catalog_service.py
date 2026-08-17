"""Marketplace catalog listing, tenant approval, and revocation workflows."""

from __future__ import annotations

from dataclasses import dataclass

from src.domain.model.plugins import parse_plugin_manifest
from src.domain.ports.plugins import PluginPermission
from src.infrastructure.adapters.secondary.persistence.models import (
    PlatformPluginPackageModel,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_governance_repository import (
    PlatformPluginGovernanceRepository,
)
from src.infrastructure.plugins.governance import PluginTrustGate


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


class PluginMarketplaceCatalogService:
    """Read and govern packages without exposing signed secrets."""

    def __init__(
        self,
        repository: PlatformPluginGovernanceRepository,
        *,
        trust_gate: PluginTrustGate | None = None,
    ) -> None:
        self._repository = repository
        self._trust_gate = trust_gate or PluginTrustGate()

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

        manifest = parse_plugin_manifest(package.manifest)
        permissions = frozenset(PluginPermission(item) for item in approved_permissions)
        decision = self._trust_gate.decide(manifest, permissions)
        if not decision.allowed:
            raise PermissionError(decision.reason)
        for permission in sorted(permissions, key=lambda item: item.value):
            await self._repository.grant_permission(
                plugin_id=plugin_id,
                permission=permission.value,
                scope_type="tenant",
                scope_id=tenant_id,
                granted_by=actor_id,
            )
        return MarketplaceApprovalResult(
            plugin_id=plugin_id,
            version=version,
            granted_permissions=tuple(item.value for item in sorted(permissions)),
        )

    async def revoke(
        self,
        *,
        plugin_id: str,
        reason: str,
        version: str | None = None,
    ) -> MarketplaceRevocationResult:
        """Revoke package versions and fail closed on every permission grant."""
        rows = await self._repository.revoke_packages(plugin_id, reason, version=version)
        if not rows:
            raise LookupError("marketplace package version was not found")
        revoked_permissions = await self._repository.revoke_permissions(plugin_id)
        return MarketplaceRevocationResult(
            plugin_id=plugin_id,
            revoked_versions=tuple(row.version for row in rows),
            revoked_permissions=revoked_permissions,
        )
