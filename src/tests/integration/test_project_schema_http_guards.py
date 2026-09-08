"""Database authority for HTTP intent, immutable receipts and commit-time rows."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from src.domain.model.project_schema.document import ProjectSchemaDocument
from src.domain.model.project_schema.validation import ProjectSchemaError
from src.tests.integration.project_schema_command_support import Authorization, activated
from src.tests.integration.project_schema_http_support import (
    http_revision,
    live_schema_pg as _live_schema_pg,
    mutation,
    schema_command_pg as _schema_command_pg,
    schema_http_pg as _schema_http_pg,
    schema_storage_pg as _schema_storage_pg,
)
from src.tests.integration.test_project_schema_http_commands import executor

schema_storage_pg = _schema_storage_pg
schema_command_pg = _schema_command_pg
live_schema_pg = _live_schema_pg
schema_http_pg = _schema_http_pg
pytestmark = pytest.mark.integration


async def assert_unmodified(engine):
    async with engine.connect() as db:
        assert await db.scalar(text("SELECT revision FROM project_schema_heads")) == 1
        assert await db.scalar(text("SELECT count(*) FROM project_schema_http_receipts")) == 0
        assert await db.scalar(text("SELECT count(*) FROM entity_types")) == 1


async def test_stale_create_does_not_allocate_uuid(schema_http_pg, monkeypatch):
    import src.infrastructure.adapters.secondary.persistence.sql_project_schema_http_commands as module

    engine, sessions = schema_http_pg
    await activated(sessions)
    monkeypatch.setattr(module, "uuid4", lambda: pytest.fail("stale request allocated identity"))
    with pytest.raises(ProjectSchemaError, match="project_schema_revision_conflict"):
        await executor(sessions).execute(
            mutation("create_entity_type", fields={"name": "Place"}, expected="2"),
            legacy=AsyncMock(),
        )
    await assert_unmodified(engine)


async def test_exact_replay_still_requires_pre_return_authorization(schema_http_pg):
    engine, sessions = schema_http_pg
    await activated(sessions)
    command = mutation("create_entity_type", fields={"name": "Place"})
    await executor(sessions).execute(command, legacy=AsyncMock())
    with pytest.raises(ProjectSchemaError, match="project_schema_access_denied"):
        await executor(sessions, Authorization(deny_on_call=3)).execute(command, legacy=AsyncMock())
    async with engine.connect() as db:
        assert await db.scalar(text("SELECT revision FROM project_schema_heads")) == 2
        assert await db.scalar(text("SELECT count(*) FROM project_schema_http_receipts")) == 1


async def test_sql_independently_rejects_mismatched_python_materialization(
    schema_http_pg, monkeypatch
):
    import src.infrastructure.adapters.secondary.persistence.sql_project_schema_http_commands as module

    engine, sessions = schema_http_pg
    await activated(sessions)
    original = module.materialize_http_mutation

    def changed(*args, **kwargs):
        value = original(*args, **kwargs).to_dict()
        next(item for item in value["entity_types"] if item["name"] == "Place")["name"] = "Forged"
        return ProjectSchemaDocument.from_json(json.dumps(value))

    monkeypatch.setattr(module, "materialize_http_mutation", changed)
    with pytest.raises(DBAPIError, match="project_schema_request_mismatch"):
        await executor(sessions).execute(
            mutation("create_entity_type", fields={"name": "Place"}), legacy=AsyncMock()
        )
    await assert_unmodified(engine)


@pytest.mark.parametrize("immediate", [False, True])
async def test_late_timestamp_drift_cannot_leave_stale_response_receipt(
    schema_http_pg, monkeypatch, immediate
):
    import src.infrastructure.adapters.secondary.persistence.sql_project_schema_http_commands as module

    engine, sessions = schema_http_pg
    await activated(sessions)
    original = module._replay_http

    async def drift(db, *args):
        result = await original(db, *args)
        if result is not None:
            if immediate:
                await db.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
            await db.execute(
                text("UPDATE entity_types SET updated_at=timestamp '2000-01-01' WHERE name='Place'")
            )
        return result

    monkeypatch.setattr(module, "_replay_http", drift)
    with pytest.raises(DBAPIError, match="project_schema_http_commit_receipt_mismatch"):
        await executor(sessions).execute(
            mutation("create_entity_type", fields={"name": "Place"}), legacy=AsyncMock()
        )
    await assert_unmodified(engine)


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE project_schema_http_receipts SET response_json='{}'",
        "DELETE FROM project_schema_http_receipts",
        "TRUNCATE project_schema_http_receipts",
    ],
)
async def test_accepted_http_receipt_is_immutable(schema_http_pg, statement):
    engine, sessions = schema_http_pg
    await activated(sessions)
    await executor(sessions).execute(
        mutation("create_entity_type", fields={"name": "Place"}), legacy=AsyncMock()
    )
    with pytest.raises(DBAPIError, match="project_schema_"):
        async with engine.begin() as db:
            await db.execute(text(statement))
    async with engine.connect() as db:
        assert await db.scalar(text("SELECT count(*) FROM project_schema_http_receipts")) == 1


async def test_empty_migration_round_trip_and_history_blocks_downgrade(schema_http_pg):
    engine, sessions = schema_http_pg
    async with engine.begin() as connection:
        await connection.run_sync(http_revision, "downgrade")
        assert (
            await connection.scalar(text("SELECT to_regclass('project_schema_http_receipts')"))
            is None
        )
        await connection.run_sync(http_revision, "upgrade")
    await activated(sessions)
    await executor(sessions).execute(
        mutation("create_entity_type", fields={"name": "Place"}), legacy=AsyncMock()
    )
    with pytest.raises(RuntimeError, match="project_schema_http_downgrade_has_accepted_history"):
        async with engine.begin() as connection:
            await connection.run_sync(http_revision, "downgrade")
