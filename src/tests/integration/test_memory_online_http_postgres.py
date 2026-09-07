"""Real HTTP create transactions against the isolated migrated PostgreSQL schema."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from alembic.operations import Operations
from alembic.operations.ops import CreateTableOp
from alembic.runtime.migration import MigrationContext
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from src.application.services.online_memory_commands import OnlineMemoryCommands
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.primary.web.memory_application_authority_v2 import (
    memory_application_authority_dependency_v2,
)
from src.infrastructure.adapters.primary.web.routers import memories, tasks
from src.infrastructure.adapters.primary.web.workflow_application_authority_v2 import (
    workflow_engine_authority_dependency_v2,
)
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.knowledge_sync_models import (
    KnowledgeSyncChangeModel as Change,
    KnowledgeSyncEnrollmentModel as Enrollment,
    KnowledgeSyncReceiptModel as Receipt,
)
from src.infrastructure.adapters.secondary.persistence.models import (
    Memory,
    TaskLog,
    User,
    UserProject,
)
from src.infrastructure.adapters.secondary.persistence.sql_knowledge_sync_enrollment import (
    SqlKnowledgeSyncEnrollment,
)
from src.infrastructure.adapters.secondary.persistence.sql_online_memory_repository import (
    SqlOnlineMemoryRepository,
)
from src.tests.integration.test_knowledge_sync_postgres import (
    pg_sync as _pg_sync,
)

pg_sync = _pg_sync


@pytest.fixture
async def http_memory(pg_sync, monkeypatch):
    sessions, scope = pg_sync
    async with sessions() as session:
        connection = await session.connection()

        def add_task_table(connection):
            operations = Operations(MigrationContext.configure(connection))
            operations.invoke(CreateTableOp.from_table(TaskLog.__table__))

        await connection.run_sync(add_task_table)
        await session.commit()
        user = await session.get(User, scope.actor_id)
    graph, workflow = AsyncMock(), AsyncMock()

    async def authority():
        async with sessions() as db:
            yield SimpleNamespace(
                db=db,
                services=SimpleNamespace(
                    graph_service=graph,
                    online_commands=OnlineMemoryCommands(SqlOnlineMemoryRepository(db)),
                ),
            )

    app = FastAPI()
    app.include_router(memories.router)
    app.include_router(tasks.router)

    async def task_db():
        async with sessions() as db:
            yield db

    app.dependency_overrides[get_db] = task_db
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[memory_application_authority_dependency_v2] = authority
    app.dependency_overrides[workflow_engine_authority_dependency_v2] = lambda: workflow
    graph.index_memory = AsyncMock()
    monkeypatch.setattr(memories, "_background_index_memory", graph.index_memory)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client, sessions, scope, graph, workflow


def body(**extra):
    return {"project_id": "project", "title": "Online", "content": "Body", **extra}


def headers(key=None):
    return {"Idempotency-Key": key or str(uuid4()), "X-Memory-Expected-Revision": "0"}


async def enroll(sessions, scope):
    async with sessions() as db:
        await SqlKnowledgeSyncEnrollment(db).bootstrap(scope)
        await db.commit()


async def test_enrolled_http_create_replay_is_atomic_and_defers_projection(http_memory):
    client, sessions, scope, graph, workflow = http_memory
    await enroll(sessions, scope)
    request_headers = headers()
    first = await client.post("/api/v1/memories/", json=body(), headers=request_headers)
    assert first.status_code == 201, first.text
    second = await client.post("/api/v1/memories/", json=body(), headers=request_headers)
    assert second.status_code == 201, second.text
    assert first.json() == second.json()
    assert second.headers["Idempotency-Replayed"] == "true"
    workflow.start_workflow.assert_not_awaited()
    assert graph.ensure_episodic_node.await_count == 0
    assert graph.index_memory.await_count == 0
    async with sessions() as db:
        assert len((await db.scalars(select(Memory))).all()) == 1
        changes = (await db.scalars(select(Change))).all()
        assert [(row.revision, row.sequence, row.actor_id) for row in changes] == [
            (1, 1, scope.actor_id)
        ]
        assert len((await db.scalars(select(Receipt))).all()) == 1
        task = (await db.scalars(select(TaskLog))).one()
        assert task.id == first.json()["task_id"]
        assert task.payload["source_revision"] == 1
        assert task.payload["memory_id"] == first.json()["id"]
        assert task.task_type == "memory_revision_projection"
        assert task.status == "PENDING"
        assert "deferred" in task.message
        assert (await db.get(Memory, first.json()["id"])).task_id == task.id
    changed = await client.post(
        "/api/v1/memories/", json=body(title="Different"), headers=request_headers
    )
    assert changed.status_code == 409
    assert changed.json()["detail"]["code"] == "knowledge_sync_idempotency_conflict"
    workflow.start_workflow.assert_not_awaited()


@pytest.mark.parametrize(
    ("request_headers", "extra", "expected"),
    [
        ({}, {}, 428),
        ({"Idempotency-Key": str(uuid4())}, {}, 428),
        ({"Idempotency-Key": "invalid", "X-Memory-Expected-Revision": "0"}, {}, 422),
        ({"Idempotency-Key": str(uuid4()), "X-Memory-Expected-Revision": "1"}, {}, 422),
        (headers(), {"is_public": True}, 422),
        (headers(), {"collaborators": ["other"]}, 422),
        (headers(), {"entities": [{"name": "E", "type": "person"}]}, 422),
        (headers(), {"relationships": [{"source": "A", "target": "B", "type": "knows"}]}, 422),
    ],
)
async def test_enrolled_http_rejects_missing_protocol_and_nonportable_fields_without_writes(
    http_memory, request_headers, extra, expected
):
    client, sessions, scope, _, workflow = http_memory
    await enroll(sessions, scope)
    response = await client.post("/api/v1/memories/", json=body(**extra), headers=request_headers)
    assert response.status_code == expected, response.text
    async with sessions() as db:
        for model in (Memory, Change, Receipt, TaskLog):
            assert (await db.scalars(select(model))).all() == []
    workflow.start_workflow.assert_not_awaited()


async def test_disabled_http_preserves_fields_without_client_protocol(http_memory):
    client, sessions, scope, graph, workflow = http_memory
    # Legacy Project ownership remains sufficient without UserProject membership.
    async with sessions() as db:
        membership = (await db.scalars(select(UserProject))).one()
        await db.delete(membership)
        await db.commit()
    extra = {
        "is_public": True,
        "collaborators": ["friend"],
        "metadata": {"label": "x"},
        "entities": [{"name": "E", "type": "person"}],
    }
    response = await client.post("/api/v1/memories/", json=body(**extra))
    assert response.status_code == 201, response.text
    assert response.json()["is_public"] is True
    assert response.json()["collaborators"] == ["friend"]
    assert response.json()["metadata"] == {"label": "x"}
    assert response.json()["entities"][0]["name"] == "E"
    assert graph.ensure_episodic_node.await_count == 1
    assert workflow.start_workflow.await_count == 1
    async with sessions() as db:
        assert not (await db.get(Enrollment, scope.project_id)).enabled
        assert (await db.scalars(select(Change))).all() == []
        assert (await db.scalars(select(Receipt))).all() == []


async def test_disabled_http_holds_project_lock_until_commit_before_bootstrap(http_memory):
    client, sessions, scope, graph, _ = http_memory
    entered, release = asyncio.Event(), asyncio.Event()

    async def pause_graph(**kwargs):
        entered.set()
        await release.wait()

    graph.ensure_episodic_node.side_effect = pause_graph
    request = asyncio.create_task(client.post("/api/v1/memories/", json=body()))
    await asyncio.wait_for(entered.wait(), 5)
    bootstrap = asyncio.create_task(enroll(sessions, scope))
    try:
        await asyncio.sleep(0.1)
        assert not bootstrap.done()
    finally:
        release.set()
    response = await asyncio.wait_for(request, 5)
    await asyncio.wait_for(bootstrap, 5)
    assert response.status_code == 201, response.text
    async with sessions() as db:
        changes = (await db.scalars(select(Change))).all()
        assert len(changes) == 1
        assert changes[0].memory_id == response.json()["id"]
        assert changes[0].source_kind == "bootstrap"


async def test_bootstrap_lock_forces_waiting_http_to_observe_enabled_state(http_memory):
    client, sessions, scope, _, workflow = http_memory
    async with sessions() as db:
        await SqlKnowledgeSyncEnrollment(db).bootstrap(scope)
        request = asyncio.create_task(client.post("/api/v1/memories/", json=body()))
        await asyncio.sleep(0.1)
        assert not request.done()
        await db.commit()
    response = await asyncio.wait_for(request, 5)
    assert response.status_code == 428, response.text
    workflow.start_workflow.assert_not_awaited()
    async with sessions() as db:
        assert (await db.scalars(select(Memory))).all() == []


async def test_failed_task_staging_rolls_back_memory_receipt_and_journal(http_memory, monkeypatch):
    from src.infrastructure.adapters.primary.web.routers import memory_online_create

    client, sessions, scope, _, workflow = http_memory
    await enroll(sessions, scope)

    def fail_task(**kwargs):
        raise RuntimeError("Task staging unavailable")

    monkeypatch.setattr(memory_online_create, "TaskLog", fail_task)
    response = await client.post("/api/v1/memories/", json=body(), headers=headers())
    assert response.status_code == 500
    async with sessions() as db:
        for model in (Memory, Change, Receipt, TaskLog):
            assert (await db.scalars(select(model))).all() == []
    workflow.start_workflow.assert_not_awaited()


async def test_enrolled_owner_without_membership_cannot_gain_new_write_authority(http_memory):
    client, sessions, scope, _, workflow = http_memory
    await enroll(sessions, scope)
    async with sessions() as db:
        membership = (await db.scalars(select(UserProject))).one()
        await db.delete(membership)
        await db.commit()
    response = await client.post("/api/v1/memories/", json=body(), headers=headers())
    assert response.status_code == 403, response.text
    workflow.start_workflow.assert_not_awaited()


async def test_http_replay_requires_current_write_membership(http_memory):
    client, sessions, scope, _, workflow = http_memory
    await enroll(sessions, scope)
    request_headers = headers()
    first = await client.post("/api/v1/memories/", json=body(), headers=request_headers)
    assert first.status_code == 201, first.text
    async with sessions() as db:
        membership = (await db.scalars(select(UserProject))).one()
        membership.role = "viewer"
        await db.commit()
    response = await client.post("/api/v1/memories/", json=body(), headers=request_headers)
    assert response.status_code == 403, response.text
    workflow.start_workflow.assert_not_awaited()


async def test_http_create_replay_after_delete_returns_original_without_recreating(http_memory):
    from src.domain.model.knowledge_sync.contracts import MemorySyncMutation
    from src.infrastructure.adapters.secondary.persistence.sql_knowledge_sync_repository import (
        SqlKnowledgeSyncRepository,
    )

    client, sessions, scope, _, workflow = http_memory
    await enroll(sessions, scope)
    request_headers = headers()
    first = await client.post("/api/v1/memories/", json=body(), headers=request_headers)
    assert first.status_code == 201, first.text
    async with sessions() as db:
        await SqlKnowledgeSyncRepository(db).mutate_online(
            scope,
            str(uuid4()),
            MemorySyncMutation(
                operation="delete", memory_id=first.json()["id"], expected_revision=1
            ),
        )
        await db.commit()
    replay = await client.post("/api/v1/memories/", json=body(), headers=request_headers)
    assert replay.status_code == 201, replay.text
    assert replay.json() == first.json()
    async with sessions() as db:
        assert (await db.scalars(select(Memory))).all() == []
        assert len((await db.scalars(select(Change))).all()) == 2
        assert len((await db.scalars(select(TaskLog))).all()) == 1
    workflow.start_workflow.assert_not_awaited()


async def test_legacy_recovery_cannot_dispatch_deferred_projection_or_create_orphan_task(
    http_memory,
):
    client, sessions, scope, graph, workflow = http_memory
    await enroll(sessions, scope)
    first = await client.post("/api/v1/memories/", json=body(), headers=headers())
    assert first.status_code == 201, first.text
    assert first.headers["Memory-Processing-State"] == "deferred"
    bulk = await client.post("/api/v1/tasks/retry-pending?include_failed=true")
    assert bulk.status_code == 200, bulk.text
    assert bulk.json()["submitted"] == 0
    manual = await client.post(f"/api/v1/tasks/{first.json()['task_id']}/retry")
    assert manual.status_code == 400, manual.text
    workflow.start_workflow.assert_not_awaited()
    graph.ensure_episodic_node.assert_not_awaited()
    graph.index_memory.assert_not_awaited()
    async with sessions() as db:
        task = (await db.scalars(select(TaskLog))).one()
        assert task.status == "PENDING"
        assert task.task_type == "memory_revision_projection"
