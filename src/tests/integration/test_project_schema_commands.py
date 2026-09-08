"""Real PostgreSQL atomic bootstrap/replacement commands and rollout boundaries."""

from __future__ import annotations

import json
from dataclasses import replace
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy.exc import DBAPIError

from src.application.schemas.schema import EntityTypeUpdate
from src.domain.model.project_schema.bootstrap import ProjectSchemaBootstrapRejected
from src.domain.model.project_schema.commands import BootstrapProjectSchema, ProjectSchemaAction
from src.domain.model.project_schema.validation import ProjectSchemaError
from src.infrastructure.adapters.secondary.persistence.sql_project_schema_commands import (
    SqlProjectSchemaCommands,
)
from src.infrastructure.plugins.v2.schema_services import SqlSchemaPersistenceV2
from src.tests.integration.project_schema_command_support import (
    SCHEMA_ID,
    SCOPE,
    Authorization,
    activated,
    command_revision,
    replacement,
    schema_command_pg as _schema_command_pg,
    schema_storage_pg as _schema_storage_pg,
)
from src.tests.integration.project_schema_storage_support import (
    ENTITY_ID,
    LEGACY_TABLES,
    NEW_TABLES,
    apply_revision,
    metadata_subset,
    snapshot,
)

pytestmark = pytest.mark.integration
schema_storage_pg = _schema_storage_pg
schema_command_pg = _schema_command_pg


async def test_command_migration_roundtrip_is_off_and_preserves_legacy(schema_storage_pg):
    engine, _sessions = schema_storage_pg
    async with engine.begin() as connection:
        await connection.run_sync(apply_revision, "upgrade")
        before = await connection.run_sync(snapshot)
        await connection.run_sync(command_revision, "upgrade")
        assert await connection.run_sync(snapshot) == before
        for table in NEW_TABLES:
            assert await connection.scalar(sa.text(f"SELECT count(*) FROM {table}")) == 0
        assert (
            await connection.run_sync(
                lambda sync: compare_metadata(
                    MigrationContext.configure(sync),
                    metadata_subset((*LEGACY_TABLES, *NEW_TABLES), commands=True),
                )
            )
            == []
        )
        await connection.run_sync(command_revision, "downgrade")
        assert await connection.run_sync(snapshot) == before
        await connection.run_sync(command_revision, "upgrade")


async def test_bootstrap_preserves_original_ids_and_raw_values_then_replays(schema_command_pg):
    engine, sessions = schema_command_pg
    authorization = Authorization()
    authority = SqlProjectSchemaCommands(sessions=sessions, authorization=authorization)
    command = BootstrapProjectSchema(schema_id=SCHEMA_ID, change_id=str(uuid4()))
    async with engine.connect() as connection:
        before = await connection.run_sync(snapshot)
    receipt = await authority.bootstrap(SCOPE, command)
    assert receipt.to_dict()["document"]["entity_types"][0]["id"] == ENTITY_ID
    assert receipt.to_dict()["document"]["entity_types"][0]["description"] == ""
    assert await authority.bootstrap(SCOPE, command) == receipt
    assert authorization.calls == [(SCOPE, ProjectSchemaAction.BOOTSTRAP)] * 4
    async with engine.connect() as connection:
        assert await connection.run_sync(snapshot) == before
        assert await connection.scalar(sa.text("SELECT count(*) FROM project_schema_changes")) == 1
        refs = (
            await connection.execute(
                sa.text("SELECT source_type_id,target_type_id FROM edge_type_maps")
            )
        ).one()
        assert refs == (ENTITY_ID, ENTITY_ID)


async def test_read_does_not_create_head_or_defaults_and_authorization_is_required(
    schema_command_pg,
):
    engine, sessions = schema_command_pg
    authority = SqlProjectSchemaCommands(sessions=sessions, authorization=Authorization())
    assert await authority.read(SCOPE) is None
    with pytest.raises(ProjectSchemaError, match="project_schema_access_denied"):
        await authority.read(replace(SCOPE, actor_id="outsider"))
    async with engine.connect() as connection:
        assert await connection.scalar(sa.text("SELECT count(*) FROM project_schema_heads")) == 0


async def test_revoked_authorization_rolls_back_every_bootstrap_write(schema_command_pg):
    engine, sessions = schema_command_pg
    authority = SqlProjectSchemaCommands(
        sessions=sessions, authorization=Authorization(deny_on_call=2)
    )
    with pytest.raises(ProjectSchemaError, match="project_schema_access_denied"):
        await authority.bootstrap(
            SCOPE, BootstrapProjectSchema(schema_id=SCHEMA_ID, change_id=str(uuid4()))
        )
    async with engine.connect() as connection:
        for table in NEW_TABLES:
            assert await connection.scalar(sa.text(f"SELECT count(*) FROM {table}")) == 0
        assert await connection.scalar(sa.text("SELECT source_type_id FROM edge_type_maps")) is None


