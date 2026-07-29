"""Durable Artifact content orphan GC lease and restart tests."""

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from sqlalchemy import select
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.domain.ports.repositories.artifact_content_authority_repository import (
    ArtifactContentScope,
)
from src.infrastructure.adapters.secondary.persistence.artifact_content_orphan_gc_worker import (
    ArtifactContentOrphanGcWorker,
)
from src.infrastructure.adapters.secondary.persistence.artifact_model import (
    ArtifactContentOrphanGcModel,
    ArtifactModel,
)
from src.infrastructure.adapters.secondary.persistence.models import (
    Conversation,
    Project,
    Tenant,
    User,
)
from src.infrastructure.adapters.secondary.persistence.sql_artifact_content_authority import (
    SqlArtifactContentAuthorityRepository,
)

TENANT_ID = "tenant-artifact-gc"
PROJECT_ID = "project-artifact-gc"
CONVERSATION_ID = "conversation-artifact-gc"
ARTIFACT_ID = "artifact-cloud-gc"
ACTIVE_OBJECT_KEY = "artifacts/tenant-artifact-gc/project-artifact-gc/active.txt"
CONTENT_HASH = f"sha256:{'1' * 64}"


class RecordingGcStorage:
    """Object-store double with restart-stable objects and delete failure injection."""

    def __init__(self) -> None:
        self.objects: set[str] = {ACTIVE_OBJECT_KEY}
        self.deletes: list[str] = []
        self.fail_delete = False

    async def delete_file(self, object_key: str) -> bool:
        self.deletes.append(object_key)
        if self.fail_delete:
            raise RuntimeError("object delete unavailable")
        if object_key not in self.objects:
            return False
        self.objects.remove(object_key)
        return True


async def _seed_authority(session: AsyncSession) -> ArtifactContentScope:
    user = User(
        id="artifact-gc-user",
        email="artifact-gc@example.com",
        hashed_password="hashed",
        is_active=True,
        is_superuser=False,
    )
    tenant = Tenant(
        id=TENANT_ID,
        name="Artifact GC",
        slug="artifact-gc",
        owner_id=user.id,
    )
    project = Project(
        id=PROJECT_ID,
        tenant_id=TENANT_ID,
        name="Artifact GC",
        owner_id=user.id,
    )
    conversation = Conversation(
        id=CONVERSATION_ID,
        project_id=PROJECT_ID,
        tenant_id=TENANT_ID,
        user_id=user.id,
        title="Artifact GC",
    )
    artifact = ArtifactModel(
        id=ARTIFACT_ID,
        project_id=PROJECT_ID,
        tenant_id=TENANT_ID,
        conversation_id=CONVERSATION_ID,
        filename="active.txt",
        mime_type="text/plain",
        category="document",
        size_bytes=4,
        object_key=ACTIVE_OBJECT_KEY,
        content_revision=1,
        content_hash=CONTENT_HASH,
        status="ready",
        artifact_metadata={},
    )
    session.add_all([user, tenant, project, conversation, artifact])
    await session.commit()
    return ArtifactContentScope(
        artifact_id=ARTIFACT_ID,
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        conversation_id=CONVERSATION_ID,
    )


async def _record_pending(
    session: AsyncSession,
    scope: ArtifactContentScope,
    object_key: str,
) -> None:
    repository = SqlArtifactContentAuthorityRepository(session)
    await repository.record_orphan_gc(
        scope=scope,
        object_key=object_key,
        idempotency_key=f"artifact-gc:{object_key[-8:]}",
        request_hash=f"sha256:{'2' * 64}",
        content_revision=2,
        content_hash=CONTENT_HASH,
        reason_code="commit_not_observed",
        status="pending",
    )
    await session.commit()


@pytest.mark.unit
def test_postgresql_gc_claim_targets_queue_row_and_skips_locked() -> None:
    now = datetime(2030, 7, 28, tzinfo=UTC)
    statement = SqlArtifactContentAuthorityRepository._orphan_gc_claim_statement(
        now=now,
        limit=5,
    )

    sql = str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    assert "artifact_content_orphan_gc.status = 'pending'" in sql
    assert sql.endswith("FOR UPDATE OF artifact_content_orphan_gc SKIP LOCKED")


@pytest.mark.unit
async def test_gc_lease_inputs_fail_closed_before_database_access(test_engine) -> None:
    sessions = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    async with sessions() as session:
        repository = SqlArtifactContentAuthorityRepository(session)
        naive_now = datetime(2030, 7, 28)

        with pytest.raises(ValueError, match="timezone-aware"):
            await repository.claim_orphan_gc(
                lease_owner="worker",
                lease_token="token",
                now=naive_now,
                lease_expires_at=naive_now + timedelta(seconds=30),
                limit=1,
            )
        with pytest.raises(ValueError, match="lease owner"):
            await repository.complete_orphan_gc_lease(
                "artifacts/orphan",
                lease_owner="",
                lease_token="token",
                status="deleted",
                last_error_code=None,
                next_attempt_at=datetime(2030, 7, 28, tzinfo=UTC),
            )


