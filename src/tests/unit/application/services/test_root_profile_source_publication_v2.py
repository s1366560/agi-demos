"""ROOT publication rejects unresolved sources before artifact IO or runtime mutation."""

from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.application.services.plugin_marketplace_publication_service_v2 import (
    PluginMarketplacePublicationServiceV2,
)
from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.adapters.secondary.persistence.platform_plugin_desired_bundle_repository_v2 import (
    PlatformPluginDesiredBundleSetRepositoryV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_profile_source_repository_v2 import (
    PlatformPluginProfileSourceRepositoryV2,
)
from src.infrastructure.plugins.v2.layer_composer import (
    desired_bundle_set_digest_v2,
    profile_source_digest_v2,
)
from src.infrastructure.plugins.v2.production_bundle import production_bundle_sources_v2

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("case", ["missing", "other_scope", "wrong_revision", "wrong_digest"])
async def test_unresolved_root_source_rejects_before_load_or_publish(db_session, case):
    sources = production_bundle_sources_v2()
    source = replace(sources.profile_source, source_id="root-explicit")
    source = replace(source, digest=profile_source_digest_v2(source))
    root = ScopeV2(kind=ScopeKindV2.ROOT)
    repository = PlatformPluginProfileSourceRepositoryV2(db_session)
    if case != "missing":
        await repository.record_source(
            scope=(
                ScopeV2(kind=ScopeKindV2.TENANT, tenant_id="other")
                if case == "other_scope"
                else root
            ),
            source=source,
            expected_revision=None,
        )
    reference = replace(
        sources.desired_set.profile_source,
        source_id=source.source_id,
        revision=2 if case == "wrong_revision" else source.revision,
        digest=("sha256:" + "0" * 64) if case == "wrong_digest" else source.digest,
    )
    desired = replace(sources.desired_set, profile_source=reference)
    desired = replace(desired, digest=desired_bundle_set_digest_v2(desired))
    desired_repo = PlatformPluginDesiredBundleSetRepositoryV2(db_session)
    await desired_repo.record_desired_set(
        scope=root, desired_set=desired, expected_revision=None, actor_id="test"
    )
    coordinator = MagicMock()
    publisher = PluginMarketplacePublicationServiceV2(
        mutation_session=db_session,
        receipt_session_factory=async_sessionmaker(db_session.bind, expire_on_commit=False),
        desired_repository=desired_repo,
        source_repository=repository,
        governance_repository=MagicMock(),
        publication_repository=MagicMock(),
        artifact_client=MagicMock(),
        production_sources=sources,
        trusted_public_keys=(),
        host=MagicMock(),
        route_coordinator=coordinator,
        publication_policy=MagicMock(),
    )
    load = AsyncMock()
    publisher._load_bundle = load
    with pytest.raises(ValueError):
        await publisher.publish_current()
    load.assert_not_awaited()
    coordinator.publish_snapshot.assert_not_called()
