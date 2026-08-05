"""Unit tests for Actor execution HITL recovery."""

from unittest.mock import AsyncMock

import pytest

from src.infrastructure.agent.actor import execution
from src.infrastructure.agent.hitl import coordinator as hitl_coordinator_mod
from src.infrastructure.agent.hitl.state_store import HITLAgentState


class _FakeAgent:
    def __init__(self) -> None:
        self.calls = []

    async def execute_chat(
        self,
        conversation_id,
        user_message,
        user_id,
        conversation_context,
        tenant_id,
        message_id,
        canonical_run_id=None,
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
                "canonical_run_id": canonical_run_id,
                "hitl_response": hitl_response,
            }
        )
        yield {"type": "complete", "data": {"content": "ok"}}


class _FakeStateStore:
    def __init__(self, redis_client) -> None:
        self.deleted_request_id = None

    async def load_state_by_request(self, request_id):
        return None

    async def delete_state_by_request(self, request_id):
        self.deleted_request_id = request_id
        return True


class _SummaryFakeAgent(_FakeAgent):
    async def execute_chat(
        self,
        conversation_id,
        user_message,
        user_id,
        conversation_context,
        tenant_id,
        message_id,
        canonical_run_id=None,
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
                "canonical_run_id": canonical_run_id,
                "hitl_response": hitl_response,
            }
        )
        yield {"type": "context_summary_generated", "data": {"summary": "saved"}}
        yield {"type": "complete", "data": {"content": "ok"}}


class _ErrorAgent(_FakeAgent):
    async def execute_chat(
        self,
        conversation_id,
        user_message,
        user_id,
        conversation_context,
        tenant_id,
        message_id,
        canonical_run_id=None,
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
                "canonical_run_id": canonical_run_id,
                "hitl_response": hitl_response,
            }
        )
        if False:
            yield {"type": "noop", "data": {}}
        raise RuntimeError("resume failed")


class _CanonicalRunAgent:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def execute_chat(self, **kwargs):
        self.calls.append(kwargs)
        yield {"type": "complete", "data": {"content": "ok"}}


@pytest.fixture(autouse=True)
def _stub_mark_hitl_completed(monkeypatch) -> AsyncMock:
    completion_mock = AsyncMock()
    monkeypatch.setattr(hitl_coordinator_mod, "mark_hitl_request_completed", completion_mock)
    return completion_mock


@pytest.fixture(autouse=True)
def _stub_run_authority(monkeypatch) -> tuple[AsyncMock, AsyncMock]:
    mark = AsyncMock()
    settle = AsyncMock()
    monkeypatch.setattr(execution, "_mark_root_run_authority_running", mark)
    monkeypatch.setattr(execution, "_settle_root_run_authority", settle)
    return mark, settle


