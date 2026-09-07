"""Scoped HTTP commands must never silently downgrade to legacy writes."""

import os
from uuid import uuid4

import pytest
from sqlalchemy import select

from src.infrastructure.adapters.secondary.persistence.knowledge_sync_models import (
    KnowledgeSyncChangeModel as Change,
    KnowledgeSyncReceiptModel as Receipt,
)
from src.infrastructure.adapters.secondary.persistence.models import Memory
from src.tests.integration.test_memory_online_http_postgres import (
    body,
    enroll,
    headers,
    http_memory as _http_memory,
    pg_sync as _pg_sync,
)

pg_sync = _pg_sync
http_memory = _http_memory
pytestmark = pytest.mark.skipif(
    os.getenv("KNOWLEDGE_SYNC_POSTGRES_TESTS") != "1",
    reason="Requires the isolated knowledge sync PostgreSQL test database",
)


@pytest.mark.parametrize(
    "request_headers",
    [headers(), {"Idempotency-Key": str(uuid4())}, {"X-Memory-Expected-Revision": "0"}],
)
async def test_disabled_create_refuses_explicit_command_protocol(http_memory, request_headers):
    client, sessions, _, graph, workflow = http_memory
    response = await client.post("/api/v1/memories/", json=body(), headers=request_headers)
    assert response.status_code == 503, response.text
    assert response.json()["detail"]["code"] == "memory_command_unavailable"
    async with sessions() as db:
        assert (await db.scalars(select(Memory))).all() == []
        assert (await db.scalars(select(Change))).all() == []
        assert (await db.scalars(select(Receipt))).all() == []
    graph.ensure_episodic_node.assert_not_awaited()
    workflow.start_workflow.assert_not_awaited()


@pytest.mark.parametrize("method", ["PATCH", "DELETE"])
async def test_disabled_mutation_refuses_explicit_command_protocol(http_memory, method):
    client, sessions, _, _, _ = http_memory
    created = await client.post("/api/v1/memories/", json=body())
    assert created.status_code == 201, created.text
    memory_id = created.json()["id"]
    options = {"json": {"title": "Changed", "version": 1}} if method == "PATCH" else {}
    response = await client.request(
        method,
        f"/api/v1/memories/{memory_id}",
        headers={"Idempotency-Key": str(uuid4()), "X-Memory-Expected-Revision": "1"},
        **options,
    )
    assert response.status_code == 503, response.text
    async with sessions() as db:
        memory = await db.get(Memory, memory_id)
        assert (memory.title, memory.version) == ("Online", 1)


@pytest.mark.parametrize("method", ["GET", "PATCH", "DELETE"])
@pytest.mark.parametrize("enabled", [False, True])
async def test_supplied_wrong_project_cannot_read_or_mutate_enrolled_memory(
    http_memory, method, enabled
):
    client, sessions, scope, _, _ = http_memory
    if enabled:
        await enroll(sessions, scope)
    created = await client.post(
        "/api/v1/memories/", json=body(), headers=headers() if enabled else {}
    )
    assert created.status_code == 201, created.text
    memory_id = created.json()["id"]
    options = {"json": {"title": "Changed", "version": 1}} if method == "PATCH" else {}
    response = await client.request(
        method,
        f"/api/v1/memories/{memory_id}?project_id=other-project",
        headers={"Idempotency-Key": str(uuid4()), "X-Memory-Expected-Revision": "1"}
        if method != "GET"
        else {},
        **options,
    )
    assert response.status_code == 404, response.text
    async with sessions() as db:
        memory = await db.get(Memory, memory_id)
        assert (memory.title, memory.version) == ("Online", 1)
        assert len((await db.scalars(select(Change))).all()) == int(enabled)
        assert len((await db.scalars(select(Receipt))).all()) == int(enabled)


async def test_correct_project_keeps_delete_receipt_replay_after_tombstone(http_memory):
    client, sessions, scope, graph, _ = http_memory
    graph.get_memory_graph_context.return_value = ([], [])
    await enroll(sessions, scope)
    created = await client.post("/api/v1/memories/", json=body(), headers=headers())
    memory_id = created.json()["id"]
    path = f"/api/v1/memories/{memory_id}?project_id=project"
    read = await client.get(path)
    assert read.status_code == 200, read.text
    assert read.json()["id"] == memory_id
    updated = await client.patch(
        path,
        json={"title": "Scoped edit", "version": 1},
        headers={"Idempotency-Key": str(uuid4()), "X-Memory-Expected-Revision": "1"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["version"] == 2
    command = {"Idempotency-Key": str(uuid4()), "X-Memory-Expected-Revision": "2"}
    first = await client.delete(path, headers=command)
    assert first.status_code == 204, first.text
    replay = await client.delete(path, headers=command)
    assert replay.status_code == 204, replay.text
    assert replay.headers["Idempotency-Replayed"] == "true"
    wrong = await client.delete(f"/api/v1/memories/{memory_id}?project_id=other", headers=command)
    assert wrong.status_code == 404, wrong.text
