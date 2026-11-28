"""Durable memory-update jobs: save first, index later, never fake completion."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.application.services.memory_update_dispatch import (
    MemoryUpdateDispatcher,
    install_memory_update_dispatcher,
)
from src.application.services.memory_update_jobs import (
    MAX_ATTEMPTS,
    execute_memory_update_job,
    resume_memory_update_jobs,
    stage_memory_update_job,
)
from src.infrastructure.adapters.secondary.persistence.knowledge_sync_models import (
    KnowledgeSyncEnrollmentModel,
)
from src.infrastructure.adapters.secondary.persistence.models import (
    Base,
    Memory,
    Project,
    TaskLog,
    Tenant,
    User,
)
from src.infrastructure.agent.tools.memory_tools import (
    MemoryToolRuntime,
    _exclude_unsearchable_memory_hits,
    _execute_memory_update,
    _memory_tool_runtime,
)


class _SlowExtract:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.calls = 0

    async def __call__(self, _payload: dict[str, object]) -> None:
        self.calls += 1
        self.started.set()
        await self.release.wait()


@pytest.fixture
async def factory(tmp_path: Path) -> Callable[[], AsyncSession]:
    # Recovery and its observers need independent transactions. Closing an
    # observer sharing the worker's connection can roll back the worker's update.
    engine = create_async_engine(
        URL.create("sqlite+aiosqlite", database=str(tmp_path / "memory-jobs.sqlite"))
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    def open_session() -> AsyncSession:
        return maker()

    yield open_session
    await engine.dispose()


async def _seed(factory: Callable[[], AsyncSession], *, content: str = "before") -> None:
    session = factory()
    session.add(
        User(
            id="user-1",
            email="user@example.com",
            hashed_password="x",
            full_name="User",
            is_active=True,
        )
    )
    session.add(
        Tenant(
            id="tenant-1",
            name="Tenant",
            slug="tenant",
            owner_id="user-1",
        )
    )
    session.add(
        Project(
            id="project-1",
            tenant_id="tenant-1",
            name="Project",
            owner_id="user-1",
        )
    )
    session.add(
        Memory(
            id="memory-1",
            project_id="project-1",
            author_id="user-1",
            title="Title",
            content=content,
            version=1,
            processing_status="COMPLETED",
            status="ENABLED",
            meta={"tenant_id": "tenant-1", "category": "fact"},
        )
    )
    await session.commit()
    await session.close()


async def _stage_update(
    factory: Callable[[], AsyncSession], *, content: str, revision: int = 2
) -> str:
    session = factory()
    memory = await session.get(Memory, "memory-1")
    assert memory is not None
    memory.content = content
    memory.version = revision
    task_id = await stage_memory_update_job(
        session,
        memory_id=memory.id,
        project_id=memory.project_id,
        tenant_id="tenant-1",
        user_id="user-1",
        content_changed=True,
        revision=revision,
        content=content,
        title=memory.title,
        tags=[],
        category="fact",
    )
    await session.commit()
    await session.close()
    return task_id


@pytest.mark.unit
async def test_slow_extraction_does_not_block_the_saved_update(
    factory: Callable[[], AsyncSession],
) -> None:
    await _seed(factory)
    extract = _SlowExtract()
    indexed: list[str] = []

    async def index(payload: dict[str, object]) -> None:
        indexed.append(str(payload["content"]))

    session = factory()
    memory = await session.get(Memory, "memory-1")
    assert memory is not None
    memory.content = "after"
    memory.version = 2
    task_id = await stage_memory_update_job(
        session,
        memory_id="memory-1",
        project_id="project-1",
        tenant_id="tenant-1",
        user_id="user-1",
        content_changed=True,
        revision=2,
        content="after",
        title="Title",
        tags=[],
        category="fact",
    )
    await session.commit()
    saved = await session.get(Memory, "memory-1")
    assert saved is not None
    assert saved.content == "after"
    assert saved.processing_status == "PENDING"
    await session.close()

    worker = asyncio.create_task(
        execute_memory_update_job(factory, task_id, extract=extract, index=index)
    )
    await asyncio.wait_for(extract.started.wait(), timeout=1)
    assert not worker.done()
    assert indexed == []
    extract.release.set()
    assert await asyncio.wait_for(worker, timeout=1) == "completed"
    check = factory()
    done = await check.get(Memory, "memory-1")
    assert done is not None
    assert done.processing_status == "COMPLETED"
    assert indexed == ["after"]
    await check.close()


@pytest.mark.unit
async def test_enqueue_failure_does_not_report_saved(
    factory: Callable[[], AsyncSession],
) -> None:
    await _seed(factory)
    session = factory()
    with pytest.raises(Exception, match="memory_update_job_not_staged"):
        await stage_memory_update_job(
            session,
            memory_id="missing",
            project_id="project-1",
            tenant_id="tenant-1",
            user_id="user-1",
            content_changed=True,
            revision=1,
            content="after",
            title="Title",
            tags=[],
            category="fact",
        )
    await session.rollback()
    await session.close()
    check = factory()
    memory = await check.get(Memory, "memory-1")
    assert memory is not None
    assert memory.content == "before"
    assert memory.processing_status == "COMPLETED"
    await check.close()


@pytest.mark.unit
async def test_restart_resumes_a_pending_job(factory: Callable[[], AsyncSession]) -> None:
    await _seed(factory)
    task_id = await _stage_update(factory, content="after")
    calls = 0

    async def extract(_payload: dict[str, object]) -> None:
        nonlocal calls
        calls += 1

    outcomes = await resume_memory_update_jobs(
        factory, extract=extract, index=lambda _payload: _ok()
    )
    assert outcomes == ["completed"]
    assert calls == 1
    again = await execute_memory_update_job(
        factory, task_id, extract=extract, index=lambda _payload: _ok()
    )
    assert again == "already_completed"
    assert calls == 1


@pytest.mark.unit
async def test_cancelled_job_can_be_resumed(factory: Callable[[], AsyncSession]) -> None:
    await _seed(factory)
    task_id = await _stage_update(factory, content="after")

    async def extract(_payload: dict[str, object]) -> None:
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await execute_memory_update_job(
            factory, task_id, extract=extract, index=lambda _payload: _ok()
        )
    outcomes = await resume_memory_update_jobs(
        factory,
        extract=lambda _payload: _ok(),
        index=lambda _payload: _ok(),
    )
    assert outcomes == ["completed"]


@pytest.mark.unit
async def test_old_revision_does_not_overwrite_a_newer_update(
    factory: Callable[[], AsyncSession],
) -> None:
    await _seed(factory)
    old_task = await _stage_update(factory, content="first", revision=2)
    session = factory()
    memory = await session.get(Memory, "memory-1")
    assert memory is not None
    memory.content = "second"
    memory.version = 3
    new_task = await stage_memory_update_job(
        session,
        memory_id="memory-1",
        project_id="project-1",
        tenant_id="tenant-1",
        user_id="user-1",
        content_changed=True,
        revision=3,
        content="second",
        title="Title",
        tags=[],
        category="fact",
    )
    await session.commit()
    await session.close()

    async def extract(payload: dict[str, object]) -> None:
        if payload["content"] == "first":
            payload["content"] = "stale-write"

    assert (
        await execute_memory_update_job(
            factory, old_task, extract=extract, index=lambda _payload: _ok()
        )
        == "stale_or_deleted"
    )
    check = factory()
    current = await check.get(Memory, "memory-1")
    assert current is not None
    assert current.content == "second"
    assert current.version == 3
    assert current.processing_status == "PENDING"
    await check.close()
    assert (
        await execute_memory_update_job(
            factory, new_task, extract=lambda _payload: _ok(), index=lambda _payload: _ok()
        )
        == "completed"
    )


@pytest.mark.unit
async def test_extraction_failure_is_not_full_completion(
    factory: Callable[[], AsyncSession],
) -> None:
    await _seed(factory)
    task_id = await _stage_update(factory, content="after")
    indexed: list[str] = []

    async def extract(_payload: dict[str, object]) -> None:
        raise RuntimeError("provider completion failed")

    async def index(payload: dict[str, object]) -> None:
        indexed.append(str(payload["memory_id"]))

    assert (
        await execute_memory_update_job(factory, task_id, extract=extract, index=index) == "failed"
    )
    assert indexed == ["memory-1"]
    session = factory()
    memory = await session.get(Memory, "memory-1")
    task = await session.get(TaskLog, task_id)
    assert memory is not None and task is not None
    assert memory.processing_status == "PENDING"
    assert task.status == "PENDING"
    assert task.result["stages"]["extraction"] == "RuntimeError"
    assert task.result["stages"]["index"] == "succeeded"
    assert task.result["completed"] is False
    await session.close()

    for _ in range(MAX_ATTEMPTS - 1):
        await execute_memory_update_job(factory, task_id, extract=extract, index=index)
    session = factory()
    memory = await session.get(Memory, "memory-1")
    task = await session.get(TaskLog, task_id)
    assert memory is not None and task is not None
    assert memory.processing_status == "FAILED"
    assert task.status == "FAILED"
    assert memory.processing_status != "COMPLETED"
    await session.close()


@pytest.mark.unit
async def test_delete_prevents_the_job_from_recreating_memory(
    factory: Callable[[], AsyncSession],
) -> None:
    await _seed(factory)
    task_id = await _stage_update(factory, content="after")
    session = factory()
    memory = await session.get(Memory, "memory-1")
    assert memory is not None
    await session.delete(memory)
    await session.commit()
    await session.close()
    assert (
        await execute_memory_update_job(
            factory,
            task_id,
            extract=lambda _payload: _ok(),
            index=lambda _payload: _ok(),
        )
        == "stale_or_deleted"
    )
    check = factory()
    assert await check.get(Memory, "memory-1") is None
    await check.close()


@pytest.mark.unit
async def test_tool_rejects_another_project_without_writing(
    factory: Callable[[], AsyncSession],
) -> None:
    await _seed(factory)

    class _Graph:
        embedder = None

        async def add_episode(self, _episode: object) -> None:
            raise AssertionError("graph work must not start")

    result = json.loads(
        await _execute_memory_update(
            memory_id="memory-1",
            title=None,
            content="stolen",
            tags=None,
            metadata=None,
            session_factory=factory,
            graph_service=_Graph(),
            project_id="other-project",
            tenant_id="tenant-1",
            user_id="user-1",
        )
    )
    assert result["code"] == "memory_forbidden"
    check = factory()
    memory = await check.get(Memory, "memory-1")
    assert memory is not None
    assert memory.content == "before"
    await check.close()


@pytest.mark.unit
async def test_stage_timeout_is_a_queryable_retry(factory: Callable[[], AsyncSession]) -> None:
    await _seed(factory)
    task_id = await _stage_update(factory, content="after")

    async def extract(_payload: dict[str, object]) -> None:
        await asyncio.sleep(5)

    started = time.perf_counter()
    assert (
        await execute_memory_update_job(
            factory,
            task_id,
            extract=extract,
            index=lambda _payload: _ok(),
            stage_timeout_s=0.05,
        )
        == "failed"
    )
    assert time.perf_counter() - started < 2
    session = factory()
    task = await session.get(TaskLog, task_id)
    memory = await session.get(Memory, "memory-1")
    assert task is not None and memory is not None
    assert task.error_message == "extraction:TimeoutError"
    assert task.result["stages"]["extraction"] == "TimeoutError"
    assert memory.processing_status == "PENDING"
    assert memory.processing_status != "COMPLETED"
    await session.close()


@pytest.mark.unit
async def test_cancelled_accelerator_is_recovered_by_resume(
    factory: Callable[[], AsyncSession],
) -> None:
    await _seed(factory)
    task_id = await _stage_update(factory, content="after")
    extract = _SlowExtract()
    dispatcher = MemoryUpdateDispatcher(factory, extract=extract, index=lambda _payload: _ok())
    install_memory_update_dispatcher(dispatcher)
    try:
        assert dispatcher.kick(task_id) is None
        await asyncio.wait_for(extract.started.wait(), 1)
        await dispatcher.aclose()
    finally:
        install_memory_update_dispatcher(None)
    outcomes = await resume_memory_update_jobs(
        factory,
        extract=lambda _payload: _ok(),
        index=lambda _payload: _ok(),
    )
    assert outcomes == ["completed"]


@pytest.mark.unit
async def test_saved_update_returns_pending_before_slow_extraction(
    factory: Callable[[], AsyncSession],
) -> None:
    await _seed(factory)
    session = factory()
    session.add(
        KnowledgeSyncEnrollmentModel(
            project_id="project-1",
            tenant_id="tenant-1",
            enabled=False,
        )
    )
    await session.commit()
    await session.close()
    extract = _SlowExtract()

    class _Episode:
        def __init__(self) -> None:
            self.status = "PENDING"

    class _Graph:
        embedder = None

        async def add_episode(self, episode: _Episode) -> _Episode:
            await extract(episode)
            episode.status = "COMPLETED"
            return episode

    dispatcher = MemoryUpdateDispatcher(factory, extract=extract, index=lambda _payload: _ok())
    install_memory_update_dispatcher(dispatcher)
    try:
        started = time.perf_counter()
        result = json.loads(
            await _execute_memory_update(
                memory_id="memory-1",
                title=None,
                content="after the save",
                tags=None,
                metadata=None,
                session_factory=factory,
                graph_service=_Graph(),
                project_id="project-1",
                tenant_id="tenant-1",
                user_id="user-1",
            )
        )
        elapsed = time.perf_counter() - started
        assert elapsed < 1
        assert result["status"] == "updated"
        assert result["saved"] is True
        assert result["processing_status"] == "PENDING"
        assert result["searchable"] is False
        assert result["revision"] == 2
        await asyncio.wait_for(extract.started.wait(), 1)
        assert not extract.release.is_set()
        extract.release.set()
        await dispatcher.join()
    finally:
        install_memory_update_dispatcher(None)
    check = factory()
    memory = await check.get(Memory, "memory-1")
    assert memory is not None
    assert memory.content == "after the save"
    assert memory.processing_status == "COMPLETED"
    await check.close()


@pytest.mark.unit
async def test_late_old_extraction_does_not_overwrite_a_newer_revision(
    factory: Callable[[], AsyncSession],
) -> None:
    await _seed(factory)
    old_task = await _stage_update(factory, content="first", revision=2)
    extract = _SlowExtract()
    worker = asyncio.create_task(
        execute_memory_update_job(
            factory,
            old_task,
            extract=extract,
            index=lambda _payload: _ok(),
            stage_timeout_s=30,
        )
    )
    await asyncio.wait_for(extract.started.wait(), 1)
    session = factory()
    memory = await session.get(Memory, "memory-1")
    assert memory is not None
    memory.content = "second"
    memory.version = 3
    new_task = await stage_memory_update_job(
        session,
        memory_id="memory-1",
        project_id="project-1",
        tenant_id="tenant-1",
        user_id="user-1",
        content_changed=True,
        revision=3,
        content="second",
        title="Title",
        tags=[],
        category="fact",
    )
    await session.commit()
    await session.close()
    extract.release.set()
    assert await asyncio.wait_for(worker, 1) == "stale_or_deleted"
    check = factory()
    current = await check.get(Memory, "memory-1")
    newer = await check.get(TaskLog, new_task)
    assert current is not None and newer is not None
    assert current.content == "second"
    assert current.version == 3
    assert current.task_id == new_task
    assert newer.status == "PENDING"
    await check.close()


@pytest.mark.unit
async def test_delete_during_extraction_is_not_resurrected(
    factory: Callable[[], AsyncSession],
) -> None:
    await _seed(factory)
    task_id = await _stage_update(factory, content="after")
    extract = _SlowExtract()
    worker = asyncio.create_task(
        execute_memory_update_job(
            factory,
            task_id,
            extract=extract,
            index=lambda _payload: _ok(),
            stage_timeout_s=30,
        )
    )
    await asyncio.wait_for(extract.started.wait(), 1)
    session = factory()
    memory = await session.get(Memory, "memory-1")
    assert memory is not None
    await session.delete(memory)
    await session.commit()
    await session.close()
    extract.release.set()
    assert await asyncio.wait_for(worker, 1) == "stale_or_deleted"
    check = factory()
    assert await check.get(Memory, "memory-1") is None
    await check.close()


@pytest.mark.unit
async def test_live_processing_claim_blocks_a_second_worker(
    factory: Callable[[], AsyncSession],
) -> None:
    await _seed(factory)
    task_id = await _stage_update(factory, content="after")
    calls = 0
    extract = _SlowExtract()

    async def counting(payload: dict[str, object]) -> None:
        nonlocal calls
        calls += 1
        await extract(payload)

    first = asyncio.create_task(
        execute_memory_update_job(
            factory,
            task_id,
            extract=counting,
            index=lambda _payload: _ok(),
            stage_timeout_s=30,
        )
    )
    await asyncio.wait_for(extract.started.wait(), 1)
    assert (
        await execute_memory_update_job(
            factory,
            task_id,
            extract=counting,
            index=lambda _payload: _ok(),
            stage_timeout_s=30,
        )
        == "in_progress"
    )
    assert calls == 1
    extract.release.set()
    assert await asyncio.wait_for(first, 1) == "completed"
    assert calls == 1


@pytest.mark.unit
async def test_expired_processing_lease_can_be_reclaimed(
    factory: Callable[[], AsyncSession],
) -> None:
    await _seed(factory)
    task_id = await _stage_update(factory, content="after")
    session = factory()
    task = await session.get(TaskLog, task_id)
    assert task is not None
    task.status = "PROCESSING"
    task.worker_id = "dead-worker"
    task.started_at = datetime.now(UTC) - timedelta(seconds=5)
    await session.commit()
    await session.close()
    assert (
        await execute_memory_update_job(
            factory,
            task_id,
            extract=lambda _payload: _ok(),
            index=lambda _payload: _ok(),
            stage_timeout_s=1,
        )
        == "completed"
    )


@pytest.mark.unit
async def test_timeout_releases_the_claim_for_resume(
    factory: Callable[[], AsyncSession],
) -> None:
    await _seed(factory)
    task_id = await _stage_update(factory, content="after")

    async def extract(_payload: dict[str, object]) -> None:
        await asyncio.sleep(5)

    dispatcher = MemoryUpdateDispatcher(
        factory,
        extract=extract,
        index=lambda _payload: _ok(),
        stage_timeout_s=0.05,
        retry_delay_s=lambda _attempt: 0,
    )
    dispatcher.kick(task_id)
    await dispatcher.join()
    session = factory()
    task = await session.get(TaskLog, task_id)
    assert task is not None
    assert task.status == "FAILED"
    assert task.worker_id is None
    assert task.retry_count == MAX_ATTEMPTS
    assert task.error_message == "extraction:TimeoutError"
    await session.close()
    outcomes = await resume_memory_update_jobs(
        factory,
        extract=lambda _payload: _ok(),
        index=lambda _payload: _ok(),
        stage_timeout_s=1,
    )
    assert outcomes == []
    session = factory()
    task = await session.get(TaskLog, task_id)
    assert task is not None
    assert task.status == "FAILED"
    await session.close()


@pytest.mark.unit
async def test_rollback_removes_the_staged_task_and_keeps_the_saved_body(
    factory: Callable[[], AsyncSession],
) -> None:
    await _seed(factory)
    session = factory()
    memory = await session.get(Memory, "memory-1")
    assert memory is not None
    memory.content = "after"
    memory.version = 2
    task_id = await stage_memory_update_job(
        session,
        memory_id="memory-1",
        project_id="project-1",
        tenant_id="tenant-1",
        user_id="user-1",
        content_changed=True,
        revision=2,
        content="after",
        title="Title",
        tags=[],
        category="fact",
    )
    await session.rollback()
    await session.close()
    check = factory()
    stored = await check.get(Memory, "memory-1")
    assert stored is not None
    assert stored.content == "before"
    assert stored.processing_status == "COMPLETED"
    assert await check.get(TaskLog, task_id) is None
    await check.close()


@pytest.mark.unit
async def test_search_hides_pending_and_failed_memories(
    factory: Callable[[], AsyncSession],
) -> None:
    await _seed(factory)
    session = factory()
    pending = await session.get(Memory, "memory-1")
    assert pending is not None
    pending.processing_status = "PENDING"
    session.add(
        Memory(
            id="memory-ready",
            project_id="project-1",
            author_id="user-1",
            title="Ready",
            content="ready",
            version=1,
            processing_status="COMPLETED",
            status="ENABLED",
            meta={"tenant_id": "tenant-1"},
        )
    )
    session.add(
        Memory(
            id="memory-failed",
            project_id="project-1",
            author_id="user-1",
            title="Failed",
            content="failed",
            version=1,
            processing_status="FAILED",
            status="ENABLED",
            meta={"tenant_id": "tenant-1", "index_error": "extraction:TimeoutError"},
        )
    )
    await session.commit()
    await session.close()
    token = _memory_tool_runtime.set(
        MemoryToolRuntime(
            session_factory=factory,
            graph_service=None,
            chunk_search=None,
            project_id="project-1",
            tenant_id="tenant-1",
        )
    )
    try:
        visible = await _exclude_unsearchable_memory_hits(
            [
                {"source_id": "memory-1", "content": "pending"},
                {"source_id": "memory-ready", "content": "ready"},
                {"source_id": "memory-failed", "content": "failed"},
                {"source_id": "graph-only", "content": "fact"},
            ],
            "project-1",
        )
    finally:
        _memory_tool_runtime.reset(token)
    assert [item["source_id"] for item in visible] == ["memory-ready", "graph-only"]


async def _ok() -> None:
    return None
