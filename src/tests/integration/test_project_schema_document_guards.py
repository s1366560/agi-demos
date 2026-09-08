"""Full-document atomic materialization, paging budgets and operation-owned sessions."""

from __future__ import annotations

import json
from uuid import uuid4

import pytest
from sqlalchemy import text

from src.domain.model.project_schema.commands import ProjectSchemaReceipt
from src.domain.model.project_schema.transport import (
    MAX_TRANSPORT_BYTES,
    SchemaHistoryQuery,
    SchemaReceiptQuery,
)
from src.infrastructure.adapters.secondary.persistence.models import User
from src.tests.integration.project_schema_command_support import SCHEMA_ID, activated, replacement
from src.tests.integration.project_schema_http_support import (
    headers as mutation_headers,
    http_client,
    live_schema_pg as _live_schema_pg,
    schema_command_pg as _schema_command_pg,
    schema_host as _schema_host,
    schema_http_pg as _schema_http_pg,
    schema_storage_pg as _schema_storage_pg,
)
from src.tests.integration.test_project_schema_document_api import BASE, body, observed
from src.tests.integration.test_project_schema_m0 import authority

schema_storage_pg = _schema_storage_pg
schema_command_pg = _schema_command_pg
live_schema_pg = _live_schema_pg
schema_http_pg = _schema_http_pg
schema_host = _schema_host
pytestmark = pytest.mark.integration


async def test_full_replacement_updates_entities_edges_and_mapping_atomically(
    schema_http_pg, schema_host
):
    engine, sessions = schema_http_pg
    _, bootstrap = await activated(sessions)
    entity_id = str(uuid4())

    def change(document):
        document["entity_types"][0].update(name="Actor", description="changed entity")
        document["entity_types"].append(
            {
                "id": entity_id,
                "name": "Place",
                "description": "",
                "schema": {},
                "status": "ENABLED",
                "source": "user",
            }
        )
        document["edge_types"][0].update(
            name="VISITS", status="DISABLED", description="changed edge"
        )
        document["mappings"][0].update(target_type_id=entity_id, status="DISABLED")

    command = replacement(bootstrap, change)
    async with http_client(schema_host, sessions) as client:
        headers = await observed(client)
        response = await client.post(BASE + "replace", json=body(command), headers=headers)
        assert response.status_code == 200, response.text
        assert response.json()["document"]["mappings"][0]["target_type_id"] == entity_id
    async with engine.connect() as db:
        row = (
            await db.execute(
                text("SELECT source_type, target_type, edge_type, status FROM edge_type_maps")
            )
        ).one()
        assert tuple(row) == ("Actor", "Place", "VISITS", "DISABLED")
        assert await db.scalar(text("SELECT count(*) FROM entity_types")) == 2
        assert await db.scalar(text("SELECT revision FROM project_schema_heads")) == 2
        assert await db.scalar(text("SELECT count(*) FROM project_schema_changes")) == 2
        assert await db.scalar(text("SELECT count(*) FROM project_schema_http_receipts")) == 0


async def test_actual_history_preserves_a_complete_prefix_below_two_mib(
    schema_http_pg, schema_host
):
    _, sessions = schema_http_pg
    _, previous = await activated(sessions)

    def enlarge(document):
        document["entity_types"].extend(
            {
                "id": str(uuid4()),
                "name": f"Type {n}",
                "description": "d" * 4000,
                "schema": {"text": "s" * 10000},
                "source": "user",
                "status": "ENABLED",
            }
            for n in range(70)
        )

    async with http_client(schema_host, sessions) as client:
        headers = await observed(client)
        for index in range(3):
            command = replacement(previous, enlarge if index == 0 else None)
            response = await client.post(BASE + "replace", json=body(command), headers=headers)
            assert response.status_code == 200, response.text[:500]
            previous = ProjectSchemaReceipt(receipt_json=response.text)
        page = await client.post(
            BASE + "history",
            json={"schema_id": SCHEMA_ID, "after_revision": 1, "limit": 100},
            headers=headers,
        )
        assert page.status_code == 200, page.text[:500]
        value = page.json()
        assert len(page.content) <= MAX_TRANSPORT_BYTES
        assert value["upper_revision"] == 4 and value["has_more"] is True
        assert [r["revision"] for r in value["receipts"]] == [2, 3]
        assert value["next_after_revision"] == 3
        final = await client.post(
            BASE + "history",
            json={"schema_id": SCHEMA_ID, "after_revision": 3, "limit": 100},
            headers=headers,
        )
        assert final.json()["receipts"][0]["revision"] == 4
        assert final.json()["has_more"] is False


async def test_document_services_never_flush_unrelated_request_orm_work(
    schema_http_pg, schema_host
):
    engine, sessions = schema_http_pg
    _, bootstrap = await activated(sessions)
    command = replacement(bootstrap)
    async with authority(schema_host, sessions) as value:
        pending = User(
            id="unrelated-m2", email="unrelated-m2@example.test", hashed_password="unused"
        )
        value.db.add(pending)
        service = value.services.documents
        assert (await service.read()).to_dict()["revision"] == 1
        accepted = await service.replace(command)
        receipt = await service.receipt(
            SchemaReceiptQuery(schema_id=SCHEMA_ID, change_id=command.change_id)
        )
        assert receipt.receipt_json == accepted.receipt_json
        history = await service.history(
            SchemaHistoryQuery(schema_id=SCHEMA_ID, after_revision=0, limit=100)
        )
        assert len(json.loads(history)["receipts"]) == 2
        assert pending in value.db.new
        async with engine.connect() as db:
            assert await db.scalar(text("SELECT count(*) FROM users WHERE id='unrelated-m2'")) == 0


async def test_m1_change_id_cannot_be_reused_as_full_replace(schema_http_pg, schema_host):
    _, sessions = schema_http_pg
    _, bootstrap = await activated(sessions)
    command = replacement(bootstrap)
    async with http_client(schema_host, sessions) as client:
        headers = await observed(client)
        response = await client.post(
            "/api/v1/projects/project-a/schema/entities",
            json={"name": "Place"},
            headers=mutation_headers(change_id=command.change_id),
        )
        assert response.status_code == 200
        response = await client.post(BASE + "replace", json=body(command), headers=headers)
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "project_schema_change_id_reused"


async def test_wrong_tenant_and_project_cannot_discover_receipt(schema_http_pg, schema_host):
    _, sessions = schema_http_pg
    _, bootstrap = await activated(sessions)
    request = {"schema_id": SCHEMA_ID, "change_id": bootstrap.to_dict()["change_id"]}
    async with http_client(schema_host, sessions) as client:
        headers = await observed(client)
        wrong_tenant = await client.post(
            BASE + "receipt?tenant_id=tenant-b", json=request, headers=headers
        )
        assert wrong_tenant.status_code == 403
        wrong_project = await client.post(
            "/api/v1/projects/project-b/schema/document/receipt", json=request, headers=headers
        )
        assert wrong_project.status_code == 403
        missing = await client.post(
            BASE + "receipt", json={**request, "schema_id": str(uuid4())}, headers=headers
        )
        assert missing.status_code == 404
