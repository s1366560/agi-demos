"""Rollback appends a distinct generation and authority in one caller transaction."""

from dataclasses import replace

import pytest
from sqlalchemy import func, select

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.adapters.secondary.persistence.models import (
    PlatformPluginV2PublicationModel,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_desired_bundle_repository_v2 import (
    PlatformPluginDesiredBundleSetRepositoryV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_publication_source_repository_v2 import (
    PlatformPluginPublicationSourceRepositoryV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_publication_v2 import (
    PlatformPluginPublicationPolicyV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_repository_v2 import (
    PlatformPluginLedgerV2Error,
    PlatformPluginRepositoryV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_rollback_repository_v2 import (
    PlatformPluginRollbackRepositoryV2,
)
from src.infrastructure.plugins.v2.layer_composer import desired_bundle_set_digest_v2
from src.infrastructure.plugins.v2.production_bundle import production_bundle_sources_v2
from src.tests.unit.infrastructure.adapters.secondary.persistence.test_platform_plugin_repository_v2 import (
    _publication,
)

pytestmark = pytest.mark.unit
ROOT = ScopeV2(kind=ScopeKindV2.ROOT)
POLICY = PlatformPluginPublicationPolicyV2.local_default()


async def _seed(db):
    publication, _ = await _publication(generation=3, version=7)
    ledger = PlatformPluginRepositoryV2(db)
    record = await ledger.record_publication_and_receipt(publication, data_plane_id="python-api-v2")
    desired = production_bundle_sources_v2().desired_set
    sources = PlatformPluginPublicationSourceRepositoryV2(db)
    await sources.record(scope=ROOT, publication_id=record.publication.id, desired_set=desired)
    desired_repo = PlatformPluginDesiredBundleSetRepositoryV2(db)
    await desired_repo.record_desired_set(
        scope=ROOT, desired_set=desired, expected_revision=None, actor_id="initial"
    )
    newer = replace(desired, revision=desired.revision + 1, bundles=())
    newer = replace(newer, digest=desired_bundle_set_digest_v2(newer))
    await desired_repo.record_desired_set(
        scope=ROOT, desired_set=newer, expected_revision=desired.revision, actor_id="changed"
    )
    pending, _ = await _publication(generation=9, version=11)
    await ledger.record_requested_distribution(pending.snapshot, pending.envelope, policy=POLICY)
    await db.commit()
    return record.publication.id, desired, newer


async def test_rollback_new_authority_generation_version_and_original_history(db_session):
    source_id, old, current = await _seed(db_session)
    result = await PlatformPluginRollbackRepositoryV2(db_session).republish_last_ready(
        policy=POLICY, actor_id="platform-admin"
    )
    assert result.generation == 10
    assert result.requested_version == 12
    assert result.republished_from_id == source_id
    assert result.status == "reconciling"
    assert result.ready_at is None
    desired = await PlatformPluginDesiredBundleSetRepositoryV2(db_session).current_desired_set(ROOT)
    assert desired.actor_id == "platform-admin"
    assert desired.desired_set.revision == current.revision + 1
    assert desired.desired_set.bundles == old.bundles
    assert desired.desired_set.digest == desired_bundle_set_digest_v2(desired.desired_set)
    assert (
        await PlatformPluginPublicationSourceRepositoryV2(db_session).read(
            scope=ROOT, publication_id=result.id
        )
        == desired.desired_set
    )
    original = await db_session.get(PlatformPluginV2PublicationModel, source_id)
    assert original.generation == 3
    assert original.snapshot_digest != result.snapshot_digest
    assert (
        result.distribution["snapshot"]["entries"] == original.distribution["snapshot"]["entries"]
    )
    await db_session.commit()


async def test_caller_rollback_restores_desired_request_and_version_allocation(db_session):
    _, _, current = await _seed(db_session)
    repo = PlatformPluginRollbackRepositoryV2(db_session)
    await repo.republish_last_ready(policy=POLICY, actor_id="admin")
    await db_session.rollback()
    desired = await PlatformPluginDesiredBundleSetRepositoryV2(db_session).current_desired_set(ROOT)
    assert desired.desired_set == current
    assert (
        await db_session.scalar(select(func.count()).select_from(PlatformPluginV2PublicationModel))
        == 2
    )
    retry = await repo.republish_last_ready(policy=POLICY, actor_id="admin")
    assert retry.requested_version == 12
    assert retry.generation == 10


async def test_no_ready_fails_without_creating_desired(db_session):
    with pytest.raises(PlatformPluginLedgerV2Error, match="globally-ready") as error:
        await PlatformPluginRollbackRepositoryV2(db_session).republish_last_ready(
            policy=POLICY, actor_id="admin"
        )
    assert error.value.code == "globally_ready_not_found"
    assert (
        await PlatformPluginDesiredBundleSetRepositoryV2(db_session).current_desired_set(ROOT)
        is None
    )


async def test_corrupt_ready_identity_rejects_before_desired_mutation(db_session):
    source_id, _, current = await _seed(db_session)
    source = await db_session.get(PlatformPluginV2PublicationModel, source_id)
    source.generation = 99
    await db_session.flush()
    with pytest.raises(PlatformPluginLedgerV2Error) as error:
        await PlatformPluginRollbackRepositoryV2(db_session).republish_last_ready(
            policy=POLICY, actor_id="admin"
        )
    assert error.value.code == "rollback_source_invalid"
    desired = await PlatformPluginDesiredBundleSetRepositoryV2(db_session).current_desired_set(ROOT)
    assert desired.desired_set == current