@pytest.mark.unit
async def test_expired_lease_can_be_reclaimed_but_stale_owner_is_fenced(test_engine) -> None:
    sessions = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    now = datetime(2030, 7, 28, 10, tzinfo=UTC)

    async with sessions() as session:
        scope = await _seed_authority(session)
        await _record_pending(session, scope, "artifacts/orphan-expired")
        repository = SqlArtifactContentAuthorityRepository(session)
        first = await repository.claim_orphan_gc(
            lease_owner="worker-old",
            lease_token="token-old",
            now=now,
            lease_expires_at=now + timedelta(seconds=1),
            limit=1,
        )
        await session.commit()
        assert len(first) == 1

    async with sessions() as session:
        repository = SqlArtifactContentAuthorityRepository(session)
        second = await repository.claim_orphan_gc(
            lease_owner="worker-new",
            lease_token="token-new",
            now=now + timedelta(seconds=2),
            lease_expires_at=now + timedelta(seconds=32),
            limit=1,
        )
        stale_completed = await repository.complete_orphan_gc_lease(
            "artifacts/orphan-expired",
            lease_owner="worker-old",
            lease_token="token-old",
            status="deleted",
            last_error_code=None,
            next_attempt_at=now + timedelta(seconds=2),
        )
        fresh_completed = await repository.complete_orphan_gc_lease(
            "artifacts/orphan-expired",
            lease_owner="worker-new",
            lease_token="token-new",
            status="missing",
            last_error_code=None,
            next_attempt_at=now + timedelta(seconds=2),
        )
        await session.commit()

        assert len(second) == 1
        assert stale_completed is False
        assert fresh_completed is True
        row = (
            await session.execute(
                select(ArtifactContentOrphanGcModel).where(
                    ArtifactContentOrphanGcModel.object_key == "artifacts/orphan-expired"
                )
            )
        ).scalar_one()
        assert row.status == "missing"
        assert row.attempts == 1
        assert row.lease_owner is None
        assert row.lease_token is None
        assert row.lease_expires_at is None


@pytest.mark.unit
async def test_worker_retries_after_restart_and_records_real_delete_history(test_engine) -> None:
    sessions = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    storage = RecordingGcStorage()
    orphan_key = "artifacts/orphan-restart"
    storage.objects.add(orphan_key)
    clock_value = datetime(2030, 7, 28, 11, tzinfo=UTC)

    async with sessions() as session:
        scope = await _seed_authority(session)
        await _record_pending(session, scope, orphan_key)

    storage.fail_delete = True
    first_worker = ArtifactContentOrphanGcWorker(
        session_factory=sessions,
        storage_service=storage,  # type: ignore[arg-type]
        owner_id="worker-before-restart",
        clock=lambda: clock_value,
        batch_size=1,
        lease_seconds=30,
    )
    assert await first_worker.run_once() == 1

    async with sessions() as session:
        failed_row = (
            await session.execute(
                select(ArtifactContentOrphanGcModel).where(
                    ArtifactContentOrphanGcModel.object_key == orphan_key
                )
            )
        ).scalar_one()
        assert failed_row.status == "pending"
        assert failed_row.attempts == 1
        assert failed_row.last_error_code == "storage_delete_failed"
        retry_at = failed_row.next_attempt_at

    storage.fail_delete = False
    clock_value = retry_at + timedelta(seconds=1)
    restarted_worker = ArtifactContentOrphanGcWorker(
        session_factory=sessions,
        storage_service=storage,  # type: ignore[arg-type]
        owner_id="worker-after-restart",
        clock=lambda: clock_value,
        batch_size=1,
        lease_seconds=30,
    )
    assert await restarted_worker.run_once() == 1

    async with sessions() as session:
        recovered_row = (
            await session.execute(
                select(ArtifactContentOrphanGcModel).where(
                    ArtifactContentOrphanGcModel.object_key == orphan_key
                )
            )
        ).scalar_one()
        assert recovered_row.status == "deleted"
        assert recovered_row.attempts == 2
        assert recovered_row.last_error_code is None
        assert orphan_key not in storage.objects
        assert storage.deletes == [orphan_key, orphan_key]


