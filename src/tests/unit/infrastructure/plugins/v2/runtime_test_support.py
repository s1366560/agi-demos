"""Explicit in-memory artifact fixtures for protocol-v2 runtime unit tests."""

from __future__ import annotations

from dataclasses import replace

from src.domain.model.plugins.artifact_attestation_v2 import artifact_digest_v2
from src.domain.model.plugins.generated_v2 import (
    DataPlaneTargetV2,
    PluginManifestV2,
    PluginModuleV2,
    ProfileSnapshotV2,
)
from src.infrastructure.plugins.v2.artifacts import ResolvedPluginArtifactV2
from src.infrastructure.plugins.v2.composer import ProfileDocumentV2
from src.infrastructure.plugins.v2.runtime_contracts import ModuleCatalogEntryV2

RUNTIME_TEST_ARTIFACT_BYTES_V2 = b"memstack-plugin-runtime-v2-test-artifact\n"
RUNTIME_TEST_ARTIFACT_DIGEST_V2 = artifact_digest_v2(RUNTIME_TEST_ARTIFACT_BYTES_V2)


class RuntimeTestArtifactResolverV2:
    """Return explicit fixture bytes while refusing dynamic entrypoint loading."""

    def resolve(self, module: PluginModuleV2) -> ResolvedPluginArtifactV2:
        return ResolvedPluginArtifactV2(
            module_ref=module.module_ref,
            entrypoint=module.entrypoint,
            source=module.artifact.source,
            canonical_bytes=RUNTIME_TEST_ARTIFACT_BYTES_V2,
            load=lambda: (_ for _ in ()).throw(
                AssertionError("unit test must provide a preloaded PluginDefinitionV2")
            ),
        )


def target_catalog_from_snapshot_v2(
    snapshot: ProfileSnapshotV2,
    target: DataPlaneTargetV2 = DataPlaneTargetV2.PYTHON,
) -> dict[str, ModuleCatalogEntryV2]:
    """Build a test-only catalog that remains structurally identical to generated rows."""
    return {
        module.module_ref: ModuleCatalogEntryV2(
            plugin_id=manifest.plugin_id,
            plugin_version=manifest.version,
            module_ref=module.module_ref,
            entrypoint=module.entrypoint,
            artifact_source=module.artifact.source,
            artifact_digest=module.artifact.digest,
            targets=module.targets,
            contract_digest=module.contract_digest,
        )
        for manifest in snapshot.manifests
        for module in manifest.modules
        if target in module.targets
    }


def disable_service_provider_closure_v2(
    document: ProfileDocumentV2,
    manifest: PluginManifestV2,
    *,
    missing_service: str,
    kept_consumer_module_ref: str,
) -> ProfileDocumentV2:
    """Disable one Provider and every dependent module except the test subject."""
    disabled_modules = {
        module.module_ref
        for module in manifest.modules
        if any(
            provided.service == missing_service for provided in module.contract.services.provides
        )
    }
    unavailable_services = {missing_service}
    changed = True
    while changed:
        changed = False
        for module in manifest.modules:
            if (
                module.module_ref == kept_consumer_module_ref
                or module.module_ref in disabled_modules
            ):
                continue
            if not any(
                required.service in unavailable_services
                for required in module.contract.services.requires
            ):
                continue
            disabled_modules.add(module.module_ref)
            unavailable_services.update(
                provided.service for provided in module.contract.services.provides
            )
            changed = True

    return replace(
        document,
        entries=tuple(
            replace(entry, enabled=False) if entry.module_ref in disabled_modules else entry
            for entry in document.entries
        ),
    )


__all__ = [
    "RUNTIME_TEST_ARTIFACT_BYTES_V2",
    "RUNTIME_TEST_ARTIFACT_DIGEST_V2",
    "RuntimeTestArtifactResolverV2",
    "disable_service_provider_closure_v2",
    "target_catalog_from_snapshot_v2",
]
