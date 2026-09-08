"""Isolated PostgreSQL fixtures; DDL bootstrap uses Alembic autogeneration."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic.autogenerate import produce_migrations
from alembic.operations import Operations
from alembic.operations.ops import ModifyTableOps
from alembic.runtime.migration import MigrationContext
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.infrastructure.adapters.secondary.persistence import project_schema_models  # noqa: F401
from src.infrastructure.adapters.secondary.persistence.models import Base

LEGACY_TABLES = ("users", "tenants", "projects", "entity_types", "edge_types", "edge_type_maps")
# These historical fixtures describe the closed foundation, not later HTTP receipts.
NEW_TABLES = tuple(
    name
    for name in Base.metadata.tables
    if name.startswith("project_schema_") and name != "project_schema_http_receipts"
)
ENTITY_ID = "00000000-0000-4000-8000-000000000002"
EDGE_ID = "00000000-0000-4000-8000-000000000003"
MAPPING_ID = "00000000-0000-4000-8000-000000000004"


def load_migration():
    path = (
        Path(__file__).resolve().parents[3]
        / "alembic/versions/32ed76ad9e43_add_closed_project_schema_storage.py"
    )
    spec = importlib.util.spec_from_file_location("project_schema_storage_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def metadata_subset(names, *, commands=False):
    metadata = sa.MetaData()
    for name in names:
        Base.metadata.tables[name].to_metadata(metadata)
    if not commands:
        # Reconstruct the immutable closed-foundation revision even as production
        # models evolve. This keeps its historical upgrade/rollback tests honest.
        for name, constraint_name in (
            ("entity_types", "uq_entity_type_project_id"),
            ("edge_types", "uq_edge_type_project_id"),
        ):
            if name in metadata.tables:
                table = metadata.tables[name]
                for constraint in tuple(table.constraints):
                    if constraint.name == constraint_name:
                        table.constraints.remove(constraint)
        _restore_closed_mapping_shape(metadata)
        _restore_closed_head(metadata)
    return metadata


def _restore_closed_mapping_shape(metadata):
    if "edge_type_maps" not in metadata.tables:
        return
    table = metadata.tables["edge_type_maps"]
    for constraint in tuple(table.constraints):
        if constraint.name in {
            "fk_schema_mapping_source_id",
            "fk_schema_mapping_target_id",
            "fk_schema_mapping_edge_id",
        }:
            table.constraints.remove(constraint)
            table.foreign_key_constraints.discard(constraint)
            for element in constraint.elements:
                table.foreign_keys.discard(element)
    for name in ("source_type_id", "target_type_id", "edge_type_id"):
        table._columns.remove(table.c[name])


def _restore_closed_head(metadata):
    if "project_schema_heads" not in metadata.tables:
        return
    table = metadata.tables["project_schema_heads"]
    for constraint in tuple(table.constraints):
        if constraint.name == "ck_project_schema_head_state":
            table.constraints.remove(constraint)
    table.append_constraint(
        sa.CheckConstraint(
            "mode = 'legacy' AND schema_id IS NULL AND revision IS NULL "
            "AND sequence = 0 AND NOT deleted",
            name="ck_project_schema_head_closed",
        )
    )


def _invoke(operations, item):
    if isinstance(item, ModifyTableOps):
        for child in item.ops:
            _invoke(operations, child)
    else:
        operations.invoke(item)


def bootstrap(connection):
    connection.dialect.default_schema_name = connection.exec_driver_sql(
        "SELECT current_schema()"
    ).scalar_one()
    baseline = metadata_subset(LEGACY_TABLES)
    project = baseline.tables["projects"]
    project.constraints.remove(
        next(c for c in project.constraints if c.name == "uq_projects_schema_scope")
    )
    context = MigrationContext.configure(connection)
    generated = produce_migrations(context, baseline)
    assert generated.upgrade_ops is not None
    for item in generated.upgrade_ops.ops:
        _invoke(Operations(context), item)
    connection.execute(
        sa.insert(Base.metadata.tables["users"]),
        {
            "id": "owner",
            "email": "schema-storage@example.test",
            "hashed_password": "unused",
        },
    )
    for suffix in ("a", "b"):
        connection.execute(
            sa.insert(Base.metadata.tables["tenants"]),
            {
                "id": f"tenant-{suffix}",
                "name": "Schema QA",
                "slug": f"schema-qa-{suffix}",
                "owner_id": "owner",
            },
        )
        connection.execute(
            sa.insert(Base.metadata.tables["projects"]),
            {
                "id": f"project-{suffix}",
                "name": "Schema QA",
                "tenant_id": f"tenant-{suffix}",
                "owner_id": "owner",
            },
        )
    connection.execute(
        sa.insert(Base.metadata.tables["entity_types"]),
        {
            "id": ENTITY_ID,
            "project_id": "project-a",
            "name": "Person",
            "description": None,
            "schema": {"age": {"type": "Integer"}},
            "status": "ENABLED",
            "source": "user",
        },
    )
    connection.execute(
        sa.insert(Base.metadata.tables["edge_types"]),
        {
            "id": EDGE_ID,
            "project_id": "project-a",
            "name": "KNOWS",
            "description": None,
            "schema": {},
            "status": "ENABLED",
            "source": "system",
        },
    )
    connection.execute(
        sa.insert(Base.metadata.tables["edge_type_maps"]),
        {
            "id": MAPPING_ID,
            "project_id": "project-a",
            "source_type": "Person",
            "target_type": "Person",
            "edge_type": "KNOWS",
            "status": "ENABLED",
            "source": "llm_discovered",
        },
    )


def snapshot(connection):
    result = {}
    for name in LEGACY_TABLES:
        table = metadata_subset(LEGACY_TABLES).tables[name]
        statement = sa.select(table).order_by(table.c.id)
        if name in {"entity_types", "edge_types"}:
            statement = statement.add_columns(sa.cast(table.c.schema, sa.Text).label("schema_raw"))
        result[name] = [dict(row) for row in connection.execute(statement).mappings()]
    return result


def apply_revision(connection, direction):
    with Operations.context(MigrationContext.configure(connection)):
        getattr(load_migration(), direction)()


@pytest.fixture
async def schema_storage_pg():
    raw = os.getenv("PROJECT_SCHEMA_POSTGRES_TEST_URL")
    if not raw:
        pytest.skip("PROJECT_SCHEMA_POSTGRES_TEST_URL must select the isolated schema QA database")
    url = sa.engine.make_url(raw)
    assert url.drivername == "postgresql+asyncpg"
    assert url.host in {"127.0.0.1", "localhost"}
    assert url.database == "memstack_schema_storage_qa"
    schema = "schema_storage_" + uuid4().hex
    engine = create_async_engine(
        url, poolclass=sa.pool.NullPool, connect_args={"server_settings": {"search_path": schema}}
    )
    try:
        async with engine.begin() as connection:
            # Schema lifecycle is managed through Alembic Operations as well.
            def create_schema(sync):
                Operations(MigrationContext.configure(sync)).execute(sa.schema.CreateSchema(schema))

            await connection.run_sync(create_schema)
            await connection.run_sync(bootstrap)
        yield engine, async_sessionmaker(engine, expire_on_commit=False)
    finally:
        async with engine.begin() as connection:

            def drop_schema(sync):
                Operations(MigrationContext.configure(sync)).execute(
                    sa.schema.DropSchema(schema, cascade=True, if_exists=True)
                )

            await connection.run_sync(drop_schema)
        await engine.dispose()
