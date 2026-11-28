"""Agent memory updates commit before graph work opens another SQL session."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import sqlalchemy as sa

from src.application.services.memory_update_jobs import execute_memory_update_job
from src.application.services.memory_update_runtime import index_with_session
from src.infrastructure.adapters.secondary.persistence.models import Memory, MemoryChunk, Project
from src.infrastructure.agent.tools.memory_tools import (
    _execute_memory_update,
    _mark_created_memory_processing_status,
)
from src.infrastructure.graph.native_graph_adapter import NativeGraphAdapter
from src.infrastructure.memory import chunk_sync
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


async def test_update_returns_before_graph_work_and_worker_indexes_committed_content(pg_sync):
    sessions, scope = pg_sync
    await seed_memory(sessions, scope)
    graph = NativeGraphAdapter(
        neo4j_client=AsyncMock(),
        llm_client=MagicMock(),
        embedding_service=SimpleNamespace(),
        queue_port=AsyncMock(),
    )
    graph.process_episode = AsyncMock()
    result = json.loads(await asyncio.wait_for(update_call(sessions, graph), timeout=5))
    assert result["status"] == "updated"
    assert result["saved"] is True
    assert result["processing_status"] == "PENDING"
    assert result["searchable"] is False
    graph.process_episode.assert_not_awaited()

    async def extract(payload):
        async with sessions() as graph_db:
            await graph_db.execute(
                sa.select(Project)
                .where(Project.id == scope.project_id)
                .with_for_update(nowait=True)
            )
            memory = await graph_db.get(Memory, "memory")
            assert memory.content == payload["content"] == "After"
            assert memory.version == 2
            await graph_db.commit()

    async def index(_payload):
        return None

    outcome = await execute_memory_update_job(
        sessions, result["task_id"], extract=extract, index=index
    )
    assert outcome == "completed"
    assert not await _mark_created_memory_processing_status(
        session_factory=sessions,
        memory_id="memory",
        project_id=scope.project_id,
        source_revision=1,
        processing_status="FAILED",
    )
    async with sessions() as db:
        memory = await db.get(Memory, "memory")
        assert memory.processing_status == "COMPLETED"
        assert memory.version == 2


async def test_saved_update_stays_pending_until_the_worker_records_failure(pg_sync):
    sessions, scope = pg_sync
    await seed_memory(sessions, scope)
    graph = AsyncMock()
    graph.embedder = None
    saved = json.loads(await asyncio.wait_for(update_call(sessions, graph), timeout=5))
    assert saved["saved"] is True
    assert saved["processing_status"] == "PENDING"
    graph.add_episode.assert_not_awaited()

    async def extract(_payload):
        raise RuntimeError("graph unavailable")

    outcome = await execute_memory_update_job(
        sessions,
        saved["task_id"],
        extract=extract,
        index=AsyncMock(),
    )
    assert outcome == "failed"
    async with sessions() as db:
        memory = await db.get(Memory, "memory")
        assert memory.content == "After"
        assert memory.version == 2
        assert memory.processing_status == "PENDING"


async def test_chunks_of_superseded_revision_are_rolled_back(pg_sync, monkeypatch):
    sessions, scope = pg_sync
    await seed_memory(sessions, scope)
    payload = {
        "memory_id": "memory",
        "project_id": scope.project_id,
        "tenant_id": scope.tenant_id,
        "source_revision": 1,
        "content": "Before",
    }
    staged, resume = asyncio.Event(), asyncio.Event()
    upsert = chunk_sync.upsert_memory_chunks

    async def wait_before_commit(*args, **kwargs):
        result = await upsert(*args, **kwargs)
        staged.set()
        await resume.wait()
        return result

    monkeypatch.setattr(chunk_sync, "upsert_memory_chunks", wait_before_commit)
    async with asyncio.timeout(10), asyncio.TaskGroup() as workers:
        workers.create_task(index_with_session(payload, sessions, None))
        await staged.wait()
        async with sessions.begin() as db:
            await db.execute(
                sa.update(Memory)
                .where(Memory.id == "memory", Memory.project_id == scope.project_id)
                .values(version=2, content="After")
            )
        resume.set()
    async with sessions() as db:
        assert list(await db.scalars(sa.select(MemoryChunk.content))) == []
        assert (await db.get(Memory, "memory")).content == "After"
