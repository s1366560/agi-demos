"""Explicit builtin maintenance retains exact source and immutable CAS history."""

from dataclasses import replace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.root_builtin_bundle_upgrade_service_v2 import (
    upgrade_root_builtin_bundle_v2,
)
from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.adapters.secondary.persistence.platform_plugin_desired_bundle_repository_v2 import (
    PlatformPluginDesiredBundleSetRepositoryV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_profile_source_repository_v2 import (
    PlatformPluginProfileSourceRepositoryV2,
)
from src.infrastructure.plugins.v2.bundle_archive import parse_bundle_archive_v2
from src.infrastructure.plugins.v2.layer_composer import desired_bundle_set_digest_v2
from src.infrastructure.plugins.v2.production_bundle import production_bundle_sources_v2

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("failure", [None, "revision", "reference", "verification"])
@pytest.mark.parametrize("scoped", [False, True])
async def test_explicit_upgrade_preserves_source_and_rejects_stale_or_invalid_candidate(
    test_db: AsyncSession, failure: str | None, scoped: bool
) -> None:
    sources = production_bundle_sources_v2()
    root = (
        ScopeV2(
            kind=ScopeKindV2.SESSION, tenant_id="tenant-a", project_id="project-a", session_id="s1"
        )
        if scoped
        else ScopeV2(kind=ScopeKindV2.ROOT)
    )
    old = replace(sources.desired_set.bundles[0], digest="sha256:" + "a" * 64)
    desired = replace(sources.desired_set, bundles=(old,))
    desired = replace(desired, digest=desired_bundle_set_digest_v2(desired))
    await PlatformPluginProfileSourceRepositoryV2(test_db).record_source(
        scope=root, source=sources.profile_source, expected_revision=None
    )
    repository = PlatformPluginDesiredBundleSetRepositoryV2(test_db)
    await repository.record_desired_set(
        scope=root, desired_set=desired, expected_revision=None, actor_id="test-maintainer"
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
    loader = AsyncMock(return_value=archive)
    if failure == "verification":
        loader.side_effect = ValueError("candidate archive verification failed")
    options = {
        "sources": sources,
        "load_verified_bundle": loader,
        "expected_revision": 2 if failure == "revision" else 1,
        "expected_bundle": replace(old, digest="sha256:" + "b" * 64)
        if failure == "reference"
        else old,
        "actor_id": "test-maintainer",
        "scope": root,
    }
    if failure:
        with pytest.raises(ValueError):
            await upgrade_root_builtin_bundle_v2(test_db, **options)
        history = await repository.list_history(root)
        assert len(history) == 1
        assert history[0].desired_set == desired
    else:
        updated = await upgrade_root_builtin_bundle_v2(test_db, **options)
        assert updated.desired_set.revision == 2
        assert updated.desired_set.profile_source == desired.profile_source
        assert updated.desired_set.bundles == sources.desired_set.bundles
        history = await repository.list_history(root)
        assert len(history) == 2
        assert history[1].desired_set == desired
