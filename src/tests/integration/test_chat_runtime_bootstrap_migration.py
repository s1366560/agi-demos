"""Exercise legacy event data through the real PostgreSQL timeline migration."""

import importlib.util
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.ext.asyncio import create_async_engine

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("already_current", [False, True])
async def test_timeline_migration_preserves_order_and_accepts_new_events(already_current: bool):
    url = os.getenv("MEMSTACK_MIGRATION_TEST_DATABASE_URL")
    if not url:
        pytest.skip("An explicitly owned PostgreSQL migration test database is required")
    engine = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"))
    schema = "qa_chat_bootstrap_" + uuid4().hex
    path = (
        Path(__file__).resolve().parents[3]
        / "alembic/versions/c86fa94f00dd_complete_chat_runtime_bootstrap.py"
    )
    spec = importlib.util.spec_from_file_location("chat_bootstrap_migration", path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    def migrate(connection):
        with Operations.context(MigrationContext.configure(connection)):
            fields = (
                [
                    sa.Column("event_time_us", sa.BigInteger(), nullable=False),
                    sa.Column("event_counter", sa.Integer(), nullable=False),
                ]
                if already_current
                else [sa.Column("sequence_number", sa.Integer(), nullable=False)]
            )
            from alembic import op

            op.create_table(
                "agent_execution_events",
                sa.Column("id", sa.String(), primary_key=True),
                sa.Column("conversation_id", sa.String(), nullable=False),
                sa.Column("message_id", sa.String(), nullable=True),
                sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
                *fields,
            )
            events = sa.Table("agent_execution_events", sa.MetaData(), autoload_with=connection)
            base_time = datetime(2026, 1, 1, tzinfo=UTC)
            times = [
                base_time,
                base_time,
                base_time - timedelta(seconds=1),
                base_time + timedelta(seconds=1),
            ]
            expected_us = [int(base_time.timestamp()) * 1_000_000] * 3
            expected_us.append(expected_us[-1] + 1_000_000)
            for index, created_at in enumerate(times):
                order = (
                    {
                        "event_time_us": expected_us[index],
                        "event_counter": index if index < 3 else 0,
                    }
                    if already_current
                    else {"sequence_number": index}
                )
                connection.execute(
                    events.insert().values(
                        id=str(index),
                        conversation_id="legacy",
                        created_at=created_at,
                        **order,
                    )
                )
            migration._event_timeline()
            # Reapplying the repair preserves already-current rows and constraints.
            migration._event_timeline()
            rows = connection.execute(
                sa.text(
                    "SELECT id, event_time_us, event_counter FROM agent_execution_events "
                    "ORDER BY event_time_us, event_counter"
                )
            ).all()
            assert rows == [
                (str(index), expected_us[index], index if index < 3 else 0) for index in range(4)
            ]
            current = sa.Table("agent_execution_events", sa.MetaData(), autoload_with=connection)
            assert "sequence_number" not in current.c
            connection.execute(
                current.insert().values(
                    id="new",
                    conversation_id="legacy",
                    created_at=base_time,
                    event_time_us=expected_us[-1] + 1,
                    event_counter=0,
                )
            )
            assert connection.scalar(sa.select(sa.func.count()).select_from(current)) == 5

    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                await connection.execute(sa.schema.CreateSchema(schema))
                await connection.execute(sa.text(f"SET LOCAL search_path TO {schema}"))
                await connection.run_sync(migrate)
            finally:
                await transaction.rollback()
    finally:
        await engine.dispose()
