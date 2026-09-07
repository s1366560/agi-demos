"""Pure scope-private Bundle and ProfileSource composition for protocol v2."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from enum import Enum
from typing import NoReturn, cast

from src.domain.model.plugins.generated_v2 import (
    BundleManifestV2,
    DesiredBundleSetV2,
    PluginManifestV2,
    ProfileEntryV2,
    ProfileLayerKindV2,
    ProfileLayerV2,
    ProfileSourceReferenceV2,
    ProfileSourceV2,
    ScopeKindV2,
    ScopeV2,
)

from .composer import ProfileDocumentV2
from .protocol import canonical_json_v2

_LAYER_KIND_RANK = {
    ProfileLayerKindV2.PROFILE: 0,
    ProfileLayerKindV2.TENANT: 1,
    ProfileLayerKindV2.PROJECT: 2,
    ProfileLayerKindV2.SESSION: 3,
}
_SCOPE_KIND_RANK = {
    ScopeKindV2.ROOT: 0,
    ScopeKindV2.TENANT: 1,
    ScopeKindV2.PROJECT: 2,
    ScopeKindV2.SESSION: 3,
}
type JsonValueV2 = None | bool | int | float | str | list["JsonValueV2"] | dict[str, "JsonValueV2"]


class ProfileSourceCompositionV2Error(ValueError):
    """Stable rejection raised before a source composition reaches LoaderV2."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True, kw_only=True)
class ProfileLayerProvenanceV2:
    """Exact source evidence for one layer applied to a scope-private document."""

    layer_id: str
    kind: ProfileLayerKindV2
    scope: ScopeV2
    source_kind: str
    source_id: str
    source_version: str
    source_digest: str


@dataclass(frozen=True, kw_only=True)
class ProfileSourceCompositionV2:
    """A deterministic pre-snapshot composition plus immutable source evidence."""

    document: ProfileDocumentV2
    manifests: tuple[PluginManifestV2, ...]
    target_scope: ScopeV2
    desired_set_id: str
    desired_set_revision: int
    desired_set_digest: str
    profile_source: ProfileSourceReferenceV2
    layer_provenance: tuple[ProfileLayerProvenanceV2, ...]
    disabled_entry_ids: tuple[str, ...]


def bundle_manifest_digest_v2(bundle: BundleManifestV2) -> str:
    """Digest immutable Bundle contents, excluding its digest and detached signature."""
    payload = _dataclass_payload(bundle)
    del payload["digest"]
    del payload["signature"]
    return _sha256_digest(payload)


def profile_source_digest_v2(source: ProfileSourceV2) -> str:
    """Digest one exact, revisioned ProfileSource including provenance and layers."""
    payload = _dataclass_payload(source)
    del payload["digest"]
    return _sha256_digest(payload)


def desired_bundle_set_digest_v2(desired_set: DesiredBundleSetV2) -> str:
    """Digest the ordered exact Bundle refs and exact ProfileSource ref."""
    payload = _dataclass_payload(desired_set)
    del payload["digest"]
    return _sha256_digest(payload)


