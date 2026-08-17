"""Application service for quarantined marketplace package installation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from src.application.schemas.plugin_marketplace import MarketplacePackageRequest
from src.domain.model.plugins import parse_plugin_manifest
from src.domain.ports.plugins import PluginPermission
from src.infrastructure.adapters.secondary.persistence.platform_plugin_governance_repository import (
    PlatformPluginGovernanceRepository,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_repository import (
    PlatformPluginRepository,
)
from src.infrastructure.plugins.governance import (
    MarketplaceCatalogEntry,
    PluginPackageBundle,
    PluginPackageVerifier,
    PluginTrustGate,
    sha256_hex,
)
from src.infrastructure.plugins.package_archive import (
    verify_plugin_package_archive,
)
from src.infrastructure.plugins.package_registry import RegistryPluginArtifact


class MarketplaceArtifactClient(Protocol):
    async def fetch(
        self,
        *,
        registry: str,
        repository: str,
        manifest_digest: str,
    ) -> RegistryPluginArtifact: ...


@dataclass(frozen=True)
class MarketplaceInstallDecision:
    status: Literal["approved", "quarantined"]
    plugin_id: str
    version: str
    reason: str
    desired_revision: int | None = None


class PluginMarketplaceInstallService:
    """Verify and record an install without mutating desired plugin state on failure."""

    def __init__(
        self,
        repository: PlatformPluginGovernanceRepository,
        plugin_repository: PlatformPluginRepository,
        artifact_client: MarketplaceArtifactClient,
        *,
        trusted_public_keys: tuple[str, ...] = (),
        trust_gate: PluginTrustGate | None = None,
    ) -> None:
        self._repository = repository
        self._plugin_repository = plugin_repository
        self._artifact_client = artifact_client
        self._trust_gate = trust_gate or PluginTrustGate()
        self._keys = trusted_public_keys

    async def request_install(
        self,
        *,
        request: MarketplacePackageRequest,
    ) -> MarketplaceInstallDecision:
        """Return approved only when signature, provenance, scan, and permission gates pass."""
        try:
            artifact = await self._artifact_client.fetch(
                registry=request.artifact.registry,
                repository=request.artifact.repository,
                manifest_digest=request.artifact.manifest_sha256,
            )
            if artifact.layer_digest != request.artifact_sha256:
                raise ValueError("requested artifact digest does not match the OCI layer")
            package = verify_plugin_package_archive(artifact.archive)
            if package.manifest != request.manifest:
                raise ValueError("package manifest differs from its catalog declaration")
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
                manifest=parsed_manifest.to_payload(),
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
            await self._plugin_repository.upsert_catalog_manifest(parsed_manifest)
            desired = await self._plugin_repository.set_desired_state(
                plugin_id=parsed_manifest.id,
                enabled=True,
                config={},
            )
            for permission in sorted(permissions, key=lambda item: item.value):
                await self._repository.grant_permission(
                    plugin_id=request.plugin_id,
                    permission=permission.value,
                    scope_type="tenant",
                    scope_id=request.tenant_id,
                )
            return MarketplaceInstallDecision(
                status="approved",
                plugin_id=request.plugin_id,
                version=request.version,
                reason="package verified and approved",
                desired_revision=desired.revision,
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
