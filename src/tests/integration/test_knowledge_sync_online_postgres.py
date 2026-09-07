"""Real PostgreSQL online CAS, enrollment fencing and atomic journal checks."""

import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import select

from src.domain.model.knowledge_sync.contracts import KnowledgeSyncError
from src.infrastructure.adapters.secondary.persistence.knowledge_sync_models import (
    KnowledgeSyncChangeModel as Change,
    KnowledgeSyncConflictModel as Conflict,
    KnowledgeSyncEnrollmentModel as Enrollment,
    KnowledgeSyncReceiptModel as Receipt,
    KnowledgeSyncTombstoneModel as Tombstone,
)
from src.infrastructure.adapters.secondary.persistence.models import Memory, Project, UserProject
from src.infrastructure.adapters.secondary.persistence.sql_knowledge_sync_enrollment import (
    SqlKnowledgeSyncEnrollment,
)
from src.infrastructure.adapters.secondary.persistence.sql_knowledge_sync_repository import (
    SqlKnowledgeSyncRepository,
)
from src.tests.integration.test_knowledge_sync_postgres import (  # noqa: F401
    pg_sync as _pg_sync,
    pytestmark,
)
from src.tests.integration.test_knowledge_sync_repository import mutation

pg_sync = _pg_sync


@pytest.mark.parametrize("enrolled", [False, True])
async def test_online_journal_and_tombstone_commit_without_changing_enrollment(pg_sync, enrolled):
    sessions, scope = pg_sync
    async with sessions() as session:
        if enrolled:
            await SqlKnowledgeSyncEnrollment(session).bootstrap(scope)
            await session.commit()
        repo = SqlKnowledgeSyncRepository(session)
        for request in (mutation(), mutation("update", 1, "Updated"), mutation("delete", 2)):
            await repo.mutate_online(scope, str(uuid4()), request)
            await session.commit()
        assert (await session.get(Enrollment, scope.project_id)).enabled is enrolled
        assert await session.get(Memory, "sync-memory-1") is None
        assert (await session.get(Tombstone, "sync-memory-1")).revision == 3
        changes = (await session.scalars(select(Change).order_by(Change.sequence))).all()
        assert [(row.sequence, row.revision, row.actor_id) for row in changes] == [
            (1, 1, scope.actor_id),
            (2, 2, scope.actor_id),
            (3, 3, scope.actor_id),
        ]
        assert [row.snapshot["deleted"] for row in changes] == [False, False, True]
        assert len((await session.scalars(select(Receipt))).all()) == 3
        assert (await session.scalars(select(Conflict))).all() == []


async def test_two_online_writers_with_same_revision_have_one_winner_and_no_pending_conflict(
    pg_sync,
):
    sessions, scope = pg_sync
    async with sessions() as seed:
        await SqlKnowledgeSyncEnrollment(seed).bootstrap(scope)
        await SqlKnowledgeSyncRepository(seed).mutate_online(scope, str(uuid4()), mutation())
        await seed.commit()
    async with sessions() as first, sessions() as second, sessions() as reader:
        await SqlKnowledgeSyncRepository(first).mutate_online(
            scope, str(uuid4()), mutation("update", 1, "Winner")
        )
        pending = asyncio.create_task(
            SqlKnowledgeSyncRepository(second).mutate_online(
                scope, str(uuid4()), mutation("update", 1, "Loser")
            )
        )
        await asyncio.sleep(0.1)
        assert not pending.done()
        assert (await SqlKnowledgeSyncRepository(reader).changes(scope, 0, 100)).next_cursor == 1
        await first.commit()
        with pytest.raises(KnowledgeSyncError, match="write_conflict"):
            await asyncio.wait_for(pending, 5)
        await second.commit()
        assert (await second.scalars(select(Conflict))).all() == []
        assert len((await second.scalars(select(Receipt))).all()) == 2
        assert (await second.get(Memory, "sync-memory-1")).title == "Winner"
        fresh = await SqlKnowledgeSyncRepository(second).mutate_online(
            scope, str(uuid4()), mutation("update", 2, "Fresh")
        )
        await second.commit()
        assert fresh.to_dict()["receipt"]["sequence"] == 3