@pytest.mark.unit
class TestActorExecutionRecovery:
    """Tests HITL resume path with snapshot fallback."""

    async def test_continue_chat_recovers_from_snapshot(
        self, monkeypatch, _stub_mark_hitl_completed: AsyncMock
    ):
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

        result = await execution.continue_project_chat(
            agent,
            "req-1",
            {"answer": "ok"},
            tenant_id="tenant-1",
            project_id="project-1",
            conversation_id="conv-1",
            message_id="msg-1",
        )

        assert result.is_error is False
        assert result.content == "ok"
        assert agent.calls
        assert agent.calls[0]["conversation_context"] == state.messages
        execution.load_hitl_snapshot.assert_awaited_once_with("req-1")
        _stub_mark_hitl_completed.assert_awaited_once_with("req-1", lease_owner=None)

    async def test_continue_chat_restores_canonical_plan_run_authority(
        self,
        monkeypatch,
        _stub_mark_hitl_completed: AsyncMock,
    ):
        state = HITLAgentState(
            conversation_id="conv-plan",
            message_id="client-message",
            canonical_run_id="plan-run",
            tenant_id="tenant-1",
            project_id="project-1",
            hitl_request_id="req-plan",
            hitl_type="permission",
            hitl_request_data={"action": "write"},
            user_message="continue",
            user_id="user-1",
        )
        agent = _CanonicalRunAgent()
        mark = AsyncMock()
        settle = AsyncMock()
        _stub_mark_hitl_completed.return_value = True

        monkeypatch.setattr(execution, "_get_redis_client", AsyncMock(return_value=object()))
        monkeypatch.setattr(execution, "_publish_event_to_stream", AsyncMock())
        monkeypatch.setattr(execution, "_persist_events", AsyncMock())
        monkeypatch.setattr(execution, "set_agent_running", AsyncMock())
        monkeypatch.setattr(execution, "clear_agent_running", AsyncMock())
        monkeypatch.setattr(execution, "delete_hitl_snapshot", AsyncMock())
        monkeypatch.setattr(execution, "load_hitl_snapshot", AsyncMock(return_value=state))
        monkeypatch.setattr(execution, "HITLStateStore", _FakeStateStore)
        monkeypatch.setattr(execution, "_mark_root_run_authority_running", mark)
        monkeypatch.setattr(execution, "_settle_root_run_authority", settle)

        result = await execution.continue_project_chat(
            agent,
            "req-plan",
            {"action": "allow"},
            tenant_id="tenant-1",
            project_id="project-1",
            conversation_id="conv-plan",
            message_id="client-message",
        )

        assert result.is_error is False
        assert agent.calls[0]["message_id"] == "client-message"
        assert agent.calls[0]["canonical_run_id"] == "plan-run"
        mark.assert_awaited_once_with(
            tenant_id="tenant-1",
            project_id="project-1",
            conversation_id="conv-plan",
            run_id="plan-run",
        )
        settle.assert_awaited_once_with(
            tenant_id="tenant-1",
            project_id="project-1",
            conversation_id="conv-plan",
            run_id="plan-run",
            outcome="success",
            error=None,
        )

    async def test_continue_chat_keeps_recovery_state_when_completion_is_rejected(
        self, monkeypatch, _stub_mark_hitl_completed: AsyncMock
    ):
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
        fake_state_store = _FakeStateStore(redis_client=object())
        delete_snapshot = AsyncMock()
        _stub_mark_hitl_completed.return_value = False

        monkeypatch.setattr(execution, "_get_redis_client", AsyncMock(return_value=object()))
        monkeypatch.setattr(execution, "_publish_event_to_stream", AsyncMock())
        monkeypatch.setattr(execution, "_persist_events", AsyncMock())
        monkeypatch.setattr(execution, "set_agent_running", AsyncMock())
        monkeypatch.setattr(execution, "refresh_agent_running_ttl", AsyncMock())
        monkeypatch.setattr(execution, "clear_agent_running", AsyncMock())
        monkeypatch.setattr(execution, "delete_hitl_snapshot", delete_snapshot)
        monkeypatch.setattr(execution, "load_hitl_snapshot", AsyncMock(return_value=state))
        monkeypatch.setattr(execution, "HITLStateStore", lambda _redis: fake_state_store)

        result = await execution.continue_project_chat(
            agent,
            "req-1",
            {"answer": "ok"},
            lease_owner="worker-1",
            tenant_id="tenant-1",
            project_id="project-1",
            conversation_id="conv-1",
            message_id="msg-1",
        )

        assert result.is_error is False
        assert fake_state_store.deleted_request_id is None
        delete_snapshot.assert_not_awaited()
        _stub_mark_hitl_completed.assert_awaited_once_with("req-1", lease_owner="worker-1")

    async def test_continue_chat_persists_context_summary_side_effects(self, monkeypatch):
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

        agent = _SummaryFakeAgent()

        monkeypatch.setattr(execution, "_get_redis_client", AsyncMock(return_value=object()))
        monkeypatch.setattr(execution, "_publish_event_to_stream", AsyncMock())
        monkeypatch.setattr(execution, "_persist_events", AsyncMock())
        monkeypatch.setattr(execution, "_flush_remaining_events", AsyncMock())
        monkeypatch.setattr(execution, "_save_context_summary", AsyncMock())
        monkeypatch.setattr(execution, "set_agent_running", AsyncMock())
        monkeypatch.setattr(execution, "refresh_agent_running_ttl", AsyncMock())
        monkeypatch.setattr(execution, "clear_agent_running", AsyncMock())
        monkeypatch.setattr(execution, "delete_hitl_snapshot", AsyncMock())
        monkeypatch.setattr(execution, "load_hitl_snapshot", AsyncMock(return_value=state))
        monkeypatch.setattr(execution, "HITLStateStore", _FakeStateStore)

        result = await execution.continue_project_chat(
            agent,
            "req-1",
            {"answer": "ok"},
            tenant_id="tenant-1",
            project_id="project-1",
            conversation_id="conv-1",
            message_id="msg-1",
        )

        assert result.is_error is False
        execution._save_context_summary.assert_awaited_once_with(
            conversation_id="conv-1",
            summary_data={"summary": "saved"},
            last_event_time_us=result.last_event_time_us,
        )

    async def test_continue_chat_rejects_binding_mismatch(self, monkeypatch):
        state = HITLAgentState(
            conversation_id="conv-1",
            message_id="msg-1",
            tenant_id="tenant-1",
            project_id="project-1",
            hitl_request_id="req-1",
            hitl_type="clarification",
            hitl_request_data={"question": "q", "allow_custom": True},
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

        result = await execution.continue_project_chat(
            agent,
            "req-1",
            {"answer": "ok"},
            tenant_id="tenant-1",
            project_id="project-1",
            conversation_id="conv-2",
            message_id="msg-1",
        )

        assert result.is_error is True
        assert result.error_message == "Rejected HITL response due to binding mismatch"
        assert not agent.calls
        execution.delete_hitl_snapshot.assert_not_awaited()

    async def test_continue_chat_keeps_recovery_state_on_resume_error(
        self, monkeypatch, _stub_mark_hitl_completed: AsyncMock
    ):
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

        agent = _ErrorAgent()

        monkeypatch.setattr(execution, "_get_redis_client", AsyncMock(return_value=object()))
        monkeypatch.setattr(execution, "_publish_event_to_stream", AsyncMock())
        monkeypatch.setattr(execution, "_persist_events", AsyncMock())
        monkeypatch.setattr(execution, "set_agent_running", AsyncMock())
        monkeypatch.setattr(execution, "refresh_agent_running_ttl", AsyncMock())
        monkeypatch.setattr(execution, "clear_agent_running", AsyncMock())
        monkeypatch.setattr(execution, "delete_hitl_snapshot", AsyncMock())
        monkeypatch.setattr(execution, "load_hitl_snapshot", AsyncMock(return_value=state))
        monkeypatch.setattr(execution, "HITLStateStore", _FakeStateStore)

        result = await execution.continue_project_chat(
            agent,
            "req-1",
            {"answer": "ok"},
            tenant_id="tenant-1",
            project_id="project-1",
            conversation_id="conv-1",
            message_id="msg-1",
        )

        assert result.is_error is True
        _stub_mark_hitl_completed.assert_not_awaited()
        execution.delete_hitl_snapshot.assert_not_awaited()

    async def test_continue_chat_finalizes_child_session_after_resume(
        self, monkeypatch, _stub_mark_hitl_completed: AsyncMock
    ):
        state = HITLAgentState(
            conversation_id="child-conv",
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
            agent_id="child-agent",
            parent_session_id="parent-conv",
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
        monkeypatch.setattr(execution, "_finalize_child_session_result", AsyncMock())
        monkeypatch.setattr(execution, "_publish_announce_via_service", AsyncMock())

        result = await execution.continue_project_chat(
            agent,
            "req-1",
            {"answer": "ok"},
            tenant_id="tenant-1",
            project_id="project-1",
            conversation_id="child-conv",
            message_id="msg-1",
        )

        assert result.is_error is False
        execution._finalize_child_session_result.assert_awaited_once_with(
            agent_id="child-agent",
            child_session_id="child-conv",
            request_message_id="msg-1",
            parent_session_id="parent-conv",
            result_content="ok",
            success=True,
            event_count=1,
            execution_time_ms=result.execution_time_ms,
            error_message=None,
        )

    async def test_continue_chat_finalizes_child_session_on_resume_error(
        self, monkeypatch, _stub_mark_hitl_completed: AsyncMock
    ):
        state = HITLAgentState(
            conversation_id="child-conv",
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
            agent_id="child-agent",
            parent_session_id="parent-conv",
            timeout_seconds=120.0,
        )

        agent = _ErrorAgent()

        monkeypatch.setattr(execution, "_get_redis_client", AsyncMock(return_value=object()))
        monkeypatch.setattr(execution, "_publish_event_to_stream", AsyncMock())
        monkeypatch.setattr(execution, "_persist_events", AsyncMock())
        monkeypatch.setattr(execution, "set_agent_running", AsyncMock())
        monkeypatch.setattr(execution, "refresh_agent_running_ttl", AsyncMock())
        monkeypatch.setattr(execution, "clear_agent_running", AsyncMock())
        monkeypatch.setattr(execution, "delete_hitl_snapshot", AsyncMock())
        monkeypatch.setattr(execution, "load_hitl_snapshot", AsyncMock(return_value=state))
        monkeypatch.setattr(execution, "HITLStateStore", _FakeStateStore)
        monkeypatch.setattr(execution, "_handle_chat_error", AsyncMock())

        await execution.continue_project_chat(
            agent,
            "req-1",
            {"answer": "ok"},
            tenant_id="tenant-1",
            project_id="project-1",
            conversation_id="child-conv",
            message_id="msg-1",
        )

        execution._handle_chat_error.assert_awaited_once()
        assert execution._handle_chat_error.await_args.kwargs["agent_id"] == "child-agent"
        assert execution._handle_chat_error.await_args.kwargs["parent_session_id"] == "parent-conv"
