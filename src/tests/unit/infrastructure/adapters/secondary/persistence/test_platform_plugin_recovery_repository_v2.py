"""Real ledger snapshots for restart recovery, never inferred from current desired."""

from dataclasses import replace

import pytest

from src.domain.model.plugins.generated_v2 import ApplyStatusV2
from src.infrastructure.adapters.secondary.persistence.platform_plugin_publication_source_repository_v2 import (
    PlatformPluginPublicationSourceRepositoryV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_recovery_repository_v2 import (
    PlatformPluginRecoveryRepositoryV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_repository_v2 import (
    PlatformPluginRepositoryV2,
)
from src.infrastructure.plugins.v2.production_bundle import production_bundle_sources_v2
from src.tests.unit.infrastructure.adapters.secondary.persistence.test_platform_plugin_repository_v2 import (
    _publication,
)
from src.tests.unit.infrastructure.adapters.secondary.persistence.test_platform_plugin_scoped_ledger_v2 import (
    _scope,
)

pytestmark = pytest.mark.unit
PLANE = "python-api-v2"


async def test_ack_nack_and_unreceipted_latest_preserve_actual_plane_evidence(db_session):
    scope = _scope()
    repository = PlatformPluginRepositoryV2(db_session, scope=scope)
    reader = PlatformPluginRecoveryRepositoryV2(db_session)
    missing = await reader.read(scope, PLANE)
    assert (missing.latest, missing.last_good, missing.latest_receipt, missing.source) == (
        None,
        None,
        None,
        None,
    )
    publication, _ = await _publication(generation=1, version=1)
    recorded = await repository.record_publication_and_receipt(publication, data_plane_id=PLANE)
    desired = production_bundle_sources_v2().desired_set
    assert desired.revision == 1
    await PlatformPluginPublicationSourceRepositoryV2(db_session).record(
        scope=scope, publication_id=recorded.publication.id, desired_set=desired
    )
    state = await reader.read(scope, PLANE)
    assert state.latest_receipt == publication.receipt
    assert state.latest == state.last_good
    assert state.source == desired
    from src.infrastructure.adapters.secondary.persistence.platform_plugin_desired_bundle_repository_v2 import (
        PlatformPluginDesiredBundleSetRepositoryV2,
    )
    from src.infrastructure.plugins.v2.layer_composer import desired_bundle_set_digest_v2

    current_desired = replace(desired, revision=2)
    current_desired = replace(current_desired, digest=desired_bundle_set_digest_v2(current_desired))
    await PlatformPluginDesiredBundleSetRepositoryV2(db_session).record_desired_set(
        scope=scope, desired_set=current_desired, expected_revision=None, actor_id="test-author"
    )
    assert (await reader.read(scope, PLANE)).source == desired
    other = await reader.read(scope, "unregistered-test-plane")
    assert other.latest is not None and other.last_good is None and other.latest_receipt is None
    foreign = await reader.read(_scope("foreign"), PLANE)
    assert foreign.latest is None
    nack = replace(
        publication,
        envelope=replace(publication.envelope, version=2, nonce="recovery-nack"),
        receipt=replace(
            publication.receipt,
            status=ApplyStatusV2.NACK,
            requested_version=2,
            error_code="candidate_rejected",
            error_message="candidate failed",
        ),
    )
    await repository.record_publication_and_receipt(nack, data_plane_id=PLANE)
    state = await reader.read(scope, PLANE)
    assert state.latest_receipt == nack.receipt
    assert state.latest.envelope.nonce == "recovery-nack"
    assert state.last_good.envelope == publication.envelope
    assert state.source == desired
    await repository.record_requested_distribution(
        publication.snapshot, replace(publication.envelope, version=3, nonce="recovery-unreceipted")
    )
    pending = await reader.read(scope, PLANE)
    assert pending.latest.envelope.version == 3
    assert pending.latest_receipt is None
    assert pending.last_good == state.last_good and pending.source == desired


async def test_corrupt_row_identity_and_receipt_fail_closed(db_session):
    scope = _scope()
    publication, _ = await _publication(generation=1, version=1)
    recorded = await PlatformPluginRepositoryV2(
        db_session, scope=scope
    ).record_publication_and_receipt(publication, data_plane_id=PLANE)
    reader = PlatformPluginRecoveryRepositoryV2(db_session)
    recorded.publication.nonce = "corrupt-nonce"
    await db_session.flush()
    with pytest.raises(ValueError, match="identity differs"):
        await reader.read(scope, PLANE)
    recorded.publication.nonce = publication.envelope.nonce
    recorded.apply_state.requested_digest = "b" * 64
    await db_session.flush()
    with pytest.raises(ValueError):
        await reader.read(scope, PLANE)
    recorded.apply_state.requested_digest = publication.snapshot.digest
    recorded.publication.required_data_plane_ids = ["different-plane"]
    await db_session.flush()
    with pytest.raises(ValueError, match="not registered"):
        await reader.read(scope, PLANE)
    recorded.publication.required_data_plane_ids = [PLANE]
    recorded.apply_state.tenant_id = "corrupt-tenant"
    await db_session.flush()
    with pytest.raises(ValueError):
        await reader.read(scope, PLANE)


async def test_latest_same_version_new_nonce_does_not_reuse_previous_ack(db_session):
    scope = _scope()
    publication, _ = await _publication(generation=1, version=1)
    repository = PlatformPluginRepositoryV2(db_session, scope=scope)
    await repository.record_publication_and_receipt(publication, data_plane_id=PLANE)
    new_envelope = replace(publication.envelope, nonce="different-request-same-version")
    await repository.record_requested_distribution(publication.snapshot, new_envelope)
    state = await PlatformPluginRecoveryRepositoryV2(db_session).read(scope, PLANE)
    assert state.latest.envelope == new_envelope
    assert state.last_good.envelope == publication.envelope
    assert state.latest_receipt is None


@pytest.mark.parametrize("plane", ["", "   "])
async def test_empty_plane_is_not_a_recovery_authority(db_session, plane):
    with pytest.raises(ValueError, match="non-empty"):
        await PlatformPluginRecoveryRepositoryV2(db_session).read(_scope(), plane)
