"""Actual existing HTTP routes carry live authorization, CAS headers and exact replay."""

from __future__ import annotations

import json

import pytest
from sqlalchemy import text, update

from src.application.schemas.schema import EntityTypeCreate
from src.infrastructure.adapters.secondary.persistence.models import User, UserProject
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error
from src.infrastructure.plugins.v2.schema_services import SchemaAccessDeniedV2
from src.tests.integration.project_schema_command_support import activated
from src.tests.integration.project_schema_http_support import (
    headers,
    http_client,
    live_schema_pg as _live_schema_pg,
    schema_command_pg as _schema_command_pg,
    schema_host as _schema_host,
    schema_http_pg as _schema_http_pg,
    schema_storage_pg as _schema_storage_pg,
)
from src.tests.integration.test_project_schema_m0 import authority

schema_storage_pg = _schema_storage_pg
schema_command_pg = _schema_command_pg
live_schema_pg = _live_schema_pg
schema_http_pg = _schema_http_pg
schema_host = _schema_host
pytestmark = pytest.mark.integration
BASE = "/api/v1/projects/project-a/schema"


async def test_all_eight_routes_use_cas_and_replay_original_bytes(schema_http_pg, schema_host):
    _, sessions = schema_http_pg
    await activated(sessions)
    async with http_client(schema_host, sessions) as client:
        create_headers = headers()
        create_body = {"name": "Place", "status": "DISABLED", "source": "user"}
        entity = await client.post(BASE + "/entities", json=create_body, headers=create_headers)
        assert entity.status_code == 200
        assert entity.json()["status"] == "DISABLED"
        entity_id = entity.json()["id"]
        changed = await client.put(
            BASE + "/entities/" + entity_id, json={"description": "later"}, headers=headers(2)
        )
        assert changed.status_code == 200
        assert changed.json()["created_at"] == entity.json()["created_at"]
        edge = await client.post(BASE + "/edges", json={"name": "VISITS"}, headers=headers(3))
        assert edge.status_code == 200
        edge_id = edge.json()["id"]
        changed_edge = await client.put(
            BASE + "/edges/" + edge_id, json={"description": "later edge"}, headers=headers(4)
        )
        assert changed_edge.status_code == 200
        mapping = await client.post(
            BASE + "/mappings",
            json={"source_type": "Person", "target_type": "Place", "edge_type": "VISITS"},
            headers=headers(5),
        )
        assert mapping.status_code == 200
        referenced = await client.delete(BASE + "/entities/" + entity_id, headers=headers(6))
        assert referenced.status_code == 409
        assert referenced.json()["detail"]["code"] == "project_schema_type_referenced"
        removed_map = await client.delete(
            BASE + "/mappings/" + mapping.json()["id"], headers=headers(6)
        )
        assert removed_map.status_code == 204 and removed_map.content == b""
        assert removed_map.headers["X-Project-Schema-Revision"] == "7"
        delete_headers = headers(7)
        removed_entity = await client.delete(
            BASE + "/entities/" + entity_id, headers=delete_headers
        )
        assert removed_entity.status_code == 204
        removed_edge = await client.delete(BASE + "/edges/" + edge_id, headers=headers(8))
        assert removed_edge.status_code == 204
        replay = await client.post(BASE + "/entities", json=create_body, headers=create_headers)
        assert replay.content == entity.content
        assert replay.headers["X-Project-Schema-Revision"] == "2"
        replay_delete = await client.delete(BASE + "/entities/" + entity_id, headers=delete_headers)
        assert replay_delete.status_code == 204 and replay_delete.content == b""
        assert replay_delete.headers["X-Project-Schema-Revision"] == "8"


async def test_legacy_with_preconditions_rejects_but_plain_legacy_write_stays_legacy(
    schema_http_pg, schema_host
):
    engine, sessions = schema_http_pg
    async with http_client(schema_host, sessions) as client:
        requested = await client.post(BASE + "/entities", json={"name": "Place"}, headers=headers())
        assert requested.status_code == 409
        assert requested.json()["detail"]["code"] == "project_schema_active_required"
        malformed = await client.post(
            BASE + "/entities",
            json={"name": "Place"},
            headers={"X-Project-Schema-Expected-Revision": "invalid"},
        )
        assert malformed.status_code == 409
        plain = await client.post(BASE + "/entities", json={"name": "Place"})
        assert plain.status_code == 200
        assert "X-Project-Schema-Revision" not in plain.headers
    async with engine.connect() as db:
        assert await db.scalar(text("SELECT count(*) FROM project_schema_heads")) == 0
        assert await db.scalar(text("SELECT count(*) FROM entity_types WHERE name='Place'")) == 1
        assert await db.scalar(text("SELECT count(*) FROM project_schema_http_receipts")) == 0


