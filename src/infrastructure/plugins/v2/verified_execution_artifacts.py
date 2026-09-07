"""Attest actual execution artifacts against contracts and optional verified archives."""

from collections.abc import Mapping, Sequence

from src.domain.model.plugins.artifact_attestation_v2 import artifact_digest_v2
from src.domain.model.plugins.generated_v2 import DataPlaneTargetV2, PluginModuleV2

from .artifacts import PluginArtifactResolverV2, ResolvedPluginArtifactV2
from .bundle_archive import VerifiedBundleArchiveV2
from .runtime_context import RuntimeV2Error
from .runtime_contracts import ModuleCatalogEntryV2, validate_contract_digests_v2


def attest_execution_artifacts_v2(
    target_rows: Sequence[tuple[str, str, PluginModuleV2]],
    *,
    target_catalog: Mapping[str, ModuleCatalogEntryV2],
    target: DataPlaneTargetV2,
    resolver: PluginArtifactResolverV2,
    verified_archives: Sequence[VerifiedBundleArchiveV2] | None = None,
) -> dict[str, ResolvedPluginArtifactV2]:
    for plugin_id, plugin_version, module in target_rows:
        catalog_entry = target_catalog.get(module.module_ref)
        if catalog_entry is None:
            raise RuntimeV2Error(
                "missing_target_catalog",
                f"module {module.module_ref} is absent from {target.value} catalog",
            )
        validate_contract_digests_v2(
            module,
            catalog_entry=catalog_entry,
            plugin_id=plugin_id,
            plugin_version=plugin_version,
        )

    expected = _verified_bytes(verified_archives, target)
    resolved_artifacts: dict[str, ResolvedPluginArtifactV2] = {}
    for _plugin_id, _plugin_version, module in target_rows:
        resolved = resolver.resolve(module)
        if expected is not None:
            content = expected.get(module.artifact.digest)
            if content is None:
                raise RuntimeV2Error("candidate_artifact_missing", "verified artifact is missing")
            if resolved.canonical_bytes != content:
                raise RuntimeV2Error(
                    "candidate_execution_artifact_mismatch",
                    "executable bytes differ from the verified archive",
                )
        if (
            resolved.module_ref != module.module_ref
            or resolved.entrypoint != module.entrypoint
            or resolved.source != module.artifact.source
        ):
            raise RuntimeV2Error(
                "artifact_resolution_mismatch",
                f"module {module.module_ref} resolver returned different artifact metadata",
            )
        actual_digest = artifact_digest_v2(resolved.canonical_bytes)
        if actual_digest != module.artifact.digest:
            raise RuntimeV2Error(
                "artifact_digest_mismatch",
                f"module {module.module_ref} resolved bytes differ from manifest",
            )
        resolved_artifacts[module.module_ref] = resolved
    return resolved_artifacts


def _verified_bytes(
    verified_archives: Sequence[VerifiedBundleArchiveV2] | None, target: DataPlaneTargetV2
) -> dict[str, bytes] | None:
    expected: dict[str, bytes] | None = None
    if verified_archives is not None:
        expected = {}
        for archive in verified_archives:
            for artifact in archive.manifest.artifacts:
                if artifact.target is target:
                    content = archive.artifacts[artifact.artifact_id]
                    previous = expected.get(artifact.digest)
                    if previous is not None and previous != content:
                        raise RuntimeV2Error(
                            "candidate_artifact_conflict", "conflicting archive bytes"
                        )
                    expected[artifact.digest] = content
    return expected
