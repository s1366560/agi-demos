"""Concurrent sessions prove CAS serialization and the legacy/active transition fence."""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError

from src.domain.model.project_schema.commands import BootstrapProjectSchema, ProjectSchemaReceipt
from src.domain.model.project_schema.validation import ProjectSchemaError
from src.infrastructure.adapters.secondary.persistence.sql_project_schema_commands import (
    SqlProjectSchemaCommands,
)
from src.tests.integration.project_schema_command_support import (
    SCHEMA_ID,
    SCOPE,
    Authorization,
    activated,
    replacement,
    schema_command_pg as _schema_command_pg,
    schema_storage_pg as _schema_storage_pg,
)

pytestmark = pytest.mark.integration
schema_storage_pg = _schema_storage_pg
schema_command_pg = _schema_command_pg


async def wait_for_project_lock(engine):
    async def observe():
        while True:
            async with engine.connect() as connection:
                waiting = await connection.scalar(
                    sa.text("""
                    SELECT count(*) FROM pg_stat_activity
                    WHERE datname=current_database() AND cardinality(pg_blocking_pids(pid)) > 0
                    AND query LIKE '%projects%'
                """)
                )
            if waiting:
                return
            await asyncio.sleep(0.01)

    await asyncio.wait_for(observe(), timeout=5)


async def test_concurrent_bootstrap_same_command_replays_one_acceptance(schema_command_pg):
    engine, sessions = schema_command_pg
    authority = SqlProjectSchemaCommands(sessions=sessions, authorization=Authorization())
    command = BootstrapProjectSchema(schema_id=SCHEMA_ID, change_id=str(uuid4()))
    results = await asyncio.gather(
        authority.bootstrap(SCOPE, command), authority.bootstrap(SCOPE, command)
    )
    assert results[0] == results[1]
    async with engine.connect() as connection:
        assert await connection.scalar(sa.text("SELECT count(*) FROM project_schema_changes")) == 1


async def test_two_cas_writers_at_same_revision_cannot_both_commit(schema_command_pg):
    engine, sessions = schema_command_pg
    authority, initial = await activated(sessions)
    first = replacement(initial, lambda d: d["entity_types"][0].update(description="first"))
    second = replacement(initial, lambda d: d["entity_types"][0].update(description="second"))
    results = await asyncio.gather(
        authority.replace(SCOPE, first), authority.replace(SCOPE, second), return_exceptions=True
    )
    assert sum(isinstance(result, ProjectSchemaReceipt) for result in results) == 1
    failures = [result for result in results if isinstance(result, ProjectSchemaError)]
    assert len(failures) == 1 and failures[0].code == "project_schema_revision_conflict"
    async with engine.connect() as connection:
        assert await connection.scalar(sa.text("SELECT revision FROM project_schema_heads")) == 2
        assert await connection.scalar(sa.text("SELECT count(*) FROM project_schema_changes")) == 2


async def test_legacy_writer_holds_project_lock_until_commit_before_bootstrap_reads(
    schema_command_pg,
):
    engine, sessions = schema_command_pg
    authority = SqlProjectSchemaCommands(sessions=sessions, authorization=Authorization())
    command = BootstrapProjectSchema(schema_id=SCHEMA_ID, change_id=str(uuid4()))
    task = None
    try:
        async with engine.connect() as writer:
            transaction = await writer.begin()
            await writer.execute(
                sa.text(
                    "UPDATE entity_types SET description='legacy committed first' WHERE project_id='project-a'"
                )
            )
            task = asyncio.create_task(authority.bootstrap(SCOPE, command))
            await wait_for_project_lock(engine)
            assert not task.done()
            await transaction.commit()
        receipt = await asyncio.wait_for(task, timeout=5)
        assert (
            receipt.to_dict()["document"]["entity_types"][0]["description"]
            == "legacy committed first"
        )
    finally:
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


async def test_legacy_transaction_opened_before_activation_cannot_commit_late_update(
    schema_command_pg,
):
    engine, sessions = schema_command_pg
    async with engine.connect() as stale:
        transaction = await stale.begin()
        await stale.execute(
            sa.text("SELECT description FROM entity_types WHERE project_id='project-a'")
        )
        _authority, _initial = await activated(sessions)
        with pytest.raises(DBAPIError, match="project_schema_command_required"):
            await stale.execute(
                sa.text(
                    "UPDATE entity_types SET description='stale bypass' WHERE project_id='project-a'"
                )
            )
        await transaction.rollback()