def compose_profile_sources_v2(
    *,
    desired_set: DesiredBundleSetV2,
    bundles: Sequence[BundleManifestV2],
    profile_source: ProfileSourceV2,
    scope: ScopeV2,
) -> ProfileSourceCompositionV2:
    """Compose Bundle -> Profile -> tenant -> project -> session for one exact scope.

    This function deliberately returns a scope-private document. Callers must publish it
    through a host keyed by the same scope authority; installing the result into the process-
    global host would erase the isolation established here.
    """
    _validate_scope(scope, context="target scope")
    _validate_desired_digest(desired_set)
    _validate_profile_source_digest(profile_source)
    _validate_profile_source_reference(desired_set.profile_source, profile_source)
    ordered_bundles = _resolve_bundles(desired_set, bundles)
    manifests = _ordered_manifests(ordered_bundles)
    manifest_ids = {manifest.plugin_id for manifest in manifests}

    rows: list[ProfileEntryV2] = []
    disabled: set[str] = set()
    provenance: list[ProfileLayerProvenanceV2] = []
    for bundle in ordered_bundles:
        for layer in bundle.layers:
            _validate_bundle_layer(layer, manifest_ids=manifest_ids)
            _apply_layer(rows, disabled, layer)
            provenance.append(
                _provenance(
                    layer,
                    source_kind="bundle",
                    source_id=bundle.bundle_id,
                    source_version=bundle.version,
                    source_digest=bundle.digest,
                )
            )

    _validate_profile_source_layers(profile_source.layers, manifest_ids=manifest_ids)
    for layer in profile_source.layers:
        if not _scope_contains(layer.scope, scope):
            continue
        _apply_layer(rows, disabled, layer)
        provenance.append(
            _provenance(
                layer,
                source_kind="profile-source",
                source_id=profile_source.source_id,
                source_version=str(profile_source.revision),
                source_digest=profile_source.digest,
            )
        )

    return ProfileSourceCompositionV2(
        document=ProfileDocumentV2(
            profile_id=profile_source.profile_id,
            entries=tuple(rows),
        ),
        manifests=manifests,
        target_scope=scope,
        desired_set_id=desired_set.desired_set_id,
        desired_set_revision=desired_set.revision,
        desired_set_digest=desired_set.digest,
        profile_source=desired_set.profile_source,
        layer_provenance=tuple(provenance),
        disabled_entry_ids=tuple(entry.entry_id for entry in rows if entry.entry_id in disabled),
    )


def _validate_desired_digest(desired_set: DesiredBundleSetV2) -> None:
    expected = desired_bundle_set_digest_v2(desired_set)
    if desired_set.digest != expected:
        _fail(
            "desired_bundle_set_digest_mismatch",
            f"desired bundle set digest mismatch: expected {expected}",
        )


def _validate_profile_source_digest(source: ProfileSourceV2) -> None:
    expected = profile_source_digest_v2(source)
    if source.digest != expected:
        _fail(
            "profile_source_digest_mismatch",
            f"profile source digest mismatch: expected {expected}",
        )


def _validate_profile_source_reference(
    reference: ProfileSourceReferenceV2,
    source: ProfileSourceV2,
) -> None:
    exact = (reference.source_id, reference.revision, reference.digest)
    actual = (source.source_id, source.revision, source.digest)
    if exact != actual:
        _fail(
            "profile_source_reference_mismatch",
            "desired bundle set does not reference the exact profile source",
        )


def _resolve_bundles(
    desired_set: DesiredBundleSetV2,
    bundles: Sequence[BundleManifestV2],
) -> tuple[BundleManifestV2, ...]:
    by_id: dict[str, BundleManifestV2] = {}
    for supplied_bundle in bundles:
        if supplied_bundle.bundle_id in by_id:
            _fail(
                "duplicate_bundle_id",
                f"duplicate supplied bundle {supplied_bundle.bundle_id}",
            )
        expected = bundle_manifest_digest_v2(supplied_bundle)
        if supplied_bundle.digest != expected:
            _fail(
                "bundle_digest_mismatch",
                f"bundle {supplied_bundle.bundle_id} digest mismatch: expected {expected}",
            )
        by_id[supplied_bundle.bundle_id] = supplied_bundle

    ordered: list[BundleManifestV2] = []
    seen: set[str] = set()
    for reference in desired_set.bundles:
        if reference.bundle_id in seen:
            _fail("duplicate_bundle_reference", f"duplicate bundle ref {reference.bundle_id}")
        seen.add(reference.bundle_id)
        resolved_bundle = by_id.get(reference.bundle_id)
        if resolved_bundle is None:
            _fail("missing_bundle", f"desired bundle {reference.bundle_id} was not supplied")
        if (reference.version, reference.digest) != (
            resolved_bundle.version,
            resolved_bundle.digest,
        ):
            _fail(
                "bundle_reference_mismatch",
                f"desired bundle {reference.bundle_id} does not match exact version and digest",
            )
        ordered.append(resolved_bundle)

    extras = sorted(by_id.keys() - seen)
    if extras:
        _fail("unexpected_bundle", f"supplied bundles are not desired: {', '.join(extras)}")
    return tuple(ordered)


