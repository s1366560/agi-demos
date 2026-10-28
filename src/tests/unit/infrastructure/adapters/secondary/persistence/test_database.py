"""Tests for persistence database initialization helpers."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.infrastructure.adapters.secondary.persistence import database
from src.infrastructure.adapters.secondary.persistence.models import (
    AGENT_EXECUTION_EVENT_CORRELATION_ID_LENGTH,
    AgentExecutionEvent,
)


@pytest.mark.unit
def test_agent_execution_event_correlation_id_allows_prefixed_uuids() -> None:
    """Correlation IDs must hold prefixed UUIDs such as cron job identifiers."""
    correlation_id_column = AgentExecutionEvent.__table__.c.correlation_id

    assert correlation_id_column.type.length == AGENT_EXECUTION_EVENT_CORRELATION_ID_LENGTH
    assert AGENT_EXECUTION_EVENT_CORRELATION_ID_LENGTH >= 41


@pytest.mark.unit
async def test_initialize_database_runs_full_migrations_without_stamping() -> None:
    """Schema owners outside SQLAlchemy must be initialized by their migrations."""
    with patch("alembic.command.upgrade") as upgrade, patch("alembic.command.stamp") as stamp:
        await database.initialize_database()

    config, target = upgrade.call_args.args
    assert target == "head"
    assert config.attributes["configure_logger"] is False
    assert config.get_main_option("script_location").endswith("/alembic")
    stamp.assert_not_called()


@pytest.mark.unit
async def test_initialize_database_propagates_migration_failure() -> None:
    """Startup must fail instead of serving from a partially migrated schema."""
    with (
        patch("alembic.command.upgrade", side_effect=RuntimeError("migration failed")),
        pytest.raises(RuntimeError, match="migration failed"),
    ):
        await database.initialize_database()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_update_agent_events_schema_widens_correlation_id_and_adds_index() -> None:
    """Schema repair should widen correlation_id and restore its lookup index."""

    class _ScalarResult:
        def __init__(self, value: int | None) -> None:
            self._value = value

        def scalar_one_or_none(self) -> int | None:
            return self._value

    conn = MagicMock()
    conn.execute = AsyncMock(
        side_effect=[
            None,
            _ScalarResult(None),
            None,
            None,
            None,
            None,
        ]
    )

    begin_ctx = AsyncMock()
    begin_ctx.__aenter__.return_value = conn
    begin_ctx.__aexit__.return_value = None
    fake_engine = MagicMock()
    fake_engine.begin.return_value = begin_ctx

    with patch.object(database, "engine", fake_engine):
        await database.update_agent_events_schema()

    executed_sql = [
        " ".join(str(await_call.args[0]).split()) for await_call in conn.execute.await_args_list
    ]

    assert any(
        "ALTER TABLE agent_execution_events ALTER COLUMN correlation_id TYPE "
        f"VARCHAR({AGENT_EXECUTION_EVENT_CORRELATION_ID_LENGTH})" in sql
        for sql in executed_sql
    )
    assert any(
        "SELECT 1 FROM pg_constraint WHERE conname = 'uq_agent_events_conv_time' "
        "AND conrelid = 'agent_execution_events'::regclass" in sql
        for sql in executed_sql
    )
    assert any(
        "ALTER TABLE agent_execution_events ADD CONSTRAINT uq_agent_events_conv_time "
        "UNIQUE (conversation_id, event_time_us, event_counter)" in sql
        for sql in executed_sql
    )
    assert not any("ADD CONSTRAINT IF NOT EXISTS" in sql for sql in executed_sql)
    assert any(
        "CREATE INDEX IF NOT EXISTS ix_agent_events_corr_id "
        "ON agent_execution_events (correlation_id)" in sql
        for sql in executed_sql
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_update_agent_events_schema_skips_existing_unique_constraint() -> None:
    """Existing unique constraints should not trigger duplicate DDL."""

    class _ScalarResult:
        def scalar_one_or_none(self) -> int:
            return 1

    conn = MagicMock()
    conn.execute = AsyncMock(
        side_effect=[
            None,
            _ScalarResult(),
            None,
            None,
            None,
        ]
    )

    begin_ctx = AsyncMock()
    begin_ctx.__aenter__.return_value = conn
    begin_ctx.__aexit__.return_value = None
    fake_engine = MagicMock()
    fake_engine.begin.return_value = begin_ctx

    with patch.object(database, "engine", fake_engine):
        await database.update_agent_events_schema()

    executed_sql = [
        " ".join(str(await_call.args[0]).split()) for await_call in conn.execute.await_args_list
    ]

    assert any("SELECT 1 FROM pg_constraint" in sql for sql in executed_sql)
    assert not any(
        "ALTER TABLE agent_execution_events ADD CONSTRAINT uq_agent_events_conv_time" in sql
        for sql in executed_sql
    )
