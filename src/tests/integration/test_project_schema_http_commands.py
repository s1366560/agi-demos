"""One transaction per original HTTP intent, including exact replay and rollback."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import text

from src.domain.model.project_schema.validation import ProjectSchemaError
from src.infrastructure.adapters.secondary.persistence.sql_project_schema_http_commands import (
    SqlProjectSchemaHttpCommands,
)
from src.tests.integration.project_schema_command_support import Authorization, activated
from src.tests.integration.project_schema_http_support import (
    live_schema_pg as _live_schema_pg,
    mutation,
    schema_command_pg as _schema_command_pg,
    schema_http_pg as _schema_http_pg,
    schema_storage_pg as _schema_storage_pg,
)

schema_storage_pg = _schema_storage_pg
schema_command_pg = _schema_command_pg
live_schema_pg = _live_schema_pg
schema_http_pg = _schema_http_pg
pytestmark = pytest.mark.integration


def executor(sessions, authorization=None):
    return SqlProjectSchemaHttpCommands(
        sessions=sessions, authorization=authorization or Authorization()
    )


async def test_all_eight_mutators_create_one_scoped_receipt_per_revision(schema_http_pg):
    engine, sessions = schema_http_pg
    await activated(sessions)
    commands = executor(sessions)
    legacy = AsyncMock(side_effect=AssertionError("active mutation used legacy writer"))
    revision = 1

    async def apply(operation, target=None, **fields):
        nonlocal revision
        result = await commands.execute(
            mutation(operation, target=target, fields=fields, expected=str(revision)), legacy=legacy
        )
        revision += 1
        value = result.to_dict()
        assert value["headers"]["X-Project-Schema-Revision"] == str(revision)
        return json.loads(value["body"]) if value["body"] else None

    entity = await apply("create_entity_type", name="Place")
    updated = await apply(
        "update_entity_type",
        entity["id"],
        description="A place",
        schema={"size": {"type": "Integer"}},
    )
    assert updated["created_at"] == entity["created_at"]
    assert updated["updated_at"] is not None
    edge = await apply("create_edge_type", name="VISITS")
    await apply("update_edge_type", edge["id"], description="Visits a place")
    mapping = await apply(
        "create_edge_map", source_type="Person", target_type="Place", edge_type="VISITS"
    )
    await apply("delete_edge_map", mapping["id"])
    await apply("delete_entity_type", entity["id"])
    await apply("delete_edge_type", edge["id"])
    legacy.assert_not_called()
    async with engine.connect() as db:
        assert await db.scalar(text("SELECT count(*) FROM project_schema_http_receipts")) == 8
        assert await db.scalar(text("SELECT count(*) FROM project_schema_changes")) == 9
        assert await db.scalar(text("SELECT revision FROM project_schema_heads")) == 9


async def test_replay_returns_original_response_after_later_update_and_delete(schema_http_pg):
    _, sessions = schema_http_pg
    await activated(sessions)
    commands = executor(sessions)
    legacy = AsyncMock()
    create = mutation("create_entity_type", fields={"name": "Place"})
    first = await commands.execute(create, legacy=legacy)
    entity_id = json.loads(first.to_dict()["body"])["id"]
    await commands.execute(
        mutation(
            "update_entity_type", target=entity_id, fields={"description": "later"}, expected="2"
        ),
        legacy=legacy,
    )
    await commands.execute(
        mutation("delete_entity_type", target=entity_id, expected="3"), legacy=legacy
    )
    replay = await commands.execute(create, legacy=legacy)
    assert replay.response_json == first.response_json
    conflicting = mutation(
        "create_entity_type", fields={"name": "Changed"}, change=create.change_id
    )
    with pytest.raises(ProjectSchemaError, match="project_schema_change_id_reused"):
        await commands.execute(conflicting, legacy=legacy)


async def test_concurrent_same_create_allocates_one_uuid_and_replays(schema_http_pg, monkeypatch):
    engine, sessions = schema_http_pg
    await activated(sessions)
    commands = executor(sessions)
    create = mutation("create_entity_type", fields={"name": "Place"})
    import src.infrastructure.adapters.secondary.persistence.sql_project_schema_http_commands as module

    calls = 0
    original = module.uuid4

    def allocate():
        nonlocal calls
        calls += 1
        return original()

    monkeypatch.setattr(module, "uuid4", allocate)
    results = await asyncio.gather(
        commands.execute(create, legacy=AsyncMock()), commands.execute(create, legacy=AsyncMock())
    )
    assert results[0] == results[1]
    assert calls == 1
    async with engine.connect() as db:
        assert await db.scalar(text("SELECT count(*) FROM project_schema_http_receipts")) == 1


async def test_precommit_denial_rolls_back_rows_head_journal_and_both_receipts(schema_http_pg):
    engine, sessions = schema_http_pg
    await activated(sessions)
    commands = executor(sessions, Authorization(deny_on_call=3))
    with pytest.raises(ProjectSchemaError, match="project_schema_access_denied"):
        await commands.execute(
            mutation("create_entity_type", fields={"name": "Place"}), legacy=AsyncMock()
        )
    async with engine.connect() as db:
        assert await db.scalar(text("SELECT revision FROM project_schema_heads")) == 1
        assert await db.scalar(text("SELECT count(*) FROM entity_types")) == 1
        assert await db.scalar(text("SELECT count(*) FROM project_schema_changes")) == 1
        assert await db.scalar(text("SELECT count(*) FROM project_schema_receipts")) == 1
        assert await db.scalar(text("SELECT count(*) FROM project_schema_http_receipts")) == 0


async def test_legacy_headers_are_not_silently_discarded(schema_http_pg):
    _, sessions = schema_http_pg
    commands = executor(sessions)
    legacy = AsyncMock(return_value="legacy result")
    with pytest.raises(ProjectSchemaError, match="project_schema_active_required"):
        await commands.execute(
            mutation("create_entity_type", fields={"name": "Place"}), legacy=legacy
        )
    legacy.assert_not_awaited()
    from dataclasses import replace

    plain = replace(
        mutation("create_entity_type", fields={"name": "Place"}),
        expected_revision=None,
        change_id=None,
    )
    assert await commands.execute(plain, legacy=legacy) == "legacy result"
    legacy.assert_awaited_once()


async def test_authorization_revoked_while_waiting_lock_never_calls_legacy_writer(schema_http_pg):
    from dataclasses import replace

    from src.tests.integration.test_project_schema_concurrency import wait_for_project_lock

    engine, sessions = schema_http_pg
    authorization = Authorization(deny_on_call=2)
    commands = executor(sessions, authorization)
    legacy = AsyncMock()
    command = replace(
        mutation("create_entity_type", fields={"name": "Place"}),
        expected_revision=None,
        change_id=None,
    )
    task = None
    try:
        async with engine.connect() as blocker:
            transaction = await blocker.begin()
            await blocker.execute(text("SELECT id FROM projects WHERE id='project-a' FOR UPDATE"))
            task = asyncio.create_task(commands.execute(command, legacy=legacy))
            await wait_for_project_lock(engine)
            await transaction.commit()
        with pytest.raises(ProjectSchemaError, match="project_schema_access_denied"):
            await task
        legacy.assert_not_awaited()
    finally:
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


@pytest.mark.parametrize("headers", [False, True])
async def test_waiting_mutation_observes_bootstrap_commit_before_choosing_mode(
    schema_http_pg, headers
):
    from dataclasses import replace
    from uuid import uuid4

    from src.domain.model.project_schema.commands import BootstrapProjectSchema
    from src.infrastructure.adapters.secondary.persistence.sql_project_schema_commands import (
        SqlProjectSchemaCommands,
    )
    from src.tests.integration.project_schema_command_support import SCHEMA_ID, SCOPE
    from src.tests.integration.test_project_schema_concurrency import wait_for_project_lock

    engine, sessions = schema_http_pg
    reached = asyncio.Event()
    release = asyncio.Event()

    class PauseBootstrap(Authorization):
        async def authorize(self, scope, action):
            await super().authorize(scope, action)
            if len(self.calls) == 2:
                reached.set()
                await release.wait()

    bootstrap = SqlProjectSchemaCommands(sessions=sessions, authorization=PauseBootstrap())
    bootstrap_task = asyncio.create_task(
        bootstrap.bootstrap(
            SCOPE, BootstrapProjectSchema(schema_id=SCHEMA_ID, change_id=str(uuid4()))
        )
    )
    command = mutation("create_entity_type", fields={"name": "Place"})
    if not headers:
        command = replace(command, expected_revision=None, change_id=None)
    legacy = AsyncMock(side_effect=AssertionError("stale legacy mode selected"))
    mutation_task = None
    try:
        await asyncio.wait_for(reached.wait(), 5)
        mutation_task = asyncio.create_task(executor(sessions).execute(command, legacy=legacy))
        await wait_for_project_lock(engine)
        release.set()
        await bootstrap_task
        if headers:
            assert json.loads((await mutation_task).to_dict()["body"])["name"] == "Place"
        else:
            with pytest.raises(ProjectSchemaError, match="project_schema_command_required"):
                await mutation_task
        legacy.assert_not_awaited()
    finally:
        release.set()
        for task in (bootstrap_task, mutation_task):
            if task is not None and not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