def _ordered_manifests(
    bundles: Sequence[BundleManifestV2],
) -> tuple[PluginManifestV2, ...]:
    manifests: list[PluginManifestV2] = []
    seen: set[str] = set()
    for bundle in bundles:
        for manifest in bundle.manifests:
            if manifest.plugin_id in seen:
                _fail(
                    "duplicate_bundle_plugin",
                    f"plugin {manifest.plugin_id} is declared by more than one bundle manifest",
                )
            seen.add(manifest.plugin_id)
            manifests.append(manifest)
    return tuple(manifests)


def _validate_bundle_layer(layer: ProfileLayerV2, *, manifest_ids: set[str]) -> None:
    if layer.kind is not ProfileLayerKindV2.BUNDLE:
        _fail("invalid_bundle_layer", f"bundle layer {layer.layer_id} must use kind bundle")
    _validate_layer(layer, manifest_ids=manifest_ids)


def _validate_profile_source_layers(
    layers: Sequence[ProfileLayerV2],
    *,
    manifest_ids: set[str],
) -> None:
    previous_rank = -1
    for layer in layers:
        if layer.kind is ProfileLayerKindV2.BUNDLE:
            _fail(
                "invalid_profile_source_layer",
                f"profile source layer {layer.layer_id} cannot use kind bundle",
            )
        rank = _LAYER_KIND_RANK[layer.kind]
        if rank < previous_rank:
            _fail(
                "invalid_layer_order",
                "profile source layers must follow profile, tenant, project, session order",
            )
        previous_rank = rank
        _validate_layer(layer, manifest_ids=manifest_ids)


def _validate_layer(layer: ProfileLayerV2, *, manifest_ids: set[str]) -> None:
    _validate_scope(layer.scope, context=f"layer {layer.layer_id}")
    expected_scope = {
        ProfileLayerKindV2.BUNDLE: ScopeKindV2.ROOT,
        ProfileLayerKindV2.PROFILE: ScopeKindV2.ROOT,
        ProfileLayerKindV2.TENANT: ScopeKindV2.TENANT,
        ProfileLayerKindV2.PROJECT: ScopeKindV2.PROJECT,
        ProfileLayerKindV2.SESSION: ScopeKindV2.SESSION,
    }[layer.kind]
    if layer.scope.kind is not expected_scope:
        _fail(
            "invalid_layer_scope",
            f"layer {layer.layer_id} kind {layer.kind.value} requires {expected_scope.value} scope",
        )

    groups = (
        tuple(entry.entry_id for entry in layer.entries),
        tuple(entry.entry_id for entry in layer.replacements),
        layer.disabled_entry_ids,
    )
    if not any(groups):
        _fail("empty_profile_layer", f"layer {layer.layer_id} has no operation")
    all_ids = tuple(identifier for group in groups for identifier in group)
    if len(all_ids) != len(set(all_ids)):
        _fail(
            "duplicate_layer_operation",
            f"layer {layer.layer_id} repeats an entry across operations",
        )
    for entry in (*layer.entries, *layer.replacements):
        if entry.scope != layer.scope:
            _fail(
                "invalid_layer_entry_scope",
                f"layer {layer.layer_id} entry {entry.entry_id} must use the layer scope",
            )
        if entry.plugin_ref not in manifest_ids:
            _fail(
                "missing_layer_manifest",
                f"layer {layer.layer_id} entry {entry.entry_id} references {entry.plugin_ref}",
            )


