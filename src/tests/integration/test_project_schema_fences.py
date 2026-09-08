"""Adversarial direct SQL cannot commit a partial or unjournaled active schema."""

from __future__ import annotations

import json
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy.exc import DBAPIError

from src.domain.model.project_schema.commands import BootstrapProjectSchema
from src.infrastructure.adapters.secondary.persistence.project_schema_mutate import (
    apply_replacement,
)
from src.infrastructure.adapters.secondary.persistence.sql_project_schema_commands import (
    SqlProjectSchemaCommands,
    _admit,
    _advance_head,
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


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE entity_types SET description='bypass'",
        "DELETE FROM entity_types",
        "INSERT INTO entity_types(id,project_id,name,schema,status,source) VALUES('00000000-0000-4000-8000-000000000099','project-a','Bypass','{}','ENABLED','user')",
        "UPDATE edge_types SET description='bypass'",
        "DELETE FROM edge_types",
        "UPDATE edge_type_maps SET status='DISABLED'",
        "DELETE FROM edge_type_maps",
        "UPDATE project_schema_heads SET revision=2,sequence=2",
        "DELETE FROM project_schema_heads",
        "UPDATE project_schema_heads SET mode='legacy',schema_id=NULL,revision=NULL,sequence=0,deleted=false",
        "UPDATE entity_types SET project_id='project-b'",
        "UPDATE entity_types SET id='00000000-0000-4000-8000-000000000099'",
        "UPDATE projects SET tenant_id='tenant-b' WHERE id='project-a'",
        "DELETE FROM projects WHERE id='project-a'",
        "UPDATE project_schema_changes SET snapshot='{}'",
        "DELETE FROM project_schema_changes",
        "UPDATE project_schema_receipts SET receipt_json='{}'",
        "DELETE FROM project_schema_receipts",
        "INSERT INTO project_schema_changes SELECT * FROM project_schema_changes",
        "INSERT INTO project_schema_receipts SELECT * FROM project_schema_receipts",
        "TRUNCATE entity_types CASCADE",
        "TRUNCATE project_schema_heads CASCADE",
    ],
)
async def test_active_direct_sql_writers_are_fenced(schema_command_pg, statement):
    engine, sessions = schema_command_pg
    authority, initial = await activated(sessions)
    with pytest.raises(DBAPIError):
        async with engine.begin() as connection:
            await connection.execute(sa.text(statement))
    current = await authority.read(SCOPE)
    assert current is not None and current.to_dict() == initial.to_dict()["document"]


async def test_forged_transaction_setting_without_head_admission_is_not_a_bypass(schema_command_pg):
    engine, sessions = schema_command_pg
    _authority, initial = await activated(sessions)
    command = replacement(initial, lambda d: d["entity_types"][0].update(description="changed"))
    with pytest.raises(DBAPIError, match="project_schema_command_required"):
        async with sessions() as db, db.begin():
            await _admit(
                db,
                SCOPE,
                document=command.document,
                change_id=command.change_id,
                expected_revision=1,
                request_json=command.request_json(SCOPE),
                source_kind="mutation",
            )
            await db.execute(sa.text("UPDATE entity_types SET description='changed'"))
    async with engine.connect() as connection:
        assert await connection.scalar(sa.text("SELECT revision FROM project_schema_heads")) == 1


