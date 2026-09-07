"""Late processing results cannot overwrite a newer memory or resurrect a delete."""

import asyncio

import pytest
import sqlalchemy as sa

from src.domain.model.memory.processing import MemoryProcessingSource
from src.infrastructure.adapters.secondary.persistence.memory_processing import (
    update_memory_processing_status,
)
from src.infrastructure.adapters.secondary.persistence.models import Memory
from src.tests.integration.test_knowledge_sync_postgres import (  # noqa: F401
    pg_sync as _pg_sync,
    pytestmark,
)

pg_sync = _pg_sync


async def seed(sessions, scope):
    async with sessions() as session:
        session.add(
            Memory(
                id="processing-memory",
                project_id=scope.project_id,
                author_id=scope.actor_id,
                title="Original",
                content="Original content",
                version=1,
                processing_status="PENDING",
                task_id="task-original",
            )
        )
        await session.commit()
    return MemoryProcessingSource(
        memory_id="processing-memory",
        project_id=scope.project_id,
        revision=1,
        task_id="task-original",
    )


@pytest.mark.parametrize("enrolled", [False, True])
async def test_processing_update_changes_only_derived_fields(pg_sync, enrolled):
    from src.infrastructure.adapters.secondary.persistence.sql_knowledge_sync_enrollment import (
        SqlKnowledgeSyncEnrollment,
    )

    sessions, scope = pg_sync
    source = await seed(sessions, scope)
    async with sessions() as session:
        if enrolled:
            await SqlKnowledgeSyncEnrollment(session).bootstrap(scope)
            await session.commit()
        assert await update_memory_processing_status(session, source, "COMPLETED")
        await session.commit()
        memory = await session.get(Memory, source.memory_id)
        assert memory.processing_status == "COMPLETED"
        assert (memory.content, memory.version, memory.task_id) == (
            "Original content",
            1,
            "task-original",
        )


@pytest.mark.parametrize("operation", ["edit", "delete", "replace_task"])
async def test_pending_processing_update_rechecks_source_after_concurrent_commit(
    pg_sync, operation
):
    sessions, scope = pg_sync
    source = await seed(sessions, scope)
    async with sessions() as writer, sessions() as worker:
        if operation == "delete":
            await writer.execute(sa.delete(Memory).where(Memory.id == source.memory_id))
        else:
            values = (
                {"content": "New content", "version": 2, "processing_status": "PENDING"}
                if operation == "edit"
                else {"task_id": "task-new", "processing_status": "COMPLETED"}
            )
            await writer.execute(
                sa.update(Memory).where(Memory.id == source.memory_id).values(**values)
            )
        pending = asyncio.create_task(update_memory_processing_status(worker, source, "FAILED"))
        await asyncio.sleep(0.1)
        assert not pending.done()
        await writer.commit()
        assert not await asyncio.wait_for(pending, 5)
        await worker.commit()
        memory = await worker.get(Memory, source.memory_id)
        if operation == "delete":
            assert memory is None
        elif operation == "edit":
            assert (memory.content, memory.version, memory.processing_status) == (
                "New content",
                2,
                "PENDING",
            )
        else:
            assert (memory.task_id, memory.processing_status) == ("task-new", "COMPLETED")


async def test_processing_source_wrong_project_is_not_applied(pg_sync):
    sessions, scope = pg_sync
    source = await seed(sessions, scope)
    async with sessions() as session:
        assert not await update_memory_processing_status(
            session,
            MemoryProcessingSource(
                memory_id=source.memory_id, project_id="other", revision=1, task_id=source.task_id
            ),
            "FAILED",
        )
        await session.commit()
        assert (await session.get(Memory, source.memory_id)).processing_status == "PENDING"
