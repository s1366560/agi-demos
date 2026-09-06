"""Requested distributions are durable before any real data-plane receipt exists."""

from dataclasses import replace

import pytest
from sqlalchemy import func, select

from src.infrastructure.adapters.secondary.persistence.models import (
    PlatformPluginV2ApplyStateEventModel,
    PlatformPluginV2ApplyStateModel,
    PlatformPluginV2PublicationModel,
    PlatformPluginV2ScopeHeadModel,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_repository_v2 import (
    PlatformPluginRepositoryV2,
)
from src.tests.unit.infrastructure.adapters.secondary.persistence.test_platform_plugin_repository_v2 import (
    _publication,
)

pytestmark = pytest.mark.unit


async def test_requested_distribution_commits_without_inventing_receipt(db_session):
    publication, payload = await _publication(generation=1, version=1)
    repository = PlatformPluginRepositoryV2(db_session)
    row = await repository.record_requested_distribution(publication.snapshot, publication.envelope)
    await db_session.commit()
    assert row.distribution == payload
    assert row.status == "reconciling"
    assert row.ready_at is None
    assert await repository.last_good_distribution("python-api-v2") is None
    for model in (PlatformPluginV2ApplyStateModel, PlatformPluginV2ApplyStateEventModel):
        assert await db_session.scalar(select(func.count()).select_from(model)) == 0
    same = await repository.record_requested_distribution(
        publication.snapshot, publication.envelope
    )
    assert same.id == row.id
    await repository.record_data_plane_receipt(
        data_plane_id="python-api-v2", nonce=publication.envelope.nonce, receipt=publication.receipt
    )
    await db_session.commit()
    assert (
        await repository.publication_readiness(publication.envelope.nonce)
    ).status.value == "ready"
    assert await repository.last_good_distribution("python-api-v2") == payload
    next_row = await repository.record_requested_distribution(
        publication.snapshot, replace(publication.envelope, nonce="another-request")
    )
    assert next_row.requested_version == row.requested_version
    assert next_row.id != row.id


@pytest.mark.parametrize("change", ["snapshot", "digest", "type_url", "version"])
async def test_invalid_typed_requested_distribution_is_rejected_before_writes(db_session, change):
    publication, _ = await _publication(generation=1, version=1)
    snapshot, envelope = publication.snapshot, publication.envelope
    if change == "snapshot":
        snapshot = replace(snapshot, generation=2)
    elif change == "digest":
        envelope = replace(envelope, snapshot_digest="0" * 64)
    elif change == "type_url":
        envelope = replace(envelope, type_url="types.memstack.ai/not-profile")
    else:
        envelope = replace(envelope, version=0)
    with pytest.raises(ValueError):
        await PlatformPluginRepositoryV2(db_session).record_requested_distribution(
            snapshot, envelope
        )
    for model in (PlatformPluginV2PublicationModel, PlatformPluginV2ScopeHeadModel):
        assert await db_session.scalar(select(func.count()).select_from(model)) == 0
