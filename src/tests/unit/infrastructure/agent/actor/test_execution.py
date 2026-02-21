"""Unit tests for actor execution helpers."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.infrastructure.agent.actor import execution
from src.infrastructure.agent.actor.types import ProjectChatRequest


class _FakeAgent:
    def __init__(self) -> None:
        self.config = SimpleNamespace(project_id="proj-1", tenant_id="tenant-1")
        self.execute_chat_kwargs: dict | None = None

    async def execute_chat(self, **kwargs):
        self.execute_chat_kwargs = kwargs
        yield {"type": "complete", "data": {"content": "done"}}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_execute_project_chat_passes_abort_signal() -> None:
    """execute_project_chat should forward abort_signal into agent.execute_chat."""
    agent = _FakeAgent()
    request = ProjectChatRequest(
        conversation_id="conv-1",
        message_id="msg-1",
        user_message="hello",
        user_id="user-1",
        conversation_context=[],
    )
    abort_signal = asyncio.Event()

    with (
        patch.object(execution, "set_agent_running", new=AsyncMock()),
        patch.object(execution, "clear_agent_running", new=AsyncMock()),
        patch.object(execution, "_get_last_db_event_time", new=AsyncMock(return_value=(0, 0))),
        patch.object(execution, "_get_redis_client", new=AsyncMock(return_value=object())),
        patch.object(execution, "_publish_event_to_stream", new=AsyncMock()),
        patch.object(execution, "_persist_events", new=AsyncMock()),
        patch.object(execution.agent_metrics, "increment"),
        patch.object(execution.agent_metrics, "observe"),
    ):
        result = await execution.execute_project_chat(
            agent=agent,
            request=request,
            abort_signal=abort_signal,
        )

    assert result.is_error is False
    assert agent.execute_chat_kwargs is not None
    assert agent.execute_chat_kwargs["abort_signal"] is abort_signal


@pytest.mark.unit
@pytest.mark.asyncio
async def test_persist_events_skips_complete_when_assistant_exists() -> None:
    """_persist_events should not add duplicate assistant_message on complete."""
    session = MagicMock()
    existing_result = MagicMock()
    existing_result.scalars.return_value.all.return_value = [{"source": "complete"}]
    session.execute = AsyncMock(return_value=existing_result)

    begin_ctx = AsyncMock()
    begin_ctx.__aenter__.return_value = None
    begin_ctx.__aexit__.return_value = None
    session.begin.return_value = begin_ctx

    session_ctx = AsyncMock()
    session_ctx.__aenter__.return_value = session
    session_ctx.__aexit__.return_value = None

    with patch.object(execution, "async_session_factory", return_value=session_ctx):
        await execution._persist_events(
            conversation_id="conv-1",
            message_id="msg-1",
            events=[{"type": "complete", "data": {"content": "final answer"}}],
        )

    # Only the assistant existence check query should run; no insert should happen.
    assert session.execute.await_count == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_persist_events_converts_complete_to_assistant_message() -> None:
    """_persist_events should persist complete content when no assistant exists."""
    session = MagicMock()
    existing_result = MagicMock()
    existing_result.scalars.return_value.all.return_value = []
    session.execute = AsyncMock(side_effect=[existing_result, MagicMock()])

    begin_ctx = AsyncMock()
    begin_ctx.__aenter__.return_value = None
    begin_ctx.__aexit__.return_value = None
    session.begin.return_value = begin_ctx

    session_ctx = AsyncMock()
    session_ctx.__aenter__.return_value = session
    session_ctx.__aexit__.return_value = None

    with patch.object(execution, "async_session_factory", return_value=session_ctx):
        await execution._persist_events(
            conversation_id="conv-1",
            message_id="msg-1",
            events=[{"type": "complete", "data": {"content": "final answer"}}],
        )

    # One query for existing assistant + one insert for converted assistant_message.
    assert session.execute.await_count == 2
