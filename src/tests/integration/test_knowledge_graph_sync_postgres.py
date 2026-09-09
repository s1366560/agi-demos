"""Real PostgreSQL ordering tests for the graph sync journal; dedicated QA DB.

Run with KNOWLEDGE_SYNC_POSTGRES_TESTS=1 against memstack_qa_sync_20260907.
The fixture autogenerates an Alembic bootstrap for dependency tables, then runs
and reverses the real graph sync revision before applying it again.
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
from collections.abc import AsyncGenerator
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic.autogenerate import produce_migrations
from alembic.operations import Operations
from alembic.operations.ops import ModifyTableOps
from alembic.runtime.migration import MigrationContext
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.configuration.config import get_settings
from src.domain.model.knowledge_sync.contracts import (
    GraphSyncContent,
    GraphSyncEntity,
    GraphSyncMutation,
    GraphSyncResolution,
    KnowledgeSyncScope,
)
from src.infrastructure.adapters.secondary.persistence.models import (
    Base,
    Project,
    Tenant,
    User,
    UserProject,
    UserTenant,
)
from src.infrastructure.adapters.secondary.persistence.sql_knowledge_graph_sync_repository import (
    SqlKnowledgeGraphSyncRepository,
)

pytestmark = pytest.mark.skipif(
    os.getenv("KNOWLEDGE_SYNC_POSTGRES_TESTS") != "1",
    reason="Explicit opt-in required for the dedicated PostgreSQL QA database",
)
QA_DATABASE = "memstack_qa_sync_20260907"
DEPENDENCY_TABLES = (
    "users",
    "tenants",
    "projects",
    "user_tenants",
    "user_projects",
)


def bootstrap(connection: sa.Connection) -> None:
    connection.dialect.default_schema_name = connection.exec_driver_sql(
        "SELECT current_schema()"
    ).scalar_one()
    metadata = sa.MetaData()
    for name in DEPENDENCY_TABLES:
        Base.metadata.tables[name].to_metadata(metadata)
    context = MigrationContext.configure(connection)
    generated = produce_migrations(context, metadata)
    assert generated.upgrade_ops is not None
    operations = Operations(context)
    for operation in generated.upgrade_ops.ops:
        if isinstance(operation, ModifyTableOps):
            for child in operation.ops:
                operations.invoke(child)
        else:
            operations.invoke(operation)
    path = (
        Path(__file__).parents[3]
        / "alembic/versions/f3a9c51e7b24_add_durable_knowledge_graph_sync_journal.py"
    )
    spec = importlib.util.spec_from_file_location("graph_sync_revision", path)
    assert spec and spec.loader
    revision = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(revision)
    with Operations.context(context):
        revision.upgrade()
        assert "knowledge_sync_graph_changes" in sa.inspect(connection).get_table_names()
        revision.downgrade()
        assert "knowledge_sync_graph_changes" not in sa.inspect(connection).get_table_names()
        revision.upgrade()


@pytest.fixture
async def pg_sync() -> AsyncGenerator[
    tuple[async_sessionmaker[AsyncSession], KnowledgeSyncScope], None
]:
    url = sa.engine.make_url(get_settings().postgres_url).set(database=QA_DATABASE)
    assert url.database == QA_DATABASE
    schema = "graph_sync_" + uuid4().hex
    engine = create_async_engine(
        url,
        poolclass=sa.pool.NullPool,
        connect_args={"server_settings": {"search_path": schema}},
    )
    async with engine.begin() as connection:
        await connection.execute(sa.text(f'CREATE SCHEMA "{schema}"'))
        await connection.run_sync(bootstrap)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    scope = KnowledgeSyncScope(tenant_id="tenant", project_id="project", actor_id="actor")
    async with sessions() as session:
        session.add(User(id="actor", email="graph-sync@example.test", hashed_password="unused"))
        await session.flush()
        session.add(Tenant(id="tenant", name="QA", slug="qa", owner_id="actor"))
        await session.flush()
        session.add(Project(id="project", name="QA", tenant_id="tenant", owner_id="actor"))
        await session.flush()
        session.add_all(
            [
                UserTenant(id="ut", tenant_id="tenant", user_id="actor", role="owner"),
                UserProject(id="up", project_id="project", user_id="actor", role="owner"),
            ]
        )
        await session.commit()
    try:
        yield sessions, scope
    finally:
        async with engine.begin() as connection:
            await connection.execute(sa.text(f'DROP SCHEMA "{schema}" CASCADE'))
        await engine.dispose()


def create(object_id: str = "memory") -> GraphSyncMutation:
    return GraphSyncMutation(
        operation="create",
        object_id=object_id,
        expected_revision=0,
        content=GraphSyncContent(
            source_revision=1,
            change_sequence=1,
            audit_attempt=1,
            entities=(GraphSyncEntity(name="Alice", kind="person"),),
        ),
    )


async def test_pg_project_lock_orders_commit_and_cursor(pg_sync) -> None:
    sessions, scope = pg_sync
    async with sessions() as first, sessions() as second, sessions() as reader:
        await SqlKnowledgeGraphSyncRepository(first).mutate_graph(
            scope, str(uuid4()), create("first")
        )

        async def second_write():
            result = await SqlKnowledgeGraphSyncRepository(second).mutate_graph(
                scope, str(uuid4()), create("second")
            )
            await second.commit()
            return result

        waiting = asyncio.create_task(second_write())
        await asyncio.sleep(0.1)
        assert not waiting.done()
        assert (
            await SqlKnowledgeGraphSyncRepository(reader).graph_changes(scope, 0, 100)
        ).next_cursor == 0
        await first.commit()
        applied = await waiting
        assert applied.to_dict()["receipt"]["sequence"] == 2
        page = await SqlKnowledgeGraphSyncRepository(reader).graph_changes(scope, 0, 100)
        assert page.next_cursor == 2 and not page.has_more


async def test_pg_conflict_and_keep_both_copy_converge_through_the_journal(pg_sync) -> None:
    sessions, scope = pg_sync
    async with sessions() as session:
        repo = SqlKnowledgeGraphSyncRepository(session)
        await repo.mutate_graph(scope, str(uuid4()), create("memory"))
        await session.commit()
        await repo.mutate_graph(
            scope,
            str(uuid4()),
            GraphSyncMutation(
                operation="update",
                object_id="memory",
                expected_revision=1,
                content=create().content,
            ),
        )
        await session.commit()
        conflict = await repo.mutate_graph(
            scope,
            str(uuid4()),
            GraphSyncMutation(
                operation="update",
                object_id="memory",
                expected_revision=1,
                content=GraphSyncContent(
                    source_revision=2,
                    change_sequence=9,
                    audit_attempt=1,
                    entities=(GraphSyncEntity(name="Offline", kind="person"),),
                ),
            ),
        )
        await session.commit()
        conflict_id = conflict.to_dict()["receipt"]["conflict_id"]
        resolved = await repo.resolve_graph(
            scope,
            str(uuid4()),
            GraphSyncResolution(
                conflict_id=conflict_id, expected_current_revision=2, decision="keep_both"
            ),
        )
        await session.commit()
        receipt = resolved.to_dict()["receipt"]
        assert receipt["status"] == "resolved"
        page = await repo.graph_changes(scope, 0, 100)
        versions = [change["version"] for change in page.to_dict()["changes"]]
        assert [version["object_id"] for version in versions] == [
            "memory",
            "memory",
            receipt["copy_object_id"],
        ]
        assert versions[-1]["content"]["entities"][0]["name"] == "Offline"
