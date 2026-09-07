"""Exercise Rust legacy writers against the real Python enrollment migrations."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.configuration.config import get_settings
from src.domain.model.knowledge_sync.contracts import KnowledgeSyncScope
from src.infrastructure.adapters.secondary.persistence.sql_knowledge_sync_enrollment import (
    SqlKnowledgeSyncEnrollment,
)
from src.tests.integration.test_knowledge_sync_postgres import (  # noqa: F401
    QA_DATABASE,
    pg_sync as _pg_sync,
    pytestmark,
)

pg_sync = _pg_sync
ROOT = Path(__file__).parents[3]


async def test_rust_legacy_memory_admission(pg_sync):
    sessions, _scope = pg_sync
    async with sessions() as session:
        schema = await session.scalar(sa.text("SELECT current_schema()"))
    url = sa.engine.make_url(get_settings().postgres_url).set(
        drivername="postgresql", database=QA_DATABASE, query={"options": f"-csearch_path={schema}"}
    )
    env = {
        **os.environ,
        "AGISTACK_LEGACY_MEMORY_TEST_URL": url.render_as_string(hide_password=False),
        "AGISTACK_LEGACY_MEMORY_TEST_SCHEMA": schema,
        "AGISTACK_LEGACY_MEMORY_BOOTSTRAP": str(Path(__file__).resolve()),
        "AGISTACK_LEGACY_MEMORY_PYTHON": sys.executable,
        "AGISTACK_LEGACY_MEMORY_ROOT": str(ROOT),
        "PYTHONPATH": str(ROOT),
    }
    process = await asyncio.create_subprocess_exec(
        "cargo",
        "test",
        "-p",
        "agistack-adapters-postgres",
        "--test",
        "memory_legacy_admission",
        "--",
        "--test-threads=1",
        "--nocapture",
        cwd=ROOT / "agi-stack",
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    stdout, _ = await process.communicate()
    assert process.returncode == 0, stdout.decode()
    print(stdout.decode())
    process = await asyncio.create_subprocess_exec(
        "cargo",
        "test",
        "-p",
        "agistack-server",
        "legacy_memory_tests",
        "--",
        "--test-threads=1",
        "--nocapture",
        cwd=ROOT / "agi-stack",
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    stdout, _ = await process.communicate()
    assert process.returncode == 0, stdout.decode()
    print(stdout.decode())


async def _bootstrap() -> None:
    schema = os.environ["AGISTACK_LEGACY_MEMORY_TEST_SCHEMA"]
    url = sa.engine.make_url(get_settings().postgres_url).set(database=QA_DATABASE)
    assert url.database == QA_DATABASE
    engine = create_async_engine(
        url,
        poolclass=sa.pool.NullPool,
        connect_args={"server_settings": {"search_path": schema}},
    )
    try:
        async with async_sessionmaker(engine)() as session:
            await session.connection()
            print("BOOTSTRAP_READY", flush=True)
            result = await SqlKnowledgeSyncEnrollment(session).bootstrap(
                KnowledgeSyncScope(project_id=sys.argv[2], tenant_id="tenant", actor_id="actor")
            )
            await session.commit()
            print(json.dumps(result), flush=True)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    assert sys.argv[1] == "--bootstrap"
    asyncio.run(_bootstrap())
