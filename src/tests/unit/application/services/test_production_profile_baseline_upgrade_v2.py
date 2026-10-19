"""Explicit baseline migration preserves overlays and rejects ambiguous retired owners."""

import json
from dataclasses import replace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.production_profile_baseline_upgrade_v2 import (
    ProductionProfileBaselineUpgradeV2Error,
    upgrade_production_profile_baseline_v2,
)
from src.application.services.root_builtin_bundle_upgrade_service_v2 import (
    upgrade_root_builtin_bundle_v2,
)
from src.domain.model.plugins.generated_v2 import (
    ProfileLayerKindV2,
    ProfileLayerV2,
    ProfileSourceReferenceV2,
    ScopeKindV2,
    ScopeV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_desired_bundle_repository_v2 import (
    PlatformPluginDesiredBundleSetRepositoryV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_profile_source_repository_v2 import (
    PlatformPluginProfileSourceRepositoryV2,
)
from src.infrastructure.plugins.v2.bundle_archive import parse_bundle_archive_v2
from src.infrastructure.plugins.v2.layer_composer import (
    desired_bundle_set_digest_v2,
    profile_source_digest_v2,
)
from src.infrastructure.plugins.v2.production_bundle import production_bundle_sources_v2

pytestmark = pytest.mark.unit


def _old_source(sources, scope):
    target = sources.profile_source.layers[0]
    baseline = replace(
        target,
        entries=(
            *target.entries[:-1],
            replace(target.entries[-1], entry_id="retired-renderer-group"),
        ),
        replacements=(sources.bundle.layers[0].entries[0],),
    )
    overlay = ProfileLayerV2(
        layer_id="operator-overrides",
        kind=ProfileLayerKindV2.PROFILE
        if scope.kind is ScopeKindV2.ROOT
        else ProfileLayerKindV2(scope.kind.value),
        scope=scope,
        entries=(),
        replacements=(replace(target.entries[1], scope=scope),),
        disabled_entry_ids=(),
    )
    source = replace(
        sources.profile_source,
        source_id="initialized-test-source",
        provenance=json.dumps({"original_provenance": sources.profile_source.provenance}),
        layers=(baseline, overlay),
    )
    return replace(source, digest=profile_source_digest_v2(source))


@pytest.mark.parametrize("kind", [ScopeKindV2.ROOT, ScopeKindV2.TENANT, ScopeKindV2.PROJECT])
async def test_explicit_upgrade_commits_new_source_with_desired_cas_and_preserves_overlays(
    test_db: AsyncSession, kind: ScopeKindV2
) -> None:
    sources = production_bundle_sources_v2()
    scope = ScopeV2(
        kind=kind,
        tenant_id="tenant-1" if kind is not ScopeKindV2.ROOT else None,
        project_id="project-1" if kind is ScopeKindV2.PROJECT else None,
    )
    source = _old_source(sources, scope)
    source_repo = PlatformPluginProfileSourceRepositoryV2(test_db)
    await source_repo.record_source(scope=scope, source=source, expected_revision=None)
    reference = ProfileSourceReferenceV2(
        source_id=source.source_id, revision=source.revision, digest=source.digest
    )
    desired = replace(sources.desired_set, profile_source=reference)
    desired = replace(desired, digest=desired_bundle_set_digest_v2(desired))
    repository = PlatformPluginDesiredBundleSetRepositoryV2(test_db)
    await repository.record_desired_set(
        scope=scope, desired_set=desired, expected_revision=None, actor_id="operator"
    )
    await test_db.commit()
    archive = parse_bundle_archive_v2(
        sources.bundle_archive,
        source=sources.desired_set.bundles[0].source,
        approved_permissions=frozenset(
            permission
            for manifest in sources.bundle.manifests
            for permission in manifest.permissions
        ),
        require_signature=False,
        require_provenance=True,
    )
    updated = await upgrade_root_builtin_bundle_v2(
        test_db,
        sources=sources,
        load_verified_bundle=AsyncMock(return_value=archive),
        expected_revision=desired.revision,
        expected_bundle=desired.bundles[0],
        actor_id="operator",
        scope=scope,
        upgrade_profile_baseline=True,
        expected_profile_source=reference,
    )
    await test_db.commit()
    assert updated.desired_set.revision == 2
    updated_ref = updated.desired_set.profile_source
    assert updated_ref.revision == 2
    migrated = await source_repo.read_exact(
        scope=scope,
        source_id=updated_ref.source_id,
        revision=updated_ref.revision,
        digest=updated_ref.digest,
    )
    assert migrated.layers[0].entries == sources.profile_source.layers[0].entries
    assert migrated.layers[0].replacements == source.layers[0].replacements
    assert migrated.layers[1:] == source.layers[1:]
    assert migrated.provenance == source.provenance
    # An explicit repeat is idempotent and does not create an extra immutable revision.
    repeated = await upgrade_root_builtin_bundle_v2(
        test_db,
        sources=sources,
        load_verified_bundle=AsyncMock(return_value=archive),
        expected_revision=2,
        expected_bundle=desired.bundles[0],
        actor_id="operator",
        scope=scope,
        upgrade_profile_baseline=True,
        expected_profile_source=updated_ref,
    )
    assert repeated.record_id == updated.record_id
    assert len(await repository.list_history(scope)) == 2


@pytest.mark.parametrize("reference_kind", ["disabled", "replacement", "parent", "inject"])
def test_retired_owner_references_require_explicit_overlay_migration(reference_kind) -> None:
    sources = production_bundle_sources_v2()
    source = _old_source(sources, ScopeV2(kind=ScopeKindV2.ROOT))
    overlay = source.layers[1]
    entry = overlay.replacements[0]
    if reference_kind == "disabled":
        overlay = replace(overlay, disabled_entry_ids=("retired-renderer-group",))
    else:
        values = {
            "replacement": {"entry_id": "retired-renderer-group"},
            "parent": {"parent_entry_id": "retired-renderer-group"},
            "inject": {"inject": {"required": "retired-renderer-group"}},
        }
        overlay = replace(overlay, replacements=(replace(entry, **values[reference_kind]),))
    source = replace(source, layers=(source.layers[0], overlay))
    with pytest.raises(ProductionProfileBaselineUpgradeV2Error) as caught:
        upgrade_production_profile_baseline_v2(source, sources.profile_source)
    assert caught.value.code == "profile_baseline_retired_entry_referenced"
    assert "retired-renderer-group" in str(caught.value)


@pytest.mark.parametrize("failure", ["lineage", "missing", "duplicate", "scope"])
def test_unknown_baseline_format_is_never_silently_replaced(failure) -> None:
    sources = production_bundle_sources_v2()
    source = _old_source(sources, ScopeV2(kind=ScopeKindV2.ROOT))
    if failure == "lineage":
        source = replace(source, provenance="third-party-profile")
    elif failure == "missing":
        source = replace(source, layers=source.layers[1:])
    elif failure == "duplicate":
        source = replace(source, layers=(source.layers[0], *source.layers))
    else:
        source = replace(
            source,
            layers=(
                replace(source.layers[0], scope=ScopeV2(kind=ScopeKindV2.TENANT, tenant_id="t")),
            ),
        )
    with pytest.raises(ProductionProfileBaselineUpgradeV2Error):
        upgrade_production_profile_baseline_v2(source, sources.profile_source)


async def test_desired_cas_failure_rolls_back_candidate_source_even_if_caller_commits(
    test_db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    sources = production_bundle_sources_v2()
    scope = ScopeV2(kind=ScopeKindV2.ROOT)
    source = _old_source(sources, scope)
    source_repo = PlatformPluginProfileSourceRepositoryV2(test_db)
    await source_repo.record_source(scope=scope, source=source, expected_revision=None)
    ref = ProfileSourceReferenceV2(source_id=source.source_id, revision=1, digest=source.digest)
    desired = replace(sources.desired_set, profile_source=ref)
    desired = replace(desired, digest=desired_bundle_set_digest_v2(desired))
    repo = PlatformPluginDesiredBundleSetRepositoryV2(test_db)
    await repo.record_desired_set(
        scope=scope, desired_set=desired, expected_revision=None, actor_id="ops"
    )
    await test_db.commit()
    archive = parse_bundle_archive_v2(
        sources.bundle_archive,
        source=desired.bundles[0].source,
        approved_permissions=frozenset(
            permission
            for manifest in sources.bundle.manifests
            for permission in manifest.permissions
        ),
        require_signature=False,
        require_provenance=True,
    )
    monkeypatch.setattr(
        PlatformPluginDesiredBundleSetRepositoryV2,
        "record_desired_set",
        AsyncMock(side_effect=ValueError("concurrent desired CAS")),
    )
    with pytest.raises(ValueError, match="concurrent desired CAS"):
        await upgrade_root_builtin_bundle_v2(
            test_db,
            sources=sources,
            load_verified_bundle=AsyncMock(return_value=archive),
            expected_revision=1,
            expected_bundle=desired.bundles[0],
            actor_id="ops",
            upgrade_profile_baseline=True,
            expected_profile_source=ref,
        )
    await test_db.commit()
    candidate = upgrade_production_profile_baseline_v2(source, sources.profile_source)
    assert (
        await source_repo.read_exact(
            scope=scope, source_id=source.source_id, revision=2, digest=candidate.digest
        )
        is None
    )
    assert (await repo.current_desired_set(scope)).desired_set == desired
