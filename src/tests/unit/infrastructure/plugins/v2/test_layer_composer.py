"""Scope-private Bundle -> Profile -> overlay composition for protocol v2."""

from __future__ import annotations

from dataclasses import replace

import pytest

from src.domain.model.plugins.generated_v2 import (
    ProfileEntryV2,
    ProfileLayerKindV2,
    ScopeKindV2,
)
from src.infrastructure.plugins.v2.layer_composer import (
    ProfileSourceCompositionV2Error,
    compose_profile_sources_v2,
    desired_bundle_set_digest_v2,
)
from src.tests.unit.infrastructure.plugins.v2.layer_composer_test_support import (
    _ZERO_DIGEST,
    _bundle,
    _desired,
    _entry,
    _layer,
    _scope,
    _source,
)


@pytest.mark.unit
def test_composition_applies_fixed_layer_order_and_preserves_replacement_slots() -> None:
    tenant_a = _scope(ScopeKindV2.TENANT)
    tenant_b = _scope(ScopeKindV2.TENANT, tenant_id="tenant-b")
    project_a = _scope(ScopeKindV2.PROJECT)
    session_a = _scope(ScopeKindV2.SESSION)
    first = _bundle(
        "bundle-a",
        plugin_id="plugin-a",
        layers=(
            _layer(
                "bundle-a-base",
                ProfileLayerKindV2.BUNDLE,
                entries=(_entry("entry-a"), _entry("entry-b")),
            ),
        ),
    )
    second = _bundle(
        "bundle-b",
        plugin_id="plugin-b",
        layers=(
            _layer(
                "bundle-b-base",
                ProfileLayerKindV2.BUNDLE,
                entries=(_entry("entry-c", plugin_ref="plugin-b"),),
                replacements=(
                    _entry("entry-a", plugin_ref="plugin-b", label="bundle-b-replacement"),
                ),
            ),
        ),
    )
    source = _source(
        (
            _layer(
                "profile-base",
                ProfileLayerKindV2.PROFILE,
                entries=(_entry("entry-d"),),
            ),
            _layer(
                "tenant-a",
                ProfileLayerKindV2.TENANT,
                scope=tenant_a,
                replacements=(_entry("entry-b", scope=tenant_a, label="tenant-a"),),
            ),
            _layer(
                "tenant-b",
                ProfileLayerKindV2.TENANT,
                scope=tenant_b,
                entries=(_entry("tenant-b-only", scope=tenant_b),),
            ),
            _layer(
                "project-a",
                ProfileLayerKindV2.PROJECT,
                scope=project_a,
                entries=(_entry("entry-e", scope=project_a),),
            ),
            _layer(
                "session-a",
                ProfileLayerKindV2.SESSION,
                scope=session_a,
                disabled_entry_ids=("entry-d",),
            ),
        )
    )

    composition = compose_profile_sources_v2(
        desired_set=_desired((first, second), source),
        bundles=(first, second),
        profile_source=source,
        scope=session_a,
    )

    assert [entry.entry_id for entry in composition.document.entries] == [
        "entry-a",
        "entry-b",
        "entry-c",
        "entry-d",
        "entry-e",
    ]
    entries = {entry.entry_id: entry for entry in composition.document.entries}
    assert entries["entry-a"].config == {"label": "bundle-b-replacement"}
    assert entries["entry-b"].scope == tenant_a
    assert entries["entry-d"].enabled is False
    assert composition.disabled_entry_ids == ("entry-d",)
    assert [item.layer_id for item in composition.layer_provenance] == [
        "bundle-a-base",
        "bundle-b-base",
        "profile-base",
        "tenant-a",
        "project-a",
        "session-a",
    ]
    assert [manifest.plugin_id for manifest in composition.manifests] == [
        "plugin-a",
        "plugin-b",
    ]


