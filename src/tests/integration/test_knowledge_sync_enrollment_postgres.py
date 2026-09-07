"""Enrollment fences must cover all writers without inventing an actor."""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError, IntegrityError

from src.domain.model.knowledge_sync.contracts import (
    KnowledgeSyncResolution,
    MemorySyncContent,
    MemorySyncMutation,
)
from src.infrastructure.adapters.secondary.persistence.knowledge_sync_models import (
    KnowledgeSyncChangeModel as Change,
    KnowledgeSyncEnrollmentModel as Enrollment,
    KnowledgeSyncTombstoneModel as Tombstone,
)
from src.infrastructure.adapters.secondary.persistence.models import Memory
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

pg_sync = _pg_sync


async def legacy_create(session, scope, memory_id="legacy", title="Original"):
    memory = Memory(
        id=memory_id,
        project_id=scope.project_id,
        author_id=scope.actor_id,
        title=title,
        content="Source",
        version=1,
    )
    session.add(memory)
    await session.flush()
    return memory


def edit(revision, title="Edit"):
    return MemorySyncMutation(
        operation="update",
        memory_id="legacy",
        expected_revision=revision,
        content=MemorySyncContent(title=title, content="Source"),
    )


async def test_bootstrap_records_initiator_and_preserves_existing_version(pg_sync):
    sessions, scope = pg_sync
    async with sessions() as session:
        await legacy_create(session, scope)
        await session.commit()
        result = await SqlKnowledgeSyncEnrollment(session).bootstrap(scope)
        await session.commit()
        assert result["enabled"] and result["bootstrap_count"] == 1 and result["next_cursor"] == 1
        changes = (await session.scalars(sa.select(Change))).all()
        assert len(changes) == 1 and changes[0].source_kind == "bootstrap"
        assert changes[0].actor_id == scope.actor_id
        assert changes[0].snapshot["revision"] == 1
        assert (await SqlKnowledgeSyncEnrollment(session).bootstrap(scope))["replayed"]
        outcome = await SqlKnowledgeSyncRepository(session).mutate(scope, str(uuid4()), edit(1))
        await session.commit()
        assert outcome.to_dict()["receipt"]["sequence"] == 2


async def test_unenrolled_writes_unchanged_and_enrolled_direct_content_writes_rejected(pg_sync):
    sessions, scope = pg_sync
    async with sessions() as session:
        await legacy_create(session, scope)
        await session.commit()
        await session.execute(
            sa.update(Memory).where(Memory.id == "legacy").values(content="Legacy edit")
        )
        await session.commit()
        assert len((await session.scalars(sa.select(Change))).all()) == 0
        await SqlKnowledgeSyncEnrollment(session).bootstrap(scope)
        await session.commit()
        with pytest.raises(IntegrityError, match="write_intent_required"):
            await session.execute(
                sa.update(Memory).where(Memory.id == "legacy").values(content="Unjournaled")
            )
        await session.rollback()
        assert (await session.get(Memory, "legacy")).content == "Legacy edit"
        await session.execute(
            sa.update(Memory).where(Memory.id == "legacy").values(processing_status="COMPLETED")
        )
        await session.commit()
        assert len((await session.scalars(sa.select(Change))).all()) == 1


async def test_writer_before_bootstrap_is_included_after_commit(pg_sync):
    sessions, scope = pg_sync
    async with sessions() as writer, sessions() as bootstrapper:
        await legacy_create(writer, scope, title="Concurrent writer")
        pending = asyncio.create_task(SqlKnowledgeSyncEnrollment(bootstrapper).bootstrap(scope))
        await asyncio.sleep(0.1)
        assert not pending.done()
        await writer.commit()
        result = await asyncio.wait_for(pending, 5)
        await bootstrapper.commit()
        assert result["bootstrap_count"] == 1
        change = await bootstrapper.scalar(sa.select(Change))
        assert change.snapshot["content"]["title"] == "Concurrent writer"


async def test_bootstrap_before_writer_fails_unjournaled_waiter_after_activation(pg_sync):
    sessions, scope = pg_sync
    async with sessions() as seed:
        await legacy_create(seed, scope)
        await seed.commit()
    async with sessions() as bootstrapper, sessions() as writer:
        await SqlKnowledgeSyncEnrollment(bootstrapper).bootstrap(scope)
        pending = asyncio.create_task(
            writer.execute(sa.update(Memory).where(Memory.id == "legacy").values(content="Late"))
        )
        await asyncio.sleep(0.1)
        assert not pending.done()
        await bootstrapper.commit()
        with pytest.raises(IntegrityError, match="write_intent_required"):
            await asyncio.wait_for(pending, 5)
        await writer.rollback()
        assert (await writer.get(Memory, "legacy")).content == "Source"
        assert (await SqlKnowledgeSyncRepository(writer).changes(scope, 0, 100)).next_cursor == 1


