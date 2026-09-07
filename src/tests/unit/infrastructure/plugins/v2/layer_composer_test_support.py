"""Typed builders shared by protocol-v2 layer composer unit tests."""

from __future__ import annotations

from dataclasses import replace

from src.domain.model.plugins.generated_v2 import (
    BundleArtifactV2,
    BundleManifestV2,
    BundleReferenceV2,
    DataPlaneTargetV2,
    DesiredBundleSetV2,
    PluginManifestV2,
    ProfileEntryV2,
    ProfileLayerKindV2,
    ProfileLayerV2,
    ProfileSourceReferenceV2,
    ProfileSourceV2,
    QuotaV2,
    RestartPolicyV2,
    RuntimeKindV2,
    ScopeKindV2,
    ScopeV2,
    TrustKindV2,
)
from src.infrastructure.plugins.v2.layer_composer import (
    bundle_manifest_digest_v2,
    desired_bundle_set_digest_v2,
    profile_source_digest_v2,
)

_ZERO_DIGEST = f"sha256:{'0' * 64}"


def _scope(
    kind: ScopeKindV2 = ScopeKindV2.ROOT,
    *,
    tenant_id: str = "tenant-a",
    project_id: str = "project-a",
    session_id: str = "session-a",
) -> ScopeV2:
    return ScopeV2(
        kind=kind,
        tenant_id=tenant_id if kind is not ScopeKindV2.ROOT else None,
        project_id=project_id if kind in {ScopeKindV2.PROJECT, ScopeKindV2.SESSION} else None,
        session_id=session_id if kind is ScopeKindV2.SESSION else None,
    )


def _entry(
    entry_id: str,
    *,
    scope: ScopeV2 | None = None,
    plugin_ref: str = "plugin-a",
    label: str | None = None,
    enabled: bool = True,
) -> ProfileEntryV2:
    return ProfileEntryV2(
        entry_id=entry_id,
        parent_entry_id=None,
        plugin_ref=plugin_ref,
        module_ref=f"builtin://tests/{plugin_ref}/{entry_id}",
        enabled=enabled,
        config={"label": label or entry_id},
        inject={},
        isolate={},
        scope=scope or _scope(),
        permissions=(),
        quotas=QuotaV2(),
        restart_policy=RestartPolicyV2.HOT_GENERATION,
    )


def _manifest(plugin_id: str) -> PluginManifestV2:
    return PluginManifestV2(
        schema_version=2,
        plugin_id=plugin_id,
        version="1.0.0",
        runtime=RuntimeKindV2.PYTHON_TRUSTED,
        trust=TrustKindV2.BUILTIN,
        modules=(),
        permissions=(),
        quotas=QuotaV2(),
    )


def _layer(
    layer_id: str,
    kind: ProfileLayerKindV2,
    *,
    scope: ScopeV2 | None = None,
    entries: tuple[ProfileEntryV2, ...] = (),
    replacements: tuple[ProfileEntryV2, ...] = (),
    disabled_entry_ids: tuple[str, ...] = (),
) -> ProfileLayerV2:
    return ProfileLayerV2(
        layer_id=layer_id,
        kind=kind,
        scope=scope or _scope(),
        entries=entries,
        replacements=replacements,
        disabled_entry_ids=disabled_entry_ids,
    )


def _bundle(
    bundle_id: str,
    *,
    plugin_id: str,
    layers: tuple[ProfileLayerV2, ...],
    version: str = "1.0.0",
) -> BundleManifestV2:
    bundle = BundleManifestV2(
        schema_version=2,
        bundle_id=bundle_id,
        version=version,
        manifests=(_manifest(plugin_id),),
        layers=layers,
        artifacts=(
            BundleArtifactV2(
                artifact_id=f"{bundle_id}-python",
                target=DataPlaneTargetV2.PYTHON,
                path=f"artifacts/{bundle_id}.py",
                digest=_ZERO_DIGEST,
                size_bytes=1,
                media_type="text/x-python",
            ),
        ),
        digest=_ZERO_DIGEST,
        signature=None,
        provenance="tests",
    )
    return replace(bundle, digest=bundle_manifest_digest_v2(bundle))


def _source(layers: tuple[ProfileLayerV2, ...]) -> ProfileSourceV2:
    source = ProfileSourceV2(
        schema_version=2,
        source_id="tenant-a-profile-source",
        profile_id="memstack-default-v2",
        revision=3,
        digest=_ZERO_DIGEST,
        provenance="tests",
        layers=layers,
    )
    return replace(source, digest=profile_source_digest_v2(source))


def _desired(
    bundles: tuple[BundleManifestV2, ...],
    source: ProfileSourceV2,
) -> DesiredBundleSetV2:
    desired = DesiredBundleSetV2(
        schema_version=2,
        desired_set_id="tenant-a-desired",
        revision=7,
        bundles=tuple(
            BundleReferenceV2(
                bundle_id=bundle.bundle_id,
                version=bundle.version,
                digest=bundle.digest,
                source=f"registry://{bundle.bundle_id}",
            )
            for bundle in bundles
        ),
        profile_source=ProfileSourceReferenceV2(
            source_id=source.source_id,
            revision=source.revision,
            digest=source.digest,
        ),
        digest=_ZERO_DIGEST,
    )
    return replace(desired, digest=desired_bundle_set_digest_v2(desired))
