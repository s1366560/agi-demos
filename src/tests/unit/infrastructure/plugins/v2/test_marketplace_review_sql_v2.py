"""Review rows survive a new database session, which is the process-restart boundary."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session

from src.infrastructure.adapters.secondary.persistence.platform_plugin_review_model_v2 import (
    PlatformPluginReviewRequestModelV2,
)
from src.infrastructure.plugins.v2.marketplace_governance_v2 import (
    SqlMarketplaceReviewQueueV2,
    decide_durable_review_v2,
    submit_durable_review_v2,
)


def test_review_survives_a_new_session() -> None:
    engine = create_engine("sqlite://")
    PlatformPluginReviewRequestModelV2.__table__.create(engine)
    with Session(engine) as first:
        submitted = SqlMarketplaceReviewQueueV2(first).submit(
            plugin_id="sample.notes",
            version="1.2.0",
            digest="sha256:abc",
            note="please review",
        )
        first.commit()
        review_id = submitted.review_id
    with Session(engine) as second:
        found = SqlMarketplaceReviewQueueV2(second).list(status="pending")
        assert [row.review_id for row in found] == [review_id]
        decided = SqlMarketplaceReviewQueueV2(second).decide(review_id, "approved")
        second.commit()
        assert decided.status == "approved"
    with Session(engine) as third:
        assert SqlMarketplaceReviewQueueV2(third).list()[0].status == "approved"


async def test_committed_review_is_visible_on_a_new_async_session() -> None:
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as connection:
        await connection.run_sync(PlatformPluginReviewRequestModelV2.__table__.create)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as first:
        submitted = await submit_durable_review_v2(
            first,
            plugin_id="sample.notes",
            version="1.2.0",
            digest="sha256:abc",
            note="please review",
        )
    async with factory() as second:
        decided = await decide_durable_review_v2(second, submitted.review_id, "approved")
        assert decided.status == "approved"
    async with factory() as third:
        found = await third.run_sync(lambda sync: SqlMarketplaceReviewQueueV2(sync).list())
        assert found[0].status == "approved"
    await engine.dispose()


def test_review_migration_upgrades_and_downgrades_on_sqlite() -> None:
    path = (
        Path(__file__).resolve().parents[6]
        / "alembic/versions/f2a3b4c5d6e8_add_plugin_review_requests_v2.py"
    )
    spec = importlib.util.spec_from_file_location("review_migration_v2", path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
        assert "platform_plugin_review_requests_v2" in inspect(connection).get_table_names()
        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()
        assert "platform_plugin_review_requests_v2" not in inspect(connection).get_table_names()
