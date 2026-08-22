"""Production baseline closure for protocol-v2 Bundle/Profile sources."""

from __future__ import annotations

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.plugins.v2.bundle_archive import parse_bundle_archive_v2
from src.infrastructure.plugins.v2.composer import compose_profile_v2, load_profile_document_v2
from src.infrastructure.plugins.v2.layer_composer import compose_profile_sources_v2
from src.infrastructure.plugins.v2.production_bundle import (
    PRODUCTION_BASE_PROFILE_PATH_V2,
    production_bundle_sources_v2,
)
from src.infrastructure.plugins.v2.target_profiles import include_production_target_hosts_v2


def test_production_bundle_is_closed_deterministic_and_composable() -> None:
    sources = production_bundle_sources_v2()
    repeated = production_bundle_sources_v2()
    approved_permissions = frozenset(
        permission for manifest in sources.bundle.manifests for permission in manifest.permissions
    )

    verified = parse_bundle_archive_v2(
        sources.bundle_archive,
        source=sources.desired_set.bundles[0].source,
        approved_permissions=approved_permissions,
        require_signature=False,
        require_provenance=True,
    )
    composition = compose_profile_sources_v2(
        desired_set=sources.desired_set,
        bundles=(verified.manifest,),
        profile_source=sources.profile_source,
        scope=ScopeV2(kind=ScopeKindV2.ROOT),
    )
    snapshot = compose_profile_v2(
        composition.document,
        {manifest.plugin_id: manifest for manifest in composition.manifests},
        generation=1,
    )
    expected = compose_profile_v2(
        include_production_target_hosts_v2(
            load_profile_document_v2(PRODUCTION_BASE_PROFILE_PATH_V2)
        ),
        {manifest.plugin_id: manifest for manifest in sources.bundle.manifests},
        generation=1,
    )

    assert sources == repeated
    assert verified.manifest == sources.bundle
    assert snapshot == expected
    assert len(snapshot.entries) > 1
    assert {manifest.plugin_id for manifest in snapshot.manifests} == {
        "memstack-native-target-hosts",
        "memstack-renderer-contributions",
        "memstack-renderer-target-hosts",
        "memstack-runtime-kernel",
    }
