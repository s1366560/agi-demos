"""Executable migration, scope, closed-state and read-only checks on PostgreSQL."""

from __future__ import annotations

from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy.exc import DBAPIError, IntegrityError

from src.application.schemas.schema import EntityTypeUpdate
from src.infrastructure.adapters.secondary.persistence.models import Base, EntityType
from src.infrastructure.adapters.secondary.persistence.project_schema_models import (
    ProjectSchemaHeadModel,
    ProjectSchemaMigrationFindingModel,
)
from src.infrastructure.adapters.secondary.persistence.sql_project_schema_inspection import (
    ProjectSchemaInspectionScopeNotFound,
    SqlProjectSchemaInspection,
)
from src.infrastructure.plugins.v2.schema_services import SqlSchemaPersistenceV2
from src.tests.integration.project_schema_storage_support import (
    ENTITY_ID,
    LEGACY_TABLES,
    NEW_TABLES,
    apply_revision,
    metadata_subset,
    schema_storage_pg as _schema_storage_pg,
    snapshot,
)

pytestmark = pytest.mark.integration
schema_storage_pg = _schema_storage_pg


async def test_upgrade_downgrade_preserves_all_legacy_rows_and_constraints(schema_storage_pg):
    engine, _sessions = schema_storage_pg
    async with engine.begin() as connection:
        before = await connection.run_sync(snapshot)
        await connection.run_sync(apply_revision, "upgrade")
        assert await connection.run_sync(snapshot) == before
        for name in NEW_TABLES:
            assert (
                await connection.scalar(
                    sa.select(sa.func.count()).select_from(Base.metadata.tables[name])
                )
            ) == 0

        def compare(sync):
            return compare_metadata(
                MigrationContext.configure(sync), metadata_subset((*LEGACY_TABLES, *NEW_TABLES))
            )

        assert await connection.run_sync(compare) == []
        await connection.execute(
            sa.insert(ProjectSchemaHeadModel).values(project_id="project-a", tenant_id="tenant-a")
        )
        head = (
            (await connection.execute(sa.select(ProjectSchemaHeadModel.__table__))).mappings().one()
        )
        assert head["mode"] == "legacy" and head["schema_id"] is None and head["revision"] is None
        assert head["sequence"] == 0 and head["deleted"] is False
        await connection.run_sync(apply_revision, "downgrade")
        assert await connection.run_sync(snapshot) == before
        assert not (
            set(NEW_TABLES)
            & set(await connection.run_sync(lambda sync: sa.inspect(sync).get_table_names()))
        )
        await connection.run_sync(apply_revision, "upgrade")
        assert await connection.run_sync(compare) == []
        expected = {
            "entity_types": "uq_entity_type_project_name",
            "edge_types": "uq_edge_type_project_name",
            "edge_type_maps": "uq_edge_map_unique",
        }
        for table, name in expected.items():
            constraints = await connection.run_sync(
                lambda sync, table=table: sa.inspect(sync).get_unique_constraints(table)
            )
            assert name in {item["name"] for item in constraints}


async def test_database_rejects_activation_and_cross_tenant_heads(schema_storage_pg):
    engine, _sessions = schema_storage_pg
    async with engine.begin() as connection:
        await connection.run_sync(apply_revision, "upgrade")
        for values, constraint in [
            (
                {
                    "project_id": "project-a",
                    "tenant_id": "tenant-a",
                    "mode": "active",
                    "schema_id": str(uuid4()),
                    "revision": 1,
                    "sequence": 1,
                },
                "ck_project_schema_head_closed",
            ),
            ({"project_id": "project-a", "tenant_id": "tenant-b"}, "fk_project_schema_head_scope"),
        ]:
            async with connection.begin_nested():
                with pytest.raises(IntegrityError, match=constraint):
                    await connection.execute(sa.insert(ProjectSchemaHeadModel).values(**values))
                # Roll back the failed savepoint before its context can release it.
                await connection.get_nested_transaction().rollback()


async def test_downgrade_refuses_to_erase_persisted_findings(schema_storage_pg):
    engine, _sessions = schema_storage_pg
    async with engine.begin() as connection:
        await connection.run_sync(apply_revision, "upgrade")
        await connection.execute(
            sa.insert(ProjectSchemaMigrationFindingModel).values(
                id=str(uuid4()),
                inspection_id=str(uuid4()),
                tenant_id="tenant-a",
                project_id="project-a",
                record_kind="entity_type",
                record_id=ENTITY_ID,
                code="legacy_schema_id_invalid",
                related_records=[],
            )
        )
        transaction = await connection.begin_nested()
        with pytest.raises(DBAPIError, match="project_schema_storage_not_empty"):
            await connection.run_sync(apply_revision, "downgrade")
        await transaction.rollback()
        assert (
            await connection.scalar(
                sa.select(sa.func.count()).select_from(ProjectSchemaMigrationFindingModel)
            )
            == 1
        )