@pytest.mark.unit
def test_scope_private_composition_does_not_mix_tenant_overlays() -> None:
    tenant_a = _scope(ScopeKindV2.TENANT)
    tenant_b = _scope(ScopeKindV2.TENANT, tenant_id="tenant-b")
    bundle = _bundle(
        "bundle-a",
        plugin_id="plugin-a",
        layers=(
            _layer(
                "bundle-base",
                ProfileLayerKindV2.BUNDLE,
                entries=(_entry("entry-a"),),
            ),
        ),
    )
    source = _source(
        (
            _layer(
                "profile-base",
                ProfileLayerKindV2.PROFILE,
                entries=(_entry("profile-entry"),),
            ),
            _layer(
                "tenant-a",
                ProfileLayerKindV2.TENANT,
                scope=tenant_a,
                replacements=(_entry("entry-a", scope=tenant_a, label="tenant-a"),),
            ),
            _layer(
                "tenant-b",
                ProfileLayerKindV2.TENANT,
                scope=tenant_b,
                replacements=(_entry("entry-a", scope=tenant_b, label="tenant-b"),),
            ),
        )
    )
    desired = _desired((bundle,), source)

    tenant_a_result = compose_profile_sources_v2(
        desired_set=desired,
        bundles=(bundle,),
        profile_source=source,
        scope=tenant_a,
    )
    tenant_b_result = compose_profile_sources_v2(
        desired_set=desired,
        bundles=(bundle,),
        profile_source=source,
        scope=tenant_b,
    )

    assert tenant_a_result.document.entries[0].config == {"label": "tenant-a"}
    assert tenant_b_result.document.entries[0].config == {"label": "tenant-b"}


@pytest.mark.unit
def test_plain_duplicate_is_rejected_even_when_rows_are_identical() -> None:
    bundle = _bundle(
        "bundle-a",
        plugin_id="plugin-a",
        layers=(
            _layer(
                "bundle-base",
                ProfileLayerKindV2.BUNDLE,
                entries=(_entry("entry-a"),),
            ),
        ),
    )
    source = _source(
        (
            _layer(
                "profile-base",
                ProfileLayerKindV2.PROFILE,
                entries=(_entry("entry-a"),),
            ),
        )
    )

    with pytest.raises(ProfileSourceCompositionV2Error) as error:
        compose_profile_sources_v2(
            desired_set=_desired((bundle,), source),
            bundles=(bundle,),
            profile_source=source,
            scope=_scope(),
        )

    assert error.value.code == "duplicate_layer_entry"


@pytest.mark.unit
@pytest.mark.parametrize(
    ("replacements", "disabled_entry_ids", "code"),
    [
        ((_entry("missing"),), (), "unknown_replacement_target"),
        ((), ("missing",), "unknown_disable_target"),
    ],
)
def test_explicit_override_must_target_an_existing_entry(
    replacements: tuple[ProfileEntryV2, ...],
    disabled_entry_ids: tuple[str, ...],
    code: str,
) -> None:
    bundle = _bundle(
        "bundle-a",
        plugin_id="plugin-a",
        layers=(
            _layer(
                "bundle-base",
                ProfileLayerKindV2.BUNDLE,
                entries=(_entry("entry-a"),),
            ),
        ),
    )
    source = _source(
        (
            _layer(
                "profile-base",
                ProfileLayerKindV2.PROFILE,
                replacements=replacements,
                disabled_entry_ids=disabled_entry_ids,
            ),
        )
    )

    with pytest.raises(ProfileSourceCompositionV2Error) as error:
        compose_profile_sources_v2(
            desired_set=_desired((bundle,), source),
            bundles=(bundle,),
            profile_source=source,
            scope=_scope(),
        )

    assert error.value.code == code


