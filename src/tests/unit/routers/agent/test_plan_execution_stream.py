"""Approval execution must preserve live events and actual terminal outcomes."""

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.infrastructure.adapters.primary.web.routers.agent import plans


@pytest.mark.unit
@pytest.mark.parametrize("ending", ["complete", "error", "cancelled", "missing"])
async def test_approved_plan_broadcasts_and_settles_stream_outcome(monkeypatch, ending):
    run = SimpleNamespace(
        status="queued", revision=1, updated_at=datetime.now(UTC), completed_at=None, error=None
    )
    session = SimpleNamespace(
        get=AsyncMock(return_value=run),
        refresh=AsyncMock(),
        commit=AsyncMock(),
        rollback=AsyncMock(),
    )

    @asynccontextmanager
    async def session_context():
        yield session

    @asynccontextmanager
    async def operation_context(**kwargs):
        yield None

    events = [
        {
            "type": "text_delta",
            "data": {"delta": "working"},
            "event_time_us": 123,
            "event_counter": 4,
        }
    ]
    if ending != "missing":
        events.append(
            {"type": ending, "data": {"message": "Execution failed"} if ending == "error" else {}}
        )

    class Service:
        async def stream_chat_v2(self, **kwargs):
            for event in events:
                yield event

    manager = SimpleNamespace(broadcast_to_conversation=AsyncMock())
    statuses = []

    async def publish(**kwargs):
        statuses.append(kwargs["run"].status)

    monkeypatch.setattr(plans, "async_session_factory", session_context)
    monkeypatch.setattr(plans, "pin_agent_turn_operation_v2", operation_context)
    monkeypatch.setattr(plans, "current_agent_turn_service_v2", AsyncMock(return_value=Service()))
    monkeypatch.setattr(plans, "get_connection_manager", lambda: manager)
    monkeypatch.setattr(plans, "_publish_plan_run_status", publish)
    settle = AsyncMock()
    monkeypatch.setattr(plans, "settle_agent_plan_run", settle)
    await plans._execute_approved_plan(
        run_id="run-1",
        conversation_id="conversation-1",
        project_id="project-1",
        tenant_id="tenant-1",
        user_id="user-1",
        message="Execute",
        message_id="message-1",
    )
    expected = {
        "complete": "ready_review",
        "error": "failed",
        "cancelled": "cancelled",
        "missing": "failed",
    }[ending]
    assert run.status == expected
    assert statuses == ["running", expected]
    assert manager.broadcast_to_conversation.await_count == len(events)
    for call, source in zip(manager.broadcast_to_conversation.await_args_list, events, strict=True):
        assert call.args[0] == "conversation-1"
        assert call.args[1]["conversation_id"] == "conversation-1"
        assert call.args[1]["type"] == source["type"]
        assert call.args[1]["data"] == source["data"]
    assert settle.await_args.kwargs["succeeded"] is (ending == "complete")
