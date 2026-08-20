"""Durable requested/applied/last-good ledger tests for plugin protocol v2."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.plugins.generated_v2 import ApplyStatusV2, SnapshotApplyReceiptV2
from src.infrastructure.adapters.secondary.persistence.models import (
    PlatformPluginV2ApplyStateEventModel,
    PlatformPluginV2ApplyStateModel,
    PlatformPluginV2PublicationModel,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_repository_v2 import (
    PlatformPluginLedgerV2Error,
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
    await repository.record_publication(publication)

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
    await repository.record_publication(first)
    await repository.record_publication(second)
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
