"""Private-schema PostgreSQL fixtures for legacy scheduler fencing."""

import uuid

import pytest_asyncio
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import Column, MetaData, String, Table, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.configuration.config import get_settings
from src.infrastructure.adapters.secondary.persistence.models import (
    CronJobModel,
    CronJobRunModel,
    CronSchedulerOwnerModel,
)

migration = ScriptDirectory.from_config(Config("alembic.ini")).get_revision("b36acb66634d").module


@pytest_asyncio.fixture(loop_scope="function")
async def database():
    schema = f"qa_legacy_admission_{uuid.uuid4().hex}"
    url = get_settings().postgres_url
    admin = create_async_engine(url)
    async with admin.begin() as connection:
        await connection.execute(text(f"CREATE SCHEMA {schema}"))
    engine = create_async_engine(url, connect_args={"server_settings": {"search_path": schema}})
    try:
        async with engine.begin() as connection:
            await connection.run_sync(CronSchedulerOwnerModel.__table__.create)
            metadata = MetaData()
            for name in ("projects", "tenants", "users"):
                Table(name, metadata, Column("id", String, primary_key=True))
            CronJobModel.__table__.to_metadata(metadata)
            CronJobRunModel.__table__.to_metadata(metadata)
            await connection.run_sync(metadata.create_all)
            for name, identity in (("projects", "project"), ("tenants", "tenant")):
                await connection.execute(metadata.tables[name].insert().values(id=identity))
            await connection.execute(
                CronJobModel.__table__.insert().values(
                    id="job", project_id="project", tenant_id="tenant", name="job",
                    schedule_type="every", schedule_config={"interval_seconds": 60},
                    payload_type="agent_turn", state={"next_run": "preserved"},
                )
            )

            def upgrade(sync):
                with Operations.context(MigrationContext.configure(sync)):
                    migration.upgrade()

            await connection.run_sync(upgrade)
        yield engine, async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()
        async with admin.begin() as connection:
            await connection.execute(text(f"DROP SCHEMA {schema} CASCADE"))
        await admin.dispose()