@pytest.mark.unit
def test_same_layer_cannot_repeat_an_entry_across_operation_groups() -> None:
    bundle = _bundle(
        "bundle-a",
        plugin_id="plugin-a",
        layers=(
            _layer(
                "bundle-base",
                ProfileLayerKindV2.BUNDLE,
                entries=(_entry("entry-a"),),
                replacements=(_entry("entry-a", label="replacement"),),
            ),
        ),
    )
    source = _source(
        (
            _layer(
                "profile-base",
                ProfileLayerKindV2.PROFILE,
                entries=(_entry("profile-entry"),),
            ),
        )
    )

    with pytest.raises(ProfileSourceCompositionV2Error) as error:
        compose_profile_sources_v2(
            desired_set=_desired((bundle,), source),
            bundles=(bundle,),
            profile_source=source,
            scope=_scope(),
        )

    assert error.value.code == "duplicate_layer_operation"


@pytest.mark.unit
def test_only_explicit_replacement_can_restore_a_disabled_entry() -> None:
    project = _scope(ScopeKindV2.PROJECT)
    tenant = _scope(ScopeKindV2.TENANT)
    bundle = _bundle(
        "bundle-a",
        plugin_id="plugin-a",
        layers=(
            _layer(
                "bundle-base",
                ProfileLayerKindV2.BUNDLE,
                entries=(_entry("entry-a"),),
            ),
        ),
    )
    source = _source(
        (
            _layer(
                "profile-base",
                ProfileLayerKindV2.PROFILE,
                entries=(_entry("profile-entry"),),
            ),
            _layer(
                "tenant-disable",
                ProfileLayerKindV2.TENANT,
                scope=tenant,
                disabled_entry_ids=("entry-a",),
            ),
            _layer(
                "project-restore",
                ProfileLayerKindV2.PROJECT,
                scope=project,
                replacements=(_entry("entry-a", scope=project, label="restored"),),
            ),
        )
    )

    composition = compose_profile_sources_v2(
        desired_set=_desired((bundle,), source),
        bundles=(bundle,),
        profile_source=source,
        scope=project,
    )

    assert composition.document.entries[0].enabled is True
    assert composition.document.entries[0].config == {"label": "restored"}
    assert composition.disabled_entry_ids == ()


@pytest.mark.unit
@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        ("bundle", "bundle_digest_mismatch"),
        ("source", "profile_source_digest_mismatch"),
        ("desired", "desired_bundle_set_digest_mismatch"),
    ],
)
def test_content_digests_are_verified_before_composition(mutate: str, code: str) -> None:
    bundle = _bundle(
        "bundle-a",
        plugin_id="plugin-a",
        layers=(
            _layer(
                "bundle-base",
                ProfileLayerKindV2.BUNDLE,
                entries=(_entry("entry-a"),),
            ),
        ),
    )
    source = _source(
        (
            _layer(
                "profile-base",
                ProfileLayerKindV2.PROFILE,
                entries=(_entry("profile-entry"),),
            ),
        )
    )
    desired = _desired((bundle,), source)
    if mutate == "bundle":
        bundle = replace(bundle, digest=_ZERO_DIGEST)
    elif mutate == "source":
        source = replace(source, digest=_ZERO_DIGEST)
    else:
        desired = replace(desired, digest=_ZERO_DIGEST)

    with pytest.raises(ProfileSourceCompositionV2Error) as error:
        compose_profile_sources_v2(
            desired_set=desired,
            bundles=(bundle,),
            profile_source=source,
            scope=_scope(),
        )

    assert error.value.code == code


@pytest.mark.unit
def test_profile_source_reference_must_match_exact_revision_and_digest() -> None:
    bundle = _bundle(
        "bundle-a",
        plugin_id="plugin-a",
        layers=(
            _layer(
                "bundle-base",
                ProfileLayerKindV2.BUNDLE,
                entries=(_entry("entry-a"),),
            ),
        ),
    )
    source = _source(
        (
            _layer(
                "profile-base",
                ProfileLayerKindV2.PROFILE,
                entries=(_entry("profile-entry"),),
            ),
        )
    )
    desired = _desired((bundle,), source)
    desired = replace(
        desired,
        profile_source=replace(desired.profile_source, revision=source.revision + 1),
    )
    desired = replace(desired, digest=desired_bundle_set_digest_v2(desired))

    with pytest.raises(ProfileSourceCompositionV2Error) as error:
        compose_profile_sources_v2(
            desired_set=desired,
            bundles=(bundle,),
            profile_source=source,
            scope=_scope(),
        )

    assert error.value.code == "profile_source_reference_mismatch"


