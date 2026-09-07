"""Deterministic protocol-v2 Bundle/ProfileSource for the production baseline."""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path

from src.domain.model.plugins.artifact_attestation_v2 import artifact_digest_v2
from src.domain.model.plugins.generated_v2 import (
    BundleArtifactV2,
    BundleManifestV2,
    BundleReferenceV2,
    DataPlaneTargetV2,
    DesiredBundleSetV2,
    PluginManifestV2,
    ProfileLayerKindV2,
    ProfileLayerV2,
    ProfileSourceReferenceV2,
    ProfileSourceV2,
    ScopeKindV2,
    ScopeV2,
)

from .composer import load_profile_document_v2
from .layer_composer import (
    bundle_manifest_digest_v2,
    desired_bundle_set_digest_v2,
    profile_source_digest_v2,
)
from .protocol import (
    bundle_manifest_v2_to_payload,
    canonical_json_v2,
    parse_plugin_manifest_v2,
)
from .target_profiles import PRODUCTION_TARGET_MANIFEST_V2_PATHS

_ROOT = Path(__file__).resolve().parents[4]
_ZERO_DIGEST_V2 = f"sha256:{'0' * 64}"
PRODUCTION_BASE_BUNDLE_ID_V2 = "memstack-platform-base"
PRODUCTION_BASE_BUNDLE_SOURCE_V2 = "builtin://memstack-platform-base/2.0.0"
PRODUCTION_PROFILE_SOURCE_ID_V2 = "memstack-default-profile"
PRODUCTION_BASE_PROFILE_PATH_V2 = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
PRODUCTION_TARGET_PROFILE_PATH_V2 = (
    _ROOT / "config/plugin-profiles/memstack-production-target-hosts.v2.yaml"
)
PRODUCTION_MANIFEST_PATHS_V2 = (
    *PRODUCTION_TARGET_MANIFEST_V2_PATHS,
    _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",
)
_SOURCE_PREFIXES_V2 = (
    "repo+python://",
    "repo+rust://",
    "repo+typescript://",
)


class ProductionBundleV2Error(ValueError):
    """Repository production inputs cannot form one exact protocol-v2 baseline."""


@dataclass(frozen=True, kw_only=True)
class ProductionBundleSourcesV2:
    """Closed baseline inputs used to seed and reconcile DesiredBundleSetV2."""

    bundle: BundleManifestV2
    bundle_archive: bytes
    profile_source: ProfileSourceV2
    desired_set: DesiredBundleSetV2


@lru_cache(maxsize=1)
def production_bundle_sources_v2() -> ProductionBundleSourcesV2:
    """Build the deterministic built-in Bundle and exact ProfileSource reference graph."""
    manifests = tuple(_load_manifest(path) for path in PRODUCTION_MANIFEST_PATHS_V2)
    base_profile = load_profile_document_v2(PRODUCTION_BASE_PROFILE_PATH_V2)
    target_profile = load_profile_document_v2(PRODUCTION_TARGET_PROFILE_PATH_V2)
    if base_profile.patches or target_profile.patches:
        raise ProductionBundleV2Error("production v2 baseline cannot contain legacy patches")

    artifacts, artifact_bytes = _production_artifacts(manifests)
    bundle = BundleManifestV2(
        schema_version=2,
        bundle_id=PRODUCTION_BASE_BUNDLE_ID_V2,
        version="2.0.0",
        manifests=manifests,
        layers=(
            ProfileLayerV2(
                layer_id="memstack-platform-base",
                kind=ProfileLayerKindV2.BUNDLE,
                scope=ScopeV2(kind=ScopeKindV2.ROOT),
                entries=base_profile.entries,
                replacements=(),
                disabled_entry_ids=(),
            ),
        ),
        artifacts=artifacts,
        digest=_ZERO_DIGEST_V2,
        signature=None,
        provenance="repo://config/plugin-manifests-v2",
    )
    bundle = replace(bundle, digest=bundle_manifest_digest_v2(bundle))
    profile_source = ProfileSourceV2(
        schema_version=2,
        source_id=PRODUCTION_PROFILE_SOURCE_ID_V2,
        profile_id=base_profile.profile_id,
        revision=1,
        digest=_ZERO_DIGEST_V2,
        provenance="repo://config/plugin-profiles/memstack-production-target-hosts.v2.yaml",
        layers=(
            ProfileLayerV2(
                layer_id="memstack-production-target-hosts",
                kind=ProfileLayerKindV2.PROFILE,
                scope=ScopeV2(kind=ScopeKindV2.ROOT),
                entries=target_profile.entries,
                replacements=(),
                disabled_entry_ids=(),
            ),
        ),
    )
    profile_source = replace(
        profile_source,
        digest=profile_source_digest_v2(profile_source),
    )
    desired_set = DesiredBundleSetV2(
        schema_version=2,
        desired_set_id="memstack-default-v2",
        revision=1,
        bundles=(
            BundleReferenceV2(
                bundle_id=bundle.bundle_id,
                version=bundle.version,
                digest=bundle.digest,
                source=PRODUCTION_BASE_BUNDLE_SOURCE_V2,
            ),
        ),
        profile_source=ProfileSourceReferenceV2(
            source_id=profile_source.source_id,
            revision=profile_source.revision,
            digest=profile_source.digest,
        ),
        digest=_ZERO_DIGEST_V2,
    )
    desired_set = replace(
        desired_set,
        digest=desired_bundle_set_digest_v2(desired_set),
    )
    return ProductionBundleSourcesV2(
        bundle=bundle,
        bundle_archive=_bundle_archive(bundle, artifact_bytes),
        profile_source=profile_source,
        desired_set=desired_set,
    )


