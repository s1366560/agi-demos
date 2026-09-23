"""Shared installed Bundle trust verification with exact registry admission.

The allowlist governs publication-time retrieval of already installed bundles; it
is not an initial marketplace-install fetch policy. This loader does not install
scoped session callbacks or wire scoped publication into application startup.
"""

from __future__ import annotations

import hashlib

from src.domain.model.plugins.generated_v2 import (
    BundleManifestV2,
    BundleReferenceV2,
    ScopeKindV2,
    ScopeV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_governance_repository import (
    PlatformPluginGovernanceRepository,
)
from src.infrastructure.plugins.package_registry import RegistryPluginArtifact, normalize_registry
from src.infrastructure.plugins.v2.bundle_archive import (
    VerifiedBundleArchiveV2,
    parse_bundle_archive_v2,
)
from src.infrastructure.plugins.v2.production_bundle import (
    PRODUCTION_BASE_BUNDLE_SOURCE_V2,
    ProductionBundleSourcesV2,
)
from src.infrastructure.plugins.v2.protocol import bundle_manifest_v2_to_payload

from .plugin_marketplace_install_service import MarketplaceArtifactClient


class MarketplacePublicationV2Error(ValueError):
    """Stable failure to resolve or publish one complete marketplace generation."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class InstalledVerifiedBundleLoaderV2:
    """Load only exact installed references; provenance alone never establishes trust."""

    def __init__(
        self,
        *,
        governance_repository: PlatformPluginGovernanceRepository,
        artifact_client: MarketplaceArtifactClient,
        production_sources: ProductionBundleSourcesV2,
        trusted_public_keys: tuple[str, ...],
        allowed_registries: frozenset[str] | None = None,
        scope: ScopeV2 = ScopeV2(kind=ScopeKindV2.ROOT),
    ) -> None:
        super().__init__()
        self._scope = scope
        self._governance_repository = governance_repository
        self._artifact_client = artifact_client
        self._production_sources = production_sources
        self._trusted_public_keys = tuple(trusted_public_keys)
        self._allowed_registries = (
            None
            if allowed_registries is None
            else frozenset(normalize_registry(registry) for registry in allowed_registries)
        )

    @staticmethod
    def _validate_reference(reference: BundleReferenceV2, bundle: BundleManifestV2) -> None:
        if (reference.bundle_id, reference.version, reference.digest) != (
            bundle.bundle_id,
            bundle.version,
            bundle.digest,
        ):
            raise MarketplacePublicationV2Error(
                "marketplace_bundle_manifest_changed", "Bundle differs from its exact reference"
            )

    async def load(self, reference: BundleReferenceV2) -> VerifiedBundleArchiveV2:
        if reference.source == PRODUCTION_BASE_BUNDLE_SOURCE_V2:
            bundle = self._production_sources.bundle
            approved = frozenset(
                permission for manifest in bundle.manifests for permission in manifest.permissions
            )
            self._validate_reference(reference, bundle)
            verified = parse_bundle_archive_v2(
                self._production_sources.bundle_archive,
                source=reference.source,
                approved_permissions=approved,
                require_signature=False,
                require_provenance=True,
            )
            self._validate_reference(reference, verified.manifest)
            return verified

        expected_source = _marketplace_bundle_source(reference.bundle_id, reference.version)
        if reference.source != expected_source:
            raise MarketplacePublicationV2Error(
                "marketplace_bundle_source_invalid",
                f"Bundle {reference.bundle_id} has an invalid marketplace source",
            )
        package = await self._governance_repository.get_package_version(
            reference.bundle_id,
            reference.version,
        )
        if package is None or package.install_status != "installed" or package.revoked:
            raise MarketplacePublicationV2Error(
                "marketplace_bundle_unavailable",
                f"Bundle {reference.bundle_id}@{reference.version} is not installed",
            )
        registry = normalize_registry(package.artifact_registry)
        if self._allowed_registries is not None and registry not in self._allowed_registries:
            raise MarketplacePublicationV2Error(
                "marketplace_registry_forbidden", "installed bundle registry is not allowed"
            )
        artifact = await self._artifact_client.fetch(
            registry=package.artifact_registry,
            repository=package.artifact_repository,
            manifest_digest=package.oci_manifest_digest,
        )
        self._validate_artifact(package.artifact_digest, package.oci_manifest_digest, artifact)
        permissions = []
        grants = [("root", "global")] if self._scope.kind is ScopeKindV2.ROOT else []
        if self._scope.tenant_id:
            grants.append(("tenant", self._scope.tenant_id))
        if self._scope.project_id:
            grants.append(("project", self._scope.project_id))
        for kind, identifier in grants:
            permissions.extend(
                await self._governance_repository.list_permissions(
                    reference.bundle_id,
                    scope_type=kind,
                    scope_id=identifier,
                )
            )
        verified = parse_bundle_archive_v2(
            artifact.archive,
            source=reference.source,
            trusted_public_keys=self._trusted_public_keys,
            approved_permissions=frozenset(row.permission for row in permissions),
            require_signature=True,
            require_provenance=True,
        )
        if bundle_manifest_v2_to_payload(verified.manifest) != package.manifest:
            raise MarketplacePublicationV2Error(
                "marketplace_bundle_manifest_changed",
                f"Bundle {reference.bundle_id}@{reference.version} differs from its trust record",
            )
        self._validate_reference(reference, verified.manifest)
        return verified

    @staticmethod
    def _validate_artifact(
        expected_layer_digest: str,
        expected_manifest_digest: str,
        artifact: RegistryPluginArtifact,
    ) -> None:
        actual_layer_digest = hashlib.sha256(artifact.archive).hexdigest()
        if (
            artifact.layer_digest != expected_layer_digest
            or actual_layer_digest != expected_layer_digest
            or artifact.manifest_digest != expected_manifest_digest
        ):
            raise MarketplacePublicationV2Error(
                "marketplace_artifact_changed",
                "marketplace OCI artifact differs from its immutable trust record",
            )


def _marketplace_bundle_source(bundle_id: str, version: str) -> str:
    return f"marketplace://{bundle_id}/{version}"