@pytest.mark.unit
@pytest.mark.parametrize(
    ("case", "code"),
    [
        ("version", "bundle_reference_mismatch"),
        ("digest", "bundle_reference_mismatch"),
        ("missing", "missing_bundle"),
        ("unexpected", "unexpected_bundle"),
        ("duplicate-supplied", "duplicate_bundle_id"),
        ("duplicate-reference", "duplicate_bundle_reference"),
    ],
)
def test_desired_bundle_inventory_is_exact_and_closed(case: str, code: str) -> None:
    first = _bundle(
        "bundle-a",
        plugin_id="plugin-a",
        layers=(
            _layer(
                "bundle-a-base",
                ProfileLayerKindV2.BUNDLE,
                entries=(_entry("entry-a"),),
            ),
        ),
    )
    second = _bundle(
        "bundle-b",
        plugin_id="plugin-b",
        layers=(
            _layer(
                "bundle-b-base",
                ProfileLayerKindV2.BUNDLE,
                entries=(_entry("entry-b", plugin_ref="plugin-b"),),
            ),
        ),
    )
    source = _source(
        (
            _layer(
                "profile-base",
                ProfileLayerKindV2.PROFILE,
                entries=(_entry("profile-entry"),),
            ),
        )
    )
    desired = _desired((first,), source)
    supplied = (first,)
    if case in {"version", "digest"}:
        reference = desired.bundles[0]
        reference = replace(
            reference,
            version="2.0.0" if case == "version" else reference.version,
            digest=_ZERO_DIGEST if case == "digest" else reference.digest,
        )
        desired = replace(desired, bundles=(reference,))
        desired = replace(desired, digest=desired_bundle_set_digest_v2(desired))
    elif case == "missing":
        supplied = ()
    elif case == "unexpected":
        supplied = (first, second)
    elif case == "duplicate-supplied":
        supplied = (first, first)
    else:
        desired = replace(desired, bundles=(desired.bundles[0], desired.bundles[0]))
        desired = replace(desired, digest=desired_bundle_set_digest_v2(desired))

    with pytest.raises(ProfileSourceCompositionV2Error) as error:
        compose_profile_sources_v2(
            desired_set=desired,
            bundles=supplied,
            profile_source=source,
            scope=_scope(),
        )

    assert error.value.code == code


@pytest.mark.unit
@pytest.mark.parametrize(
    ("case", "code"),
    [
        ("duplicate-plugin", "duplicate_bundle_plugin"),
        ("missing-layer-manifest", "missing_layer_manifest"),
    ],
)
def test_bundle_manifests_are_unique_and_cover_layer_entries(case: str, code: str) -> None:
    first = _bundle(
        "bundle-a",
        plugin_id="plugin-a",
        layers=(
            _layer(
                "bundle-a-base",
                ProfileLayerKindV2.BUNDLE,
                entries=(
                    _entry(
                        "entry-a",
                        plugin_ref="plugin-missing"
                        if case == "missing-layer-manifest"
                        else "plugin-a",
                    ),
                ),
            ),
        ),
    )
    bundles = (first,)
    if case == "duplicate-plugin":
        bundles = (
            first,
            _bundle(
                "bundle-b",
                plugin_id="plugin-a",
                layers=(
                    _layer(
                        "bundle-b-base",
                        ProfileLayerKindV2.BUNDLE,
                        entries=(_entry("entry-b"),),
                    ),
                ),
            ),
        )
    source = _source(
        (
            _layer(
                "profile-base",
                ProfileLayerKindV2.PROFILE,
                entries=(_entry("profile-entry"),),
            ),
        )
    )

    with pytest.raises(ProfileSourceCompositionV2Error) as error:
        compose_profile_sources_v2(
            desired_set=_desired(bundles, source),
            bundles=bundles,
            profile_source=source,
            scope=_scope(),
        )

    assert error.value.code == code


