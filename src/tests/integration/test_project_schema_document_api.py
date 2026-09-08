"""Cloud full snapshots use real HTTP, live generation authority and durable receipts."""

from __future__ import annotations

import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import insert, text, update

from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.secondary.persistence.models import User, UserProject, UserTenant
from src.tests.integration.project_schema_command_support import (
    SCHEMA_ID,
    activated,
    replacement,
)
from src.tests.integration.project_schema_http_support import (
    http_client,
    live_schema_pg as _live_schema_pg,
    schema_command_pg as _schema_command_pg,
    schema_host as _schema_host,
    schema_http_pg as _schema_http_pg,
    schema_storage_pg as _schema_storage_pg,
)

schema_storage_pg = _schema_storage_pg
schema_command_pg = _schema_command_pg
live_schema_pg = _live_schema_pg
schema_http_pg = _schema_http_pg
schema_host = _schema_host
pytestmark = pytest.mark.integration
BASE = "/api/v1/projects/project-a/schema/document/"
GENERATION = "X-Memstack-Knowledge-Sync-Generation"


async def observed(client):
    response = await client.post(BASE + "read", json={})
    assert response.status_code == 200, response.text
    return {GENERATION: json.dumps(response.json()["generation"])}


def body(command):
    return {
        "document": command.document.to_dict(),
        "expected_revision": command.expected_revision,
        "change_id": command.change_id,
    }


async def test_exact_replace_replay_receipt_and_history_after_later_terminal_write(
    schema_http_pg, schema_host
):
    _, sessions = schema_http_pg
    _, bootstrap = await activated(sessions)
    command = replacement(
        bootstrap, lambda d: d["entity_types"][0].update(description="full snapshot")
    )
    async with http_client(schema_host, sessions) as client:
        headers = await observed(client)
        accepted = await client.post(BASE + "replace", json=body(command), headers=headers)
        assert accepted.status_code == 200, accepted.text
        value = accepted.json()
        terminal = value["document"]
        terminal["revision"] = 3
        terminal["deleted"] = True
        for key, kind in [
            ("entity_types", "entity_type"),
            ("edge_types", "edge_type"),
            ("mappings", "mapping"),
        ]:
            terminal["tombstones"].extend(
                {"id": item["id"], "kind": kind, "deleted_revision": 3} for item in terminal[key]
            )
            terminal[key] = []
        deleted = await client.post(
            BASE + "replace",
            json={"document": terminal, "expected_revision": 2, "change_id": str(uuid4())},
            headers=headers,
        )
        assert deleted.status_code == 200, deleted.text
        replay = await client.post(BASE + "replace", json=body(command), headers=headers)
        assert replay.content == accepted.content
        receipt = await client.post(
            BASE + "receipt",
            json={"schema_id": SCHEMA_ID, "change_id": command.change_id},
            headers=headers,
        )
        assert receipt.content == accepted.content
        current = await client.post(BASE + "read", json={})
        assert current.json()["document"]["revision"] == 3
        page = await client.post(
            BASE + "history",
            json={"schema_id": SCHEMA_ID, "after_revision": 0, "limit": 2},
            headers=headers,
        )
        assert page.status_code == 200, page.text
        assert [r["revision"] for r in page.json()["receipts"]] == [1, 2]
        assert page.json()["has_more"] is True and page.json()["upper_revision"] == 3
        assert accepted.content in page.content
        final = await client.post(
            BASE + "history",
            json={"schema_id": SCHEMA_ID, "after_revision": 2, "limit": 100},
            headers=headers,
        )
        assert final.json()["next_after_revision"] == 3 and final.json()["has_more"] is False
        empty = await client.post(
            BASE + "history",
            json={"schema_id": SCHEMA_ID, "after_revision": 3, "limit": 100},
            headers=headers,
        )
        assert empty.json()["receipts"] == []


async def test_legacy_read_observes_without_memory_enrollment_and_does_not_bootstrap(
    schema_http_pg, schema_host
):
    engine, sessions = schema_http_pg
    async with http_client(schema_host, sessions) as client:
        response = await client.post(BASE + "read", json={})
        assert response.status_code == 200 and response.json()["document"] is None
        headers = {GENERATION: json.dumps(response.json()["generation"])}
        history = await client.post(
            BASE + "history",
            json={"schema_id": SCHEMA_ID, "after_revision": 0, "limit": 10},
            headers=headers,
        )
        assert history.status_code == 409
    async with engine.connect() as db:
        assert await db.scalar(text("SELECT count(*) FROM project_schema_heads")) == 0


