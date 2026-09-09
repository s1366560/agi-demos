"""Dialect gating for pure active-schema snapshot reads."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.infrastructure.adapters.secondary.persistence.models import Base
from src.infrastructure.adapters.secondary.persistence.project_schema_models import (  # noqa: F401
    ProjectSchemaChangeModel,
    ProjectSchemaHeadModel,
    ProjectSchemaHttpReceiptModel,
    ProjectSchemaMigrationFindingModel,
    ProjectSchemaReceiptModel,
    ProjectSchemaTombstoneModel,
)
from src.infrastructure.adapters.secondary.schema.active_schema_reads import (
    active_schema_snapshot,
)

pytestmark = pytest.mark.unit


async def test_active_schema_snapshot_returns_none_on_non_postgresql_dialect() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as session:
        assert await active_schema_snapshot(session, "project-a") is None
    await engine.dispose()
