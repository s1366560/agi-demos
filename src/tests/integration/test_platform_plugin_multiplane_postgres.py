"""Multi-plane readiness and last-ready recovery in an explicitly isolated PostgreSQL DB."""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.domain.model.plugins.generated_v2 import ApplyStatusV2, PublicationStatusV2
from src.infrastructure.adapters.secondary.persistence.models import (
    PlatformPluginV2ApplyStateEventModel,
    PlatformPluginV2ApplyStateModel,
    PlatformPluginV2PublicationModel,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_publication_v2 import (
    PlatformPluginPublicationPolicyV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_repository_v2 import (
    PlatformPluginRepositoryV2,
)
from src.tests.integration.test_platform_plugin_publication_readiness_postgres import (
    _build_publication,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="session")]


@pytest.fixture
async def isolated_ledger() -> AsyncIterator[tuple[async_sessionmaker[AsyncSession], str, int]]:
    database_url = os.getenv("PLATFORM_PLUGIN_V2_POSTGRES_TEST_URL")
    if not database_url:
        pytest.skip("PLATFORM_PLUGIN_V2_POSTGRES_TEST_URL must name an isolated test database")
    engine = create_async_engine(database_url, pool_pre_ping=True)
    suffix = uuid.uuid4().hex
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with engine.connect() as connection:
            assert connection.dialect.name == "postgresql"
        async with sessions() as session:
            latest = await session.scalar(
                select(
                    func.coalesce(func.max(PlatformPluginV2PublicationModel.requested_version), 0)
                )
            )
        yield sessions, suffix, int(latest or 0) + 1
    finally:
        async with sessions() as session:
            rows = list(
                (
                    await session.scalars(
                        select(PlatformPluginV2PublicationModel)
                        .where(
                            PlatformPluginV2PublicationModel.nonce.like(f"multiplane-{suffix}-%")
                        )
                        .order_by(PlatformPluginV2PublicationModel.requested_version.desc())
                    )
                ).all()
            )
            ids = [row.id for row in rows]
            await session.execute(
                delete(PlatformPluginV2ApplyStateEventModel).where(
                    PlatformPluginV2ApplyStateEventModel.requested_publication_id.in_(ids)
                )
            )
            await session.execute(
                delete(PlatformPluginV2ApplyStateModel).where(
                    PlatformPluginV2ApplyStateModel.data_plane_id.like(f"multiplane-{suffix}-%")
                )
            )
            for row in rows:
                await session.execute(
                    delete(PlatformPluginV2PublicationModel).where(
                        PlatformPluginV2PublicationModel.id == row.id
                    )
                )
            await session.commit()
        await engine.dispose()


async def test_three_planes_require_all_acks_after_nack_and_timeout(  # noqa: PLR0915
    isolated_ledger,
) -> None:
    sessions, suffix, version = isolated_ledger
    now = datetime.now(UTC)
    planes = tuple(f"multiplane-{suffix}-{name}" for name in ("python", "rust", "web"))
    publication = await _build_publication(version=version, nonce=f"multiplane-{suffix}-candidate")
    assert publication.accepted
    policy = PlatformPluginPublicationPolicyV2(
        required_data_plane_ids=planes, ack_deadline_seconds=30
    )
    async with sessions() as session:
        repo = PlatformPluginRepositoryV2(session)
        row = await repo.record_publication(publication, policy=policy, now=now)
        publication_id = row.id
        await repo.record_data_plane_receipt(
            data_plane_id=planes[0],
            nonce=publication.envelope.nonce,
            receipt=publication.receipt,
            now=now + timedelta(seconds=1),
        )
        await session.commit()
    async with sessions() as session:
        repo = PlatformPluginRepositoryV2(session)
        waiting = await repo.publication_readiness(
            publication.envelope.nonce, now=now + timedelta(seconds=2)
        )
        assert waiting.status is PublicationStatusV2.RECONCILING
        assert sum(plane.status is ApplyStatusV2.ACK for plane in waiting.data_planes) == 1
        nack = replace(
            publication.receipt,
            status=ApplyStatusV2.NACK,
            applied_version=None,
            applied_digest=None,
            error_code="staging_failed",
            error_message="readiness rejected",
        )
        await repo.record_data_plane_receipt(
            data_plane_id=planes[1],
            nonce=publication.envelope.nonce,
            receipt=nack,
            now=now + timedelta(seconds=3),
        )
        await session.commit()
    async with sessions() as session:
        repo = PlatformPluginRepositoryV2(session)
        degraded = await repo.publication_readiness(
            publication.envelope.nonce, now=now + timedelta(seconds=4)
        )
        assert degraded.status is PublicationStatusV2.DEGRADED
        rejected = next(plane for plane in degraded.data_planes if plane.data_plane_id == planes[1])
        assert rejected.error_code == "staging_failed"
        assert rejected.error_message == "readiness rejected"
        await repo.record_data_plane_receipt(
            data_plane_id=planes[1],
            nonce=publication.envelope.nonce,
            receipt=publication.receipt,
            now=now + timedelta(seconds=5),
        )
        waiting_again = await repo.publication_readiness(
            publication.envelope.nonce, now=now + timedelta(seconds=6)
        )
        assert waiting_again.status is PublicationStatusV2.RECONCILING
        await session.commit()
    async with sessions() as session:
        repo = PlatformPluginRepositoryV2(session)
        await repo.reconcile_publication_deadlines(now=now + timedelta(seconds=31))
        await session.commit()
    async with sessions() as session:
        repo = PlatformPluginRepositoryV2(session)
        timed_out = await repo.publication_readiness(
            publication.envelope.nonce, now=now + timedelta(seconds=32)
        )
        assert timed_out.status is PublicationStatusV2.DEGRADED
        missing = next(plane for plane in timed_out.data_planes if plane.data_plane_id == planes[2])
        assert missing.status is None
        assert missing.error_code is None
        await session.commit()
    async with sessions() as session:
        await PlatformPluginRepositoryV2(session).record_data_plane_receipt(
            data_plane_id=planes[2],
            nonce=publication.envelope.nonce,
            receipt=publication.receipt,
            now=now + timedelta(seconds=35),
        )
        await session.commit()
    async with sessions() as session:
        ready = await PlatformPluginRepositoryV2(session).publication_readiness(
            publication.envelope.nonce, now=now + timedelta(seconds=36)
        )
        assert ready.status is PublicationStatusV2.READY
        assert ready.ready_at == now + timedelta(seconds=35)
        for plane in ready.data_planes:
            assert plane.status is ApplyStatusV2.ACK
            assert plane.requested_version == plane.applied_version == version
            assert plane.requested_digest == plane.applied_digest == publication.snapshot.digest
        events = list(
            (
                await session.scalars(
                    select(PlatformPluginV2ApplyStateEventModel).where(
                        PlatformPluginV2ApplyStateEventModel.requested_publication_id
                        == publication_id,
                    )
                )
            ).all()
        )
        assert len(events) == 4
        assert {
            event.error_code for event in events if event.status == ApplyStatusV2.NACK.value
        } == {"staging_failed"}


async def test_republish_retains_last_globally_ready_snapshot_across_sessions(
    isolated_ledger,
) -> None:
    sessions, suffix, version = isolated_ledger
    now = datetime.now(UTC)
    planes = tuple(f"multiplane-{suffix}-{name}" for name in ("python", "rust"))
    policy = PlatformPluginPublicationPolicyV2(
        required_data_plane_ids=planes, ack_deadline_seconds=30
    )
    first = await _build_publication(version=version, nonce=f"multiplane-{suffix}-ready")
    second = await _build_publication(version=version + 1, nonce=f"multiplane-{suffix}-rejected")
    assert first.accepted and second.accepted
    async with sessions() as session:
        repo = PlatformPluginRepositoryV2(session)
        source = await repo.record_publication(first, policy=policy, now=now)
        source_id, source_snapshot = source.id, source.distribution["snapshot"]
        for plane in planes:
            await repo.record_data_plane_receipt(
                data_plane_id=plane,
                nonce=first.envelope.nonce,
                receipt=first.receipt,
                now=now + timedelta(seconds=1),
            )
        await session.commit()
    async with sessions() as session:
        repo = PlatformPluginRepositoryV2(session)
        await repo.record_publication(second, policy=policy, now=now + timedelta(seconds=2))
        await repo.record_data_plane_receipt(
            data_plane_id=planes[0],
            nonce=second.envelope.nonce,
            receipt=second.receipt,
            now=now + timedelta(seconds=3),
        )
        nack = replace(
            second.receipt,
            status=ApplyStatusV2.NACK,
            applied_version=version,
            applied_digest=first.snapshot.digest,
            error_code="staging_failed",
            error_message="candidate rejected",
        )
        await repo.record_data_plane_receipt(
            data_plane_id=planes[1],
            nonce=second.envelope.nonce,
            receipt=nack,
            now=now + timedelta(seconds=3),
        )
        await session.commit()
    async with sessions() as session:
        repo = PlatformPluginRepositoryV2(session)
        assert (
            await repo.publication_readiness(second.envelope.nonce, now=now + timedelta(seconds=4))
        ).status is PublicationStatusV2.DEGRADED
        retained = await repo.last_good_distribution(planes[1])
        assert retained is not None and retained["snapshot"] == source_snapshot
        republished = await repo.republish_last_globally_ready(
            policy=policy, nonce=f"multiplane-{suffix}-recovery", now=now + timedelta(seconds=5)
        )
        recovery_nonce = republished.nonce
        assert republished.republished_from_id == source_id
        assert republished.snapshot_digest == first.snapshot.digest
        assert republished.distribution["snapshot"] == source_snapshot
        assert republished.requested_version == version + 2
        assert republished.distribution["envelope"]["version"] == version + 2
        assert republished.distribution["envelope"]["nonce"] == recovery_nonce
        assert set(republished.required_data_plane_ids) == set(planes)
        assert republished.status == PublicationStatusV2.RECONCILING.value
        await session.commit()
    async with sessions() as session:
        repo = PlatformPluginRepositoryV2(session)
        receipt = replace(first.receipt, requested_version=version + 2, applied_version=version + 2)
        for plane in planes:
            await repo.record_data_plane_receipt(
                data_plane_id=plane,
                nonce=recovery_nonce,
                receipt=receipt,
                now=now + timedelta(seconds=6),
            )
        await session.commit()
    async with sessions() as session:
        repo = PlatformPluginRepositoryV2(session)
        recovered = await repo.publication_readiness(recovery_nonce, now=now + timedelta(seconds=7))
        assert recovered.status is PublicationStatusV2.READY
        assert recovered.republished_from_nonce == first.envelope.nonce
        historical = await repo.publication_readiness(
            first.envelope.nonce, now=now + timedelta(seconds=7)
        )
        assert historical.status is PublicationStatusV2.READY
        assert all(plane.applied_version == version for plane in historical.data_planes)
