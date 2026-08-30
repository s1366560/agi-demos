"""Unit tests for actor execution helpers."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from src.domain.model.agent.hitl.hitl_types import HITLPendingException, HITLType
from src.domain.model.agent.spawn_mode import SpawnMode
from src.domain.ports.services.agent_message_bus_port import AgentMessageType
from src.infrastructure.agent.actor import execution
from src.infrastructure.agent.actor.types import ProjectChatRequest
from src.infrastructure.agent.hitl.state_store import HITLAgentState
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error
from src.infrastructure.plugins.v2.session_event_log import MODEL_MESSAGE_COMMITTED_EVENT_V2


@pytest.fixture(autouse=True)
def root_run_authority_mocks(monkeypatch: pytest.MonkeyPatch) -> tuple[AsyncMock, AsyncMock]:
    mark = AsyncMock()
    settle = AsyncMock()
    monkeypatch.setattr(execution, "_mark_root_run_authority_running", mark)
    monkeypatch.setattr(execution, "_settle_root_run_authority", settle)
    return mark, settle


class _FakeAgent:
    def __init__(self) -> None:
        self.config = SimpleNamespace(project_id="proj-1", tenant_id="tenant-1")
        self.execute_chat_kwargs: dict | None = None

    async def execute_chat(self, **kwargs):
        self.execute_chat_kwargs = kwargs
        yield {"type": "complete", "data": {"content": "done"}}


class _FailingAgent(_FakeAgent):
    async def execute_chat(self, **kwargs):
        self.execute_chat_kwargs = kwargs
        if False:  # pragma: no cover - keeps this as an async generator for the caller
            yield {"type": "complete", "data": {"content": ""}}
        raise RuntimeError("boom")


class _CancelledAgent(_FakeAgent):
    async def execute_chat(self, **kwargs):
        self.execute_chat_kwargs = kwargs
        if False:  # pragma: no cover - keeps this as an async generator for the caller
            yield {"type": "complete", "data": {"content": ""}}
        raise asyncio.CancelledError


class _TerminalWorkspaceStatusAgent(_FakeAgent):
    async def execute_chat(self, **kwargs):
        self.execute_chat_kwargs = kwargs
        yield {
            "type": "status",
            "data": {"status": "goal_achieved:workspace_contract_submitted"},
        }


class _ModelMessageCommitAgent(_FakeAgent):
    async def execute_chat(self, **kwargs):
        self.execute_chat_kwargs = kwargs
        yield {
            "type": MODEL_MESSAGE_COMMITTED_EVENT_V2,
            "data": {"model_message": {"role": "assistant", "content": "done"}},
        }
        yield {"type": "complete", "data": {"content": "done"}}


def _jwt_like_token() -> str:
    return (
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
        "eyJ1c2VySWQiOiJ1c2VyLTEiLCJlbWFpbCI6InVzZXJAZXhhbXBsZS5jb20ifQ."
        "abc123abc123abc123abc123abc123abc123"
    )


def _make_finalization_redis_client() -> MagicMock:
    redis_client = MagicMock()
    redis_client.set = AsyncMock(return_value=True)
    redis_client.get = AsyncMock(return_value=None)
    redis_client.delete = AsyncMock(return_value=1)
    return redis_client


@pytest.mark.unit
@pytest.mark.asyncio
async def test_publish_event_to_stream_redacts_sensitive_tool_output() -> None:
    """Live Redis stream payloads should not expose credentials either."""
    jwt = _jwt_like_token()
    redis_client = MagicMock()
    redis_client.xadd = AsyncMock()

    await execution._publish_event_to_stream(
        conversation_id="conv-1",
        message_id="msg-1",
        event={"type": "observe", "data": {"observation": f'{{"token":"{jwt}"}}'}},
        event_time_us=11,
        event_counter=3,
        redis_client=redis_client,
    )

    _stream_key, message = redis_client.xadd.await_args.args[:2]
    payload = json.loads(message["data"])
    serialized = json.dumps(payload)
    assert jwt not in serialized
    assert payload["data"]["observation"] == '{"token":"[REDACTED_JWT]"}'


@pytest.mark.unit
@pytest.mark.asyncio
async def test_title_generated_uses_standard_actor_stream_envelope() -> None:
    redis_client = MagicMock()
    redis_client.xadd = AsyncMock()
    descriptor = {
        "generation": 901,
        "version": 901,
        "digest": "a" * 64,
    }

    await execution._publish_event_to_stream(
        conversation_id="conversation-a",
        event={
            "type": "title_generated",
            "data": {
                "conversation_id": "conversation-a",
                "title": "Lifecycle title",
                "plugin_generation": descriptor,
                "operation_id": "ray-turn:message-a:conversation-title:child",
                "parent_operation_id": "ray-turn:message-a",
            },
        },
        message_id="message-a",
        event_time_us=100,
        event_counter=3,
        redis_client=redis_client,
    )

    _stream_key, message = redis_client.xadd.await_args.args[:2]
    payload = json.loads(message["data"])
    assert payload["type"] == "title_generated"
    assert payload["event_time_us"] == 100
    assert payload["event_counter"] == 3
    assert payload["message_id"] == "message-a"
    assert payload["data"]["message_id"] == "message-a"
    assert payload["data"]["plugin_generation"] == descriptor
    assert payload["data"]["parent_operation_id"] == "ray-turn:message-a"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_resolve_chat_runtime_overrides_ignores_workspace_worker_overrides() -> None:
    """Workspace workers must use the selected agent definition as runtime authority."""
    request = ProjectChatRequest(
        conversation_id="workspace-worker-conv",
        message_id="msg-1",
        user_message="hello",
        user_id="user-1",
        app_model_context={
            "context_type": "workspace_worker_runtime",
            "llm_model_override": "openai/gpt-override",
            "llm_overrides": {"temperature": 1.8, "max_tokens": 128},
        },
    )

    with patch.object(
        execution,
        "_load_persisted_agent_config",
        new=AsyncMock(
            return_value={
                "llm_model_override": "openai/persisted",
                "llm_overrides": {"temperature": 1.5},
            }
        ),
    ) as load_persisted:
        llm_overrides, model_override = await execution._resolve_chat_runtime_overrides(request)

    assert llm_overrides is None
    assert model_override is None
    load_persisted.assert_not_awaited()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_resolve_chat_runtime_overrides_ignores_workspace_binding_overrides() -> None:
    """Workspace leader turns with a binding also keep agent config authoritative."""
    request = ProjectChatRequest(
        conversation_id="workspace-leader-conv",
        message_id="msg-1",
        user_message="hello",
        user_id="user-1",
        app_model_context={
            "workspace_binding": {"workspace_id": "workspace-1"},
            "llm_model_override": "openai/gpt-override",
            "llm_overrides": {"temperature": 1.8, "max_tokens": 128},
        },
    )

    with patch.object(
        execution,
        "_load_persisted_agent_config",
        new=AsyncMock(return_value={"llm_model_override": "openai/persisted"}),
    ) as load_persisted:
        llm_overrides, model_override = await execution._resolve_chat_runtime_overrides(request)

    assert llm_overrides is None
    assert model_override is None
    load_persisted.assert_not_awaited()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_resolve_chat_runtime_overrides_keeps_non_workspace_overrides() -> None:
    """Normal chat sessions still support persisted and app-provided LLM overrides."""
    request = ProjectChatRequest(
        conversation_id="normal-conv",
        message_id="msg-1",
        user_message="hello",
        user_id="user-1",
        app_model_context={
            "llm_model_override": "openai/request-model",
            "llm_overrides": {"temperature": 0.4, "max_tokens": 512},
        },
    )

    with patch.object(
        execution,
        "_load_persisted_agent_config",
        new=AsyncMock(
            return_value={
                "llm_model_override": "openai/persisted",
                "llm_overrides": {"temperature": 1.5},
            }
        ),
    ):
        llm_overrides, model_override = await execution._resolve_chat_runtime_overrides(request)

    assert llm_overrides == {"temperature": 0.4, "max_tokens": 512}
    assert model_override == "openai/request-model"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_execute_project_chat_passes_abort_signal(
    root_run_authority_mocks: tuple[AsyncMock, AsyncMock],
) -> None:
    """execute_project_chat should forward abort_signal into agent.execute_chat."""
    agent = _FakeAgent()
    request = ProjectChatRequest(
        conversation_id="conv-1",
        message_id="msg-1",
        user_message="hello",
        user_id="user-1",
        conversation_context=[],
        preferred_language="zh-CN",
        plugin_generation={
            "profile_id": "default-v2",
            "generation": 7,
            "digest": "a" * 64,
        },
    )
    abort_signal = asyncio.Event()

    with (
        patch.object(execution, "set_agent_running", new=AsyncMock()),
        patch.object(execution, "clear_agent_running", new=AsyncMock()),
        patch.object(execution, "_get_last_db_event_time", new=AsyncMock(return_value=(0, 0))),
        patch.object(execution, "_get_redis_client", new=AsyncMock(return_value=object())),
        patch.object(execution, "_publish_event_to_stream", new=AsyncMock()),
        patch.object(execution, "_persist_events", new=AsyncMock()),
        patch.object(execution, "_load_persisted_agent_config", new=AsyncMock(return_value=None)),
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
    mark, settle = root_run_authority_mocks
    mark.assert_awaited_once_with(
        tenant_id="tenant-1",
        project_id="proj-1",
        conversation_id="conv-1",
        run_id="msg-1",
    )
    settle.assert_awaited_once_with(
        tenant_id="tenant-1",
        project_id="proj-1",
        conversation_id="conv-1",
        run_id="msg-1",
        outcome="success",
        error=None,
    )
    assert agent.execute_chat_kwargs["preferred_language"] == "zh-CN"
    assert agent.execute_chat_kwargs["plugin_generation"] == request.plugin_generation


@pytest.mark.unit
@pytest.mark.asyncio
async def test_execute_project_chat_uses_canonical_run_authority_identity(
    root_run_authority_mocks: tuple[AsyncMock, AsyncMock],
) -> None:
    """Plan executions keep client message identity separate from run authority identity."""
    agent = _FakeAgent()
    request = ProjectChatRequest(
        conversation_id="conv-plan-1",
        message_id="client-message-1",
        canonical_run_id="plan-run-1",
        user_message="execute approved plan",
        user_id="user-1",
        conversation_context=[],
    )

    with (
        patch.object(execution, "set_agent_running", new=AsyncMock()),
        patch.object(execution, "clear_agent_running", new=AsyncMock()),
        patch.object(execution, "_get_last_db_event_time", new=AsyncMock(return_value=(0, 0))),
        patch.object(execution, "_get_redis_client", new=AsyncMock(return_value=object())),
        patch.object(execution, "_publish_event_to_stream", new=AsyncMock()),
        patch.object(execution, "_persist_events", new=AsyncMock()),
        patch.object(execution, "_load_persisted_agent_config", new=AsyncMock(return_value=None)),
        patch.object(execution.agent_metrics, "increment"),
        patch.object(execution.agent_metrics, "observe"),
    ):
        result = await execution.execute_project_chat(agent=agent, request=request)

    assert result.message_id == "client-message-1"
    assert agent.execute_chat_kwargs is not None
    assert agent.execute_chat_kwargs["canonical_run_id"] == "plan-run-1"
    mark, settle = root_run_authority_mocks
    mark.assert_awaited_once_with(
        tenant_id="tenant-1",
        project_id="proj-1",
        conversation_id="conv-plan-1",
        run_id="plan-run-1",
    )
    settle.assert_awaited_once_with(
        tenant_id="tenant-1",
        project_id="proj-1",
        conversation_id="conv-plan-1",
        run_id="plan-run-1",
        outcome="success",
        error=None,
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_execute_project_chat_projects_trusted_automation_success() -> None:
    agent = _FakeAgent()
    request = ProjectChatRequest(
        conversation_id="conv-1",
        message_id="run-1",
        user_message="hello",
        user_id="user-1",
        conversation_context=[],
        automation_run_id="run-1",
    )
    project_running = AsyncMock()
    project_terminal = AsyncMock()

    with (
        patch.object(execution, "set_agent_running", new=AsyncMock()),
        patch.object(execution, "clear_agent_running", new=AsyncMock()),
        patch.object(execution, "_get_last_db_event_time", new=AsyncMock(return_value=(0, 0))),
        patch.object(execution, "_get_redis_client", new=AsyncMock(return_value=object())),
        patch.object(execution, "_publish_event_to_stream", new=AsyncMock()),
        patch.object(execution, "_persist_events", new=AsyncMock()),
        patch.object(execution, "_load_persisted_agent_config", new=AsyncMock(return_value=None)),
        patch.object(execution, "_project_automation_runtime_running", new=project_running),
        patch.object(execution, "_project_automation_runtime_terminal", new=project_terminal),
        patch.object(execution, "_run_session_lifecycle", new=AsyncMock()),
        patch.object(execution.agent_metrics, "increment"),
        patch.object(execution.agent_metrics, "observe"),
    ):
        result = await execution.execute_project_chat(agent=agent, request=request)

    assert result.is_error is False
    identity = project_running.await_args.args[0]
    assert identity.runtime_execution_id == "run-1"
    assert identity.tenant_id == "tenant-1"
    assert identity.project_id == "proj-1"
    project_terminal.assert_awaited_once()
    assert project_terminal.await_args.args[0] == identity
    assert project_terminal.await_args.kwargs["outcome"] == "success"
    assert project_terminal.await_args.kwargs["event_count"] == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_execute_project_chat_projects_failure_without_parsing_error_text() -> None:
    agent = _FailingAgent()
    request = ProjectChatRequest(
        conversation_id="conv-1",
        message_id="run-1",
        user_message="hello",
        user_id="user-1",
        conversation_context=[],
        automation_run_id="run-1",
    )
    project_terminal = AsyncMock()

    with (
        patch.object(execution, "set_agent_running", new=AsyncMock()),
        patch.object(execution, "clear_agent_running", new=AsyncMock()),
        patch.object(execution, "_get_last_db_event_time", new=AsyncMock(return_value=(0, 0))),
        patch.object(execution, "_get_redis_client", new=AsyncMock(return_value=object())),
        patch.object(execution, "_publish_error_event", new=AsyncMock()),
        patch.object(execution, "_persist_events", new=AsyncMock()),
        patch.object(execution, "_load_persisted_agent_config", new=AsyncMock(return_value=None)),
        patch.object(execution, "_project_automation_runtime_running", new=AsyncMock()),
        patch.object(execution, "_project_automation_runtime_terminal", new=project_terminal),
        patch.object(execution.agent_metrics, "increment"),
        patch.object(execution.agent_metrics, "observe"),
    ):
        result = await execution.execute_project_chat(agent=agent, request=request)

    assert result.is_error is True
    assert project_terminal.await_args.kwargs["outcome"] == "failed"
    assert "boom" not in project_terminal.await_args.kwargs


@pytest.mark.unit
@pytest.mark.asyncio
async def test_execute_project_chat_persists_cancelled_then_reraises() -> None:
    agent = _CancelledAgent()
    request = ProjectChatRequest(
        conversation_id="conv-1",
        message_id="run-1",
        user_message="hello",
        user_id="user-1",
        conversation_context=[],
        automation_run_id="run-1",
    )
    project_terminal = AsyncMock()

    with (
        patch.object(execution, "set_agent_running", new=AsyncMock()),
        patch.object(execution, "clear_agent_running", new=AsyncMock()),
        patch.object(execution, "_get_last_db_event_time", new=AsyncMock(return_value=(0, 0))),
        patch.object(execution, "_get_redis_client", new=AsyncMock(return_value=object())),
        patch.object(execution, "_load_persisted_agent_config", new=AsyncMock(return_value=None)),
        patch.object(execution, "_project_automation_runtime_running", new=AsyncMock()),
        patch.object(execution, "_project_automation_runtime_terminal", new=project_terminal),
        pytest.raises(asyncio.CancelledError),
    ):
        await execution.execute_project_chat(agent=agent, request=request)

    assert project_terminal.await_args.kwargs["outcome"] == "cancelled"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_execute_project_chat_flushes_terminal_workspace_status_immediately() -> None:
    """Terminal workspace contract status should be durable before final cleanup."""
    agent = _TerminalWorkspaceStatusAgent()
    request = ProjectChatRequest(
        conversation_id="workspace-contract:supervisor-decision:conv-1",
        message_id="msg-1",
        user_message="hello",
        user_id="user-1",
        conversation_context=[],
        preferred_language="zh-CN",
    )
    persist_events = AsyncMock()

    with (
        patch.object(execution, "set_agent_running", new=AsyncMock()),
        patch.object(execution, "clear_agent_running", new=AsyncMock()),
        patch.object(execution, "_get_last_db_event_time", new=AsyncMock(return_value=(0, 0))),
        patch.object(execution, "_get_redis_client", new=AsyncMock(return_value=object())),
        patch.object(execution, "_publish_event_to_stream", new=AsyncMock()),
        patch.object(execution, "_persist_events", new=persist_events),
        patch.object(execution, "_load_persisted_agent_config", new=AsyncMock(return_value=None)),
        patch.object(execution.agent_metrics, "increment"),
        patch.object(execution.agent_metrics, "observe"),
    ):
        result = await execution.execute_project_chat(
            agent=agent,
            request=request,
            abort_signal=asyncio.Event(),
        )

    assert result.is_error is False
    assert persist_events.await_count == 1
    persisted_events = persist_events.await_args.kwargs["events"]
    assert [event["type"] for event in persisted_events] == ["status"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_execute_project_chat_flushes_model_message_commit_immediately() -> None:
    agent = _ModelMessageCommitAgent()
    request = ProjectChatRequest(
        conversation_id="conv-1",
        message_id="msg-1",
        user_message="hello",
        user_id="user-1",
        conversation_context=[],
    )
    persist_events = AsyncMock()

    with (
        patch.object(execution, "set_agent_running", new=AsyncMock()),
        patch.object(execution, "clear_agent_running", new=AsyncMock()),
        patch.object(execution, "_get_last_db_event_time", new=AsyncMock(return_value=(0, 0))),
        patch.object(execution, "_get_redis_client", new=AsyncMock(return_value=object())),
        patch.object(execution, "_publish_event_to_stream", new=AsyncMock()),
        patch.object(execution, "_persist_events", new=persist_events),
        patch.object(execution, "_load_persisted_agent_config", new=AsyncMock(return_value=None)),
        patch.object(execution.agent_metrics, "increment"),
        patch.object(execution.agent_metrics, "observe"),
    ):
        result = await execution.execute_project_chat(agent=agent, request=request)

    assert result.is_error is False
    assert persist_events.await_count == 2
    assert [
        [event["type"] for event in awaited.kwargs["events"]]
        for awaited in persist_events.await_args_list
    ] == [[MODEL_MESSAGE_COMMITTED_EVENT_V2], ["complete"]]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_continue_project_chat_flushes_model_message_commit_immediately() -> None:
    agent = _ModelMessageCommitAgent()
    state = HITLAgentState(
        conversation_id="conv-1",
        message_id="msg-1",
        tenant_id="tenant-1",
        project_id="proj-1",
        hitl_request_id="request-1",
        hitl_type="clarification",
        hitl_request_data={"question": "Proceed?"},
        messages=[],
        user_message="hello",
        user_id="user-1",
    )
    persist_events = AsyncMock()

    with (
        patch.object(execution, "_get_redis_client", new=AsyncMock(return_value=object())),
        patch.object(execution, "_load_hitl_state", new=AsyncMock(return_value=state)),
        patch.object(execution, "_validate_hitl_resume_request", return_value=None),
        patch.object(execution, "_get_last_db_event_time", new=AsyncMock(return_value=(0, 0))),
        patch.object(execution, "set_agent_running", new=AsyncMock()),
        patch.object(execution, "clear_agent_running", new=AsyncMock()),
        patch.object(execution, "_publish_event_to_stream", new=AsyncMock()),
        patch.object(execution, "_persist_events", new=persist_events),
        patch.object(execution, "_project_automation_runtime_running", new=AsyncMock()),
        patch.object(execution, "_project_automation_stream_terminal", new=AsyncMock()),
        patch(
            "src.infrastructure.agent.hitl.coordinator.mark_hitl_request_completed",
            new=AsyncMock(return_value=False),
        ),
        patch.object(execution.agent_metrics, "increment"),
        patch.object(execution.agent_metrics, "observe"),
    ):
        result = await execution.continue_project_chat(
            agent=agent,
            request_id="request-1",
            response_data={"response": "yes"},
        )

    assert result.is_error is False
    assert persist_events.await_count == 2
    assert [
        [event["type"] for event in awaited.kwargs["events"]]
        for awaited in persist_events.await_args_list
    ] == [[MODEL_MESSAGE_COMMITTED_EVENT_V2], ["complete"]]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_execute_project_chat_updates_spawn_status_for_child_session() -> None:
    agent = _FakeAgent()
    redis_client = _make_finalization_redis_client()
    request = ProjectChatRequest(
        conversation_id="child-conv",
        message_id="msg-1",
        user_message="hello",
        user_id="user-1",
        conversation_context=[],
        agent_id="child-agent",
        parent_session_id="parent-conv",
    )

    with (
        patch.object(execution, "set_agent_running", new=AsyncMock()),
        patch.object(execution, "clear_agent_running", new=AsyncMock()),
        patch.object(execution, "_get_last_db_event_time", new=AsyncMock(return_value=(0, 0))),
        patch.object(execution, "_get_redis_client", new=AsyncMock(return_value=redis_client)),
        patch.object(execution, "_publish_event_to_stream", new=AsyncMock()),
        patch.object(execution, "_publish_announce_via_service", new=AsyncMock()),
        patch.object(execution, "_record_child_result_history", new=AsyncMock()) as history_writer,
        patch.object(execution, "_persist_events", new=AsyncMock()),
        patch.object(execution, "_load_persisted_agent_config", new=AsyncMock(return_value=None)),
        patch.object(
            execution,
            "_resolve_child_terminal_status",
            new=AsyncMock(return_value="completed"),
        ),
        patch.object(execution, "_update_spawn_status", new=AsyncMock()) as update_spawn_status,
        patch.object(execution.agent_metrics, "increment"),
        patch.object(execution.agent_metrics, "observe"),
    ):
        result = await execution.execute_project_chat(
            agent=agent,
            request=request,
            abort_signal=asyncio.Event(),
        )

    assert result.is_error is False
    assert update_spawn_status.await_args_list == [
        call(
            child_session_id="child-conv",
            status="running",
            parent_session_id="parent-conv",
        ),
        call(
            child_session_id="child-conv",
            status="completed",
            parent_session_id="parent-conv",
        ),
    ]
    history_writer.assert_awaited_once_with(
        agent_id="child-agent",
        child_session_id="child-conv",
        request_message_id="msg-1",
        parent_session_id="parent-conv",
        result_content="done",
        success=True,
        event_count=1,
        execution_time_ms=result.execution_time_ms,
        error_message=None,
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_execute_project_chat_marks_failed_spawn_when_child_errors() -> None:
    agent = _FailingAgent()
    redis_client = _make_finalization_redis_client()
    request = ProjectChatRequest(
        conversation_id="child-conv",
        message_id="msg-1",
        user_message="hello",
        user_id="user-1",
        conversation_context=[],
        agent_id="child-agent",
        parent_session_id="parent-conv",
    )

    with (
        patch.object(execution, "set_agent_running", new=AsyncMock()),
        patch.object(execution, "clear_agent_running", new=AsyncMock()),
        patch.object(execution, "_get_last_db_event_time", new=AsyncMock(return_value=(0, 0))),
        patch.object(execution, "_get_redis_client", new=AsyncMock(return_value=redis_client)),
        patch.object(execution, "_publish_error_event", new=AsyncMock()),
        patch.object(execution, "_publish_announce_via_service", new=AsyncMock()),
        patch.object(execution, "_record_child_result_history", new=AsyncMock()) as history_writer,
        patch.object(execution, "_persist_events", new=AsyncMock()),
        patch.object(execution, "_load_persisted_agent_config", new=AsyncMock(return_value=None)),
        patch.object(
            execution,
            "_resolve_child_terminal_status",
            new=AsyncMock(return_value="failed"),
        ),
        patch.object(execution, "_update_spawn_status", new=AsyncMock()) as update_spawn_status,
        patch.object(execution.agent_metrics, "increment"),
        patch.object(execution.agent_metrics, "observe"),
    ):
        result = await execution.execute_project_chat(
            agent=agent,
            request=request,
            abort_signal=asyncio.Event(),
        )

    assert result.is_error is True
    assert update_spawn_status.await_args_list == [
        call(
            child_session_id="child-conv",
            status="running",
            parent_session_id="parent-conv",
        ),
        call(
            child_session_id="child-conv",
            status="failed",
            parent_session_id="parent-conv",
        ),
    ]
    history_writer.assert_awaited_once_with(
        agent_id="child-agent",
        child_session_id="child-conv",
        request_message_id="msg-1",
        parent_session_id="parent-conv",
        result_content="",
        success=False,
        event_count=0,
        execution_time_ms=result.execution_time_ms,
        error_message="boom",
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_record_child_result_history_writes_response_message() -> None:
    redis_client = object()
    message_bus = MagicMock()
    message_bus.get_message_history = AsyncMock(return_value=[])
    message_bus.send_message = AsyncMock(return_value="hist-msg-1")
    session = MagicMock()
    session.commit = AsyncMock()
    existing_result = MagicMock()
    existing_result.scalar_one_or_none.return_value = None
    session.execute = AsyncMock(return_value=existing_result)
    session_ctx = AsyncMock()
    session_ctx.__aenter__.return_value = session
    session_ctx.__aexit__.return_value = None
    conversation = MagicMock()
    conversation_repo = MagicMock()
    conversation_repo.find_by_id = AsyncMock(return_value=conversation)
    conversation_repo.save = AsyncMock()
    message_repo = MagicMock()
    message_repo.save = AsyncMock()

    with (
        patch.object(execution, "_get_redis_client", new=AsyncMock(return_value=redis_client)),
        patch.object(
            execution, "RedisAgentMessageBusAdapter", return_value=message_bus
        ) as message_bus_cls,
        patch.object(execution, "async_session_factory", return_value=session_ctx),
        patch(
            "src.infrastructure.adapters.secondary.persistence.sql_conversation_repository.SqlConversationRepository",
            return_value=conversation_repo,
        ),
        patch(
            "src.infrastructure.adapters.secondary.persistence.sql_message_repository.SqlMessageRepository",
            return_value=message_repo,
        ),
    ):
        await execution._record_child_result_history(
            agent_id="child-agent",
            child_session_id="child-conv",
            request_message_id="msg-1",
            parent_session_id="parent-conv",
            result_content="final answer",
            success=True,
            event_count=3,
            execution_time_ms=42.75,
            error_message=None,
        )

    message_bus_cls.assert_called_once_with(redis_client)
    terminal_message_id = execution._child_terminal_message_id(
        child_session_id="child-conv",
        request_message_id="msg-1",
    )
    message_bus.send_message.assert_awaited_once_with(
        from_agent_id="child-agent",
        to_agent_id="",
        session_id="child-conv",
        content="final answer",
        message_type=AgentMessageType.RESPONSE,
        metadata={
            "source": "child_result_history",
            "parent_session_id": "parent-conv",
            "success": True,
            "event_count": 3,
            "execution_time_ms": 42.75,
            "error_message": None,
            "source_message_id": "msg-1",
            "terminal_message_id": terminal_message_id,
        },
    )
    saved_message = message_repo.save.await_args.args[0]
    assert saved_message.id == terminal_message_id
    assert saved_message.conversation_id == "child-conv"
    assert saved_message.role.value == "assistant"
    assert saved_message.content == "final answer"
    assert saved_message.message_type.value == "text"
    assert saved_message.metadata == {
        "source": "child_result_history",
        "parent_session_id": "parent-conv",
        "success": True,
        "event_count": 3,
        "execution_time_ms": 42.75,
        "error_message": None,
        "source_message_id": "msg-1",
        "terminal_message_id": terminal_message_id,
    }
    conversation.increment_message_count.assert_not_called()
    conversation_repo.save.assert_not_awaited()
    session.commit.assert_awaited_once_with()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_record_child_result_history_skips_duplicate_terminal_entry() -> None:
    terminal_message_id = execution._child_terminal_message_id(
        child_session_id="child-conv",
        request_message_id="msg-1",
    )
    redis_client = object()
    message_bus = MagicMock()
    message_bus.get_message_history = AsyncMock(
        return_value=[
            SimpleNamespace(
                content="final answer",
                metadata={
                    "terminal_message_id": terminal_message_id,
                    "success": True,
                    "error_message": None,
                },
            )
        ]
    )
    message_bus.send_message = AsyncMock()
    session = MagicMock()
    session.commit = AsyncMock()
    existing_result = MagicMock()
    existing_result.scalar_one_or_none.return_value = terminal_message_id
    session.execute = AsyncMock(return_value=existing_result)
    session_ctx = AsyncMock()
    session_ctx.__aenter__.return_value = session
    session_ctx.__aexit__.return_value = None
    conversation = MagicMock()
    conversation_repo = MagicMock()
    conversation_repo.find_by_id = AsyncMock(return_value=conversation)
    conversation_repo.save = AsyncMock()
    message_repo = MagicMock()
    message_repo.save = AsyncMock()

    with (
        patch.object(execution, "_get_redis_client", new=AsyncMock(return_value=redis_client)),
        patch.object(execution, "RedisAgentMessageBusAdapter", return_value=message_bus),
        patch.object(execution, "async_session_factory", return_value=session_ctx),
        patch(
            "src.infrastructure.adapters.secondary.persistence.sql_conversation_repository.SqlConversationRepository",
            return_value=conversation_repo,
        ),
        patch(
            "src.infrastructure.adapters.secondary.persistence.sql_message_repository.SqlMessageRepository",
            return_value=message_repo,
        ),
    ):
        await execution._record_child_result_history(
            agent_id="child-agent",
            child_session_id="child-conv",
            request_message_id="msg-1",
            parent_session_id="parent-conv",
            result_content="final answer",
            success=True,
            event_count=3,
            execution_time_ms=42.75,
            error_message=None,
        )

    message_bus.send_message.assert_not_awaited()
    conversation.increment_message_count.assert_not_called()
    conversation_repo.save.assert_not_awaited()
    session.commit.assert_awaited_once_with()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_record_child_result_history_rewrites_changed_terminal_entry() -> None:
    terminal_message_id = execution._child_terminal_message_id(
        child_session_id="child-conv",
        request_message_id="msg-1",
    )
    redis_client = object()
    message_bus = MagicMock()
    message_bus.get_message_history = AsyncMock(
        return_value=[
            SimpleNamespace(
                content="stale answer",
                metadata={
                    "terminal_message_id": terminal_message_id,
                    "success": False,
                    "error_message": "boom",
                },
            )
        ]
    )
    message_bus.send_message = AsyncMock(return_value="hist-msg-2")
    session = MagicMock()
    session.commit = AsyncMock()
    existing_result = MagicMock()
    existing_result.scalar_one_or_none.return_value = None
    session.execute = AsyncMock(return_value=existing_result)
    session_ctx = AsyncMock()
    session_ctx.__aenter__.return_value = session
    session_ctx.__aexit__.return_value = None
    conversation_repo = MagicMock()
    conversation_repo.find_by_id = AsyncMock(return_value=MagicMock())
    message_repo = MagicMock()
    message_repo.save = AsyncMock()

    with (
        patch.object(execution, "_get_redis_client", new=AsyncMock(return_value=redis_client)),
        patch.object(execution, "RedisAgentMessageBusAdapter", return_value=message_bus),
        patch.object(execution, "async_session_factory", return_value=session_ctx),
        patch(
            "src.infrastructure.adapters.secondary.persistence.sql_conversation_repository.SqlConversationRepository",
            return_value=conversation_repo,
        ),
        patch(
            "src.infrastructure.adapters.secondary.persistence.sql_message_repository.SqlMessageRepository",
            return_value=message_repo,
        ),
    ):
        await execution._record_child_result_history(
            agent_id="child-agent",
            child_session_id="child-conv",
            request_message_id="msg-1",
            parent_session_id="parent-conv",
            result_content="final answer",
            success=True,
            event_count=3,
            execution_time_ms=42.75,
            error_message=None,
        )

    message_bus.send_message.assert_awaited_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_finalize_child_session_announce_uses_error_fallback() -> None:
    redis_client = _make_finalization_redis_client()

    with (
        patch.object(execution, "_get_redis_client", new=AsyncMock(return_value=redis_client)),
        patch.object(
            execution,
            "_resolve_child_terminal_status",
            new=AsyncMock(return_value="failed"),
        ),
        patch.object(execution, "_update_spawn_status", new=AsyncMock()),
        patch.object(execution, "_record_child_result_history", new=AsyncMock()),
        patch.object(
            execution, "_publish_announce_via_service", new=AsyncMock()
        ) as announce_writer,
    ):
        await execution._finalize_child_session_result(
            agent_id="child-agent",
            child_session_id="child-conv",
            request_message_id="msg-1",
            parent_session_id="parent-conv",
            result_content="",
            success=False,
            event_count=0,
            execution_time_ms=12.3,
            error_message="boom",
        )
        await asyncio.sleep(0)

    announce_writer.assert_awaited_once_with(
        agent_id="child-agent",
        parent_session_id="parent-conv",
        child_session_id="child-conv",
        result_content="boom",
        success=False,
        event_count=0,
        execution_time_ms=12.3,
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_finalize_child_session_keeps_session_mode_running() -> None:
    redis_client = _make_finalization_redis_client()
    orchestrator = SimpleNamespace(
        get_spawn_record=AsyncMock(
            return_value=SimpleNamespace(mode=SpawnMode.SESSION, status="running")
        )
    )

    with (
        patch.object(execution, "_get_redis_client", new=AsyncMock(return_value=redis_client)),
        patch(
            "src.infrastructure.plugins.v2.agent_worker_runtime.current_agent_orchestrator_v2",
            return_value=orchestrator,
        ),
        patch.object(execution, "_update_spawn_status", new=AsyncMock()) as update_status,
        patch.object(execution, "_record_child_result_history", new=AsyncMock()) as history_writer,
        patch.object(
            execution, "_publish_announce_via_service", new=AsyncMock()
        ) as announce_writer,
    ):
        await execution._finalize_child_session_result(
            agent_id="child-agent",
            child_session_id="child-conv",
            request_message_id="msg-1",
            parent_session_id="parent-conv",
            result_content="done",
            success=True,
            event_count=1,
            execution_time_ms=12.3,
            error_message=None,
        )
        await asyncio.sleep(0)

    update_status.assert_awaited_once_with(
        child_session_id="child-conv",
        status="running",
        parent_session_id="parent-conv",
    )
    history_writer.assert_awaited_once()
    announce_writer.assert_awaited_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_spawn_status_helpers_propagate_generation_service_errors() -> None:
    error = RuntimeV2Error("missing_service", "operation orchestrator is unavailable")

    with (
        patch(
            "src.infrastructure.plugins.v2.agent_worker_runtime.current_agent_orchestrator_v2",
            side_effect=error,
        ),
        pytest.raises(RuntimeV2Error) as update_error,
    ):
        await execution._update_spawn_status(
            child_session_id="child-conv",
            status="running",
            parent_session_id="parent-conv",
        )

    assert update_error.value is error

    with (
        patch(
            "src.infrastructure.plugins.v2.agent_worker_runtime.current_agent_orchestrator_v2",
            side_effect=error,
        ),
        pytest.raises(RuntimeV2Error) as resolve_error,
    ):
        await execution._resolve_child_terminal_status(
            child_session_id="child-conv",
            success=True,
        )

    assert resolve_error.value is error


@pytest.mark.unit
@pytest.mark.asyncio
async def test_finalize_child_session_releases_lock_on_idempotent_replay() -> None:
    terminal_message_id = execution._child_terminal_message_id(
        child_session_id="child-conv",
        request_message_id="msg-1",
    )
    terminal_signature = execution._child_terminal_signature(
        content="done",
        success=True,
        error_message=None,
    )
    redis_client = MagicMock()
    redis_client.set = AsyncMock(return_value=True)
    redis_client.get = AsyncMock(side_effect=[terminal_signature, "lock-token"])
    redis_client.delete = AsyncMock(return_value=1)

    with (
        patch.object(execution, "_get_redis_client", new=AsyncMock(return_value=redis_client)),
        patch("src.infrastructure.agent.actor.execution.uuid.uuid4", return_value="lock-token"),
        patch.object(execution, "_update_spawn_status", new=AsyncMock()) as update_status,
        patch.object(execution, "_record_child_result_history", new=AsyncMock()) as history_writer,
        patch.object(
            execution, "_publish_announce_via_service", new=AsyncMock()
        ) as announce_writer,
    ):
        await execution._finalize_child_session_result(
            agent_id="child-agent",
            child_session_id="child-conv",
            request_message_id="msg-1",
            parent_session_id="parent-conv",
            result_content="done",
            success=True,
            event_count=1,
            execution_time_ms=12.3,
            error_message=None,
        )

    update_status.assert_not_awaited()
    history_writer.assert_not_awaited()
    announce_writer.assert_not_awaited()
    redis_client.delete.assert_awaited_once_with(
        f"agent:child:terminal:state:{terminal_message_id}:lock"
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_handle_hitl_pending_preserves_child_session_metadata() -> None:
    captured_state: dict[str, object] = {}
    fake_state_store = SimpleNamespace(
        save_state=AsyncMock(side_effect=lambda state: captured_state.setdefault("state", state))
    )
    agent = SimpleNamespace(
        config=SimpleNamespace(tenant_id="tenant-1", project_id="proj-1", agent_mode="default")
    )
    request = ProjectChatRequest(
        conversation_id="child-conv",
        message_id="msg-1",
        user_message="hello",
        user_id="user-1",
        conversation_context=[{"role": "user", "content": "hello"}],
        agent_id="child-agent",
        parent_session_id="parent-conv",
    )
    hitl_exception = HITLPendingException(
        request_id="req-1",
        hitl_type=HITLType.CLARIFICATION,
        request_data={"question": "Need input?"},
        conversation_id="child-conv",
        message_id="msg-1",
        timeout_seconds=120.0,
        current_messages=[{"role": "assistant", "content": "pending"}],
        tool_call_id="call-1",
    )

    with (
        patch.object(execution, "_get_redis_client", new=AsyncMock(return_value=object())),
        patch.object(execution, "HITLStateStore", return_value=fake_state_store),
        patch.object(execution, "save_hitl_snapshot", new=AsyncMock()),
    ):
        result = await execution.handle_hitl_pending(
            agent=agent,
            request=request,
            hitl_exception=hitl_exception,
        )

        assert result.hitl_pending is True
    assert captured_state["state"].agent_id == "child-agent"
    assert captured_state["state"].parent_session_id == "parent-conv"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_handle_hitl_pending_persists_canonical_run_authority() -> None:
    agent = SimpleNamespace(
        config=SimpleNamespace(
            tenant_id="tenant-1",
            project_id="project-1",
            agent_mode="default",
        )
    )
    request = ProjectChatRequest(
        conversation_id="conv-plan",
        message_id="client-message",
        canonical_run_id="plan-run",
        user_message="Continue after permission",
        user_id="user-1",
    )
    pending = HITLPendingException(
        request_id="permission-1",
        conversation_id="conv-plan",
        hitl_type=HITLType.PERMISSION,
        request_data={"action": "write"},
    )
    state_store = SimpleNamespace(save_state=AsyncMock(return_value="state-key"))

    with (
        patch.object(execution, "_get_redis_client", new=AsyncMock(return_value=object())),
        patch.object(execution, "HITLStateStore", return_value=state_store),
        patch.object(execution, "save_hitl_snapshot", new=AsyncMock()),
        patch.object(execution, "_project_automation_runtime_waiting_human", new=AsyncMock()),
    ):
        await execution.handle_hitl_pending(agent, request, pending)

    saved_state = state_store.save_state.await_args.args[0]
    assert saved_state.message_id == "client-message"
    assert saved_state.canonical_run_id == "plan-run"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_handle_hitl_pending_persists_complete_plugin_distribution() -> None:
    descriptor = {
        "profile_id": "default-v2",
        "generation": 9,
        "digest": "b" * 64,
    }
    distribution = {
        "descriptor": descriptor,
        "snapshot": {"profile_id": "default-v2", "generation": 9},
        "envelope": {"version": 15, "nonce": "publication-15"},
    }
    agent = SimpleNamespace(
        config=SimpleNamespace(
            tenant_id="tenant-1",
            project_id="project-1",
            agent_mode="default",
        )
    )
    request = ProjectChatRequest(
        conversation_id="conv-v2",
        message_id="message-v2",
        user_message="Continue after permission",
        user_id="user-v2",
        plugin_generation=descriptor,
        plugin_distribution=distribution,
    )
    pending = HITLPendingException(
        request_id="permission-v2",
        conversation_id="conv-v2",
        hitl_type=HITLType.PERMISSION,
        request_data={"action": "write"},
    )
    state_store = SimpleNamespace(save_state=AsyncMock(return_value="state-key"))
    save_snapshot = AsyncMock()

    with (
        patch.object(execution, "_get_redis_client", new=AsyncMock(return_value=object())),
        patch.object(execution, "HITLStateStore", return_value=state_store),
        patch.object(execution, "save_hitl_snapshot", new=save_snapshot),
        patch.object(execution, "_project_automation_runtime_waiting_human", new=AsyncMock()),
    ):
        await execution.handle_hitl_pending(agent, request, pending)

    saved_state = state_store.save_state.await_args.args[0]
    assert saved_state.plugin_generation == descriptor
    assert saved_state.plugin_distribution == distribution
    assert save_snapshot.await_args.args[0].plugin_distribution == distribution


class _DeltaStreamingAgent(_FakeAgent):
    async def execute_chat(self, **kwargs):
        self.execute_chat_kwargs = kwargs
        yield {"type": "text_delta", "data": {"delta": "Hel"}}
        yield {"type": "text_delta", "data": {"delta": "lo"}}
        yield {"type": "complete", "data": {"content": "Hello"}}


class _RecordingPipeline:
    def __init__(self) -> None:
        self.xadd_calls: list[tuple[tuple, dict]] = []
        self.execute_calls = 0

    def xadd(self, *args, **kwargs):
        self.xadd_calls.append((args, kwargs))
        return self

    async def execute(self):
        self.execute_calls += 1
        return []


class _RecordingRedis:
    def __init__(self) -> None:
        self.pipeline_instance = _RecordingPipeline()
        self.xadd = AsyncMock()

    def pipeline(self, transaction: bool = False):
        assert transaction is False
        return self.pipeline_instance


def _stream_payload(redis_message: dict) -> dict:
    return json.loads(redis_message["data"])


@pytest.mark.unit
@pytest.mark.asyncio
async def test_execute_project_chat_batches_delta_events_into_one_pipeline_flush() -> None:
    agent = _DeltaStreamingAgent()
    redis_client = _RecordingRedis()
    request = ProjectChatRequest(
        conversation_id="conv-1",
        message_id="msg-1",
        user_message="hello",
        user_id="user-1",
        conversation_context=[],
    )

    with (
        patch.object(execution, "set_agent_running", new=AsyncMock()),
        patch.object(execution, "clear_agent_running", new=AsyncMock()),
        patch.object(execution, "_get_last_db_event_time", new=AsyncMock(return_value=(0, 0))),
        patch.object(execution, "_get_redis_client", new=AsyncMock(return_value=redis_client)),
        patch.object(execution, "_persist_events", new=AsyncMock()),
        patch.object(execution, "_load_persisted_agent_config", new=AsyncMock(return_value=None)),
        patch.object(execution.agent_metrics, "increment"),
        patch.object(execution.agent_metrics, "observe"),
    ):
        result = await execution.execute_project_chat(agent=agent, request=request)

    assert result.is_error is False

    pipeline = redis_client.pipeline_instance
    # Both deltas were flushed together when the structural event arrived.
    assert pipeline.execute_calls == 1
    assert len(pipeline.xadd_calls) == 2
    payloads = [_stream_payload(call_args[1]) for call_args, _kwargs in pipeline.xadd_calls]
    assert [p["type"] for p in payloads] == ["text_delta", "text_delta"]
    delta_times = [p["event_time_us"] for p in payloads]
    assert all(t > 0 for t in delta_times)
    assert delta_times[0] <= delta_times[1]
    assert [p["data"]["delta"] for p in payloads] == ["Hel", "lo"]
    assert all(call_args[0] == "agent:events:conv-1" for call_args, _ in pipeline.xadd_calls)

    # The structural event bypassed the pipeline and published directly.
    redis_client.xadd.assert_awaited_once()
    direct = redis_client.xadd.await_args
    assert direct.args[0] == "agent:events:conv-1"
    assert _stream_payload(direct.args[1])["type"] == "complete"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_execute_project_chat_flushes_deltas_on_interval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(execution, "_STREAM_DELTA_FLUSH_INTERVAL_S", 0.0)
    agent = _DeltaStreamingAgent()
    redis_client = _RecordingRedis()
    request = ProjectChatRequest(
        conversation_id="conv-1",
        message_id="msg-1",
        user_message="hello",
        user_id="user-1",
        conversation_context=[],
    )

    with (
        patch.object(execution, "set_agent_running", new=AsyncMock()),
        patch.object(execution, "clear_agent_running", new=AsyncMock()),
        patch.object(execution, "_get_last_db_event_time", new=AsyncMock(return_value=(0, 0))),
        patch.object(execution, "_get_redis_client", new=AsyncMock(return_value=redis_client)),
        patch.object(execution, "_persist_events", new=AsyncMock()),
        patch.object(execution, "_load_persisted_agent_config", new=AsyncMock(return_value=None)),
        patch.object(execution.agent_metrics, "increment"),
        patch.object(execution.agent_metrics, "observe"),
    ):
        result = await execution.execute_project_chat(agent=agent, request=request)

    assert result.is_error is False
    pipeline = redis_client.pipeline_instance
    # Interval trigger flushed each delta separately; the complete event did
    # not trigger another flush because the buffer was already empty.
    assert pipeline.execute_calls == 2
    assert len(pipeline.xadd_calls) == 2
