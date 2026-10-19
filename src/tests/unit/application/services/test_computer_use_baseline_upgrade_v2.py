"""A legacy initialized scope admits the new first-party factory without losing overlays."""

from dataclasses import replace
from unittest.mock import AsyncMock

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.root_builtin_bundle_upgrade_service_v2 import (
    upgrade_root_builtin_bundle_v2,
)
from src.domain.model.plugins.generated_v2 import (
    BundleReferenceV2,
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
from src.infrastructure.plugins.v2.composer import compose_profile_v2
from src.infrastructure.plugins.v2.layer_composer import (
    bundle_manifest_digest_v2,
    compose_profile_sources_v2,
    desired_bundle_set_digest_v2,
    profile_source_digest_v2,
)
from src.infrastructure.plugins.v2.production_bundle import production_bundle_sources_v2
from src.tests.unit.infrastructure.plugins.v2.test_bundle_archive_v2 import (
    _archive,
    _bundle,
    _public_key_pem,
)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("kind", [ScopeKindV2.TENANT, ScopeKindV2.PROJECT])
async def test_initialized_scope_adds_computer_use_and_preserves_signed_addon_and_overlays(
    test_db: AsyncSession, kind: ScopeKindV2
) -> None:
    sources = production_bundle_sources_v2()
    scope = ScopeV2(
        kind=kind,
        tenant_id="tenant-qa",
        project_id="project-qa" if kind is ScopeKindV2.PROJECT else None,
    )
    native = next(m for m in sources.bundle.manifests if m.plugin_id == "memstack-computer-use")
    native_digests = {m.artifact.digest for m in native.modules}
    old_bundle = replace(
        sources.bundle,
        manifests=tuple(m for m in sources.bundle.manifests if m.plugin_id != native.plugin_id),
        artifacts=tuple(a for a in sources.bundle.artifacts if a.digest not in native_digests),
    )
    old_bundle = replace(old_bundle, digest=bundle_manifest_digest_v2(old_bundle))
    old_ref = replace(sources.desired_set.bundles[0], digest=old_bundle.digest)
    signer = Ed25519PrivateKey.generate()
    addon = _bundle(signer=signer, permissions=("service.clock.read",))
    addon_ref = BundleReferenceV2(
        bundle_id=addon.bundle_id,
        version=addon.version,
        digest=addon.digest,
        source="marketplace://conformance-v2/1.0.0",
    )
    addon_archive = parse_bundle_archive_v2(
        _archive(addon),
        source=addon_ref.source,
        trusted_public_keys=(_public_key_pem(signer),),
        approved_permissions=frozenset({"service.clock.read"}),
        require_signature=True,
        require_provenance=True,
    )
    baseline = sources.profile_source.layers[0]
    old_baseline = replace(
        baseline, entries=tuple(e for e in baseline.entries if e.plugin_ref != native.plugin_id)
    )
    overlay = ProfileLayerV2(
        layer_id="operator-overrides",
        kind=ProfileLayerKindV2(kind.value),
        scope=scope,
        entries=(),
        replacements=(replace(baseline.entries[1], scope=scope),),
        disabled_entry_ids=(addon.layers[0].entries[0].entry_id,),
    )
    source = replace(sources.profile_source, layers=(old_baseline, overlay))
    source = replace(source, digest=profile_source_digest_v2(source))
    reference = ProfileSourceReferenceV2(
        source_id=source.source_id, revision=source.revision, digest=source.digest
    )
    desired = replace(sources.desired_set, bundles=(old_ref, addon_ref), profile_source=reference)
    desired = replace(desired, digest=desired_bundle_set_digest_v2(desired))
    # The previous scope is itself valid before the first-party addition.
    previous = compose_profile_sources_v2(
        desired_set=desired, bundles=(old_bundle, addon), profile_source=source, scope=scope
    )
    compose_profile_v2(
        previous.document,
        {m.plugin_id: m for m in previous.manifests},
        generation=desired.revision,
    )
    source_repo = PlatformPluginProfileSourceRepositoryV2(test_db)
    repo = PlatformPluginDesiredBundleSetRepositoryV2(test_db)
    await source_repo.record_source(scope=scope, source=source, expected_revision=None)
    await repo.record_desired_set(
        scope=scope, desired_set=desired, expected_revision=None, actor_id="operator"
    )
    await test_db.commit()
    current_archive = parse_bundle_archive_v2(
        sources.bundle_archive,
        source=old_ref.source,
        approved_permissions=frozenset(
            permission
            for manifest in sources.bundle.manifests
            for permission in manifest.permissions
        ),
        require_signature=False,
        require_provenance=True,
    )
    loader = AsyncMock(side_effect=[current_archive, addon_archive])
    updated = await upgrade_root_builtin_bundle_v2(
        test_db,
        sources=sources,
        load_verified_bundle=loader,
        expected_revision=desired.revision,
        expected_bundle=old_ref,
        actor_id="operator",
        scope=scope,
        upgrade_profile_baseline=True,
        expected_profile_source=reference,
    )
    assert updated.desired_set.bundles == (sources.desired_set.bundles[0], addon_ref)
    updated_ref = updated.desired_set.profile_source
    migrated = await source_repo.read_exact(
        scope=scope,
        source_id=updated_ref.source_id,
        revision=updated_ref.revision,
        digest=updated_ref.digest,
    )
    assert migrated.layers[1:] == source.layers[1:]
    composition = compose_profile_sources_v2(
        desired_set=updated.desired_set,
        bundles=(current_archive.manifest, addon_archive.manifest),
        profile_source=migrated,
        scope=scope,
    )
    snapshot = compose_profile_v2(
        composition.document,
        {m.plugin_id: m for m in composition.manifests},
        generation=updated.desired_set.revision,
    )
    factory = next(e for e in snapshot.entries if e.plugin_ref == "memstack-computer-use")
    assert factory.module_ref == "builtin://memstack/computer-use/native"
    assert factory.enabled and factory.config["default_enabled"] is False
    assert not next(e for e in snapshot.entries if e.entry_id == "root-provider").enabled
