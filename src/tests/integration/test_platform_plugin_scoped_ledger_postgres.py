"""Real PostgreSQL lock and constraint coverage on the migrated v2 ledger slice."""

import asyncio
import importlib.util
import os
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.adapters.secondary.persistence.models import (
    PlatformPluginV2ApplyStateEventModel,
    PlatformPluginV2ApplyStateModel,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_repository_v2 import (
    PlatformPluginLedgerV2Error,
    PlatformPluginRepositoryV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_scope_ledger_v2 import (
    ScopeLedgerBindingV2,
)
from src.tests.unit.infrastructure.adapters.secondary.persistence.test_platform_plugin_repository_v2 import (
    _publication,
)

pytestmark = pytest.mark.integration


@pytest.fixture
async def sessions():
    url = os.environ.get("PLATFORM_PLUGIN_V2_POSTGRES_TEST_URL")
    if not url:
        pytest.skip("requires isolated migrated PostgreSQL ledger")
    engine = create_async_engine(url)
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


def _scope():
    return ScopeV2(kind=ScopeKindV2.TENANT, tenant_id=uuid4().hex)


async def test_downgrade_refuses_scoped_head_without_removing_schema(sessions):
    async with sessions.begin() as session:
        await PlatformPluginRepositoryV2(session, scope=_scope()).allocate_publication_version()
    path = (
        Path(__file__).resolve().parents[3]
        / "alembic/versions/b58c04d49a92_scope_plugin_publication_ledger.py"
    )
    spec = importlib.util.spec_from_file_location("scoped_ledger_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    def downgrade(connection):
        with Operations.context(MigrationContext.configure(connection)):
            module.downgrade()

    async with sessions() as session:
        connection = await session.connection()
        with pytest.raises(DBAPIError, match="requires ROOT-only data"):
            await connection.run_sync(downgrade)
        await session.rollback()
        assert await session.scalar(text("SELECT count(*) FROM platform_plugin_v2_scope_heads")) > 0


async def test_first_scope_allocation_serializes_and_rollback_reuses_version(sessions):
    scope = _scope()

    async def allocate():
        async with sessions.begin() as session:
            await session.execute(text("SET LOCAL lock_timeout = '5s'"))
            return await PlatformPluginRepositoryV2(
                session, scope=scope
            ).allocate_publication_version()

    versions = await asyncio.wait_for(asyncio.gather(*(allocate() for _ in range(8))), 15)
    assert sorted(versions) == list(range(1, 9))
    async with sessions() as session:
        assert (
            await PlatformPluginRepositoryV2(session, scope=scope).allocate_publication_version()
            == 9
        )
        await session.rollback()
    assert await allocate() == 9


async def test_cross_scope_nonce_race_preserves_domain_error_and_transaction(sessions, monkeypatch):
    publication, _ = await _publication(generation=1, version=1)
    value = replace(publication, envelope=replace(publication.envelope, nonce=uuid4().hex))
    barrier = asyncio.Barrier(2)
    original_insert = ScopeLedgerBindingV2.insert_publication

    async def synchronized_insert(binding, session, model):
        # Both real transactions have completed the pre-insert nonce lookup.
        await barrier.wait()
        await original_insert(binding, session, model)

    monkeypatch.setattr(ScopeLedgerBindingV2, "insert_publication", synchronized_insert)

    async def record(scope):
        async with sessions.begin() as session:
            await session.execute(text("SET LOCAL lock_timeout = '5s'"))
            repository = PlatformPluginRepositoryV2(session, scope=scope)
            try:
                await repository.record_publication(value)
            except PlatformPluginLedgerV2Error:
                assert await session.scalar(select(1)) == 1
                return "conflict"
            return "recorded"

    outcomes = await asyncio.wait_for(asyncio.gather(record(_scope()), record(_scope())), 15)
    assert sorted(outcomes) == ["conflict", "recorded"]


async def test_concurrent_first_receipt_is_idempotent_and_plane_is_scope_private(sessions):
    publication, _ = await _publication(generation=1, version=7)
    scope = _scope()
    value = replace(publication, envelope=replace(publication.envelope, nonce=uuid4().hex))

    async def record():
        async with sessions.begin() as session:
            await session.execute(text("SET LOCAL lock_timeout = '5s'"))
            result = await PlatformPluginRepositoryV2(
                session, scope=scope
            ).record_publication_and_receipt(value, data_plane_id="python-api-v2")
            return result.publication.id, result.apply_state.id

    results = await asyncio.wait_for(asyncio.gather(*(record() for _ in range(6))), 20)
    assert len(set(results)) == 1
    publication_id, state_id = results[0]
    async with sessions.begin() as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(PlatformPluginV2ApplyStateEventModel)
                .where(
                    PlatformPluginV2ApplyStateEventModel.requested_publication_id == publication_id
                )
            )
            == 1
        )
        other = await PlatformPluginRepositoryV2(
            session, scope=_scope()
        ).record_publication_and_receipt(
            replace(value, envelope=replace(value.envelope, nonce=uuid4().hex)),
            data_plane_id="python-api-v2",
        )
        assert other.apply_state.id != state_id
        assert other.publication.requested_version == 7
        foreign_id = other.publication.id
    # The database independently rejects cross-scope references even without the repository.
    async with sessions() as session:
        state = await session.get(PlatformPluginV2ApplyStateModel, state_id)
        state.applied_publication_id = foreign_id
        with pytest.raises(IntegrityError):
            await session.flush()
        await session.rollback()