@pytest.mark.parametrize(
    "raw",
    [
        b'{"x":1,"x":2}',
        b'{"x":NaN}',
        b'{"x":Infinity}',
        b'{"x":1e999}',
        b'{"x":"\\ud800"}',
        b"[]",
        b"{}garbage",
        b"\xff",
        b'{"actor_id":"owner"}',
    ],
)
async def test_raw_read_body_rejected_before_authority(
    schema_http_pg, schema_host, raw, monkeypatch
):
    from src.infrastructure.plugins.v2.schema_authorization import SqlProjectSchemaAuthorizationV2

    async def forbidden(*args, **kwargs):
        pytest.fail("malformed transport reached database authorization")

    monkeypatch.setattr(SqlProjectSchemaAuthorizationV2, "discover_scope", forbidden)
    _, sessions = schema_http_pg
    async with http_client(schema_host, sessions) as client:
        response = await client.post(BASE + "read", content=raw)
        assert response.status_code == 422


async def test_generation_condition_missing_duplicate_malformed_stale(schema_http_pg, schema_host):
    _, sessions = schema_http_pg
    async with http_client(schema_host, sessions) as client:
        good = await observed(client)
        request = {"schema_id": SCHEMA_ID, "change_id": str(uuid4())}
        missing = await client.post(BASE + "receipt", json=request)
        assert missing.status_code == 428
        duplicate = await client.post(
            BASE + "receipt",
            json=request,
            headers=[(GENERATION, good[GENERATION]), (GENERATION, good[GENERATION])],
        )
        assert duplicate.status_code == 400
        invalid = await client.post(
            BASE + "receipt", json=request, headers={GENERATION: '{"x":1,"x":1}'}
        )
        assert invalid.status_code == 400
        descriptor = json.loads(good[GENERATION])
        descriptor["descriptor"]["generation"] += 1
        stale = await client.post(
            BASE + "receipt", json=request, headers={GENERATION: json.dumps(descriptor)}
        )
        assert stale.status_code == 412


async def test_stale_cas_scope_and_shared_bootstrap_change_identity(schema_http_pg, schema_host):
    _, sessions = schema_http_pg
    _, bootstrap = await activated(sessions)
    command = replacement(bootstrap)
    async with http_client(schema_host, sessions) as client:
        headers = await observed(client)
        collision = body(command)
        collision["change_id"] = bootstrap.to_dict()["change_id"]
        response = await client.post(BASE + "replace", json=collision, headers=headers)
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "project_schema_change_id_reused"
        scope = body(command)
        scope["document"]["tenant_id"] = "tenant-b"
        response = await client.post(BASE + "replace", json=scope, headers=headers)
        assert response.status_code == 422
        response = await client.post(BASE + "replace", json=body(command), headers=headers)
        assert response.status_code == 200
        stale = body(command)
        stale["change_id"] = str(uuid4())
        response = await client.post(BASE + "replace", json=stale, headers=headers)
        assert response.status_code == 409
        for cursor in [-1, 3]:
            response = await client.post(
                BASE + "history",
                json={"schema_id": SCHEMA_ID, "after_revision": cursor, "limit": 1},
                headers=headers,
            )
            assert response.status_code == 422
        response = await client.post(
            BASE + "history",
            json={"schema_id": str(uuid4()), "after_revision": 0, "limit": 1},
            headers=headers,
        )
        assert response.status_code == 409