@pytest.mark.parametrize("deny_call", [1, 2])
async def test_receipt_replay_still_requires_current_authorization(schema_command_pg, deny_call):
    engine, sessions = schema_command_pg
    command = BootstrapProjectSchema(schema_id=SCHEMA_ID, change_id=str(uuid4()))
    initial_authority = SqlProjectSchemaCommands(sessions=sessions, authorization=Authorization())
    receipt = await initial_authority.bootstrap(SCOPE, command)
    revoked = SqlProjectSchemaCommands(
        sessions=sessions, authorization=Authorization(deny_on_call=deny_call)
    )
    with pytest.raises(ProjectSchemaError, match="project_schema_access_denied"):
        await revoked.bootstrap(SCOPE, command)
    async with engine.connect() as connection:
        assert (
            await connection.scalar(sa.text("SELECT receipt_json FROM project_schema_receipts"))
            == receipt.receipt_json
        )
        assert await connection.scalar(sa.text("SELECT count(*) FROM project_schema_changes")) == 1


async def test_database_scope_check_is_independent_of_injected_authorization(schema_command_pg):
    engine, sessions = schema_command_pg
    invalid_scope = replace(SCOPE, tenant_id="tenant-b")
    authority = SqlProjectSchemaCommands(
        sessions=sessions, authorization=Authorization(allowed=invalid_scope)
    )
    with pytest.raises(ProjectSchemaError, match="project_schema_scope_not_found"):
        await authority.bootstrap(
            invalid_scope, BootstrapProjectSchema(schema_id=SCHEMA_ID, change_id=str(uuid4()))
        )
    async with engine.connect() as connection:
        assert await connection.scalar(sa.text("SELECT count(*) FROM project_schema_heads")) == 0


async def test_legacy_empty_project_deletion_remains_available(schema_command_pg):
    engine, _sessions = schema_command_pg
    async with engine.begin() as connection:
        await connection.execute(sa.text("DELETE FROM projects WHERE id='project-b'"))
    async with engine.connect() as connection:
        assert (
            await connection.scalar(sa.text("SELECT count(*) FROM projects WHERE id='project-b'"))
            == 0
        )


async def test_old_persistence_can_write_legacy_but_cannot_bypass_active_commands(
    schema_command_pg,
):
    _engine, sessions = schema_command_pg
    async with sessions() as session:
        old = SqlSchemaPersistenceV2(_session=session)
        await old.update_entity_type(
            project_id=SCOPE.project_id,
            entity_id=ENTITY_ID,
            data=EntityTypeUpdate(description="legacy write"),
        )
    authority, receipt = await activated(sessions)
    assert receipt.to_dict()["document"]["entity_types"][0]["description"] == "legacy write"
    async with sessions() as session:
        with pytest.raises(DBAPIError, match="project_schema_command_required"):
            await SqlSchemaPersistenceV2(_session=session).update_entity_type(
                project_id=SCOPE.project_id,
                entity_id=ENTITY_ID,
                data=EntityTypeUpdate(description="active bypass"),
            )
    current = await authority.read(SCOPE)
    assert current is not None and current.to_dict() == receipt.to_dict()["document"]


@pytest.mark.parametrize("raw", ['{"number":0.123456789123456789}', '{"number":1e-400}'])
async def test_legacy_numbers_project_through_portable_binary64_without_rewriting_raw_json(
    schema_command_pg, raw
):
    engine, sessions = schema_command_pg
    async with engine.begin() as connection:
        await connection.execute(
            sa.text("UPDATE entity_types SET schema=CAST(:raw AS json)"), {"raw": raw}
        )
    authority, initial = await activated(sessions)
    assert initial.to_dict()["document"]["entity_types"][0]["schema"] == json.loads(raw)
    assert await authority.read(SCOPE) is not None
    async with engine.connect() as connection:
        assert await connection.scalar(sa.text("SELECT schema::text FROM entity_types")) == raw


@pytest.mark.parametrize("defect", ["uuid", "missing_reference", "duplicate_json"])
async def test_bootstrap_invalid_legacy_rejects_all_without_repair(schema_command_pg, defect):
    engine, sessions = schema_command_pg
    statement = {
        "uuid": "UPDATE entity_types SET id='historical-invalid-id'",
        "missing_reference": "UPDATE edge_type_maps SET source_type='person'",
        "duplicate_json": "UPDATE entity_types SET schema=CAST(:raw AS json)",
    }[defect]
    async with engine.begin() as connection:
        await connection.execute(sa.text(statement), {"raw": '{"x":1,"x":2}'})
        before = await connection.run_sync(snapshot)
    authority = SqlProjectSchemaCommands(sessions=sessions, authorization=Authorization())
    with pytest.raises(ProjectSchemaBootstrapRejected):
        await authority.bootstrap(
            SCOPE, BootstrapProjectSchema(schema_id=SCHEMA_ID, change_id=str(uuid4()))
        )
    async with engine.connect() as connection:
        assert await connection.run_sync(snapshot) == before
        assert await connection.scalar(sa.text("SELECT count(*) FROM project_schema_heads")) == 0


