"""Application service for quarantined marketplace package installation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from src.application.schemas.plugin_marketplace import MarketplacePackageRequest
from src.domain.model.plugins import parse_plugin_manifest
from src.domain.ports.plugins import PluginPermission
from src.infrastructure.adapters.secondary.persistence.platform_plugin_governance_repository import (
    PlatformPluginGovernanceRepository,
)
from src.infrastructure.plugins.governance import (
    MarketplaceCatalogEntry,
    PluginPackageBundle,
    PluginPackageVerifier,
    PluginTrustGate,
    sha256_hex,
)


@dataclass(frozen=True)
class MarketplaceInstallDecision:
    status: Literal["approved", "quarantined"]
    plugin_id: str
    version: str
    reason: str


class PluginMarketplaceInstallService:
    """Verify and record an install without mutating desired plugin state on failure."""

    def __init__(
        self,
        repository: PlatformPluginGovernanceRepository,
        *,
        trusted_public_keys: tuple[str, ...] = (),
        trust_gate: PluginTrustGate | None = None,
    ) -> None:
        self._repository = repository
        self._trust_gate = trust_gate or PluginTrustGate()
        self._keys = trusted_public_keys

    async def request_install(
        self,
        *,
        request: MarketplacePackageRequest,
    ) -> MarketplaceInstallDecision:
        """Return approved only when signature, provenance, scan, and permission gates pass."""
        try:
            parsed_manifest = parse_plugin_manifest(request.manifest)
            public_key = serialization.load_pem_public_key(
                request.signature.public_key_pem.encode("utf-8")
            )
            if not isinstance(public_key, Ed25519PublicKey):
                raise ValueError("signature key must be Ed25519")
            bundle = PluginPackageBundle(
                manifest=parsed_manifest,
                canonical_manifest=parsed_manifest.to_json(),
                artifact_digest=request.artifact_sha256,
                signature_base64=request.signature.signature_base64,
                public_key_pem=request.signature.public_key_pem,
                provenance={
                    "predicateType": request.provenance.predicate_type,
                    "builder": {"id": request.provenance.builder_id},
                    "subject": [
                        {
                            "name": request.provenance.subject_name,
                            "digest": {"sha256": request.artifact_sha256},
                        }
                    ],
                },
                checksum={"sha256": request.artifact_sha256},
            )
            entry = MarketplaceCatalogEntry(
                plugin_id=request.plugin_id,
                version=request.version,
                publisher=request.publisher,
                bundle=bundle,
            )
            verifier = PluginPackageVerifier(
                self._keys or (request.signature.public_key_pem,),
            )
            verifier.verify(entry, artifact_sha256=request.artifact_sha256)
            permissions = frozenset(PluginPermission(item) for item in request.approved_permissions)
            trust = self._trust_gate.decide(entry.bundle.manifest, permissions)
            if not trust.allowed:
                return self._quarantine(entry, trust.reason)
            if not request.tenant_admin_approved:
                return self._quarantine(entry, "tenant admin approval is required")
            if not request.security_scan_passed:
                return self._quarantine(entry, "security scan failed")
            await self._repository.upsert_package(
                plugin_id=request.plugin_id,
                version=request.version,
                publisher=request.publisher,
                artifact_digest=request.artifact_sha256,
                signature={
                    "algorithm": "Ed25519",
                    "public_key_sha256": sha256_hex(
                        request.signature.public_key_pem.encode("utf-8")
                    ),
                    "signature_sha256": sha256_hex(
                        request.signature.signature_base64.encode("ascii")
                    ),
                },
                provenance={
                    "predicateType": request.provenance.predicate_type,
                    "builderId": request.provenance.builder_id,
                    "subjectName": request.provenance.subject_name,
                },
                security_scan_status="passed",
            )
            return MarketplaceInstallDecision(
                status="approved",
                plugin_id=request.plugin_id,
                version=request.version,
                reason="package verified and approved",
            )
        except Exception as exc:
            return MarketplaceInstallDecision(
                status="quarantined",
                plugin_id=request.plugin_id,
                version=request.version,
                reason=str(exc),
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
