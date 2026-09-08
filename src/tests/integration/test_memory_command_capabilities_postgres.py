"""Command affordances reflect enrolled scope and the same write permission checks."""

import os
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from src.infrastructure.adapters.secondary.persistence.models import (
    Memory,
    MemoryShare,
    Project,
    User,
    UserProject,
    UserTenant,
)
from src.infrastructure.adapters.secondary.persistence.sql_online_memory_repository import (
    SqlOnlineMemoryRepository,
)
from src.tests.integration.test_memory_online_http_postgres import (
    body,
    enroll,
    http_memory as _http_memory,
    pg_sync as _pg_sync,
)

pg_sync = _pg_sync
http_memory = _http_memory
pytestmark = pytest.mark.skipif(
    os.getenv("KNOWLEDGE_SYNC_POSTGRES_TESTS") != "1",
    reason="Requires the isolated knowledge sync PostgreSQL database",
)


async def page(client):
    response = await client.get("/api/v1/memories/?project_id=project&page=1&page_size=50")
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize(
    "role,expected",
    [("owner", ["update", "delete"]), ("member", ["update", "delete"]), ("viewer", [])],
)
async def test_enrolled_page_projects_exact_scope_and_object_actions(http_memory, role, expected):
    client, sessions, scope, _, _ = http_memory
    created = await client.post("/api/v1/memories/", json=body())
    assert created.status_code == 201, created.text
    await enroll(sessions, scope)
    async with sessions() as db:
        (await db.get(UserProject, "up")).role = role
        await db.commit()
    result = await page(client)
    capability = result["command_capabilities"]
    assert capability == {
        "protocol_version": 1,
        "tenant_id": "tenant",
        "project_id": "project",
        "actor_id": "actor",
        "allowed_actions": ["create"] if expected else [],
        "objects": [
            {"memory_id": created.json()["id"], "revision": 1, "allowed_actions": expected}
        ],
    }


async def test_disabled_page_keeps_read_without_advertising_legacy_writes(http_memory):
    client, _, _, _, _ = http_memory
    await client.post("/api/v1/memories/", json=body())
    result = await page(client)
    assert len(result["memories"]) == 1
    assert result["command_capabilities"] is None


@pytest.mark.parametrize("expires,expected", [(None, ["update"]), (-1, []), (60, ["update"])])
async def test_edit_share_does_not_grant_delete_and_expiry_is_enforced(
    http_memory, expires, expected
):
    client, sessions, scope, _, _ = http_memory
    created = await client.post("/api/v1/memories/", json=body())
    memory_id = created.json()["id"]
    async with sessions() as db:
        db.add(User(id="other", email="other@example.test", hashed_password="unused"))
        await db.flush()
        (await db.get(Memory, memory_id)).author_id = "other"
        db.add(
            MemoryShare(
                id="share",
                memory_id=memory_id,
                shared_with_user_id="actor",
                shared_by="other",
                permissions={"edit": True},
                expires_at=None
                if expires is None
                else datetime.now(UTC) + timedelta(seconds=expires),
            )
        )
        await db.commit()
    await enroll(sessions, scope)
    async with sessions() as db:
        (await db.get(UserProject, "up")).role = "member"
        await db.commit()
    capability = (await page(client))["command_capabilities"]
    assert capability["allowed_actions"] == ["create"]
    assert capability["objects"] == [
        {"memory_id": memory_id, "revision": 1, "allowed_actions": expected}
    ]


async def test_revoked_tenant_membership_removes_commands_without_widening_legacy_access(
    http_memory,
):
    client, sessions, scope, _, _ = http_memory
    await client.post("/api/v1/memories/", json=body())
    await enroll(sessions, scope)
    assert (await page(client))["command_capabilities"] is not None
    async with sessions() as db:
        await db.delete(await db.get(UserTenant, "ut"))
        await db.commit()
    assert (await page(client))["command_capabilities"] is None


async def test_capability_failure_is_local_to_commands(http_memory, monkeypatch):
    client, sessions, scope, _, _ = http_memory
    await client.post("/api/v1/memories/", json=body())
    await enroll(sessions, scope)

    async def unavailable(*args, **kwargs):
        raise RuntimeError("injected capability failure")

    monkeypatch.setattr(SqlOnlineMemoryRepository, "capabilities", unavailable)
    result = await page(client)
    assert len(result["memories"]) == 1
    assert result["command_capabilities"] is None


async def test_capabilities_never_attach_actions_to_stale_or_foreign_page_rows(http_memory):
    client, sessions, scope, _, _ = http_memory
    memory_id = (await client.post("/api/v1/memories/", json=body())).json()["id"]
    await enroll(sessions, scope)
    async with sessions() as db:
        db.add(Project(id="other-project", name="Other", tenant_id="tenant", owner_id="actor"))
        await db.flush()
        db.add(
            Memory(
                id="foreign",
                project_id="other-project",
                author_id="actor",
                title="Other",
                content="Other content",
                content_type="text",
            )
        )
        await db.commit()
        result = await SqlOnlineMemoryRepository(db).capabilities(
            "actor", "project", ((memory_id, 2), ("missing", 1), ("foreign", 1))
        )
        assert result.objects == ()
        assert len((await db.scalars(select(Memory))).all()) == 2


@pytest.mark.parametrize("remaining", [0, 1])
async def test_capabilities_stop_advertising_writes_at_revision_limit(http_memory, remaining):
    from src.domain.model.knowledge_sync.contracts import MAX_REVISION

    client, sessions, scope, _, _ = http_memory
    memory_id = (await client.post("/api/v1/memories/", json=body())).json()["id"]
    async with sessions() as db:
        (await db.get(Memory, memory_id)).version = MAX_REVISION - remaining
        await db.commit()
    await enroll(sessions, scope)
    async with sessions() as db:
        result = await SqlOnlineMemoryRepository(db).capabilities(
            "actor", "project", ((memory_id, MAX_REVISION - remaining),)
        )
        assert result.allowed_actions == ("create",)
        if remaining:
            assert result.objects[0].allowed_actions == ("update", "delete")
        else:
            assert result.objects == ()


async def test_repository_capabilities_require_enrollment_and_current_membership(http_memory):
    _, sessions, scope, _, _ = http_memory
    async with sessions() as db:
        assert await SqlOnlineMemoryRepository(db).capabilities("actor", "project", ()) is None
    await enroll(sessions, scope)
    async with sessions() as db:
        await db.delete(await db.get(UserTenant, "ut"))
        await db.commit()
        assert await SqlOnlineMemoryRepository(db).capabilities("actor", "project", ()) is None