async def test_cas_preserves_identity_and_receipt_replay_precedes_stale_revision(schema_command_pg):
    engine, sessions = schema_command_pg
    authority, initial = await activated(sessions)
    command = replacement(
        initial, lambda d: d["entity_types"][0].update(name="Human", source="explicit")
    )
    receipt = await authority.replace(SCOPE, command)
    assert receipt.to_dict()["revision"] == 2
    assert receipt.to_dict()["document"]["entity_types"][0]["id"] == ENTITY_ID
    assert await authority.replace(SCOPE, command) == receipt
    with pytest.raises(ProjectSchemaError, match="project_schema_revision_conflict"):
        await authority.replace(SCOPE, replace(command, change_id=str(uuid4())))
    changed = replacement(initial, lambda d: d["entity_types"][0].update(name="Different"))
    with pytest.raises(ProjectSchemaError, match="project_schema_change_id_reused"):
        await authority.replace(SCOPE, replace(changed, change_id=command.change_id))
    async with engine.connect() as connection:
        assert await connection.scalar(sa.text("SELECT source_type FROM edge_type_maps")) == "Human"
        assert await connection.scalar(sa.text("SELECT count(*) FROM project_schema_changes")) == 2


async def test_unrepresentable_document_does_not_partially_replace(schema_command_pg):
    engine, sessions = schema_command_pg
    authority, initial = await activated(sessions)

    def duplicate(value):
        value["entity_types"].append({**value["entity_types"][0], "id": str(uuid4())})

    with pytest.raises(ProjectSchemaError, match="project_schema_legacy_unrepresentable"):
        await authority.replace(SCOPE, replacement(initial, duplicate))
    async with engine.connect() as connection:
        assert await connection.scalar(sa.text("SELECT revision FROM project_schema_heads")) == 1


async def test_create_and_name_swap_preserve_member_and_mapping_identity(schema_command_pg):
    engine, sessions = schema_command_pg
    authority, initial = await activated(sessions)
    added_id = str(uuid4())

    def add_type(value):
        value["entity_types"].append({**value["entity_types"][0], "id": added_id, "name": "Robot"})

    created = await authority.replace(SCOPE, replacement(initial, add_type))
    async with engine.connect() as connection:
        timestamps = (
            await connection.execute(
                sa.text(
                    "SELECT id,created_at FROM entity_types UNION ALL SELECT id,created_at FROM edge_type_maps ORDER BY id"
                )
            )
        ).all()

    def swap_names(value):
        for item in value["entity_types"]:
            item["name"] = "Robot" if item["id"] == ENTITY_ID else "Person"

    swapped = await authority.replace(SCOPE, replacement(created, swap_names))
    assert {item["id"] for item in swapped.to_dict()["document"]["entity_types"]} == {
        ENTITY_ID,
        added_id,
    }
    async with engine.connect() as connection:
        assert (
            await connection.execute(
                sa.text(
                    "SELECT id,created_at FROM entity_types UNION ALL SELECT id,created_at FROM edge_type_maps ORDER BY id"
                )
            )
        ).all() == timestamps
        assert await connection.scalar(sa.text("SELECT source_type FROM edge_type_maps")) == "Robot"


async def test_terminal_deletion_keeps_tombstones_and_forbids_reactivation_or_downgrade(
    schema_command_pg,
):
    engine, sessions = schema_command_pg
    authority, initial = await activated(sessions)

    def delete_document(value):
        value["deleted"] = True
        for key, kind in (
            ("entity_types", "entity_type"),
            ("edge_types", "edge_type"),
            ("mappings", "mapping"),
        ):
            value["tombstones"].extend(
                {"id": item["id"], "kind": kind, "deleted_revision": 2} for item in value[key]
            )
            value[key] = []

    receipt = await authority.replace(SCOPE, replacement(initial, delete_document))
    assert len(receipt.to_dict()["document"]["tombstones"]) == 3
    with pytest.raises(ProjectSchemaError, match="project_schema_transition_invalid"):
        await authority.replace(SCOPE, replacement(receipt))
    with pytest.raises(ProjectSchemaError, match="project_schema_already_active"):
        await authority.bootstrap(
            SCOPE, BootstrapProjectSchema(schema_id=str(uuid4()), change_id=str(uuid4()))
        )
    with pytest.raises(DBAPIError, match="project_schema_command_rollback_requires_empty_state"):
        async with engine.begin() as connection:
            await connection.run_sync(command_revision, "downgrade")