@pytest.mark.parametrize("fault", ["missing_rows", "extra_row", "bad_name_reference", "late_write"])
async def test_commit_checks_actual_rows_even_with_valid_head_journal_and_receipt(
    schema_command_pg, fault
):
    engine, sessions = schema_command_pg
    authority, initial = await activated(sessions)
    command = replacement(initial, lambda d: d["entity_types"][0].update(description="accepted"))
    with pytest.raises(
        DBAPIError, match="project_schema_(commit_document_mismatch|mapping_name_mismatch)"
    ):
        async with sessions() as db, db.begin():
            await _admit(
                db,
                SCOPE,
                document=command.document,
                change_id=command.change_id,
                expected_revision=1,
                request_json=command.request_json(SCOPE),
                source_kind="mutation",
            )
            await _advance_head(db, SCOPE, document=command.document, exists=True)
            if fault != "missing_rows":
                await apply_replacement(db, command.document)
            if fault == "extra_row":
                await db.execute(
                    sa.text(
                        "INSERT INTO entity_types(id,project_id,name,schema,status,source) VALUES('00000000-0000-4000-8000-000000000099','project-a','Extra','{}','ENABLED','user')"
                    )
                )
            elif fault == "bad_name_reference":
                await db.execute(sa.text("UPDATE edge_type_maps SET source_type='Wrong name'"))
            elif fault == "late_write":
                await db.execute(sa.text("SET CONSTRAINTS ALL IMMEDIATE"))
                await db.execute(sa.text("UPDATE entity_types SET description='late bypass'"))
    current = await authority.read(SCOPE)
    assert current is not None and current.to_dict() == initial.to_dict()["document"]
    async with engine.connect() as connection:
        assert await connection.scalar(sa.text("SELECT count(*) FROM project_schema_changes")) == 1
        assert await connection.scalar(sa.text("SELECT count(*) FROM project_schema_receipts")) == 1


@pytest.mark.parametrize(
    "table", ["project_schema_changes", "project_schema_receipts", "edge_type_maps"]
)
async def test_failure_in_any_command_write_rolls_back_head_rows_and_history(
    schema_command_pg, table
):
    engine, sessions = schema_command_pg
    async with engine.begin() as connection:

        def fail_writes(sync):
            operations = Operations(MigrationContext.configure(sync))
            operations.execute(
                "CREATE FUNCTION qa_fail_schema_write() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'qa_command_write_failed'; END $$"
            )
            operations.execute(
                f"CREATE TRIGGER qa_fail_schema_write BEFORE INSERT OR UPDATE ON {table} FOR EACH ROW EXECUTE FUNCTION qa_fail_schema_write()"
            )

        await connection.run_sync(fail_writes)
    authority = SqlProjectSchemaCommands(sessions=sessions, authorization=Authorization())
    with pytest.raises(DBAPIError, match="qa_command_write_failed"):
        await authority.bootstrap(
            SCOPE, BootstrapProjectSchema(schema_id=SCHEMA_ID, change_id=str(uuid4()))
        )
    async with engine.connect() as connection:
        for name in (
            "project_schema_heads",
            "project_schema_changes",
            "project_schema_receipts",
            "project_schema_tombstones",
        ):
            assert await connection.scalar(sa.text(f"SELECT count(*) FROM {name}")) == 0
        assert await connection.scalar(sa.text("SELECT source_type_id FROM edge_type_maps")) is None


async def test_database_bootstrap_refuses_changed_ids_even_with_matching_forged_request(
    schema_command_pg,
):
    _engine, sessions = schema_command_pg
    from src.domain.model.project_schema.bootstrap import bootstrap_document
    from src.domain.model.project_schema.document import ProjectSchemaDocument
    from src.infrastructure.adapters.secondary.persistence.sql_project_schema_inspection import (
        SqlProjectSchemaInspection,
    )

    async with sessions() as db:
        records = await SqlProjectSchemaInspection(session=db).read_records(
            tenant_id=SCOPE.tenant_id, project_id=SCOPE.project_id
        )
    document = bootstrap_document(scope=SCOPE, schema_id=SCHEMA_ID, records=records).to_dict()
    original = document["entity_types"][0]["id"]
    new_id = str(uuid4())
    document["entity_types"][0]["id"] = new_id
    for mapping in document["mappings"]:
        if mapping["source_type_id"] == original:
            mapping["source_type_id"] = new_id
        if mapping["target_type_id"] == original:
            mapping["target_type_id"] = new_id
    changed = ProjectSchemaDocument.from_json(json.dumps(document))
    command = BootstrapProjectSchema(schema_id=SCHEMA_ID, change_id=str(uuid4()))
    with pytest.raises(DBAPIError, match="project_schema_bootstrap_preservation_required"):
        async with sessions() as db, db.begin():
            await _admit(
                db,
                SCOPE,
                document=changed,
                change_id=command.change_id,
                expected_revision=0,
                request_json=command.request_json(SCOPE),
                source_kind="bootstrap",
            )
            await _advance_head(db, SCOPE, document=changed, exists=False)
