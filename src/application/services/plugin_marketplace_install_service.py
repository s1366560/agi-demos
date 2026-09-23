"""Application service for signed protocol-v2 marketplace Bundle installation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from src.application.schemas.plugin_marketplace import MarketplacePackageRequest
from src.application.services.plugin_marketplace_desired_bundle_service_v2 import (
    PluginMarketplaceDesiredBundleServiceV2,
)
from src.domain.model.plugins.generated_v2 import (
    BundleReferenceV2,
    ScopeKindV2,
    ScopeV2,
    TrustKindV2,
)
from src.infrastructure.adapters.secondary.persistence.models import PlatformPluginPackageModel
from src.infrastructure.adapters.secondary.persistence.platform_plugin_governance_repository import (
    PlatformPluginGovernanceRepository,
)
from src.infrastructure.plugins.governance import sha256_hex
from src.infrastructure.plugins.package_registry import RegistryPluginArtifact
from src.infrastructure.plugins.v2.bundle_archive import parse_bundle_archive_v2
from src.infrastructure.plugins.v2.protocol import bundle_manifest_v2_to_payload


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
    desired_changed: bool = False


class PluginMarketplaceInstallService:
    """Verify one closed v2 Bundle and append only protocol-v2 desired state."""

    def __init__(  # pyright: ignore[reportMissingSuperCall]
        self,
        repository: PlatformPluginGovernanceRepository,
        desired_bundles: PluginMarketplaceDesiredBundleServiceV2,
        artifact_client: MarketplaceArtifactClient,
        *,
        trusted_public_keys: tuple[str, ...],
    ) -> None:
        self._repository = repository
        self._desired_bundles = desired_bundles
        self._artifact_client = artifact_client
        self._trusted_public_keys = trusted_public_keys

    async def request_install(
        self,
        *,
        request: MarketplacePackageRequest,
        actor_id: str | None = None,
    ) -> MarketplaceInstallDecision:
        """Approve only a signed, provenance-bearing, permission-approved v2 Bundle."""
        try:
            _admit_install_request(request, trusted_public_keys=self._trusted_public_keys)
            existing = await self._repository.get_package_version(
                request.plugin_id,
                request.version,
            )
            catalog_material: _CatalogSignatureMaterial | None = None
            if request.signature is None or request.provenance is None:
                catalog_material = _resolve_catalog_signature_material(
                    existing,
                    trusted_public_keys=self._trusted_public_keys,
                )
            else:
                # Fail closed on an untrusted claimant before touching artifacts.
                _ = _trusted_signer_fingerprint(
                    request.signature.public_key_pem,
                    self._trusted_public_keys,
                )

            artifact = await self._artifact_client.fetch(
                registry=request.artifact.registry,
                repository=request.artifact.repository,
                manifest_digest=request.artifact.manifest_sha256,
            )
            if artifact.layer_digest != request.artifact_sha256:
                raise ValueError("requested artifact digest does not match the OCI layer")
            verified = parse_bundle_archive_v2(
                artifact.archive,
                source=_bundle_source(request.plugin_id, request.version),
                trusted_public_keys=_verification_keys(request, catalog_material),
                approved_permissions=request.approved_permissions,
                require_signature=True,
                require_provenance=True,
            )
            bundle = verified.manifest
            bundle_payload = bundle_manifest_v2_to_payload(bundle)
            if bundle_payload != request.manifest:
                raise ValueError("Bundle descriptor differs from its catalog declaration")
            if bundle.bundle_id != request.plugin_id or bundle.version != request.version:
                raise ValueError("Bundle identity differs from the marketplace package")
            if any(manifest.trust is TrustKindV2.BUILTIN for manifest in bundle.manifests):
                raise ValueError("marketplace Bundle cannot claim builtin trust")
            signature = bundle.signature
            if signature is None:
                raise ValueError("marketplace Bundle must carry a detached signature")
            signature_record, provenance_record = _install_records(
                request,
                signature=signature,
                bundle_provenance=bundle.provenance,
                catalog_material=catalog_material,
                trusted_public_keys=self._trusted_public_keys,
            )
            _validate_immutable_package_version(
                existing,
                publisher=request.publisher,
                artifact=artifact,
                artifact_digest=request.artifact_sha256,
                manifest=bundle_payload,
                signature=signature_record,
                provenance=provenance_record,
            )

            _ = await self._repository.upsert_package(
                plugin_id=bundle.bundle_id,
                version=bundle.version,
                publisher=request.publisher,
                artifact_digest=request.artifact_sha256,
                artifact_registry=artifact.registry,
                artifact_repository=artifact.repository,
                oci_manifest_digest=artifact.manifest_digest,
                manifest=bundle_payload,
                signature=signature_record,
                provenance=provenance_record,
                security_scan_status="passed",
            )
            mutation = await self._desired_bundles.install(
                scope=ScopeV2(
                    kind=ScopeKindV2.PROJECT if request.project_id else ScopeKindV2.TENANT,
                    tenant_id=request.tenant_id,
                    project_id=request.project_id,
                ),
                bundle=BundleReferenceV2(
                    bundle_id=bundle.bundle_id,
                    version=bundle.version,
                    digest=bundle.digest,
                    source=_bundle_source(bundle.bundle_id, bundle.version),
                ),
                actor_id=actor_id,
            )
            for permission in sorted(request.approved_permissions):
                _ = await self._repository.grant_permission(
                    plugin_id=request.plugin_id,
                    permission=permission,
                    scope_type="project" if request.project_id else "tenant",
                    scope_id=request.project_id or request.tenant_id,
                    granted_by=actor_id,
                )
            return MarketplaceInstallDecision(
                status="approved",
                plugin_id=request.plugin_id,
                version=request.version,
                reason="protocol v2 Bundle verified and desired",
                desired_revision=mutation.record.desired_set.revision,
                desired_changed=mutation.changed,
            )
        except Exception as exc:
            return MarketplaceInstallDecision(
                status="quarantined",
                plugin_id=request.plugin_id,
                version=request.version,
                reason=str(exc),
            )


def _bundle_source(bundle_id: str, version: str) -> str:
    return f"marketplace://{bundle_id}/{version}"


@dataclass(frozen=True)
class _CatalogSignatureMaterial:
    """Install material resolved from a redacted catalog row + trust store.

    The signature and provenance records are the catalog row's own (verbatim),
    so a catalog-driven reinstall never mutates the immutable declaration. The
    archive signature is pinned by the row's recorded signature digest, and the
    signing PEM is picked from the trust store by the recorded signer
    fingerprint.
    """

    verification_keys: tuple[str, ...]
    signature_sha256: str
    signature_record: dict[str, object]
    provenance_record: dict[str, object]


def _resolve_catalog_signature_material(
    existing: PlatformPluginPackageModel | None,
    *,
    trusted_public_keys: tuple[str, ...],
) -> _CatalogSignatureMaterial:
    if existing is None:
        raise ValueError("catalog entry is required to resolve marketplace signature material")
    if existing.revoked:
        raise ValueError("revoked marketplace Bundle version cannot be reinstalled")
    signature_record = dict(existing.signature) if isinstance(existing.signature, dict) else {}
    provenance_record = dict(existing.provenance) if isinstance(existing.provenance, dict) else {}
    fingerprint = signature_record.get("public_key_sha256")
    signature_sha256 = signature_record.get("signature_sha256")
    if not isinstance(fingerprint, str) or not fingerprint:
        raise ValueError("catalog entry is missing its signer fingerprint")
    if not isinstance(signature_sha256, str) or not signature_sha256:
        raise ValueError("catalog entry is missing its signature digest")
    if not provenance_record:
        raise ValueError("catalog entry is missing provenance metadata")
    if not trusted_public_keys:
        raise ValueError("protocol v2 marketplace trust store is empty")
    verification_keys = _pem_for_fingerprint(fingerprint, trusted_public_keys)
    return _CatalogSignatureMaterial(
        verification_keys=verification_keys,
        signature_sha256=signature_sha256,
        signature_record=signature_record,
        provenance_record=provenance_record,
    )


def _admit_install_request(
    request: MarketplacePackageRequest,
    *,
    trusted_public_keys: tuple[str, ...],
) -> None:
    """Fail closed on policy violations and malformed material before any I/O."""
    if not trusted_public_keys:
        raise ValueError("protocol v2 marketplace trust store is empty")
    if not request.tenant_admin_approved:
        raise ValueError("tenant admin approval is required")
    if not request.security_scan_passed:
        raise ValueError("security scan failed")
    if (request.signature is None) != (request.provenance is None):
        raise ValueError("marketplace signature and provenance must be provided together")


def _verification_keys(
    request: MarketplacePackageRequest,
    catalog_material: _CatalogSignatureMaterial | None,
) -> tuple[str, ...]:
    if request.signature is not None:
        return (request.signature.public_key_pem,)
    assert catalog_material is not None
    return catalog_material.verification_keys


def _install_records(
    request: MarketplacePackageRequest,
    *,
    signature: str,
    bundle_provenance: str | None,
    catalog_material: _CatalogSignatureMaterial | None,
    trusted_public_keys: tuple[str, ...],
) -> tuple[dict[str, object], dict[str, object]]:
    """Derive the stored signature/provenance records for one verified bundle."""
    if catalog_material is not None:
        if sha256_hex(signature.encode("ascii")) != catalog_material.signature_sha256:
            raise ValueError("Bundle signature differs from its catalog declaration")
        return catalog_material.signature_record, catalog_material.provenance_record
    assert request.signature is not None
    assert request.provenance is not None
    if signature != request.signature.signature_base64:
        raise ValueError("Bundle signature differs from its catalog declaration")
    signature_record: dict[str, object] = {
        "algorithm": "Ed25519",
        "public_key_sha256": _trusted_signer_fingerprint(
            request.signature.public_key_pem,
            trusted_public_keys,
        ),
        "signature_sha256": sha256_hex(signature.encode("ascii")),
    }
    provenance_record: dict[str, object] = {
        "reference": bundle_provenance,
        "predicateType": request.provenance.predicate_type,
        "builderId": request.provenance.builder_id,
        "subjectName": request.provenance.subject_name,
    }
    return signature_record, provenance_record


def _pem_for_fingerprint(
    fingerprint: str,
    trusted_pems: tuple[str, ...],
) -> tuple[str, ...]:
    for trusted_pem in trusted_pems:
        try:
            if _trusted_signer_fingerprint(trusted_pem, trusted_pems) == fingerprint:
                return (trusted_pem,)
        except ValueError:
            continue
    raise ValueError("catalog signer fingerprint is not covered by the trust store")


def _trusted_signer_fingerprint(claimed_pem: str, trusted_pems: tuple[str, ...]) -> str:
    try:
        claimed = serialization.load_pem_public_key(claimed_pem.encode("utf-8"))
    except (TypeError, ValueError) as exc:
        raise ValueError("marketplace signing key must be valid PEM") from exc
    if not isinstance(claimed, Ed25519PublicKey):
        raise ValueError("marketplace signing key must be Ed25519")
    claimed_raw = claimed.public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
    for trusted_pem in trusted_pems:
        try:
            trusted = serialization.load_pem_public_key(trusted_pem.encode("utf-8"))
        except (TypeError, ValueError):
            continue
        if not isinstance(trusted, Ed25519PublicKey):
            continue
        trusted_raw = trusted.public_bytes(
            serialization.Encoding.Raw,
            serialization.PublicFormat.Raw,
        )
        if trusted_raw == claimed_raw:
            return sha256_hex(claimed_raw)
    raise ValueError("marketplace signing key is not trusted")


def _validate_immutable_package_version(
    existing: PlatformPluginPackageModel | None,
    *,
    publisher: str,
    artifact: RegistryPluginArtifact,
    artifact_digest: str,
    manifest: dict[str, object],
    signature: dict[str, object],
    provenance: dict[str, object],
) -> None:
    if existing is None:
        return
    if existing.revoked:
        raise ValueError("revoked marketplace Bundle version cannot be reinstalled")
    immutable_fields_match = (
        existing.publisher == publisher
        and existing.artifact_digest == artifact_digest
        and existing.artifact_registry == artifact.registry
        and existing.artifact_repository == artifact.repository
        and existing.oci_manifest_digest == artifact.manifest_digest
        and existing.manifest == manifest
        and existing.signature == signature
        and existing.provenance == provenance
    )
    if not immutable_fields_match:
        raise ValueError("marketplace Bundle version is immutable")


__all__ = [
    "MarketplaceArtifactClient",
    "MarketplaceInstallDecision",
    "PluginMarketplaceInstallService",
]
