"""Exercise the package editor against the actual memory HTTP mutation handlers."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from plugins.business.knowledge.backend.memory_maintenance import delete_memory, reindex_memory
from plugins.business.knowledge.backend.package_memory_editor import save_memory
from plugins.business.knowledge.backend.project_memory_operation import list_project_memories
from src.infrastructure.adapters.primary.web.routers import memories
from src.tests.unit.routers.test_optional_business_http_v2 import http, publisher  # noqa: F401

pytestmark = [pytest.mark.unit, pytest.mark.asyncio(loop_scope="session")]
BASE = "/api/v1/platform-plugins/v2/optional-business"
SCOPE = {"tenant_id": "t", "project_id": "p"}


async def test_signed_editor_persists_and_pins_revisions(http, publisher, db_session, monkeypatch):  # noqa: F811
    client, keys = http
    app = client._transport.app
    app.include_router(memories.router)
    app.state.package_operations_v1 = {
        "app.knowledge.memories.read": list_project_memories,
        "app.knowledge.memories.write": save_memory,
        "app.knowledge.memories.delete": delete_memory,
        "app.knowledge.memories.reindex": reindex_memory,
    }
    graph = SimpleNamespace(ensure_episodic_node=AsyncMock())
    commands = SimpleNamespace(
        open=AsyncMock(return_value=SimpleNamespace(enabled=False)),
        open_memory=AsyncMock(
            return_value=SimpleNamespace(enabled=False, scope=SimpleNamespace(project_id="p"))
        ),
    )
    app.dependency_overrides[memories.memory_application_authority_dependency_v2] = (
        lambda: SimpleNamespace(
            db=db_session, services=SimpleNamespace(online_commands=commands, graph_service=graph)
        )
    )
    app.dependency_overrides[memories.workflow_engine_authority_dependency_v2] = (
        lambda: SimpleNamespace(start_workflow=AsyncMock())
    )
    monkeypatch.setattr(memories, "_background_index_memory", AsyncMock())
    body, digest = publisher[1](
        application_command={
            "read-memory": "app.knowledge.memories.read",
            "delete-memory": "app.knowledge.memories.delete",
            "reindex-memory": "app.knowledge.memories.reindex",
            "save-memory": "app.knowledge.memories.write",
        }
    )
    owner = {"Authorization": "Bearer " + keys["owner"]}
    assert (await client.post(BASE + "/install", json=body, headers=owner)).is_success
    assert (await client.post(BASE + "/sample.notes/enable", json=SCOPE, headers=owner)).is_success

    async def invoke(command, payload, role="owner"):
        return await client.post(
            BASE + "/sample.notes/commands",
            json={**SCOPE, "expected_digest": digest, "command_id": command, "payload": payload},
            headers={"Authorization": "Bearer " + keys[role]},
        )

    draft = {"title": "Draft", "content": "Private", "tags": [], "savedAt": "2026-11-24"}
    assert (await invoke("save-memory", {"draft": draft})).json() == {"saved": True}
    assert (await invoke("read-memory", {"draft": True})).json() == {"draft": draft}
    assert (await invoke("save-memory", {"draft": draft}, "viewer")).status_code == 403

    initial = {"title": "First", "content": "Original", "change_id": str(uuid4()), "version": 0}
    assert (await invoke("save-memory", initial, "viewer")).status_code == 403
    assert (await invoke("save-memory", {**initial, "project_id": "other"})).status_code in (
        400,
        422,
    )
    created = await invoke("save-memory", initial)
    assert created.is_success, created.text
    record = created.json()
    assert record["title"] == "First" and record["version"] == 1
    edit = {
        **initial,
        "id": record["id"],
        "version": 1,
        "title": "Revised",
        "change_id": str(uuid4()),
    }
    updated = await invoke("save-memory", edit)
    assert updated.is_success, updated.text
    assert updated.json()["version"] == 2
    assert (await invoke("save-memory", edit)).status_code == 409
    inspected = await invoke("read-memory", {"id": record["id"]})
    assert inspected.json()["title"] == "Revised"
    assert (await invoke("reindex-memory", {"id": "missing"})).status_code == 404
    assert (await invoke("reindex-memory", {"id": record["id"]}, "viewer")).status_code == 403
    deletion = {"id": record["id"], "version": 1, "change_id": str(uuid4())}
    assert (await invoke("delete-memory", deletion)).status_code == 409
    deletion["version"] = 2
    assert (await invoke("delete-memory", deletion, "viewer")).status_code == 403
    assert (await invoke("delete-memory", deletion)).json() == {
        "deleted": True,
        "memoryId": record["id"],
    }
    assert (await invoke("read-memory", {"id": record["id"]})).status_code == 404
