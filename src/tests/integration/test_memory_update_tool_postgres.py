"""Agent memory updates commit before graph work opens another SQL session."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
import sqlalchemy as sa

from src.infrastructure.adapters.secondary.persistence.models import Memory, MemoryChunk, Project
from src.infrastructure.agent.tools.memory_tools import (
    _execute_memory_update,
    _mark_created_memory_processing_status,
)
from src.infrastructure.graph.native_graph_adapter import NativeGraphAdapter
from src.tests.integration.test_knowledge_sync_postgres import (  # noqa: F401
    pg_sync as _pg_sync,
    pytestmark,
)

pg_sync = _pg_sync


async def seed_memory(sessions, scope):
    async with sessions() as db:
        db.add(
            Memory(
                id="memory",
                project_id=scope.project_id,
                author_id=scope.actor_id,
                title="Original",
                content="Before",
                version=1,
                processing_status="COMPLETED",
                meta={"tenant_id": scope.tenant_id, "category": "fact"},
            )
        )
        await db.commit()


def update_call(sessions, graph):
    return _execute_memory_update(
        memory_id="memory",
        title="Updated",
        content="After",
        tags=None,
        metadata=None,
        session_factory=sessions,
        graph_service=graph,
    )


@pytest.mark.parametrize("graph_status", ["COMPLETED", "PENDING"])
async def test_update_graph_can_lock_project_and_read_committed_content(pg_sync, graph_status):
    sessions, scope = pg_sync
    await seed_memory(sessions, scope)

    async def rebuild(**kwargs):
        async with sessions() as graph_db:
            # This would fail with LockNotAvailable under the old outer write
            # transaction, which awaited graph work before committing.
            await graph_db.execute(
                sa.select(Project)
                .where(Project.id == scope.project_id)
                .with_for_update(nowait=True)
            )
            memory = await graph_db.get(Memory, "memory")
            assert memory.content == kwargs["content"] == "After"
            assert memory.version == 2
            await graph_db.commit()

    queue = AsyncMock() if graph_status == "PENDING" else None
    graph = NativeGraphAdapter(
        neo4j_client=AsyncMock(),
        llm_client=MagicMock(),
        embedding_service=SimpleNamespace(),
        queue_port=queue,
    )
    graph._check_embedding_dimension = AsyncMock()
    graph.delete_episode_by_memory_id = AsyncMock()
    graph.process_episode = AsyncMock(side_effect=rebuild)
    graph.add_episode = AsyncMock(wraps=graph.add_episode)
    if queue is not None:
        queue.add_episode.side_effect = rebuild
    result = await asyncio.wait_for(update_call(sessions, graph), timeout=5)
    assert json.loads(result)["status"] == "updated"
    assert json.loads(result)["processing_status"] == graph_status
    graph.delete_episode_by_memory_id.assert_awaited_once_with("memory")
    graph.add_episode.assert_awaited_once()
    assert not await _mark_created_memory_processing_status(
        session_factory=sessions,
        memory_id="memory",
        project_id=scope.project_id,
        source_revision=1,
        processing_status="FAILED",
    )
    async with sessions() as db:
        memory = await db.get(Memory, "memory")
        assert memory.processing_status == graph_status
        assert memory.version == 2
        chunks = list(
            (
                await db.scalars(sa.select(MemoryChunk).where(MemoryChunk.source_id == "memory"))
            ).all()
        )
        assert [chunk.content for chunk in chunks] == ["After"]


@pytest.mark.parametrize("cancelled", [False, True])
async def test_graph_failure_or_cancellation_keeps_saved_content_and_marks_failed(
    pg_sync, cancelled
):
    sessions, scope = pg_sync
    await seed_memory(sessions, scope)
    graph_started = asyncio.Event()

    async def rebuild(episode):
        graph_started.set()
        if cancelled:
            await asyncio.Event().wait()
        raise RuntimeError("graph unavailable")

    graph = AsyncMock()
    graph.embedder = None
    graph.add_episode.side_effect = rebuild
    task = asyncio.create_task(update_call(sessions, graph))
    try:
        await asyncio.wait_for(graph_started.wait(), timeout=5)
        if cancelled:
            assert not task.done()
            # The slow graph keeps the operation alive, without holding SQL locks.
            async with sessions() as observer:
                await observer.execute(
                    sa.select(Project)
                    .where(Project.id == scope.project_id)
                    .with_for_update(nowait=True)
                )
                memory = await observer.get(Memory, "memory")
                assert memory.content == "After"
                await observer.commit()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, timeout=5)
        else:
            assert "error" in json.loads(await asyncio.wait_for(task, timeout=5))
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async with sessions() as db:
        memory = await db.get(Memory, "memory")
        assert memory.content == "After"
        assert memory.version == 2
        assert memory.processing_status == "FAILED"
