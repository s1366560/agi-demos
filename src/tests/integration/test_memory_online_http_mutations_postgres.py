"""PATCH/delete admission and original-command replay over real PostgreSQL HTTP."""

import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import select

from src.infrastructure.adapters.secondary.persistence.knowledge_sync_models import (
    KnowledgeSyncChangeModel as Change,
    KnowledgeSyncConflictModel as Conflict,
    KnowledgeSyncReceiptModel as Receipt,
    KnowledgeSyncTombstoneModel as Tombstone,
)
from src.infrastructure.adapters.secondary.persistence.models import Memory, TaskLog, UserProject
from src.tests.integration.test_memory_online_http_postgres import (
    body,
    enroll,
    headers,
    http_memory as _http_memory,
    pg_sync as _pg_sync,
)

pg_sync = _pg_sync
http_memory = _http_memory


def command_headers(revision, key=None):
    return {
        "Idempotency-Key": key or str(uuid4()),
        "X-Memory-Expected-Revision": str(revision),
    }


async def create_enrolled(http_memory):
    client, sessions, scope, _, _ = http_memory
    await enroll(sessions, scope)
    response = await client.post(
        "/api/v1/memories/",
        json=body(tags=["kept"], metadata={"kept": True}),
        headers=headers(),
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def test_partial_patch_replay_after_later_edit_returns_original_snapshot(http_memory):
    client, sessions, _, graph, workflow = http_memory
    memory_id = await create_enrolled(http_memory)
    path = f"/api/v1/memories/{memory_id}"
    request_headers = command_headers(1)
    original = {"title": "First edit", "version": 1}
    first = await client.patch(path, json=original, headers=request_headers)
    assert first.status_code == 200, first.text
    assert first.json()["version"] == 2
    assert first.json()["content"] == "Body"
    assert first.json()["metadata"] == {"kept": True}
    assert first.json()["tags"] == ["kept"]
    later = await client.patch(
        path, json={"content": "Later body", "version": 2}, headers=command_headers(2)
    )
    assert later.status_code == 200, later.text
    replay = await client.patch(path, json=original, headers=request_headers)
    assert replay.status_code == 200, replay.text
    assert replay.json() == first.json()
    assert replay.headers["Idempotency-Replayed"] == "true"
    different = await client.patch(
        path, json={"title": "Other", "version": 1}, headers=request_headers
    )
    assert different.status_code == 409, different.text
    assert different.json()["detail"]["code"] == "knowledge_sync_idempotency_conflict"
    async with sessions() as db:
        memory = await db.get(Memory, memory_id)
        assert (memory.version, memory.content) == (3, "Later body")
        assert len((await db.scalars(select(Change))).all()) == 3
        assert len((await db.scalars(select(Receipt))).all()) == 3
        tasks = (await db.scalars(select(TaskLog))).all()
        assert len(tasks) == 3
        assert all(task.task_type == "memory_revision_projection" for task in tasks)
        assert memory.task_id == later.json()["task_id"]
    workflow.start_workflow.assert_not_awaited()
    graph.delete_episode_by_memory_id.assert_not_awaited()
    graph.ensure_episodic_node.assert_not_awaited()
    graph.index_memory.assert_not_awaited()


@pytest.mark.parametrize(
    ("request_headers", "payload", "expected"),
    [
        ({}, {"title": "New", "version": 1}, 428),
        (command_headers(2), {"title": "New", "version": 1}, 422),
        (command_headers(1), {"title": None, "version": 1}, 422),
        (command_headers(1), {"entities": [], "version": 1}, 422),
        (command_headers(1), {"relationships": [], "version": 1}, 422),
        ({"Idempotency-Key": "bad", "X-Memory-Expected-Revision": "1"}, {"version": 1}, 422),
    ],
)
async def test_invalid_patch_rejected_without_journal_or_task(
    http_memory, request_headers, payload, expected
):
    client, sessions, _, _, _ = http_memory
    memory_id = await create_enrolled(http_memory)
    response = await client.patch(
        f"/api/v1/memories/{memory_id}", json=payload, headers=request_headers
    )
    assert response.status_code == expected, response.text
    async with sessions() as db:
        assert (await db.get(Memory, memory_id)).version == 1
        for model in (Change, Receipt, TaskLog):
            assert len((await db.scalars(select(model))).all()) == 1


async def test_delete_replay_uses_tombstone_and_current_authority(http_memory):
    client, sessions, _, graph, workflow = http_memory
    memory_id = await create_enrolled(http_memory)
    async with sessions() as db:
        membership = (await db.scalars(select(UserProject))).one()
        membership.role = "member"
        await db.commit()
    request_headers = command_headers(1)
    first = await client.delete(f"/api/v1/memories/{memory_id}", headers=request_headers)
    assert first.status_code == 204, first.text
    replay = await client.delete(f"/api/v1/memories/{memory_id}", headers=request_headers)
    assert replay.status_code == 204, replay.text
    assert replay.headers["Idempotency-Replayed"] == "true"
    async with sessions() as db:
        assert await db.get(Memory, memory_id) is None
        assert (await db.get(Tombstone, memory_id)).revision == 2
        assert len((await db.scalars(select(Change))).all()) == 2
        assert len((await db.scalars(select(TaskLog))).all()) == 2
        membership = (await db.scalars(select(UserProject))).one()
        membership.role = "viewer"
        await db.commit()
    revoked = await client.delete(f"/api/v1/memories/{memory_id}", headers=request_headers)
    assert revoked.status_code == 403, revoked.text
    workflow.start_workflow.assert_not_awaited()
    graph.delete_episode_by_memory_id.assert_not_awaited()


@pytest.mark.parametrize("method", ["patch", "delete"])
async def test_stale_revision_rejected_without_offline_conflict(http_memory, method):
    client, sessions, _, _, _ = http_memory
    memory_id = await create_enrolled(http_memory)
    kwargs = {"headers": command_headers(2)}
    if method == "patch":
        kwargs["json"] = {"title": "New", "version": 2}
    response = await client.request(method, f"/api/v1/memories/{memory_id}", **kwargs)
    assert response.status_code == 409, response.text
    async with sessions() as db:
        assert (await db.get(Memory, memory_id)).version == 1
        assert (await db.scalars(select(Conflict))).all() == []
        assert len((await db.scalars(select(Receipt))).all()) == 1


async def test_two_http_patches_have_one_revision_winner(http_memory):
    client, sessions, _, _, _ = http_memory
    memory_id = await create_enrolled(http_memory)
    replies = await asyncio.gather(
        *[
            client.patch(
                f"/api/v1/memories/{memory_id}",
                json={"title": title, "version": 1},
                headers=command_headers(1),
            )
            for title in ("A", "B")
        ]
    )
    assert sorted(response.status_code for response in replies) == [200, 409]
    async with sessions() as db:
        assert (await db.get(Memory, memory_id)).version == 2
        assert len((await db.scalars(select(Change))).all()) == 2
        assert len((await db.scalars(select(TaskLog))).all()) == 2


async def test_patch_retains_nonportable_fields_and_replays_original_projection(http_memory):
    client, sessions, scope, _, _ = http_memory
    original = {
        "entities": [{"name": "Original", "type": "person"}],
        "relationships": [{"source": "A", "target": "B", "type": "knows"}],
        "collaborators": ["kept"],
        "is_public": True,
    }
    created = await client.post("/api/v1/memories/", json=body(**original))
    assert created.status_code == 201, created.text
    memory_id = created.json()["id"]
    await enroll(sessions, scope)
    request_headers = command_headers(1)
    payload = {"version": 1, "title": "Changed"}
    first = await client.patch(
        f"/api/v1/memories/{memory_id}", json=payload, headers=request_headers
    )
    assert first.status_code == 200, first.text
    for field in original:
        assert first.json()[field] == created.json()[field]
    async with sessions() as db:
        memory = await db.get(Memory, memory_id)
        memory.entities = [{"name": "Later", "type": "person"}]
        memory.collaborators = ["later"]
        memory.is_public = False
        await db.commit()
        journal = (await db.scalars(select(Change).where(Change.revision == 2))).one()
        assert "retained_fields" not in journal.snapshot
        assert "entities" not in journal.snapshot["content"]
    replay = await client.patch(
        f"/api/v1/memories/{memory_id}", json=payload, headers=request_headers
    )
    assert replay.status_code == 200, replay.text
    assert replay.json() == first.json()


@pytest.mark.parametrize("method", ["patch", "delete"])
async def test_task_staging_failure_rolls_back_mutation_atomically(
    http_memory, monkeypatch, method
):
    from src.infrastructure.adapters.primary.web.routers import memory_online_mutations

    client, sessions, _, _, _ = http_memory
    memory_id = await create_enrolled(http_memory)

    def fail_task(**kwargs):
        raise RuntimeError("Task staging failed")

    monkeypatch.setattr(memory_online_mutations, "TaskLog", fail_task)
    kwargs = {"headers": command_headers(1)}
    if method == "patch":
        kwargs["json"] = {"title": "New", "version": 1}
    response = await client.request(method, f"/api/v1/memories/{memory_id}", **kwargs)
    assert response.status_code == 500, response.text
    async with sessions() as db:
        memory = await db.get(Memory, memory_id)
        assert (memory.title, memory.version) == ("Online", 1)
        assert await db.get(Tombstone, memory_id) is None
        for model in (Change, Receipt, TaskLog):
            assert len((await db.scalars(select(model))).all()) == 1


@pytest.mark.parametrize("method", ["patch", "delete"])
async def test_disabled_mutation_holds_bootstrap_lock_until_commit(http_memory, method):
    client, sessions, scope, graph, _ = http_memory
    created = await client.post("/api/v1/memories/", json=body())
    assert created.status_code == 201, created.text
    memory_id = created.json()["id"]
    entered, release = asyncio.Event(), asyncio.Event()

    async def pause_cleanup(*args, **kwargs):
        entered.set()
        await release.wait()

    graph.delete_episode_by_memory_id.side_effect = pause_cleanup
    kwargs = {"json": {"title": "Updated", "version": 1}} if method == "patch" else {}
    request = asyncio.create_task(client.request(method, f"/api/v1/memories/{memory_id}", **kwargs))
    await asyncio.wait_for(entered.wait(), 5)
    bootstrap = asyncio.create_task(enroll(sessions, scope))
    try:
        await asyncio.sleep(0.1)
        assert not bootstrap.done()
    finally:
        release.set()
    response = await asyncio.wait_for(request, 5)
    await asyncio.wait_for(bootstrap, 5)
    assert response.status_code == (200 if method == "patch" else 204), response.text
    async with sessions() as db:
        changes = (await db.scalars(select(Change))).all()
        if method == "delete":
            assert changes == []
            assert await db.get(Memory, memory_id) is None
        else:
            assert [(row.revision, row.source_kind) for row in changes] == [(2, "bootstrap")]


@pytest.mark.parametrize("method", ["patch", "delete"])
async def test_bootstrap_first_forces_waiting_legacy_mutation_to_require_protocol(
    http_memory, method
):
    from src.infrastructure.adapters.secondary.persistence.sql_knowledge_sync_enrollment import (
        SqlKnowledgeSyncEnrollment,
    )

    client, sessions, scope, _, _ = http_memory
    created = await client.post("/api/v1/memories/", json=body())
    assert created.status_code == 201, created.text
    memory_id = created.json()["id"]
    async with sessions() as db:
        await SqlKnowledgeSyncEnrollment(db).bootstrap(scope)
        kwargs = {"json": {"title": "Updated", "version": 1}} if method == "patch" else {}
        request = asyncio.create_task(
            client.request(method, f"/api/v1/memories/{memory_id}", **kwargs)
        )
        await asyncio.sleep(0.1)
        assert not request.done()
        await db.commit()
    response = await asyncio.wait_for(request, 5)
    assert response.status_code == 428, response.text
    async with sessions() as db:
        assert (await db.get(Memory, memory_id)).version == 1


async def test_partial_patch_presence_is_part_of_command_identity(http_memory):
    client, _, _, _, _ = http_memory
    memory_id = await create_enrolled(http_memory)
    request_headers = command_headers(1)
    first = await client.patch(
        f"/api/v1/memories/{memory_id}", json={"version": 1}, headers=request_headers
    )
    assert first.status_code == 200, first.text
    explicit = await client.patch(
        f"/api/v1/memories/{memory_id}",
        json={"version": 1, "tags": ["kept"]},
        headers=request_headers,
    )
    assert explicit.status_code == 409, explicit.text


async def test_patch_replay_after_delete_does_not_recreate_or_enqueue(http_memory):
    client, sessions, _, _, workflow = http_memory
    memory_id = await create_enrolled(http_memory)
    path = f"/api/v1/memories/{memory_id}"
    request_headers = command_headers(1)
    payload = {"title": "Updated", "version": 1}
    first = await client.patch(path, json=payload, headers=request_headers)
    assert first.status_code == 200, first.text
    deleted = await client.delete(path, headers=command_headers(2))
    assert deleted.status_code == 204, deleted.text
    replay = await client.patch(path, json=payload, headers=request_headers)
    assert replay.status_code == 200, replay.text
    assert replay.json() == first.json()
    async with sessions() as db:
        assert await db.get(Memory, memory_id) is None
        assert len((await db.scalars(select(TaskLog))).all()) == 3
    workflow.start_workflow.assert_not_awaited()


@pytest.mark.parametrize("fail_staging", [False, True])
async def test_delete_share_and_chunk_cleanup_is_atomic_with_tombstone(
    http_memory, monkeypatch, fail_staging
):
    from src.infrastructure.adapters.primary.web.routers import memory_online_mutations
    from src.infrastructure.adapters.secondary.persistence.models import MemoryChunk, MemoryShare

    client, sessions, scope, _, _ = http_memory
    memory_id = await create_enrolled(http_memory)
    async with sessions() as db:
        db.add(
            MemoryShare(
                id="share",
                memory_id=memory_id,
                shared_with_user_id=scope.actor_id,
                shared_by=scope.actor_id,
                permissions={"edit": True},
            )
        )
        for chunk_id, source_id in (("owned", memory_id), ("unrelated", "unrelated")):
            db.add(
                MemoryChunk(
                    id=chunk_id,
                    project_id=scope.project_id,
                    source_type="memory",
                    source_id=source_id,
                    content="chunk",
                    content_hash="hash",
                )
            )
        await db.commit()
    if fail_staging:

        def fail_task(**kwargs):
            raise RuntimeError("Task staging failed")

        monkeypatch.setattr(memory_online_mutations, "TaskLog", fail_task)
    response = await client.delete(f"/api/v1/memories/{memory_id}", headers=command_headers(1))
    assert response.status_code == (500 if fail_staging else 204), response.text
    async with sessions() as db:
        assert (await db.get(MemoryShare, "share") is not None) is fail_staging
        assert (await db.get(MemoryChunk, "owned") is not None) is fail_staging
        assert await db.get(MemoryChunk, "unrelated") is not None
        assert (await db.get(Memory, memory_id) is not None) is fail_staging
        assert (await db.get(Tombstone, memory_id) is None) is fail_staging


async def test_patch_and_delete_deferred_tasks_are_not_recovered_by_legacy_routes(http_memory):
    client, sessions, _, graph, workflow = http_memory
    memory_id = await create_enrolled(http_memory)
    patched = await client.patch(
        f"/api/v1/memories/{memory_id}",
        json={"title": "Updated", "version": 1},
        headers=command_headers(1),
    )
    assert patched.status_code == 200, patched.text
    first_retry = await client.post("/api/v1/tasks/retry-pending?include_failed=true")
    assert first_retry.status_code == 200, first_retry.text
    assert first_retry.json()["submitted"] == 0
    deleted = await client.delete(f"/api/v1/memories/{memory_id}", headers=command_headers(2))
    assert deleted.status_code == 204, deleted.text
    second_retry = await client.post("/api/v1/tasks/retry-pending?include_failed=true")
    assert second_retry.status_code == 200, second_retry.text
    assert second_retry.json()["submitted"] == 0
    async with sessions() as db:
        tasks = (await db.scalars(select(TaskLog))).all()
        assert len(tasks) == 3
        for task in tasks:
            assert task.task_type == "memory_revision_projection"
            assert task.status == "PENDING"
            assert "deferred" in task.message
            manual = await client.post(f"/api/v1/tasks/{task.id}/retry")
            assert manual.status_code == 400, manual.text
    workflow.start_workflow.assert_not_awaited()
    graph.delete_episode_by_memory_id.assert_not_awaited()
    graph.index_memory.assert_not_awaited()


async def test_enrolled_edit_share_cannot_delete_and_revocation_blocks_patch_replay(http_memory):
    from src.infrastructure.adapters.secondary.persistence.models import MemoryShare, User

    client, sessions, scope, _, _ = http_memory
    created = await client.post("/api/v1/memories/", json=body())
    memory_id = created.json()["id"]
    async with sessions() as db:
        db.add(User(id="other", email="other@example.test", hashed_password="unused"))
        await db.flush()
        memory = await db.get(Memory, memory_id)
        memory.author_id = "other"
        db.add(
            MemoryShare(
                id="editor",
                memory_id=memory_id,
                shared_with_user_id=scope.actor_id,
                shared_by="other",
                permissions={"edit": True},
            )
        )
        await db.commit()
    await enroll(sessions, scope)
    async with sessions() as db:
        membership = (await db.scalars(select(UserProject))).one()
        membership.role = "member"
        await db.commit()
    request_headers = command_headers(1)
    payload = {"title": "Updated", "version": 1}
    first = await client.patch(
        f"/api/v1/memories/{memory_id}", json=payload, headers=request_headers
    )
    assert first.status_code == 200, first.text
    denied_delete = await client.delete(f"/api/v1/memories/{memory_id}", headers=command_headers(2))
    assert denied_delete.status_code == 403, denied_delete.text
    async with sessions() as db:
        await db.delete(await db.get(MemoryShare, "editor"))
        await db.commit()
    denied_replay = await client.patch(
        f"/api/v1/memories/{memory_id}", json=payload, headers=request_headers
    )
    assert denied_replay.status_code == 403, denied_replay.text


async def test_disabled_patch_preserves_legacy_expired_share_and_null_field_semantics(http_memory):
    from datetime import UTC, datetime, timedelta

    from src.infrastructure.adapters.secondary.persistence.models import MemoryShare, User

    client, sessions, scope, _, _ = http_memory
    created = await client.post("/api/v1/memories/", json=body())
    memory_id = created.json()["id"]
    async with sessions() as db:
        db.add(User(id="other", email="other@example.test", hashed_password="unused"))
        await db.flush()
        memory = await db.get(Memory, memory_id)
        memory.author_id = "other"
        membership = (await db.scalars(select(UserProject))).one()
        membership.role = "viewer"
        db.add(
            MemoryShare(
                id="legacy-editor",
                memory_id=memory_id,
                shared_with_user_id=scope.actor_id,
                shared_by="other",
                permissions={"edit": True},
                expires_at=datetime.now(UTC) - timedelta(days=1),
            )
        )
        await db.commit()
    response = await client.patch(
        f"/api/v1/memories/{memory_id}",
        json={"version": 1, "title": None, "entities": [], "tags": ["legacy"]},
        headers={"Idempotency-Key": "ignored", "X-Memory-Expected-Revision": "ignored"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["title"] == "Online"
    assert response.json()["tags"] == ["legacy"]
    async with sessions() as db:
        assert (await db.scalars(select(Change))).all() == []
        assert (await db.scalars(select(Receipt))).all() == []