@pytest.mark.unit
async def test_worker_requires_two_missing_observations_and_reclaims_late_object(
    test_engine,
) -> None:
    sessions = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    storage = RecordingGcStorage()
    orphan_key = "artifacts/orphan-late-put"
    clock_value = datetime(2030, 7, 28, 11, 15, tzinfo=UTC)

    async with sessions() as session:
        scope = await _seed_authority(session)
        await _record_pending(session, scope, orphan_key)

    worker = ArtifactContentOrphanGcWorker(
        session_factory=sessions,
        storage_service=storage,  # type: ignore[arg-type]
        owner_id="worker-late-put",
        clock=lambda: clock_value,
        batch_size=1,
        lease_seconds=30,
    )
    assert await worker.run_once() == 1

    async with sessions() as session:
        first_observation = (
            await session.execute(
                select(ArtifactContentOrphanGcModel).where(
                    ArtifactContentOrphanGcModel.object_key == orphan_key
                )
            )
        ).scalar_one()
        assert first_observation.status == "pending"
        assert first_observation.attempts == 1
        assert first_observation.last_error_code == "storage_object_not_observed"
        retry_at = first_observation.next_attempt_at

    storage.objects.add(orphan_key)
    clock_value = retry_at + timedelta(seconds=1)
    assert await worker.run_once() == 1

    async with sessions() as session:
        recovered = (
            await session.execute(
                select(ArtifactContentOrphanGcModel).where(
                    ArtifactContentOrphanGcModel.object_key == orphan_key
                )
            )
        ).scalar_one()
        assert recovered.status == "deleted"
        assert recovered.attempts == 2
        assert recovered.last_error_code is None
        assert orphan_key not in storage.objects


@pytest.mark.unit
async def test_worker_blocks_on_fresh_locked_authority_before_delete(test_engine) -> None:
    sessions = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    storage = RecordingGcStorage()
    orphan_key = "artifacts/orphan-locked-authority"
    storage.objects.add(orphan_key)
    now = datetime(2030, 7, 28, 11, 30, tzinfo=UTC)

    async with sessions() as session:
        scope = await _seed_authority(session)
        await _record_pending(session, scope, orphan_key)

    original_get_authority = SqlArtifactContentAuthorityRepository.get_authority
    observed_locked_read = False

    async def require_locked_authority(
        repository,
        scope,
        *,
        for_update: bool = False,
    ):
        nonlocal observed_locked_read
        assert for_update is True
        observed_locked_read = True
        return await original_get_authority(
            repository,
            scope,
            for_update=for_update,
        )

    worker = ArtifactContentOrphanGcWorker(
        session_factory=sessions,
        storage_service=storage,  # type: ignore[arg-type]
        owner_id="worker-authority-lock",
        clock=lambda: now,
        batch_size=1,
        lease_seconds=30,
    )
    with patch.object(
        SqlArtifactContentAuthorityRepository,
        "get_authority",
        new=require_locked_authority,
    ):
        assert await worker.run_once() == 1

    assert observed_locked_read is True
    assert orphan_key in storage.deletes


@pytest.mark.unit
async def test_worker_retains_referenced_object_and_bounds_each_dispatch(test_engine) -> None:
    sessions = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    storage = RecordingGcStorage()
    now = datetime(2030, 7, 28, 12, tzinfo=UTC)
    orphan_keys = ["zz/artifacts/orphan-a", "zz/artifacts/orphan-b", "zz/artifacts/orphan-c"]
    storage.objects.update(orphan_keys)

    async with sessions() as session:
        scope = await _seed_authority(session)
        await _record_pending(session, scope, ACTIVE_OBJECT_KEY)
        for object_key in orphan_keys:
            await _record_pending(session, scope, object_key)

    worker = ArtifactContentOrphanGcWorker(
        session_factory=sessions,
        storage_service=storage,  # type: ignore[arg-type]
        owner_id="worker-bounded",
        clock=lambda: now,
        batch_size=2,
        lease_seconds=30,
    )
    assert await worker.run_once() == 2

    async with sessions() as session:
        rows = (
            (
                await session.execute(
                    select(ArtifactContentOrphanGcModel).order_by(
                        ArtifactContentOrphanGcModel.object_key
                    )
                )
            )
            .scalars()
            .all()
        )
        terminal = [row for row in rows if row.status != "pending"]
        assert len(terminal) == 2
        active_row = next(row for row in rows if row.object_key == ACTIVE_OBJECT_KEY)
        assert active_row.status == "retained"
        assert ACTIVE_OBJECT_KEY in storage.objects
        assert ACTIVE_OBJECT_KEY not in storage.deletes

    assert await worker.run_once() == 2
    assert await worker.run_once() == 0
    assert not (set(orphan_keys) & storage.objects)
