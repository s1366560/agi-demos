"""Pure package-install decision service for the plugin marketplace."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from src.domain.ports.plugins import PluginPermission
from src.infrastructure.plugins.governance import (
    MarketplaceCatalogEntry,
    PluginPackageVerifier,
    PluginTrustGate,
)


@dataclass(frozen=True)
class MarketplaceInstallDecision:
    """Outcome of one install request."""

    status: Literal["approved", "quarantined"]
    plugin_id: str
    version: str
    reason: str


class PluginMarketplaceService:
    """Verify packages and produce an install decision without side effects."""

    def __init__(
        self,
        verifier: PluginPackageVerifier,
        trust_gate: PluginTrustGate | None = None,
    ) -> None:
        self._verifier = verifier
        self._trust_gate = trust_gate or PluginTrustGate()

    def decide(
        self,
        entry: MarketplaceCatalogEntry,
        *,
        artifact_sha256: str,
        approved_permissions: frozenset[PluginPermission],
        tenant_admin_approved: bool,
        security_scan_passed: bool,
    ) -> MarketplaceInstallDecision:
        """Return an approved decision only after every gate passes."""
        if not tenant_admin_approved:
            return self._quarantine(entry, "tenant admin approval is required")
        if not security_scan_passed:
            return self._quarantine(entry, "static security scan failed")
        try:
            self._verifier.verify(entry, artifact_sha256=artifact_sha256)
            decision = self._trust_gate.decide(entry.bundle.manifest, approved_permissions)
        except Exception as exc:
            return self._quarantine(entry, str(exc))
        if not decision.allowed:
            return self._quarantine(entry, decision.reason)
        return MarketplaceInstallDecision(
            status="approved",
            plugin_id=entry.plugin_id,
            version=entry.version,
            reason="package verified and approved",
        )

    @staticmethod
    def _quarantine(
        entry: MarketplaceCatalogEntry,
        reason: str,
    ) -> MarketplaceInstallDecision:
        return MarketplaceInstallDecision(
            status="quarantined",
            plugin_id=entry.plugin_id,
            version=entry.version,
            reason=reason,
        )
