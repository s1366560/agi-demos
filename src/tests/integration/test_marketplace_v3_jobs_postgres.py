"""Running marketplace jobs remain visible while the installation transaction is locked."""

from __future__ import annotations

import asyncio
import importlib.util
import os
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.schema import CreateSchema, DropSchema

from src.application.services.plugin_marketplace_v3 import PluginMarketplaceV3

pytestmark = pytest.mark.integration


def migrate(connection):
    path = (
        Path(__file__).resolve().parents[3]
        / "alembic/versions/37d3b107b19c_add_unified_plugin_marketplace_records.py"
    )
    spec = importlib.util.spec_from_file_location("marketplace_jobs_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with Operations.context(MigrationContext.configure(connection)):
        module.upgrade()


@pytest_asyncio.fixture(loop_scope="function")
async def sessions():
    url = os.environ.get("PLATFORM_PLUGIN_V2_POSTGRES_TEST_URL")
    if not url:
        pytest.skip("requires the owned PostgreSQL runner")
    schema = f"marketplace_jobs_{uuid4().hex}"
    admin = create_async_engine(url)
    engine = create_async_engine(
        url,
        connect_args={
            "server_settings": {
                "search_path": schema,
                "lock_timeout": "5s",
                "statement_timeout": "10s",
            }
        },
    )
    try:
        async with admin.begin() as connection:
            await connection.execute(CreateSchema(schema))
        async with engine.begin() as connection:
            await connection.run_sync(migrate)
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()
        async with admin.begin() as connection:
            await connection.execute(DropSchema(schema, cascade=True))
        await admin.dispose()


async def test_running_job_visible_on_independent_connection_before_runtime_finishes(sessions):
    entered, release = asyncio.Event(), asyncio.Event()
    async with sessions() as mutation:
        service = PluginMarketplaceV3(mutation, "tenant", "project")
        installation = await service.add_record(
            "installation",
            {
                "status": "downloaded",
                "package": {"resources": {}},
                "owned_skills": [],
                "owned_servers": [],
            },
        )
        await mutation.commit()
        writer_pid = await mutation.scalar(text("select pg_backend_pid()"))

        async def activate(payload):
            entered.set()
            await release.wait()
            payload["status"] = "enabled"

        service._activate = activate
        task = asyncio.create_task(
            service.mutate(installation.id, "enable", {"idempotency_key": "visible-job"})
        )
        await asyncio.wait_for(entered.wait(), 5)
        async with sessions() as observer:
            reader_pid = await observer.scalar(text("select pg_backend_pid()"))
            assert writer_pid != reader_pid
            jobs = await PluginMarketplaceV3(observer, "tenant", "project").records("operation")
            assert len(jobs) == 1
            assert jobs[0].payload["status"] == "running"
            job_id = jobs[0].id
        release.set()
        result = await asyncio.wait_for(task, 5)
        assert result["job_id"] == job_id
        await mutation.commit()
    async with sessions() as restarted:
        job = await PluginMarketplaceV3(restarted, "tenant", "project").record(job_id, "operation")
        assert job.payload["status"] == "completed"
        assert job.payload["stage"] == "enabled"