def _apply_layer(
    rows: list[ProfileEntryV2],
    disabled: set[str],
    layer: ProfileLayerV2,
) -> None:
    positions = {entry.entry_id: index for index, entry in enumerate(rows)}
    for entry in layer.entries:
        if entry.entry_id in positions:
            _fail(
                "duplicate_layer_entry",
                f"layer {layer.layer_id} adds existing entry {entry.entry_id}",
            )
        positions[entry.entry_id] = len(rows)
        rows.append(entry)
        _record_enabled(disabled, entry)

    for replacement in layer.replacements:
        position = positions.get(replacement.entry_id)
        if position is None:
            _fail(
                "unknown_replacement_target",
                f"layer {layer.layer_id} replaces unknown entry {replacement.entry_id}",
            )
        rows[position] = replacement
        _record_enabled(disabled, replacement)

    for entry_id in layer.disabled_entry_ids:
        position = positions.get(entry_id)
        if position is None:
            _fail(
                "unknown_disable_target",
                f"layer {layer.layer_id} disables unknown entry {entry_id}",
            )
        rows[position] = replace(rows[position], enabled=False)
        disabled.add(entry_id)


def _record_enabled(disabled: set[str], entry: ProfileEntryV2) -> None:
    if entry.enabled:
        disabled.discard(entry.entry_id)
    else:
        disabled.add(entry.entry_id)


def _validate_scope(scope: ScopeV2, *, context: str) -> None:
    tenant = scope.tenant_id
    project = scope.project_id
    session = scope.session_id
    valid = (
        (scope.kind is ScopeKindV2.ROOT and tenant is None and project is None and session is None)
        or (
            scope.kind is ScopeKindV2.TENANT
            and bool(tenant)
            and project is None
            and session is None
        )
        or (
            scope.kind is ScopeKindV2.PROJECT and bool(tenant) and bool(project) and session is None
        )
        or (scope.kind is ScopeKindV2.SESSION and bool(tenant) and bool(project) and bool(session))
    )
    if not valid:
        _fail("invalid_scope", f"{context} has inconsistent {scope.kind.value} identifiers")


def _scope_contains(parent: ScopeV2, child: ScopeV2) -> bool:
    if _SCOPE_KIND_RANK[parent.kind] > _SCOPE_KIND_RANK[child.kind]:
        return False
    for field in ("tenant_id", "project_id", "session_id"):
        parent_value = getattr(parent, field)
        if parent_value is not None and parent_value != getattr(child, field):
            return False
    return True


def _provenance(
    layer: ProfileLayerV2,
    *,
    source_kind: str,
    source_id: str,
    source_version: str,
    source_digest: str,
) -> ProfileLayerProvenanceV2:
    return ProfileLayerProvenanceV2(
        layer_id=layer.layer_id,
        kind=layer.kind,
        scope=layer.scope,
        source_kind=source_kind,
        source_id=source_id,
        source_version=source_version,
        source_digest=source_digest,
    )


def _dataclass_payload(
    value: BundleManifestV2 | ProfileSourceV2 | DesiredBundleSetV2,
) -> dict[str, JsonValueV2]:
    payload = _json_value(asdict(value))
    if not isinstance(payload, dict):  # pragma: no cover - dataclass invariant
        _fail("invalid_digest_input", "digest input must be an object")
    return payload


def _json_value(value: object) -> JsonValueV2:
    if isinstance(value, Enum):
        return cast(JsonValueV2, value.value)
    if isinstance(value, Mapping):
        mapping = cast(Mapping[object, object], value)
        return {str(key): _json_value(item) for key, item in mapping.items()}
    if isinstance(value, (list, tuple)):
        sequence = cast(Sequence[object], value)
        return [_json_value(item) for item in sequence]
    return cast(JsonValueV2, value)


def _sha256_digest(payload: object) -> str:
    return f"sha256:{hashlib.sha256(canonical_json_v2(payload)).hexdigest()}"


def _fail(code: str, message: str) -> NoReturn:
    raise ProfileSourceCompositionV2Error(code, message)


__all__ = [
    "ProfileLayerProvenanceV2",
    "ProfileSourceCompositionV2",
    "ProfileSourceCompositionV2Error",
    "bundle_manifest_digest_v2",
    "compose_profile_sources_v2",
    "desired_bundle_set_digest_v2",
    "profile_source_digest_v2",
]
