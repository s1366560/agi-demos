"""Real PostgreSQL admission must not invert the derived Memory writer lock order."""

from __future__ import annotations

import asyncio
import os
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.domain.model.knowledge_sync.contracts import (
    KnowledgeSyncScope,
    MemorySyncContent,
    MemorySyncMutation,
)
from src.domain.model.memory.processing import MemoryProcessingSource
from src.infrastructure.adapters.secondary.persistence.memory_processing import (
    update_memory_processing_status,
)
from src.infrastructure.adapters.secondary.persistence.models import Memory
from src.infrastructure.adapters.secondary.persistence.sql_cloud_knowledge_sync_repository import (
    SqlCloudKnowledgeSyncRepository,
)
from src.tests.integration.test_knowledge_sync_postgres import pg_sync as _pg_sync

pg_sync = _pg_sync
pytestmark = pytest.mark.skipif(
    os.getenv("KNOWLEDGE_SYNC_POSTGRES_TESTS") != "1",
    reason="Requires the existing dedicated PostgreSQL QA database opt-in",
)


async def test_cloud_sync_and_derived_processing_do_not_deadlock(
    pg_sync: tuple[async_sessionmaker[AsyncSession], KnowledgeSyncScope],
) -> None:
    sessions, scope = pg_sync
    memory_id = "cloud-sync-lock-review"
    source = MemoryProcessingSource(memory_id=memory_id, project_id=scope.project_id, revision=1)
    async with sessions() as db:
        db.add(
            Memory(
                id=memory_id,
                project_id=scope.project_id,
                author_id=scope.actor_id,
                title="Original",
                content="Body",
            )
        )
        await db.commit()
        await SqlCloudKnowledgeSyncRepository(db, scope, lambda: None).bootstrap()
        await db.commit()

    async with sessions() as cloud, sessions() as derived, sessions() as observer:
        cloud_pid = await cloud.scalar(text("SELECT pg_backend_pid()"))
        derived_pid = await derived.scalar(text("SELECT pg_backend_pid()"))
        repository = SqlCloudKnowledgeSyncRepository(cloud, scope, lambda: None)
        assert (await repository.status()).enabled

        async def process() -> bool:
            try:
                applied = await update_memory_processing_status(derived, source, "COMPLETED")
                await derived.commit()
                return applied
            except BaseException:
                await derived.rollback()
                raise

        async def synchronize() -> None:
            try:
                await repository.mutate(
                    scope,
                    str(uuid4()),
                    MemorySyncMutation(
                        operation="update",
                        memory_id=memory_id,
                        expected_revision=1,
                        content=MemorySyncContent(title="Cloud update", content="New body"),
                    ),
                )
                await cloud.commit()
            except BaseException:
                await cloud.rollback()
                raise

        writer = asyncio.create_task(process())
        sync = None
        try:
            # On the fixed path the real derived UPDATE can finish immediately.
            # On the old path it holds Memory and waits on cloud's enrollment
            # lock; starting sync now deterministically closes the lock cycle.
            async with asyncio.timeout(10):
                while not writer.done():
                    blocking = await observer.scalar(
                        text("SELECT pg_blocking_pids(:pid)"), {"pid": derived_pid}
                    )
                    if cloud_pid in blocking:
                        break
                    await asyncio.sleep(0.01)
            sync = asyncio.create_task(synchronize())
            results = await asyncio.wait_for(
                asyncio.gather(writer, sync, return_exceptions=True), timeout=10
            )
            assert results == [True, None], results
        finally:
            for task in (writer, sync):
                if task is not None and not task.done():
                    task.cancel()
            await asyncio.gather(
                *(task for task in (writer, sync) if task is not None), return_exceptions=True
            )

    async with sessions() as db:
        memory = await db.scalar(select(Memory).where(Memory.id == memory_id))
        assert memory is not None
        assert memory.version == 2
        assert memory.content == "New body"
        # The newer portable revision correctly invalidates derived processing.
        assert memory.processing_status == "PENDING"
