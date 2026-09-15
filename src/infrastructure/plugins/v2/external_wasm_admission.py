"""Generation-local admission of signed archive-backed WASM modules."""

from collections.abc import Mapping, Sequence
from functools import partial

from src.domain.model.plugins.artifact_attestation_v2 import artifact_digest_v2
from src.domain.model.plugins.generated_v2 import (
    BundleReferenceV2,
    DataPlaneTargetV2,
    PluginManifestV2,
    PluginModuleV2,
    ProfileEntryV2,
    RuntimeKindV2,
    TrustKindV2,
)

from .artifacts import ResolvedPluginArtifactV2
from .bundle_archive import VerifiedBundleArchiveV2, require_signed_archive_verification_v2
from .runtime_context import RuntimeV2Error
from .runtime_contracts import ModuleCatalogEntryV2, generated_target_catalog_v2


def admit_external_wasm_artifacts_v2(
    *,
    manifests: Sequence[PluginManifestV2],
    entries: Sequence[ProfileEntryV2],
    target: DataPlaneTargetV2,
    target_catalog: Mapping[str, ModuleCatalogEntryV2],
    archives: Sequence[VerifiedBundleArchiveV2] | None,
) -> tuple[dict[str, ModuleCatalogEntryV2], dict[str, ResolvedPluginArtifactV2]]:
    """Never derive executable identity from an unverified snapshot alone."""
    catalog = dict(target_catalog)
    resolved: dict[str, ResolvedPluginArtifactV2] = {}
    if not any(
        target in module.targets and module.module_ref not in target_catalog
        for manifest in manifests
        for module in manifest.modules
    ):
        return catalog, resolved
    builtin_catalog = {
        key: row
        for plane in DataPlaneTargetV2
        for key, row in generated_target_catalog_v2(plane).items()
    }
    builtin_plugins = {row.plugin_id for row in builtin_catalog.values()}
    for manifest in manifests:
        for module in manifest.modules:
            if target not in module.targets or module.module_ref in target_catalog:
                continue
            if (
                manifest.plugin_id in builtin_plugins
                or module.module_ref in builtin_catalog
                or module.module_ref.startswith("builtin://")
            ):
                raise RuntimeV2Error(
                    "external_builtin_collision", "external module claims a builtin identity"
                )
            if archives is None:
                raise RuntimeV2Error(
                    "missing_target_catalog", "external module requires verified archives"
                )
            if target is not DataPlaneTargetV2.PYTHON or module.targets != (
                DataPlaneTargetV2.PYTHON,
            ):
                raise RuntimeV2Error(
                    "external_wasm_target_invalid", "external WASM execution supports only Python"
                )
            if (
                manifest.runtime is not RuntimeKindV2.WASM
                or manifest.trust is not TrustKindV2.SIGNED
            ):
                raise RuntimeV2Error(
                    "external_runtime_forbidden", "external execution requires signed WASM"
                )
            content, bundle_reference = _verified_content(
                manifest, module, target, archives, entries
            )
            if module.module_ref in resolved:
                raise RuntimeV2Error(
                    "duplicate_module_ref", "external module identity is duplicated"
                )
            catalog[module.module_ref] = ModuleCatalogEntryV2(
                plugin_id=manifest.plugin_id,
                plugin_version=manifest.version,
                module_ref=module.module_ref,
                entrypoint=module.entrypoint,
                artifact_source=module.artifact.source,
                artifact_digest=module.artifact.digest,
                targets=module.targets,
                contract_digest=module.contract_digest,
            )
            resolved[module.module_ref] = ResolvedPluginArtifactV2(
                module_ref=module.module_ref,
                entrypoint=module.entrypoint,
                source=module.artifact.source,
                canonical_bytes=content,
                load=partial(_load_wasm_definition, bundle_reference, manifest, module, content),
            )
    return catalog, resolved


def _verified_content(
    manifest: PluginManifestV2,
    module: PluginModuleV2,
    target: DataPlaneTargetV2,
    archives: Sequence[VerifiedBundleArchiveV2],
    entries: Sequence[ProfileEntryV2],
) -> tuple[bytes, BundleReferenceV2]:
    candidates = [
        archive
        for archive in archives
        if any(item.plugin_id == manifest.plugin_id for item in archive.manifest.manifests)
    ]
    if len(candidates) != 1:
        raise RuntimeV2Error(
            "external_manifest_ownership_invalid",
            "external manifest must have one archive owner",
        )
    archive = candidates[0]
    approved = require_signed_archive_verification_v2(archive)
    archived = next(
        item for item in archive.manifest.manifests if item.plugin_id == manifest.plugin_id
    )
    if archived != manifest:
        raise RuntimeV2Error(
            "external_manifest_mismatch",
            "snapshot manifest differs from its signed archive",
        )
    if not set(manifest.permissions).issubset(approved):
        raise RuntimeV2Error(
            "external_permission_unapproved",
            "external manifest permission was not approved",
        )
    for entry in entries:
        if entry.plugin_ref == manifest.plugin_id and not set(entry.permissions).issubset(
            manifest.permissions
        ):
            raise RuntimeV2Error(
                "external_entry_permission_invalid", "entry requests undeclared permissions"
            )
    artifacts = [
        item
        for item in archive.manifest.artifacts
        if item.target is target and item.digest == module.artifact.digest
    ]
    if not artifacts:
        raise RuntimeV2Error("candidate_artifact_missing", "signed module artifact is missing")
    payloads = [archive.artifacts.get(item.artifact_id) for item in artifacts]
    content = payloads[0]
    if (
        content is None
        or any(item != content for item in payloads)
        or artifact_digest_v2(content) != module.artifact.digest
    ):
        raise RuntimeV2Error("artifact_digest_mismatch", "signed module artifact bytes differ")
    return content, BundleReferenceV2(
        bundle_id=archive.manifest.bundle_id,
        version=archive.manifest.version,
        digest=archive.manifest.digest,
        source=archive.source,
    )


def _load_wasm_definition(
    bundle_reference: BundleReferenceV2,
    manifest: PluginManifestV2,
    module: PluginModuleV2,
    content: bytes,
) -> object:
    # Delayed import avoids the definition factory's runtime type dependency cycle.
    from .wasm_tool_runtime import create_verified_wasm_definition_v2

    return create_verified_wasm_definition_v2(
        bundle_reference=bundle_reference, manifest=manifest, module=module, artifact_bytes=content
    )
