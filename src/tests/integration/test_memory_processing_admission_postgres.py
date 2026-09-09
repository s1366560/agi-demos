"""Real PostgreSQL fencing of background graph effects."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import delete

from src.domain.model.knowledge_sync.contracts import KnowledgeSyncError
from src.infrastructure.adapters.primary.web.startup import workflow
from src.infrastructure.adapters.secondary.persistence.models import Memory, TaskLog
from src.infrastructure.adapters.secondary.persistence.sql_knowledge_graph_sync_repository import (
    SqlKnowledgeGraphSyncRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_knowledge_sync_enrollment import (
    SqlKnowledgeSyncEnrollment,
)
from src.tests.integration.test_knowledge_sync_postgres import pg_sync, pytestmark  # noqa: F401


@pytest.fixture
async def processing(pg_sync, monkeypatch):  # noqa: F811
    sessions, scope = pg_sync
    async with sessions() as session:
        connection = await session.connection()
        await connection.run_sync(lambda sync: TaskLog.__table__.create(sync))
        session.add(
            Memory(
                id="memory",
                project_id="project",
                author_id="actor",
                title="Title",
                content="Current content",
                version=2,
                processing_status="PENDING",
                task_id="task",
                status="ENABLED",
            )
        )
        session.add(
            TaskLog(id="task", group_id="project", task_type="add_episode", status="PENDING")
        )
        await session.commit()
    monkeypatch.setattr(workflow, "async_session_factory", sessions)
    payload = {
        "task_id": "task",
        "memory_id": "memory",
        "source_revision": 2,
        "uuid": "memory",
        "project_id": "project",
        "tenant_id": "tenant",
        "content": "Current content",
        "user_id": "actor",
    }
    return sessions, scope, payload


@pytest.mark.parametrize(
    "mismatch",
    ["revision", "tenant", "project", "task", "removed", "uuid", "content", "missing_revision"],
)
async def test_invalid_source_never_enters_graph(processing, mismatch):
    sessions, _, payload = processing
    if mismatch == "removed":
        async with sessions() as session:
            await session.execute(delete(Memory).where(Memory.id == "memory"))
            await session.commit()
    else:
        field, value = {
            "revision": ("source_revision", 1),
            "tenant": ("tenant_id", "foreign"),
            "project": ("project_id", "foreign"),
            "task": ("task_id", "old-task"),
            "uuid": ("uuid", "foreign"),
            "content": ("content", "Stale content"),
            "missing_revision": ("source_revision", None),
        }[mismatch]
        payload[field] = value
    graph = SimpleNamespace(process_episode=AsyncMock())
    with pytest.raises((KnowledgeSyncError, ValueError)):
        await workflow._run_episode_processing_workflow(payload, graph)
    graph.process_episode.assert_not_awaited()
    async with sessions() as session:
        memory = await session.get(Memory, "memory")
        if memory:
            assert memory.processing_status == "PENDING"


async def test_bootstrap_before_job_journals_the_derived_record(processing):
    sessions, scope, payload = processing
    async with sessions() as session:
        await SqlKnowledgeSyncEnrollment(session).bootstrap(scope)
        await session.commit()
    from src.infrastructure.graph.schemas import EntityNode

    alice = EntityNode(name="Alice", entity_type="Person")
    result = SimpleNamespace(nodes=[alice], edges=[], episodic_edges=[])
    graph = SimpleNamespace(process_episode=AsyncMock(return_value=result))
    # Enrolled projects no longer fence the pipeline: it is a derived writer
    # and journals its extraction into the PostgreSQL sync journal.
    await workflow._run_episode_processing_workflow(payload, graph)
    graph.process_episode.assert_awaited_once()
    async with sessions() as session:
        memory = await session.get(Memory, "memory")
        assert memory is not None and memory.processing_status == "COMPLETED"
        repo = SqlKnowledgeGraphSyncRepository(session)
        page = await repo.graph_changes(scope, 0, 100)
        changes = page.to_dict()["changes"]
        assert len(changes) == 1
        version = changes[0]["version"]
        assert version["object_id"] == "memory"
        assert version["content"]["source_revision"] == 2
        assert version["content"]["audit_attempt"] == 1
        assert version["content"]["entities"] == [{"name": "Alice", "kind": "Person"}]


@pytest.mark.parametrize("ending", ["success", "failure", "cancel"])
async def test_bootstrap_waits_through_graph_and_releases_after_exit(processing, ending):
    sessions, scope, payload = processing
    entered, release = asyncio.Event(), asyncio.Event()

    async def graph_call(**kwargs):
        entered.set()
        await release.wait()
        if ending == "failure":
            raise RuntimeError("graph unavailable")
        return SimpleNamespace(nodes=[], edges=[], episodic_edges=[])

    async def bootstrap():
        async with sessions() as session:
            result = await SqlKnowledgeSyncEnrollment(session).bootstrap(scope)
            await session.commit()
            return result

    job = asyncio.create_task(
        workflow._run_episode_processing_workflow(
            payload, SimpleNamespace(process_episode=graph_call)
        )
    )
    await asyncio.wait_for(entered.wait(), 5)
    enabling = asyncio.create_task(bootstrap())
    await asyncio.sleep(0.1)
    assert not enabling.done()
    if ending == "cancel":
        job.cancel()
    else:
        release.set()
    if ending == "success":
        await asyncio.wait_for(job, 5)
    else:
        with pytest.raises(asyncio.CancelledError if ending == "cancel" else RuntimeError):
            await asyncio.wait_for(job, 5)
    await asyncio.wait_for(enabling, 5)


@pytest.mark.parametrize("enrolled", [False, True])
async def test_reprocess_fence_spans_request_commit_and_workflow_start(processing, enrolled):
    from src.infrastructure.adapters.primary.web.routers.memories import reprocess_memory

    sessions, scope, _ = processing
    async with sessions() as session:
        memory = await session.get(Memory, "memory")
        memory.processing_status = "COMPLETED"
        await session.commit()
        if enrolled:
            await SqlKnowledgeSyncEnrollment(session).bootstrap(scope)
            await session.commit()
    entered, release = asyncio.Event(), asyncio.Event()

    async def start(**kwargs):
        entered.set()
        await release.wait()

    graph = SimpleNamespace(delete_episode_by_memory_id=AsyncMock())
    engine = SimpleNamespace(start_workflow=AsyncMock(side_effect=start))

    async def request():
        async with sessions() as db:
            return await reprocess_memory(
                "memory",
                current_user=SimpleNamespace(id="actor"),
                workflow_engine=engine,
                memory_application=SimpleNamespace(
                    db=db, services=SimpleNamespace(graph_service=graph)
                ),
            )

    if enrolled:
        response = await request()
        assert response.status_code == 422
        assert b"knowledge_sync_write_context_required" in response.body
        graph.delete_episode_by_memory_id.assert_not_awaited()
        engine.start_workflow.assert_not_awaited()
        return
    job = asyncio.create_task(request())
    await asyncio.wait_for(entered.wait(), 5)
    async with sessions() as db:
        memory = await db.get(Memory, "memory")
        assert memory.processing_status == "PENDING"

    async def enable():
        async with sessions() as db:
            await SqlKnowledgeSyncEnrollment(db).bootstrap(scope)
            await db.commit()

    enabling = asyncio.create_task(enable())
    await asyncio.sleep(0.1)
    assert not enabling.done()
    release.set()
    await asyncio.wait_for(job, 5)
    await asyncio.wait_for(enabling, 5)
    graph.delete_episode_by_memory_id.assert_awaited_once_with("memory")


@pytest.mark.parametrize(
    "invalid", ["scope", "tenant", "row_project", "row_tenant", "removed", "enrolled"]
)
async def test_incremental_refresh_rejects_scope_before_graph(processing, invalid):
    sessions, scope, _ = processing
    payload = {
        "task_id": "task",
        "project_id": "project",
        "tenant_id": "tenant",
        "episode_uuids": ["episode"],
    }
    row = {
        "uuid": "episode",
        "content": "Graph content",
        "project_id": "project",
        "tenant_id": "tenant",
    }
    if invalid == "scope":
        payload.pop("project_id")
    elif invalid == "tenant":
        payload["tenant_id"] = "foreign"
    elif invalid == "row_project":
        row["project_id"] = "foreign"
    elif invalid == "row_tenant":
        row["tenant_id"] = "foreign"
    elif invalid == "removed":
        row["memory_id"] = "missing-memory"
    elif invalid == "enrolled":
        async with sessions() as db:
            await SqlKnowledgeSyncEnrollment(db).bootstrap(scope)
            await db.commit()
    client = SimpleNamespace(execute_query=AsyncMock(return_value=SimpleNamespace(records=[row])))
    graph = SimpleNamespace(_neo4j_client=client, process_episode=AsyncMock())
    with pytest.raises(KnowledgeSyncError):
        await workflow._run_incremental_refresh_workflow(payload, graph)
    graph.process_episode.assert_not_awaited()


async def test_incremental_refresh_uses_current_sql_content_and_exact_query(processing):
    _, _, _ = processing
    row = {
        "uuid": "memory",
        "memory_id": "memory",
        "content": "Stale graph content",
        "project_id": "project",
        "tenant_id": "tenant",
    }
    client = SimpleNamespace(execute_query=AsyncMock(return_value=SimpleNamespace(records=[row])))
    graph = SimpleNamespace(_neo4j_client=client, process_episode=AsyncMock())
    await workflow._run_incremental_refresh_workflow(
        {"task_id": "task", "project_id": "project", "episode_uuids": ["memory"]},
        graph,
    )
    assert graph.process_episode.call_args.kwargs["content"] == "Current content"
    assert graph.process_episode.call_args.kwargs["tenant_id"] == "tenant"
    assert "ep.project_id = $project_id" in client.execute_query.call_args.args[0]
    assert client.execute_query.call_args.kwargs["project_id"] == "project"


@pytest.mark.parametrize("ending", ["success", "failure", "cancel"])
async def test_incremental_lease_blocks_bootstrap_until_graph_exit(processing, ending):
    sessions, scope, _ = processing
    entered, release = asyncio.Event(), asyncio.Event()

    async def process(**kwargs):
        entered.set()
        await release.wait()
        if ending == "failure":
            raise RuntimeError("graph unavailable")

    row = {
        "uuid": "graph-only",
        "content": "Graph content",
        "project_id": "project",
        "tenant_id": "tenant",
    }
    client = SimpleNamespace(execute_query=AsyncMock(return_value=SimpleNamespace(records=[row])))
    graph = SimpleNamespace(_neo4j_client=client, process_episode=process)
    job = asyncio.create_task(
        workflow._run_incremental_refresh_workflow(
            {"task_id": "task", "project_id": "project"},
            graph,
        )
    )
    await asyncio.wait_for(entered.wait(), 5)

    async def enable():
        async with sessions() as db:
            await SqlKnowledgeSyncEnrollment(db).bootstrap(scope)
            await db.commit()

    enabling = asyncio.create_task(enable())
    await asyncio.sleep(0.1)
    assert not enabling.done()
    if ending == "cancel":
        job.cancel()
    else:
        release.set()
    if ending == "success":
        await asyncio.wait_for(job, 5)
    else:
        with pytest.raises(asyncio.CancelledError if ending == "cancel" else RuntimeError):
            await asyncio.wait_for(job, 5)
    await asyncio.wait_for(enabling, 5)
    async with sessions() as db:
        task = await db.get(TaskLog, "task")
        assert task.status == ("COMPLETED" if ending == "success" else "FAILED")


async def test_enrolled_community_rebuild_never_deletes_graph(processing):
    sessions, scope, _ = processing
    async with sessions() as db:
        await SqlKnowledgeSyncEnrollment(db).bootstrap(scope)
        await db.commit()
    client = SimpleNamespace(execute_query=AsyncMock())
    with pytest.raises(KnowledgeSyncError):
        await workflow._run_rebuild_communities_workflow(
            {"task_id": "task", "project_id": "project"},
            SimpleNamespace(_neo4j_client=client),
        )
    client.execute_query.assert_not_awaited()


async def test_source_check_success_but_processing_cas_miss_has_no_graph_effect(
    processing, monkeypatch
):
    sessions, _, payload = processing
    transition = AsyncMock(return_value=False)
    monkeypatch.setattr(workflow, "update_memory_processing_status", transition)
    graph = SimpleNamespace(process_episode=AsyncMock())
    with pytest.raises(KnowledgeSyncError, match="knowledge_sync_write_conflict"):
        await workflow._run_episode_processing_workflow(payload, graph)
    transition.assert_awaited_once()
    graph.process_episode.assert_not_awaited()
    async with sessions() as db:
        task = await db.get(TaskLog, "task")
        memory = await db.get(Memory, "memory")
        assert task.status == "FAILED"
        assert task.started_at is None
        assert task.result is None
        assert memory.processing_status == "PENDING"


async def test_completion_cas_miss_does_not_publish_success(processing, monkeypatch):
    sessions, _, payload = processing
    transition = workflow.update_memory_processing_status

    async def miss_completion(session, source, status):
        if status != "PROCESSING":
            return False
        return await transition(session, source, status)

    monkeypatch.setattr(workflow, "update_memory_processing_status", miss_completion)
    graph = SimpleNamespace(process_episode=AsyncMock(return_value=SimpleNamespace()))
    with pytest.raises(KnowledgeSyncError, match="knowledge_sync_write_conflict"):
        await workflow._run_episode_processing_workflow(payload, graph)
    graph.process_episode.assert_awaited_once()
    async with sessions() as db:
        task = await db.get(TaskLog, "task")
        assert task.status == "FAILED"
        assert task.result is None