async def test_repeatable_read_old_disabled_snapshot_cannot_bypass_fence(pg_sync):
    sessions, scope = pg_sync
    async with sessions() as seed:
        await legacy_create(seed, scope)
        await seed.commit()
    async with sessions() as reader, sessions() as bootstrapper:
        await reader.execute(sa.text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"))
        assert not (await reader.get(Enrollment, scope.project_id)).enabled
        await SqlKnowledgeSyncEnrollment(bootstrapper).bootstrap(scope)
        await bootstrapper.commit()
        with pytest.raises(DBAPIError, match="concurrent update"):
            await reader.execute(
                sa.update(Memory).where(Memory.id == "legacy").values(content="Stale snapshot")
            )
        await reader.rollback()


async def test_structural_intent_without_same_transaction_journal_rolls_back(pg_sync):
    sessions, scope = pg_sync
    async with sessions() as session:
        await legacy_create(session, scope)
        await session.commit()
        await SqlKnowledgeSyncEnrollment(session).bootstrap(scope)
        await session.commit()
        repo = SqlKnowledgeSyncRepository(session)
        current = await repo._current(scope, "legacy")
        await repo._apply(
            scope,
            "legacy",
            current,
            MemorySyncContent(title="No journal", content="Source"),
            deleted=False,
        )
        with pytest.raises(IntegrityError, match="journal_required"):
            await session.commit()
        await session.rollback()
        assert (await session.get(Memory, "legacy")).version == 1
        assert (await repo.changes(scope, 0, 100)).next_cursor == 1


async def test_one_journal_cannot_authorize_two_content_revisions(pg_sync):
    sessions, scope = pg_sync
    async with sessions() as session:
        await legacy_create(session, scope)
        await session.commit()
        await SqlKnowledgeSyncEnrollment(session).bootstrap(scope)
        await session.commit()
        repo = SqlKnowledgeSyncRepository(session)
        await repo.mutate(scope, str(uuid4()), edit(1, "Journaled"))
        current = await repo._current(scope, "legacy")
        await repo._apply(
            scope,
            "legacy",
            current,
            MemorySyncContent(title="Unjournaled", content="Source"),
            deleted=False,
        )
        with pytest.raises(IntegrityError, match="journal_terminal_mismatch|journal_required"):
            await session.commit()
        await session.rollback()
        assert (await session.get(Memory, "legacy")).version == 1
        assert (await repo.changes(scope, 0, 100)).next_cursor == 1


async def test_enrolled_delete_and_explicit_restore_in_one_transaction(pg_sync):
    sessions, scope = pg_sync
    async with sessions() as session:
        await legacy_create(session, scope)
        await session.commit()
        await SqlKnowledgeSyncEnrollment(session).bootstrap(scope)
        await session.commit()
        repo = SqlKnowledgeSyncRepository(session)
        await repo.mutate(
            scope,
            str(uuid4()),
            MemorySyncMutation(operation="delete", memory_id="legacy", expected_revision=1),
        )
        conflict = await repo.mutate(scope, str(uuid4()), edit(1, "Restore"))
        await repo.resolve(
            scope,
            str(uuid4()),
            KnowledgeSyncResolution(
                conflict_id=conflict.to_dict()["receipt"]["conflict_id"],
                expected_current_revision=2,
                decision="use_proposed",
            ),
        )
        await session.commit()
        assert (await session.get(Memory, "legacy")).version == 3
        assert await session.get(Tombstone, "legacy") is None
        assert (await repo.changes(scope, 0, 100)).next_cursor == 3


async def test_bootstrap_actor_is_initiator_not_original_content_author(pg_sync):
    from src.infrastructure.adapters.secondary.persistence.models import User

    sessions, scope = pg_sync
    async with sessions() as session:
        session.add(
            User(id="original-author", email="original@example.test", hashed_password="unused")
        )
        await session.flush()
        memory = await legacy_create(session, scope)
        memory.author_id = "original-author"
        await session.commit()
        await SqlKnowledgeSyncEnrollment(session).bootstrap(scope)
        await session.commit()
        change = await session.scalar(sa.select(Change))
        assert change.source_kind == "bootstrap" and change.actor_id == scope.actor_id
        assert change.snapshot["author_id"] == "original-author"
        assert (
            await session.get(Enrollment, scope.project_id)
        ).bootstrap_actor_id == scope.actor_id


async def test_bootstrap_rollback_leaves_no_cursor_or_partial_snapshot(pg_sync):
    from src.infrastructure.adapters.secondary.persistence.knowledge_sync_models import (
        KnowledgeSyncCursorModel,
    )

    sessions, scope = pg_sync
    async with sessions() as session:
        await legacy_create(session, scope)
        await session.commit()
        await SqlKnowledgeSyncEnrollment(session).bootstrap(scope)
        await session.rollback()
        assert not (await session.get(Enrollment, scope.project_id)).enabled
        assert (
            await session.get(KnowledgeSyncCursorModel, (scope.tenant_id, scope.project_id)) is None
        )
        assert not (await session.scalars(sa.select(Change))).all()
        assert await session.get(Memory, "legacy") is not None


async def test_journal_requires_exact_portable_snapshot_not_just_matching_revision(pg_sync):
    from dataclasses import replace

    sessions, scope = pg_sync
    async with sessions() as session:
        await legacy_create(session, scope)
        await session.commit()
        await SqlKnowledgeSyncEnrollment(session).bootstrap(scope)
        await session.commit()
        repo = SqlKnowledgeSyncRepository(session)
        current = await repo._current(scope, "legacy")
        actual = await repo._apply(
            scope,
            "legacy",
            current,
            MemorySyncContent(
                title="Actual", content="Source", metadata_json='{"origin":"actual"}'
            ),
            deleted=False,
        )
        fabricated = replace(
            actual,
            content=MemorySyncContent(
                title="Actual", content="Source", metadata_json='{"origin":"different"}'
            ),
        )
        await repo._accepted(scope, str(uuid4()), "structural-test", fabricated)
        with pytest.raises(IntegrityError, match="journal_required"):
            await session.commit()
        await session.rollback()
        assert (await session.get(Memory, "legacy")).version == 1
        assert (await repo.changes(scope, 0, 100)).next_cursor == 1


async def test_preexisting_journal_cannot_authorize_later_transaction(pg_sync):
    from dataclasses import replace

    sessions, scope = pg_sync
    async with sessions() as session:
        await legacy_create(session, scope)
        await session.commit()
        await SqlKnowledgeSyncEnrollment(session).bootstrap(scope)
        await session.commit()
        repo = SqlKnowledgeSyncRepository(session)
        current = await repo._current(scope, "legacy")
        content = MemorySyncContent(title="Later", content="Source")
        anticipated = replace(current, revision=2, content=content)
        session.add(
            Change(
                tenant_id=scope.tenant_id,
                project_id=scope.project_id,
                sequence=2,
                actor_id=scope.actor_id,
                change_id=str(uuid4()),
                memory_id="legacy",
                revision=2,
                snapshot=anticipated.to_dict(),
                source_kind="mutation",
            )
        )
        await session.commit()
        await repo._apply(scope, "legacy", current, content, deleted=False)
        with pytest.raises(IntegrityError, match="journal_required"):
            await session.commit()
        await session.rollback()
        assert (await session.get(Memory, "legacy")).version == 1


async def test_project_same_tenant_update_is_unchanged_and_enrolled_scope_move_rejected(pg_sync):
    from src.infrastructure.adapters.secondary.persistence.models import Project, Tenant

    sessions, scope = pg_sync
    async with sessions() as session:
        await session.execute(
            sa.update(Project)
            .where(Project.id == scope.project_id)
            .values(tenant_id=scope.tenant_id)
        )
        await session.commit()
        await SqlKnowledgeSyncEnrollment(session).bootstrap(scope)
        await session.commit()
        session.add(Tenant(id="other-tenant", name="Other", slug="other", owner_id=scope.actor_id))
        await session.commit()
        with pytest.raises(IntegrityError, match="scope_immutable"):
            await session.execute(
                sa.update(Project)
                .where(Project.id == scope.project_id)
                .values(tenant_id="other-tenant")
            )
        await session.rollback()
        assert (await session.get(Project, scope.project_id)).tenant_id == scope.tenant_id


async def test_other_unenrolled_project_remains_writable_but_cannot_steal_reserved_id(pg_sync):
    from src.domain.model.knowledge_sync.contracts import KnowledgeSyncScope
    from src.infrastructure.adapters.secondary.persistence.models import Project

    sessions, scope = pg_sync
    async with sessions() as session:
        await legacy_create(session, scope)
        await session.commit()
        await SqlKnowledgeSyncEnrollment(session).bootstrap(scope)
        await session.commit()
        session.add(
            Project(
                id="unenrolled",
                name="Unenrolled",
                tenant_id=scope.tenant_id,
                owner_id=scope.actor_id,
            )
        )
        await session.commit()
        other = KnowledgeSyncScope(
            tenant_id=scope.tenant_id, project_id="unenrolled", actor_id=scope.actor_id
        )
        await legacy_create(session, other, memory_id="other-memory")
        await session.commit()
        assert not (await session.get(Enrollment, "unenrolled")).enabled
        await SqlKnowledgeSyncRepository(session).mutate(
            scope,
            str(uuid4()),
            MemorySyncMutation(operation="delete", memory_id="legacy", expected_revision=1),
        )
        await session.commit()
        with pytest.raises(IntegrityError, match="id_collision"):
            await legacy_create(session, other, memory_id="legacy")
        await session.rollback()
        assert await session.get(Memory, "other-memory") is not None
        assert await session.get(Memory, "legacy") is None
        assert await session.get(Tombstone, "legacy") is not None
        with pytest.raises(IntegrityError, match="id_collision"):
            await session.execute(
                sa.update(Memory).where(Memory.id == "other-memory").values(id="legacy")
            )
        await session.rollback()
        assert await session.get(Memory, "other-memory") is not None
        assert await session.get(Memory, "legacy") is None


@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("parent", ["project", "tenant"])
@pytest.mark.parametrize("cascade", [False, True])
async def test_parent_cascade_deletion_preserves_existing_behavior(
    pg_sync, enabled, parent, cascade
):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    from src.infrastructure.adapters.secondary.persistence.models import (
        Project,
        Tenant,
        UserProject,
        UserTenant,
    )

    sessions, scope = pg_sync
    async with sessions() as session:
        if cascade:
            # Exercise deployed CASCADE variants without changing application FK policy.
            def use_cascades(sync_session):
                operations = Operations(MigrationContext.configure(sync_session.connection()))
                for table, column, target in (
                    ("memories", "project_id", "projects"),
                    ("projects", "tenant_id", "tenants"),
                ):
                    name = f"{table}_{column}_fkey"
                    operations.drop_constraint(name, table, type_="foreignkey")
                    operations.create_foreign_key(
                        name, table, target, [column], ["id"], ondelete="CASCADE"
                    )

            await session.run_sync(use_cascades)
        await legacy_create(session, scope)
        await session.commit()
        if enabled:
            await SqlKnowledgeSyncEnrollment(session).bootstrap(scope)
            await session.commit()
        model, identity = (
            (Project, scope.project_id) if parent == "project" else (Tenant, scope.tenant_id)
        )
        await session.execute(sa.delete(UserProject))
        await session.execute(sa.delete(UserTenant))
        if not cascade:
            with pytest.raises(IntegrityError, match="violates foreign key constraint"):
                await session.execute(sa.delete(model).where(model.id == identity))
            await session.rollback()
            assert await session.get(Memory, "legacy") is not None
            return
        await session.execute(sa.delete(model).where(model.id == identity))
        await session.commit()
        assert await session.get(Memory, "legacy") is None
        assert await session.get(Enrollment, scope.project_id) is None
        assert (await session.scalars(sa.select(Change))).all() == []


async def test_missing_fence_with_existing_parent_still_rejects_memory_delete(pg_sync):
    sessions, scope = pg_sync
    async with sessions() as session:
        await legacy_create(session, scope)
        await session.commit()
        await session.execute(
            sa.delete(Enrollment).where(Enrollment.project_id == scope.project_id)
        )
        with pytest.raises(IntegrityError, match="fence_missing"):
            await session.execute(sa.delete(Memory).where(Memory.id == "legacy"))
        await session.rollback()
        assert await session.get(Memory, "legacy") is not None
        assert await session.get(Enrollment, scope.project_id) is not None


async def test_delete_requires_terminal_tombstone_in_same_atomic_commit(pg_sync):
    sessions, scope = pg_sync
    async with sessions() as session:
        await legacy_create(session, scope)
        await session.commit()
        await SqlKnowledgeSyncEnrollment(session).bootstrap(scope)
        await session.commit()
        repo = SqlKnowledgeSyncRepository(session)
        await repo.mutate(
            scope,
            str(uuid4()),
            MemorySyncMutation(operation="delete", memory_id="legacy", expected_revision=1),
        )
        await session.execute(sa.delete(Tombstone).where(Tombstone.memory_id == "legacy"))
        with pytest.raises(IntegrityError, match="tombstone_required"):
            await session.commit()
        await session.rollback()
        assert (await session.get(Memory, "legacy")).version == 1
        assert (await repo.changes(scope, 0, 100)).next_cursor == 1