async def test_history_project_readable_but_receipt_actor_scoped(schema_http_pg, schema_host):
    engine, sessions = schema_http_pg
    _, bootstrap = await activated(sessions)
    async with engine.begin() as db:
        await db.execute(
            insert(User).values(
                id="reader", email="reader@example.test", hashed_password="unused", is_active=True
            )
        )
        await db.execute(
            insert(UserTenant).values(
                id="reader-tenant", user_id="reader", tenant_id="tenant-a", role="member"
            )
        )
        await db.execute(
            insert(UserProject).values(
                id="reader-project", user_id="reader", project_id="project-a", role="viewer"
            )
        )
    async with http_client(schema_host, sessions) as client:
        headers = await observed(client)
        client._transport.app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
            id="reader"
        )
        receipt = await client.post(
            BASE + "receipt",
            json={"schema_id": SCHEMA_ID, "change_id": bootstrap.to_dict()["change_id"]},
            headers=headers,
        )
        assert receipt.status_code == 404
        history = await client.post(
            BASE + "history",
            json={"schema_id": SCHEMA_ID, "after_revision": 0, "limit": 100},
            headers=headers,
        )
        assert history.status_code == 200 and len(history.json()["receipts"]) == 1
        denied = await client.post(
            BASE + "replace", json=body(replacement(bootstrap)), headers=headers
        )
        assert denied.status_code == 403
        async with engine.begin() as db:
            await db.execute(
                update(UserProject).where(UserProject.user_id == "reader").values(role="owner")
            )
        accepted = await client.post(
            BASE + "replace", json=body(replacement(bootstrap)), headers=headers
        )
        assert accepted.status_code == 200, accepted.text
        client._transport.app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
            id="owner"
        )
        history = await client.post(
            BASE + "history",
            json={"schema_id": SCHEMA_ID, "after_revision": 0, "limit": 100},
            headers=headers,
        )
        assert [r["revision"] for r in history.json()["receipts"]] == [1, 2]


@pytest.mark.parametrize("operation", ["receipt", "history"])
async def test_corrupt_stored_receipt_is_internal_error(
    schema_http_pg, schema_host, monkeypatch, operation
):
    import src.infrastructure.adapters.secondary.persistence.project_schema_history as history_module

    _, sessions = schema_http_pg
    _, bootstrap = await activated(sessions)
    original = history_module.validate_stored_receipt

    def corrupt(_raw, **kwargs):
        return original('{"revision": true}', **kwargs)

    monkeypatch.setattr(history_module, "validate_stored_receipt", corrupt)
    request = {"schema_id": SCHEMA_ID}
    request.update(
        {"change_id": bootstrap.to_dict()["change_id"]}
        if operation == "receipt"
        else {"after_revision": 0, "limit": 100}
    )
    async with http_client(schema_host, sessions) as client:
        headers = await observed(client)
        with pytest.raises(RuntimeError, match="corrupt stored schema receipt"):
            await client.post(BASE + operation, json=request, headers=headers)


@pytest.mark.parametrize("operation", ["receipt", "history"])
@pytest.mark.parametrize("retire", ["membership", "generation"])
async def test_readback_rechecks_live_authority_before_return(
    schema_http_pg, schema_host, monkeypatch, operation, retire
):
    import src.infrastructure.adapters.secondary.persistence.sql_project_schema_commands as commands_module
    from src.infrastructure.plugins.v2.boundary import current_generation_v2
    from src.infrastructure.plugins.v2.runtime import RuntimeV2Error

    engine, sessions = schema_http_pg
    _, bootstrap = await activated(sessions)
    symbol = "exact_receipt" if operation == "receipt" else "receipt_history"
    original = getattr(commands_module, symbol)

    async def revoke(*args, **kwargs):
        result = await original(*args, **kwargs)
        if retire == "generation":
            await current_generation_v2().dispose()
        else:
            async with engine.begin() as db:
                await db.execute(update(User).where(User.id == "owner").values(is_active=False))
        return result

    monkeypatch.setattr(commands_module, symbol, revoke)
    request = {"schema_id": SCHEMA_ID}
    request.update(
        {"change_id": bootstrap.to_dict()["change_id"]}
        if operation == "receipt"
        else {"after_revision": 0, "limit": 100}
    )
    async with http_client(schema_host, sessions) as client:
        headers = await observed(client)
        if retire == "generation":
            with pytest.raises(RuntimeV2Error):
                await client.post(BASE + operation, json=request, headers=headers)
        else:
            response = await client.post(BASE + operation, json=request, headers=headers)
            assert response.status_code == 403


async def test_generation_raw_unicode_is_invalid_before_descriptor_parse(
    schema_http_pg, schema_host
):
    _, sessions = schema_http_pg
    async with http_client(schema_host, sessions) as client:
        good = await observed(client)
        envelope = json.loads(good[GENERATION])
        envelope["descriptor"]["profile_id"] = "\ud800"
        response = await client.post(
            BASE + "read", json={}, headers={GENERATION: json.dumps(envelope)}
        )
        assert response.status_code == 400