async def test_inspection_is_single_select_without_autoflush_or_initialization(schema_storage_pg):
    engine, sessions = schema_storage_pg
    async with engine.begin() as connection:
        await connection.run_sync(apply_revision, "upgrade")
        before = await connection.run_sync(snapshot)
    statements = []

    def capture(_connection, _cursor, statement, _parameters, _context, _many):
        statements.append(statement)

    async with sessions() as session:
        await session.execute(sa.text("SET TRANSACTION READ ONLY"))
        record = await session.get(EntityType, ENTITY_ID)
        record.name = "Unflushed edit"
        sa.event.listen(engine.sync_engine, "before_cursor_execute", capture)
        try:
            result = await SqlProjectSchemaInspection(session=session).inspect(
                tenant_id="tenant-a", project_id="project-a"
            )
        finally:
            sa.event.remove(engine.sync_engine, "before_cursor_execute", capture)
        assert result.findings == ()
        assert len(statements) == 1 and "UNION ALL" in statements[0]
        assert record.name == "Unflushed edit" and record in session.dirty
        await session.rollback()
    async with engine.connect() as connection:
        assert await connection.run_sync(snapshot) == before
        for name in NEW_TABLES:
            assert (
                await connection.scalar(
                    sa.select(sa.func.count()).select_from(Base.metadata.tables[name])
                )
                == 0
            )


async def test_empty_scope_stays_empty_and_wrong_tenant_cannot_read(schema_storage_pg):
    _engine, sessions = schema_storage_pg
    async with sessions() as session:
        inspector = SqlProjectSchemaInspection(session=session)
        result = await inspector.inspect(tenant_id="tenant-b", project_id="project-b")
        assert result.findings == () and result.entity_type_count == 0
        with pytest.raises(ProjectSchemaInspectionScopeNotFound):
            await inspector.inspect(tenant_id="tenant-a", project_id="project-b")
        assert await session.scalar(sa.select(sa.func.count()).select_from(EntityType)) == 1


async def test_inspection_reports_original_bad_ids_without_normalizing_legacy_json(
    schema_storage_pg,
):
    engine, sessions = schema_storage_pg
    map_id = "00000000-0000-4000-8000-000000000099"
    async with engine.begin() as connection:
        await connection.run_sync(apply_revision, "upgrade")
        await connection.execute(
            sa.insert(EntityType).values(
                id="legacy-unparsed-id",
                project_id="project-a",
                name="LegacyBad",
                schema=sa.cast(sa.literal('{"x": 1, "x": 2}'), sa.JSON),
            )
        )
        await connection.execute(
            sa.insert(Base.metadata.tables["edge_types"]).values(
                id=ENTITY_ID,
                project_id="project-a",
                name="DifferentEdge",
                schema={},
            )
        )
        await connection.execute(
            sa.insert(Base.metadata.tables["edge_type_maps"]).values(
                id=map_id,
                project_id="project-a",
                source_type="Person",
                target_type="Missing",
                edge_type="KNOWS",
            )
        )
        before = await connection.run_sync(snapshot)
    async with sessions() as session:
        await session.execute(sa.text("SET TRANSACTION READ ONLY"))
        result = await SqlProjectSchemaInspection(session=session).inspect(
            tenant_id="tenant-a",
            project_id="project-a",
        )
        actual = {(item.code, item.record_id) for item in result.findings}
        assert ("legacy_schema_id_invalid", "legacy-unparsed-id") in actual
        assert ("legacy_schema_definition_invalid", "legacy-unparsed-id") in actual
        assert any(item.code == "legacy_schema_id_collision" for item in result.findings)
        assert ("legacy_schema_reference_missing", map_id) in actual
    async with engine.connect() as connection:
        assert await connection.run_sync(snapshot) == before
        for name in NEW_TABLES:
            assert (
                await connection.scalar(
                    sa.select(sa.func.count()).select_from(Base.metadata.tables[name])
                )
                == 0
            )


async def test_existing_writer_remains_the_only_authority_while_storage_is_closed(
    schema_storage_pg,
):
    engine, sessions = schema_storage_pg
    async with engine.begin() as connection:
        await connection.run_sync(apply_revision, "upgrade")
    async with sessions() as session:
        row = await SqlSchemaPersistenceV2(_session=session).update_entity_type(
            project_id="project-a",
            entity_id=ENTITY_ID,
            data=EntityTypeUpdate(description="Legacy edit"),
        )
        assert row.id == ENTITY_ID and row.description == "Legacy edit"
    async with engine.connect() as connection:
        for name in NEW_TABLES:
            assert (
                await connection.scalar(
                    sa.select(sa.func.count()).select_from(Base.metadata.tables[name])
                )
                == 0
            )
