"""Tests for SqlAgentExecutionEventRepository."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.agent import AgentExecutionEvent
from src.infrastructure.adapters.secondary.persistence.sql_agent_execution_event_repository import (
    SqlAgentExecutionEventRepository,
)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_events_by_message_ids_filters_by_conversation_and_message_ids() -> None:
    """Batch lookups must scope by conversation_id to avoid cross-conversation leaks."""
    session = MagicMock(spec=AsyncSession)
    result = MagicMock()
    scalars = MagicMock()
    scalars.all.return_value = []
    result.scalars.return_value = scalars
    session.execute = AsyncMock(return_value=result)

    repo = SqlAgentExecutionEventRepository(session)

    await repo.get_events_by_message_ids("conv-a", {"shared-msg"})

    statement = session.execute.await_args.args[0]
    compiled = statement.compile()

    assert "agent_execution_events.conversation_id = :conversation_id_1" in str(compiled)
    assert "agent_execution_events.message_id IN" in str(compiled)
    assert compiled.params["conversation_id_1"] == "conv-a"
    assert compiled.params["message_id_1"] == ["shared-msg"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_events_by_message_filters_by_conversation_and_message_id() -> None:
    """Single-message lookups must scope by conversation_id to avoid leaks."""
    session = MagicMock(spec=AsyncSession)
    result = MagicMock()
    scalars = MagicMock()
    scalars.all.return_value = []
    result.scalars.return_value = scalars
    session.execute = AsyncMock(return_value=result)

    repo = SqlAgentExecutionEventRepository(session)

    await repo.get_events_by_message("conv-a", "shared-msg")

    statement = session.execute.await_args.args[0]
    compiled = statement.compile()

    assert "agent_execution_events.conversation_id = :conversation_id_1" in str(compiled)
    assert "agent_execution_events.message_id = :message_id_1" in str(compiled)
    assert compiled.params["conversation_id_1"] == "conv-a"
    assert compiled.params["message_id_1"] == "shared-msg"


@pytest.mark.unit
def test_to_db_sanitizes_nested_nul_bytes() -> None:
    """PostgreSQL JSON path extraction cannot convert JSON strings containing NUL bytes."""
    session = MagicMock(spec=AsyncSession)
    repo = SqlAgentExecutionEventRepository(session)
    event = AgentExecutionEvent(
        conversation_id="conv-a",
        message_id="msg-a",
        event_type="observe",
        event_data={
            "observation": "binary\x00output",
            "nested": ["ok\x00value", {"detail": "fine"}],
        },
    )

    model = repo._to_db(event)

    assert model.event_data["observation"] == "binary[NUL]output"
    assert model.event_data["nested"][0] == "ok[NUL]value"
