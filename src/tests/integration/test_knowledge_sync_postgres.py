"""Real PostgreSQL ordering tests in a dedicated QA database, never the app DB.

Run with KNOWLEDGE_SYNC_POSTGRES_TESTS=1 after creating memstack_qa_sync_20260907.
The historical baseline migration is empty and cannot initialize an empty DB.
The fixture autogenerates an Alembic bootstrap for dependency tables, then runs
and reverses the real sync revision before applying it again for the tests.
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
    KnowledgeSyncScope,
    MemorySyncContent,
    MemorySyncMutation,
)
from src.infrastructure.adapters.secondary.persistence.models import (
    Base,
    Memory,
    Project,
    Tenant,
    User,
    UserProject,
    UserTenant,
)
from src.infrastructure.adapters.secondary.persistence.sql_knowledge_sync_repository import (
    SqlKnowledgeSyncRepository,
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
    "memories",
    "memory_shares",
    "memory_chunks",
)


class _PublicVector(sa.types.UserDefinedType):
    cache_ok = True

    def get_col_spec(self, **kw):
        return "public.vector"


def bootstrap(connection: sa.Connection) -> None:
    connection.dialect.default_schema_name = connection.exec_driver_sql(
        "SELECT current_schema()"
    ).scalar_one()
    metadata = sa.MetaData()
    for name in DEPENDENCY_TABLES:
        Base.metadata.tables[name].to_metadata(metadata)
    metadata.tables["memory_chunks"].c.embedding.type = _PublicVector()
    context = MigrationContext.configure(connection)
    generated = produce_migrations(context, metadata)
    assert generated.upgrade_ops is not None
    operations = Operations(context)
    operations.execute("CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public")
    for operation in generated.upgrade_ops.ops:
        if isinstance(operation, ModifyTableOps):
            for child in operation.ops:
                operations.invoke(child)
        else:
            operations.invoke(operation)
    path = (
        Path(__file__).parents[3]
        / "alembic/versions/a931fc278146_add_durable_knowledge_sync_foundation.py"
    )
    spec = importlib.util.spec_from_file_location("sync_revision", path)
    assert spec and spec.loader
    revision = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(revision)
    with Operations.context(context):
        revision.upgrade()
        assert "knowledge_sync_changes" in sa.inspect(connection).get_table_names()
        revision.downgrade()
        assert "knowledge_sync_changes" not in sa.inspect(connection).get_table_names()
        revision.upgrade()
        guard_path = (
            Path(__file__).parents[3]
            / "alembic/versions/b353e93ff302_fence_enrolled_knowledge_writes_and_.py"
        )
        guard_spec = importlib.util.spec_from_file_location("sync_guard_revision", guard_path)
        assert guard_spec and guard_spec.loader
        guard_revision = importlib.util.module_from_spec(guard_spec)
        guard_spec.loader.exec_module(guard_revision)
        guard_revision.upgrade()
        assert "knowledge_sync_enrollments" in sa.inspect(connection).get_table_names()
        guard_revision.downgrade()
        assert "knowledge_sync_enrollments" not in sa.inspect(connection).get_table_names()
        guard_revision.upgrade()
        graph_path = (
            Path(__file__).parents[3]
            / "alembic/versions/f3a9c51e7b24_add_durable_knowledge_graph_sync_journal.py"
        )
        graph_spec = importlib.util.spec_from_file_location("graph_sync_revision", graph_path)
        assert graph_spec and graph_spec.loader
        graph_revision = importlib.util.module_from_spec(graph_spec)
        graph_spec.loader.exec_module(graph_revision)
        graph_revision.upgrade()
        assert "knowledge_sync_graph_objects" in sa.inspect(connection).get_table_names()
        graph_revision.downgrade()
        assert "knowledge_sync_graph_objects" not in sa.inspect(connection).get_table_names()
        graph_revision.upgrade()


@pytest.fixture
async def pg_sync() -> AsyncGenerator[
    tuple[async_sessionmaker[AsyncSession], KnowledgeSyncScope], None
]:
    url = sa.engine.make_url(get_settings().postgres_url).set(database=QA_DATABASE)
    assert url.database == QA_DATABASE
    schema = "sync_" + uuid4().hex
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
        session.add(User(id="actor", email="sync@example.test", hashed_password="unused"))
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


def create(memory_id: str = "memory") -> MemorySyncMutation:
    return MemorySyncMutation(
        operation="create",
        memory_id=memory_id,
        expected_revision=0,
        content=MemorySyncContent(title="Original", content="Source"),
    )


async def test_pg_project_lock_orders_commit_and_cursor(pg_sync) -> None:
    sessions, scope = pg_sync
    async with sessions() as first, sessions() as second, sessions() as reader:
        await SqlKnowledgeSyncRepository(first).mutate(scope, str(uuid4()), create("first"))

        async def second_write():
            result = await SqlKnowledgeSyncRepository(second).mutate(
                scope, str(uuid4()), create("second")
            )
            await second.commit()
            return result

        waiting = asyncio.create_task(second_write())
        await asyncio.sleep(0.1)
        assert not waiting.done()
        assert (await SqlKnowledgeSyncRepository(reader).changes(scope, 0, 100)).next_cursor == 0
        await first.commit()
        outcome = await asyncio.wait_for(waiting, 5)
        assert outcome.to_dict()["receipt"]["sequence"] == 2
        page = await SqlKnowledgeSyncRepository(reader).changes(scope, 0, 100)
        assert [x["version"]["memory_id"] for x in page.to_dict()["changes"]] == ["first", "second"]


async def test_pg_concurrent_same_key_replays_one_write(pg_sync) -> None:
    sessions, scope = pg_sync
    key = str(uuid4())

    async def write():
        async with sessions() as session:
            outcome = await SqlKnowledgeSyncRepository(session).mutate(scope, key, create())
            await session.commit()
            return outcome

    left, right = await asyncio.gather(write(), write())
    assert left.receipt_json == right.receipt_json
    assert {left.replayed, right.replayed} == {False, True}
    async with sessions() as session:
        assert (await SqlKnowledgeSyncRepository(session).changes(scope, 0, 100)).next_cursor == 1


async def test_pg_concurrent_cas_has_one_conflict(pg_sync) -> None:
    sessions, scope = pg_sync
    async with sessions() as session:
        await SqlKnowledgeSyncRepository(session).mutate(scope, str(uuid4()), create())
        await session.commit()

    async def write(title):
        async with sessions() as session:
            outcome = await SqlKnowledgeSyncRepository(session).mutate(
                scope,
                str(uuid4()),
                MemorySyncMutation(
                    operation="update",
                    memory_id="memory",
                    expected_revision=1,
                    content=MemorySyncContent(title=title, content="Edit"),
                ),
            )
            await session.commit()
            return outcome.to_dict()["receipt"]

    receipts = await asyncio.gather(write("Left"), write("Right"))
    assert {receipt["status"] for receipt in receipts} == {"applied", "conflict"}
    async with sessions() as session:
        assert (await session.get(Memory, "memory")).version == 2
        assert (await SqlKnowledgeSyncRepository(session).changes(scope, 0, 100)).next_cursor == 2


async def test_pg_rollback_reuses_cursor_without_lost_change(pg_sync) -> None:
    sessions, scope = pg_sync
    async with sessions() as first:
        await SqlKnowledgeSyncRepository(first).mutate(scope, str(uuid4()), create("rolled-back"))
        await first.rollback()
    async with sessions() as second:
        outcome = await SqlKnowledgeSyncRepository(second).mutate(
            scope, str(uuid4()), create("committed")
        )
        await second.commit()
        assert outcome.to_dict()["receipt"]["sequence"] == 1
        assert await second.get(Memory, "rolled-back") is None
        page = await SqlKnowledgeSyncRepository(second).changes(scope, 0, 100)
        assert page.next_cursor == 1
        assert page.to_dict()["changes"][0]["version"]["memory_id"] == "committed"


async def test_pg_different_project_global_id_race_rejects_without_partial_journal(pg_sync) -> None:
    from src.domain.model.knowledge_sync.contracts import KnowledgeSyncError

    sessions, scope = pg_sync
    async with sessions() as session:
        session.add(
            Project(id="other", name="Other", tenant_id=scope.tenant_id, owner_id=scope.actor_id)
        )
        await session.flush()
        session.add(
            UserProject(id="other-up", project_id="other", user_id=scope.actor_id, role="owner")
        )
        await session.commit()
    other = KnowledgeSyncScope(
        tenant_id=scope.tenant_id, project_id="other", actor_id=scope.actor_id
    )
    async with sessions() as first, sessions() as second:
        await SqlKnowledgeSyncRepository(first).mutate(scope, str(uuid4()), create())
        waiting = asyncio.create_task(
            SqlKnowledgeSyncRepository(second).mutate(other, str(uuid4()), create())
        )
        await asyncio.sleep(0.1)
        assert not waiting.done()
        await first.commit()
        with pytest.raises(KnowledgeSyncError, match="write_conflict"):
            await asyncio.wait_for(waiting, 5)
        await second.commit()
        assert (await SqlKnowledgeSyncRepository(second).changes(other, 0, 100)).next_cursor == 0


async def test_pg_signed_integer_revision_limit_fails_before_write(pg_sync) -> None:
    from src.domain.model.knowledge_sync.contracts import MAX_REVISION, KnowledgeSyncError

    sessions, scope = pg_sync
    async with sessions() as session:
        repo = SqlKnowledgeSyncRepository(session)
        await repo.mutate(scope, str(uuid4()), create())
        await session.execute(
            sa.update(Memory).where(Memory.id == "memory").values(version=MAX_REVISION - 1)
        )
        await session.commit()
        last = await repo.mutate(
            scope,
            str(uuid4()),
            MemorySyncMutation(
                operation="update",
                memory_id="memory",
                expected_revision=MAX_REVISION - 1,
                content=MemorySyncContent(title="Last", content="Last"),
            ),
        )
        await session.commit()
        assert last.to_dict()["receipt"]["version"]["revision"] == MAX_REVISION
        with pytest.raises(KnowledgeSyncError, match="input_invalid"):
            MemorySyncMutation(
                operation="delete", memory_id="memory", expected_revision=MAX_REVISION
            )
        assert (await repo.changes(scope, 0, 100)).next_cursor == 2


async def test_pg_keep_current_can_resolve_at_maximum_revision(pg_sync) -> None:
    from src.domain.model.knowledge_sync.contracts import MAX_REVISION, KnowledgeSyncResolution

    sessions, scope = pg_sync
    async with sessions() as session:
        repo = SqlKnowledgeSyncRepository(session)
        await repo.mutate(scope, str(uuid4()), create())
        await session.execute(
            sa.update(Memory).where(Memory.id == "memory").values(version=MAX_REVISION)
        )
        await session.commit()
        conflict = await repo.mutate(
            scope,
            str(uuid4()),
            MemorySyncMutation(
                operation="update",
                memory_id="memory",
                expected_revision=1,
                content=MemorySyncContent(title="Offline", content="Offline"),
            ),
        )
        resolved = await repo.resolve(
            scope,
            str(uuid4()),
            KnowledgeSyncResolution(
                conflict_id=conflict.to_dict()["receipt"]["conflict_id"],
                expected_current_revision=MAX_REVISION,
                decision="keep_current",
            ),
        )
        await session.commit()
        assert resolved.to_dict()["receipt"]["version"]["revision"] == MAX_REVISION
        assert (await repo.changes(scope, 0, 100)).next_cursor == 1
