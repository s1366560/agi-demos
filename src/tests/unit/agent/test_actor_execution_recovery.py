"""Unit tests for Actor execution HITL recovery."""

from unittest.mock import AsyncMock

import pytest

from src.infrastructure.agent.actor import execution
from src.infrastructure.agent.hitl.state_store import HITLAgentState


class _FakeAgent:
    def __init__(self):
        self.calls = []

    async def execute_chat(
        self,
        conversation_id,
        user_message,
        user_id,
        conversation_context,
        tenant_id,
        message_id,
        hitl_response=None,
    ):
        self.calls.append(
            {
                "conversation_id": conversation_id,
                "user_message": user_message,
                "user_id": user_id,
                "conversation_context": conversation_context,
                "tenant_id": tenant_id,
                "message_id": message_id,
                "hitl_response": hitl_response,
            }
        )
        yield {"type": "complete", "data": {"content": "ok"}}


class _FakeStateStore:
    def __init__(self, redis_client):
        self.deleted_request_id = None

    async def load_state_by_request(self, request_id):
        return None

    async def delete_state_by_request(self, request_id):
        self.deleted_request_id = request_id
        return True


@pytest.mark.unit
class TestActorExecutionRecovery:
    """Tests HITL resume path with snapshot fallback."""

    async def test_continue_chat_recovers_from_snapshot(self, monkeypatch):
        state = HITLAgentState(
            conversation_id="conv-1",
            message_id="msg-1",
            tenant_id="tenant-1",
            project_id="project-1",
            hitl_request_id="req-1",
            hitl_type="clarification",
            hitl_request_data={"question": "q"},
            messages=[{"role": "user", "content": "hi"}],
            user_message="hi",
            user_id="user-1",
            correlation_id="corr-1",
            timeout_seconds=120.0,
        )

        agent = _FakeAgent()

        monkeypatch.setattr(execution, "_get_redis_client", AsyncMock(return_value=object()))
        monkeypatch.setattr(execution, "_publish_event_to_stream", AsyncMock())
        monkeypatch.setattr(execution, "_persist_events", AsyncMock())
        monkeypatch.setattr(execution, "set_agent_running", AsyncMock())
        monkeypatch.setattr(execution, "refresh_agent_running_ttl", AsyncMock())
        monkeypatch.setattr(execution, "clear_agent_running", AsyncMock())
        monkeypatch.setattr(execution, "delete_hitl_snapshot", AsyncMock())
        monkeypatch.setattr(execution, "load_hitl_snapshot", AsyncMock(return_value=state))
        monkeypatch.setattr(execution, "HITLStateStore", _FakeStateStore)

        result = await execution.continue_project_chat(agent, "req-1", {"answer": "ok"})

        assert result.is_error is False
        assert result.content == "ok"
        assert agent.calls
        assert agent.calls[0]["conversation_context"] == state.messages
        execution.load_hitl_snapshot.assert_awaited_once_with("req-1")