@pytest.mark.parametrize("operation", ["create", "update", "delete"])
async def test_outer_rollback_removes_online_memory_journal_and_receipt_together(
    pg_sync, operation
):
    sessions, scope = pg_sync
    async with sessions() as session:
        repo = SqlKnowledgeSyncRepository(session)
        await SqlKnowledgeSyncEnrollment(session).bootstrap(scope)
        if operation != "create":
            await repo.mutate_online(scope, str(uuid4()), mutation())
        await session.commit()
        await repo.mutate_online(
            scope,
            str(uuid4()),
            mutation(operation, 0 if operation == "create" else 1, "Rolled back"),
        )
        await session.rollback()
        memory = await session.get(Memory, "sync-memory-1")
        if operation == "create":
            assert memory is None
        else:
            assert (memory.version, memory.title) == (1, "Original")
        expected_count = 0 if operation == "create" else 1
        assert (await repo.changes(scope, 0, 100)).next_cursor == expected_count
        assert len((await session.scalars(select(Receipt))).all()) == expected_count
        assert await session.get(Tombstone, "sync-memory-1") is None


@pytest.mark.parametrize("online_first", [False, True])
async def test_online_and_bootstrap_order_preserves_exactly_one_current_journal(
    pg_sync, online_first
):
    sessions, scope = pg_sync
    async with sessions() as writer, sessions() as bootstrapper:
        enrollment = SqlKnowledgeSyncEnrollment(bootstrapper)
        repo = SqlKnowledgeSyncRepository(writer)
        if online_first:
            await repo.mutate_online(scope, str(uuid4()), mutation())
            pending = asyncio.create_task(enrollment.bootstrap(scope))
            await asyncio.sleep(0.1)
            assert not pending.done()
            await writer.commit()
            await asyncio.wait_for(pending, 5)
            await bootstrapper.commit()
        else:
            await enrollment.bootstrap(scope)
            pending = asyncio.create_task(repo.mutate_online(scope, str(uuid4()), mutation()))
            await asyncio.sleep(0.1)
            assert not pending.done()
            await bootstrapper.commit()
            await asyncio.wait_for(pending, 5)
            await writer.commit()
    async with sessions() as reader:
        assert (await reader.get(Enrollment, scope.project_id)).enabled
        assert (await reader.get(Memory, "sync-memory-1")).version == 1
        assert len((await reader.scalars(select(Change))).all()) == 1
        assert len((await reader.scalars(select(Receipt))).all()) == 1


async def test_online_rejects_cross_project_live_and_tombstone_identity_collisions(pg_sync):
    sessions, scope = pg_sync
    async with sessions() as session:
        repo = SqlKnowledgeSyncRepository(session)
        await SqlKnowledgeSyncEnrollment(session).bootstrap(scope)
        await repo.mutate_online(scope, str(uuid4()), mutation())
        session.add(
            Project(id="other", name="Other", tenant_id=scope.tenant_id, owner_id=scope.actor_id)
        )
        await session.flush()
        session.add(
            UserProject(id="other-member", project_id="other", user_id=scope.actor_id, role="owner")
        )
        await session.commit()
        other = await repo.resolve_scope(scope.actor_id, "other")
        for deleted in (False, True):
            if deleted:
                await repo.mutate_online(scope, str(uuid4()), mutation("delete", 1))
                await session.commit()
            with pytest.raises(KnowledgeSyncError, match="id_collision"):
                await repo.mutate_online(other, str(uuid4()), mutation())
            await session.commit()
            assert (await repo.changes(other, 0, 100)).next_cursor == 0