@pytest.mark.unit
@pytest.mark.parametrize(
    ("case", "code"),
    [
        ("target", "invalid_scope"),
        ("layer", "invalid_layer_scope"),
        ("entry", "invalid_layer_entry_scope"),
        ("empty", "empty_profile_layer"),
    ],
)
def test_scope_and_layer_shapes_fail_closed(case: str, code: str) -> None:
    tenant = _scope(ScopeKindV2.TENANT)
    source_layer = _layer(
        "profile-base",
        ProfileLayerKindV2.PROFILE,
        entries=(_entry("profile-entry"),),
    )
    target_scope = _scope()
    if case == "target":
        target_scope = replace(target_scope, tenant_id="tenant-a")
    elif case == "layer":
        source_layer = _layer(
            "tenant-layer",
            ProfileLayerKindV2.TENANT,
            entries=(_entry("tenant-entry"),),
        )
    elif case == "entry":
        source_layer = _layer(
            "tenant-layer",
            ProfileLayerKindV2.TENANT,
            scope=tenant,
            entries=(_entry("tenant-entry"),),
        )
        target_scope = tenant
    else:
        source_layer = _layer("profile-base", ProfileLayerKindV2.PROFILE)
    bundle = _bundle(
        "bundle-a",
        plugin_id="plugin-a",
        layers=(
            _layer(
                "bundle-base",
                ProfileLayerKindV2.BUNDLE,
                entries=(_entry("entry-a"),),
            ),
        ),
    )
    source = _source((source_layer,))

    with pytest.raises(ProfileSourceCompositionV2Error) as error:
        compose_profile_sources_v2(
            desired_set=_desired((bundle,), source),
            bundles=(bundle,),
            profile_source=source,
            scope=target_scope,
        )

    assert error.value.code == code


@pytest.mark.unit
@pytest.mark.parametrize(
    ("bundle_kind", "source_kinds", "code"),
    [
        (ProfileLayerKindV2.PROFILE, (ProfileLayerKindV2.PROFILE,), "invalid_bundle_layer"),
        (ProfileLayerKindV2.BUNDLE, (ProfileLayerKindV2.BUNDLE,), "invalid_profile_source_layer"),
        (
            ProfileLayerKindV2.BUNDLE,
            (ProfileLayerKindV2.TENANT, ProfileLayerKindV2.PROFILE),
            "invalid_layer_order",
        ),
    ],
)
def test_layer_source_and_order_are_fixed(
    bundle_kind: ProfileLayerKindV2,
    source_kinds: tuple[ProfileLayerKindV2, ...],
    code: str,
) -> None:
    bundle = _bundle(
        "bundle-a",
        plugin_id="plugin-a",
        layers=(_layer("bundle-base", bundle_kind, entries=(_entry("entry-a"),)),),
    )
    source = _source(
        tuple(
            _layer(
                f"source-{index}",
                kind,
                scope=(
                    _scope(ScopeKindV2.TENANT) if kind is ProfileLayerKindV2.TENANT else _scope()
                ),
                entries=(
                    _entry(
                        f"source-entry-{index}",
                        scope=(
                            _scope(ScopeKindV2.TENANT)
                            if kind is ProfileLayerKindV2.TENANT
                            else _scope()
                        ),
                    ),
                ),
            )
            for index, kind in enumerate(source_kinds)
        )
    )

    with pytest.raises(ProfileSourceCompositionV2Error) as error:
        compose_profile_sources_v2(
            desired_set=_desired((bundle,), source),
            bundles=(bundle,),
            profile_source=source,
            scope=_scope(ScopeKindV2.TENANT),
        )

    assert error.value.code == code
