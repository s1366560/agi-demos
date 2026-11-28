"""Search persisted memories using an enabled signed command and its admitted project."""

import pytest

from plugins.business.knowledge.backend.project_memory_operation import list_project_memories
from src.infrastructure.adapters.secondary.persistence.models import Memory, Project, Tenant
from src.tests.unit.routers.test_optional_business_http_v2 import http, publisher  # noqa: F401

pytestmark = [pytest.mark.unit, pytest.mark.asyncio(loop_scope="session")]
BASE = "/api/v1/platform-plugins/v2/optional-business"
CAPABILITY = "app.knowledge.memories.read"


async def test_signed_project_search_checks_scope_before_reading(http, publisher, db_session):  # noqa: F811
    client, keys = http
    app = client._transport.app
    app.state.package_operations_v1 = {CAPABILITY: list_project_memories}
    db_session.add(Tenant(id="other", name="Other", slug="unrelated", owner_id="viewer"))
    await db_session.flush()
    for key, tenant in (("elsewhere", "t"), ("private", "other")):
        db_session.add(Project(id=key, tenant_id=tenant, name=key, owner_id="viewer"))
    await db_session.flush()
    for project, title in (
        ("p", "First"),
        ("p", "Second"),
        ("private", "Hidden"),
        ("elsewhere", "Third"),
    ):
        db_session.add(
            Memory(
                id=title,
                project_id=project,
                author_id="owner",
                title=title,
                content="shared term" + "x" * 400,
                meta={"source": "private author details"},
            )
        )
    await db_session.commit()

    headers = {"Authorization": f"Bearer {keys['owner']}"}
    scope = {"project_id": "p", "tenant_id": "t"}
    body, digest = publisher[1](application_command={"list-memories": CAPABILITY})
    base = BASE + "/sample.notes"
    assert (await client.post(BASE + "/install", json=body, headers=headers)).is_success
    assert (await client.post(base + "/enable", json=scope, headers=headers)).is_success

    async def search(payload, binding=scope, actor=headers):
        return await client.post(
            base + "/commands",
            headers=actor,
            json={
                **binding,
                "expected_digest": digest,
                "command_id": "list-memories",
                "payload": payload,
            },
        )

    first = (await search({"search": "shared", "limit": 1})).json()
    second = (await search({"search": "shared", "limit": 1, "offset": 1})).json()
    assert first["has_more"] and not second["has_more"]
    assert {first["items"][0]["title"], second["items"][0]["title"]} == {"First", "Second"}
    summary = first["items"][0]
    assert set(summary) == {"id", "title", "excerpt", "content_type"}
    assert len(summary["excerpt"]) == 320
    assert (await search({"search": "Hidden"})).json()["items"] == []
    for binding in [
        {"project_id": "private", "tenant_id": "other"},
        {"project_id": "private", "tenant_id": "t"},
        {"project_id": "elsewhere", "tenant_id": "t"},
    ]:
        assert (await search({}, binding)).status_code in {403, 404}
    assert (await search({"project_id": "private"})).status_code in {400, 422}
    assert (
        await search({}, actor={"Authorization": f"Bearer {keys['viewer']}"})
    ).status_code == 403
