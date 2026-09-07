"""Real PostgreSQL round trip and model parity for permission receipt storage."""

import importlib.util
import os
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.ext.asyncio import create_async_engine

from src.infrastructure.adapters.secondary.persistence import (
    automation_permission_models,  # noqa: F401
)
from src.infrastructure.adapters.secondary.persistence.models import Base

pytestmark = pytest.mark.integration
PREFIX = "agistack_automation_permission_"


async def test_permission_migration_round_trip_matches_models():
    url = os.getenv("DATABASE_URL")
    if not url:
        pytest.skip("DATABASE_URL is required for real PostgreSQL migration validation")
    engine = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"))
    schema = "qa_permission_migration_" + uuid4().hex
    path = (
        Path(__file__).resolve().parents[3]
        / "alembic/versions/72847abc4b82_add_exact_automation_permission_receipts.py"
    )
    spec = importlib.util.spec_from_file_location("permission_migration", path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    def round_trip(connection):
        context = MigrationContext.configure(
            connection,
            opts={
                "include_object": lambda _obj, name, kind, _reflected, _compare: (
                    name.startswith(PREFIX) if kind == "table" else True
                )
            },
        )
        with Operations.context(context):
            migration.upgrade()
            assert compare_metadata(context, Base.metadata) == []
            migration.downgrade()
            assert sa.inspect(connection).get_table_names() == []
            migration.upgrade()
            assert compare_metadata(context, Base.metadata) == []

    try:
        async with engine.begin() as connection:
            await connection.execute(sa.text(f"CREATE SCHEMA {schema}"))
            await connection.execute(sa.text(f"SET LOCAL search_path TO {schema}"))
            await connection.run_sync(round_trip)
    finally:
        async with engine.begin() as connection:
            await connection.execute(sa.text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
        await engine.dispose()