def _load_manifest(path: Path) -> PluginManifestV2:
    import json

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProductionBundleV2Error(f"cannot load production manifest {path}") from exc
    return parse_plugin_manifest_v2(payload)


def _production_artifacts(
    manifests: tuple[PluginManifestV2, ...],
) -> tuple[tuple[BundleArtifactV2, ...], dict[str, bytes]]:
    sources: dict[tuple[DataPlaneTargetV2, str], str] = {}
    for manifest in manifests:
        for module in manifest.modules:
            for target in module.targets:
                key = (target, module.artifact.digest)
                previous = sources.setdefault(key, module.artifact.source)
                if previous != module.artifact.source:
                    raise ProductionBundleV2Error(
                        f"artifact {target.value}@{module.artifact.digest} has conflicting sources"
                    )

    artifacts: list[BundleArtifactV2] = []
    content_by_path: dict[str, bytes] = {}
    for (target, digest), source in sorted(
        sources.items(),
        key=lambda item: (item[0][0].value, item[0][1]),
    ):
        content = _read_repository_artifact(source)
        if artifact_digest_v2(content) != digest:
            raise ProductionBundleV2Error(
                f"repository artifact {source} differs from generated manifest digest"
            )
        digest_hex = digest.removeprefix("sha256:")
        path = f"artifacts/{target.value}/{digest_hex}.bin"
        artifacts.append(
            BundleArtifactV2(
                artifact_id=f"memstack-{target.value}-{digest_hex[:16]}",
                target=target,
                path=path,
                digest=digest,
                size_bytes=len(content),
                media_type="application/octet-stream",
            )
        )
        content_by_path[path] = content
    return tuple(artifacts), content_by_path


def _read_repository_artifact(source: str) -> bytes:
    relative: str | None = None
    for prefix in _SOURCE_PREFIXES_V2:
        if source.startswith(prefix):
            relative = source.removeprefix(prefix)
            break
    if relative is None:
        raise ProductionBundleV2Error(f"unsupported production artifact source {source}")
    path = (_ROOT / relative).resolve()
    if not path.is_relative_to(_ROOT) or not path.is_file():
        raise ProductionBundleV2Error(f"production artifact source is unavailable: {source}")
    try:
        return path.read_bytes()
    except OSError as exc:
        raise ProductionBundleV2Error(f"cannot read production artifact {source}") from exc


def _bundle_archive(
    bundle: BundleManifestV2,
    artifacts: dict[str, bytes],
) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as archive:
        _write_archive_entry(
            archive,
            "bundle.json",
            canonical_json_v2(bundle_manifest_v2_to_payload(bundle)),
        )
        for path, content in sorted(artifacts.items()):
            _write_archive_entry(archive, path, content)
    return output.getvalue()


def _write_archive_entry(archive: zipfile.ZipFile, path: str, content: bytes) -> None:
    info = zipfile.ZipInfo(path, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_STORED
    info.external_attr = 0o100644 << 16
    archive.writestr(info, content)


__all__ = [
    "PRODUCTION_BASE_BUNDLE_ID_V2",
    "PRODUCTION_BASE_BUNDLE_SOURCE_V2",
    "PRODUCTION_PROFILE_SOURCE_ID_V2",
    "ProductionBundleSourcesV2",
    "ProductionBundleV2Error",
    "production_bundle_sources_v2",
]
