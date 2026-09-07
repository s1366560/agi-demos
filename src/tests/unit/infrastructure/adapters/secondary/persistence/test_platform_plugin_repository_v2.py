"""Durable requested/applied/last-good ledger tests for plugin protocol v2."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.plugins.generated_v2 import (
    ApplyStatusV2,
    PublicationStatusV2,
    SnapshotApplyReceiptV2,
)
from src.infrastructure.adapters.secondary.persistence.models import (
    PlatformPluginV2ApplyStateEventModel,
    PlatformPluginV2ApplyStateModel,
    PlatformPluginV2PublicationModel,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_repository_v2 import (
    PlatformPluginLedgerV2Error,
    PlatformPluginPublicationPolicyV2,
    PlatformPluginRepositoryV2,
)
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2

_ROOT = Path(__file__).resolve().parents[7]
_PROFILE = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFESTS = (_ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",)


async def _publication(*, generation: int, version: int):
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    publication = await host.bootstrap(
        profile_path=_PROFILE,
        manifest_paths=_MANIFESTS,
        generation=generation,
        version=version,
        nonce=f"ledger-{version}",
    )
    distribution = host.current_distribution
    assert distribution is not None
    await host.close()
    return publication, distribution.to_payload()


@pytest.mark.unit
async def test_v2_ledger_persists_full_distribution_and_ack(
    db_session: AsyncSession,
) -> None:
    publication, distribution = await _publication(generation=1, version=1)
    repository = PlatformPluginRepositoryV2(db_session)

    recorded = await repository.record_publication_and_receipt(
        publication,
        data_plane_id="python-api-v2",
    )

    assert isinstance(recorded.publication, PlatformPluginV2PublicationModel)
    assert isinstance(recorded.apply_state, PlatformPluginV2ApplyStateModel)
    assert recorded.publication.distribution == distribution
    assert recorded.apply_state.status == "ack"
    assert recorded.apply_state.requested_publication_id == recorded.publication.id
    assert recorded.apply_state.applied_publication_id == recorded.publication.id
    assert await repository.last_good_distribution("python-api-v2") == distribution


@pytest.mark.unit
async def test_v2_nack_retains_last_good_and_appends_receipt_evidence(
    db_session: AsyncSession,
) -> None:
    first, first_distribution = await _publication(generation=1, version=1)
    requested, _requested_distribution = await _publication(generation=2, version=2)
    nack = replace(
        requested,
        receipt=SnapshotApplyReceiptV2(
            status=ApplyStatusV2.NACK,
            requested_version=2,
            requested_digest=requested.snapshot.digest,
            applied_version=1,
            applied_digest=first.snapshot.digest,
            error_code="publication_staging_failed",
            error_message="route graph rejected",
        ),
    )
    repository = PlatformPluginRepositoryV2(db_session)
    first_record = await repository.record_publication_and_receipt(
        first,
        data_plane_id="python-api-v2",
    )

    rejected_record = await repository.record_publication_and_receipt(
        nack,
        data_plane_id="python-api-v2",
    )

    assert rejected_record.apply_state.status == "nack"
    assert rejected_record.apply_state.requested_publication_id == rejected_record.publication.id
    assert rejected_record.apply_state.applied_publication_id == first_record.publication.id
    assert rejected_record.apply_state.applied_version == 1
    assert rejected_record.apply_state.applied_digest == first.snapshot.digest
    assert await repository.last_good_distribution("python-api-v2") == first_distribution
    event_count = await db_session.scalar(
        select(func.count()).select_from(PlatformPluginV2ApplyStateEventModel)
    )
    assert event_count == 2


@pytest.mark.unit
async def test_v2_ledger_rejects_receipt_for_another_publication(
    db_session: AsyncSession,
) -> None:
    publication, _distribution = await _publication(generation=1, version=1)
    invalid = replace(
        publication,
        receipt=replace(publication.receipt, requested_digest="a" * 64),
    )

    with pytest.raises(ValueError, match="receipt does not match publication"):
        await PlatformPluginRepositoryV2(db_session).record_publication_and_receipt(
            invalid,
            data_plane_id="python-api-v2",
        )


@pytest.mark.unit
async def test_v2_ledger_returns_latest_complete_requested_distribution(
    db_session: AsyncSession,
) -> None:
    first, _first_distribution = await _publication(generation=1, version=1)
    second, second_distribution = await _publication(generation=2, version=2)
    repository = PlatformPluginRepositoryV2(db_session)
    await repository.record_publication(first)
    await repository.record_publication(second)

    assert await repository.latest_requested_distribution() == second_distribution


@pytest.mark.unit
async def test_v2_ledger_records_external_data_plane_receipt_by_nonce(
    db_session: AsyncSession,
) -> None:
    publication, _distribution = await _publication(generation=3, version=3)
    repository = PlatformPluginRepositoryV2(db_session)
    await repository.record_publication(
        publication,
        policy=PlatformPluginPublicationPolicyV2(
            required_data_plane_ids=("desktop-sidecar",),
            ack_deadline_seconds=30,
        ),
    )

    state = await repository.record_data_plane_receipt(
        data_plane_id="desktop-sidecar",
        nonce=publication.envelope.nonce,
        receipt=publication.receipt,
    )

    assert state.data_plane_id == "desktop-sidecar"
    assert state.status == "ack"
    assert state.requested_version == 3
    assert state.applied_version == 3

    repeated = await repository.record_data_plane_receipt(
        data_plane_id="desktop-sidecar",
        nonce=publication.envelope.nonce,
        receipt=publication.receipt,
    )
    event_count = await db_session.scalar(
        select(func.count()).select_from(PlatformPluginV2ApplyStateEventModel)
    )
    assert repeated.id == state.id
    assert event_count == 1


@pytest.mark.unit
async def test_v2_ledger_rejects_unknown_or_stale_external_receipt(
    db_session: AsyncSession,
) -> None:
    first, _first_distribution = await _publication(generation=1, version=1)
    second, _second_distribution = await _publication(generation=2, version=2)
    repository = PlatformPluginRepositoryV2(db_session)
    policy = PlatformPluginPublicationPolicyV2(
        required_data_plane_ids=("rust-server",),
        ack_deadline_seconds=30,
    )
    await repository.record_publication(first, policy=policy)
    await repository.record_publication(second, policy=policy)
    await repository.record_data_plane_receipt(
        data_plane_id="rust-server",
        nonce=second.envelope.nonce,
        receipt=second.receipt,
    )

    with pytest.raises(PlatformPluginLedgerV2Error) as unknown:
        await repository.record_data_plane_receipt(
            data_plane_id="rust-server",
            nonce="missing-publication",
            receipt=second.receipt,
        )
    assert unknown.value.code == "publication_not_found"

    with pytest.raises(PlatformPluginLedgerV2Error) as stale:
        await repository.record_data_plane_receipt(
            data_plane_id="rust-server",
            nonce=first.envelope.nonce,
            receipt=first.receipt,
        )
    assert stale.value.code == "stale_receipt"


@pytest.mark.unit
async def test_v2_publication_waits_for_all_required_planes_and_recovers_from_nack(
    db_session: AsyncSession,
) -> None:
    now = datetime(2026, 8, 22, 8, 0, tzinfo=UTC)
    publication, _distribution = await _publication(generation=1, version=1)
    policy = PlatformPluginPublicationPolicyV2(
        required_data_plane_ids=("python-api-v2", "rust-server"),
        ack_deadline_seconds=30,
    )
    repository = PlatformPluginRepositoryV2(db_session)

    row = await repository.record_publication(publication, policy=policy, now=now)
    await repository.record_data_plane_receipt(
        data_plane_id="python-api-v2",
        nonce=publication.envelope.nonce,
        receipt=publication.receipt,
        now=now + timedelta(seconds=1),
    )
    waiting = await repository.publication_readiness(
        publication.envelope.nonce,
        now=now + timedelta(seconds=2),
    )

    assert row.required_data_plane_ids == ["python-api-v2", "rust-server"]
    assert row.ack_deadline_at == now + timedelta(seconds=30)
    assert waiting.status is PublicationStatusV2.RECONCILING
    assert [plane.data_plane_id for plane in waiting.data_planes] == [
        "python-api-v2",
        "rust-server",
    ]
    assert [plane.status for plane in waiting.data_planes] == [ApplyStatusV2.ACK, None]

    nack = SnapshotApplyReceiptV2(
        status=ApplyStatusV2.NACK,
        requested_version=publication.envelope.version,
        requested_digest=publication.snapshot.digest,
        applied_version=None,
        applied_digest=None,
        error_code="staging_failed",
        error_message="module rejected",
    )
    await repository.record_data_plane_receipt(
        data_plane_id="rust-server",
        nonce=publication.envelope.nonce,
        receipt=nack,
        now=now + timedelta(seconds=3),
    )
    degraded = await repository.publication_readiness(
        publication.envelope.nonce,
        now=now + timedelta(seconds=4),
    )
    assert degraded.status is PublicationStatusV2.DEGRADED

    await repository.record_data_plane_receipt(
        data_plane_id="rust-server",
        nonce=publication.envelope.nonce,
        receipt=publication.receipt,
        now=now + timedelta(seconds=35),
    )
    ready = await repository.publication_readiness(
        publication.envelope.nonce,
        now=now + timedelta(seconds=36),
    )
    assert ready.status is PublicationStatusV2.READY
    assert ready.ready_at == now + timedelta(seconds=35)


@pytest.mark.unit
async def test_v2_publication_timeout_degrades_then_late_ack_recovers(
    db_session: AsyncSession,
) -> None:
    now = datetime(2026, 8, 22, 9, 0, tzinfo=UTC)
    publication, _distribution = await _publication(generation=2, version=2)
    repository = PlatformPluginRepositoryV2(db_session)
    await repository.record_publication(
        publication,
        policy=PlatformPluginPublicationPolicyV2(
            required_data_plane_ids=("desktop-sidecar",),
            ack_deadline_seconds=30,
        ),
        now=now,
    )

    timed_out = await repository.publication_readiness(
        publication.envelope.nonce,
        now=now + timedelta(seconds=30),
    )
    assert timed_out.status is PublicationStatusV2.DEGRADED

    await repository.record_data_plane_receipt(
        data_plane_id="desktop-sidecar",
        nonce=publication.envelope.nonce,
        receipt=publication.receipt,
        now=now + timedelta(seconds=31),
    )
    recovered = await repository.publication_readiness(
        publication.envelope.nonce,
        now=now + timedelta(seconds=32),
    )
    assert recovered.status is PublicationStatusV2.READY


@pytest.mark.unit
async def test_v2_deadline_sweep_persists_timeout_without_read_query(
    db_session: AsyncSession,
) -> None:
    now = datetime(2026, 8, 22, 9, 15, tzinfo=UTC)
    publication, _distribution = await _publication(generation=3, version=3)
    repository = PlatformPluginRepositoryV2(db_session)
    row = await repository.record_publication(
        publication,
        policy=PlatformPluginPublicationPolicyV2(
            required_data_plane_ids=("rust-server",),
            ack_deadline_seconds=30,
        ),
        now=now,
    )

    reconciled = await repository.reconcile_publication_deadlines(now=now + timedelta(seconds=30))

    assert reconciled == 1
    assert row.status == PublicationStatusV2.DEGRADED.value
    assert row.status_updated_at == now + timedelta(seconds=30)


@pytest.mark.unit
async def test_v2_historical_readiness_uses_append_only_receipt_events(
    db_session: AsyncSession,
) -> None:
    now = datetime(2026, 8, 22, 9, 30, tzinfo=UTC)
    first, _first_distribution = await _publication(generation=1, version=1)
    second, _second_distribution = await _publication(generation=2, version=2)
    policy = PlatformPluginPublicationPolicyV2(
        required_data_plane_ids=("rust-server",),
        ack_deadline_seconds=30,
    )
    repository = PlatformPluginRepositoryV2(db_session)
    await repository.record_publication(first, policy=policy, now=now)
    await repository.record_data_plane_receipt(
        data_plane_id="rust-server",
        nonce=first.envelope.nonce,
        receipt=first.receipt,
        now=now + timedelta(seconds=1),
    )
    await repository.record_publication(second, policy=policy, now=now + timedelta(seconds=2))
    await repository.record_data_plane_receipt(
        data_plane_id="rust-server",
        nonce=second.envelope.nonce,
        receipt=second.receipt,
        now=now + timedelta(seconds=3),
    )

    historical = await repository.publication_readiness(
        first.envelope.nonce,
        now=now + timedelta(seconds=4),
    )

    assert historical.status is PublicationStatusV2.READY
    assert len(historical.data_planes) == 1
    assert historical.data_planes[0].status is ApplyStatusV2.ACK
    assert historical.data_planes[0].requested_version == first.envelope.version
    assert historical.data_planes[0].requested_digest == first.snapshot.digest
    assert historical.data_planes[0].applied_version == first.envelope.version
    assert historical.data_planes[0].applied_digest == first.snapshot.digest


@pytest.mark.unit
async def test_v2_ledger_rejects_unregistered_and_never_requested_planes(
    db_session: AsyncSession,
) -> None:
    first, _first_distribution = await _publication(generation=1, version=1)
    second, _second_distribution = await _publication(generation=2, version=2)
    policy = PlatformPluginPublicationPolicyV2(
        required_data_plane_ids=("rust-server",),
        ack_deadline_seconds=30,
    )
    repository = PlatformPluginRepositoryV2(db_session)
    await repository.record_publication(first, policy=policy)

    with pytest.raises(PlatformPluginLedgerV2Error) as unregistered:
        await repository.record_data_plane_receipt(
            data_plane_id="desktop-renderer-ephemeral",
            nonce=first.envelope.nonce,
            receipt=first.receipt,
        )
    assert unregistered.value.code == "data_plane_not_required"

    await repository.record_publication(second, policy=policy)
    with pytest.raises(PlatformPluginLedgerV2Error) as stale:
        await repository.record_data_plane_receipt(
            data_plane_id="rust-server",
            nonce=first.envelope.nonce,
            receipt=first.receipt,
        )
    assert stale.value.code == "stale_receipt"


@pytest.mark.unit
async def test_v2_republish_uses_most_recent_globally_ready_snapshot(
    db_session: AsyncSession,
) -> None:
    now = datetime(2026, 8, 22, 10, 0, tzinfo=UTC)
    first, _first_distribution = await _publication(generation=1, version=1)
    rejected, _rejected_distribution = await _publication(generation=2, version=2)
    repository = PlatformPluginRepositoryV2(db_session)
    ready_record = await repository.record_publication_and_receipt(
        first,
        data_plane_id="python-api-v2",
        now=now,
    )
    rejected_receipt = replace(
        rejected,
        receipt=SnapshotApplyReceiptV2(
            status=ApplyStatusV2.NACK,
            requested_version=2,
            requested_digest=rejected.snapshot.digest,
            applied_version=1,
            applied_digest=first.snapshot.digest,
            error_code="staging_failed",
            error_message="rejected",
        ),
    )
    await repository.record_publication_and_receipt(
        rejected_receipt,
        data_plane_id="python-api-v2",
        now=now + timedelta(seconds=1),
    )

    republished = await repository.republish_last_globally_ready(
        policy=PlatformPluginPublicationPolicyV2(
            required_data_plane_ids=("python-api-v2", "rust-server"),
            ack_deadline_seconds=30,
        ),
        nonce="republish-last-ready-3",
        now=now + timedelta(seconds=2),
    )

    assert republished.republished_from_id == ready_record.publication.id
    assert republished.requested_version == 3
    assert republished.snapshot_digest == first.snapshot.digest
    assert republished.nonce == "republish-last-ready-3"
    assert republished.distribution["envelope"]["version"] == 3
    assert republished.distribution["envelope"]["nonce"] == "republish-last-ready-3"
    assert republished.status == PublicationStatusV2.RECONCILING.value


@pytest.mark.unit
async def test_v2_publication_nonce_cannot_change_roster_or_deadline(
    db_session: AsyncSession,
) -> None:
    now = datetime(2026, 8, 22, 11, 0, tzinfo=UTC)
    publication, _distribution = await _publication(generation=1, version=1)
    repository = PlatformPluginRepositoryV2(db_session)
    policy = PlatformPluginPublicationPolicyV2(
        required_data_plane_ids=("rust-server",),
        ack_deadline_seconds=30,
    )
    first = await repository.record_publication(publication, policy=policy, now=now)

    repeated = await repository.record_publication(
        publication,
        policy=policy,
        now=now + timedelta(seconds=10),
    )
    assert repeated.id == first.id
    assert repeated.ack_deadline_at == now + timedelta(seconds=30)

    with pytest.raises(ValueError, match="cannot change its required data-plane roster"):
        await repository.record_publication(
            publication,
            policy=PlatformPluginPublicationPolicyV2(
                required_data_plane_ids=("desktop-sidecar",),
                ack_deadline_seconds=30,
            ),
        )

    with pytest.raises(ValueError, match="cannot change its ACK deadline"):
        await repository.record_publication(
            publication,
            policy=PlatformPluginPublicationPolicyV2(
                required_data_plane_ids=("rust-server",),
                ack_deadline_seconds=60,
            ),
        )