@pytest.mark.parametrize(
    "raw",
    [
        '{"name":"Place","schema":{"number":NaN}}',
        '{"name":"Place","schema":{"number":Infinity}}',
        '{"name":"Place","schema":{"text":"\\ud800"}}',
    ],
)
async def test_nonportable_raw_json_is_422(schema_http_pg, schema_host, raw):
    engine, sessions = schema_http_pg
    await activated(sessions)
    async with http_client(schema_host, sessions) as client:
        response = await client.post(
            BASE + "/entities",
            content=raw.encode(),
            headers={**headers(), "Content-Type": "application/json"},
        )
        assert response.status_code == 422
        assert response.json()["detail"]["code"] == "project_schema_mutation_invalid"
    async with engine.connect() as db:
        assert await db.scalar(text("SELECT revision FROM project_schema_heads")) == 1
        assert await db.scalar(text("SELECT count(*) FROM project_schema_http_receipts")) == 0


@pytest.mark.parametrize("retire", ["membership", "user", "operation", "generation"])
async def test_precommit_revocation_returns_no_receipt_and_rolls_back(
    schema_http_pg, schema_host, monkeypatch, retire
):
    import src.infrastructure.adapters.secondary.persistence.sql_project_schema_http_commands as module

    engine, sessions = schema_http_pg
    await activated(sessions)
    async with authority(schema_host, sessions) as value:
        original = module._replay_http

        async def retire_after_receipt(*args, **kwargs):
            receipt = await original(*args, **kwargs)
            if receipt is not None:
                if retire == "operation":
                    await value.operation.dispose()
                elif retire == "generation":
                    await value.operation.generation.dispose()
                else:
                    async with sessions.begin() as change:
                        if retire == "membership":
                            await change.execute(
                                update(UserProject)
                                .where(UserProject.user_id == "owner")
                                .values(role="viewer")
                            )
                        else:
                            await change.execute(
                                update(User).where(User.id == "owner").values(is_active=False)
                            )
            return receipt

        monkeypatch.setattr(module, "_replay_http", retire_after_receipt)
        expected_error = (
            RuntimeV2Error if retire in {"operation", "generation"} else SchemaAccessDeniedV2
        )
        with pytest.raises(expected_error):
            await value.services.create_entity_type(
                user_id="owner",
                project_id="project-a",
                data=EntityTypeCreate(name="Place"),
                expected_revision="1",
                change_id=headers()["X-Project-Schema-Change-Id"],
            )
    async with engine.connect() as db:
        assert await db.scalar(text("SELECT revision FROM project_schema_heads")) == 1
        assert await db.scalar(text("SELECT count(*) FROM project_schema_http_receipts")) == 0
        assert await db.scalar(text("SELECT count(*) FROM entity_types")) == 1


async def test_active_command_never_flushes_unrelated_request_session(schema_http_pg, schema_host):
    engine, sessions = schema_http_pg
    await activated(sessions)
    async with authority(schema_host, sessions) as value:
        pending = User(id="unrelated", email="unrelated@example.test", hashed_password="unused")
        value.db.add(pending)
        receipt = await value.services.create_entity_type(
            user_id="owner",
            project_id="project-a",
            data=EntityTypeCreate(name="Place"),
            expected_revision="1",
            change_id=headers()["X-Project-Schema-Change-Id"],
        )
        assert json.loads(receipt.to_dict()["body"])["name"] == "Place"
        assert pending in value.db.new
        async with engine.connect() as db:
            assert await db.scalar(text("SELECT count(*) FROM users WHERE id='unrelated'")) == 0


@pytest.mark.parametrize("invalid", ["name", "schema_size", "schema_depth", "target_id"])
async def test_invalid_client_contract_is_422_and_does_not_write(
    schema_http_pg, schema_host, invalid
):
    engine, sessions = schema_http_pg
    await activated(sessions)
    body = {"name": "Place"}
    if invalid == "name":
        body["name"] = ""
    elif invalid == "schema_size":
        body["schema"] = {"description": "x" * 16_385}
    elif invalid == "schema_depth":
        nested = {}
        for _ in range(17):
            nested = {"child": nested}
        body["schema"] = nested
    async with http_client(schema_host, sessions) as client:
        response = (
            await client.delete(BASE + "/entities/not-a-uuid", headers=headers())
            if invalid == "target_id"
            else await client.post(BASE + "/entities", json=body, headers=headers())
        )
        assert response.status_code == 422
        assert response.json()["detail"]["code"] == "project_schema_mutation_invalid"
    async with engine.connect() as db:
        assert await db.scalar(text("SELECT revision FROM project_schema_heads")) == 1
        assert await db.scalar(text("SELECT count(*) FROM project_schema_http_receipts")) == 0
