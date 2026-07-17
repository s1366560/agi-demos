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


def test_prepare_event_for_persistence_redacts_sensitive_tool_output() -> None:
    """Actor persistence path must match repository-level event redaction."""
    jwt = _jwt_like_token()

    persistable, _has_text_end, _has_complete = execution._prepare_event_for_persistence(
        {
            "type": "observe",
            "event_time_us": 10,
            "event_counter": 2,
            "data": {
                "observation": f'{{"passed":"{jwt}"}}',
                "nested": [{"authorization": f"Bearer {jwt}"}],
            },
        },
        has_text_end_messages=False,
        has_complete_assistant_message=False,
    )

    assert persistable is not None
    serialized = json.dumps(persistable.event_data)
    assert jwt not in serialized
    assert "[REDACTED_JWT]" in persistable.event_data["observation"]
    assert persistable.event_data["nested"][0]["authorization"] == "Bearer [REDACTED_JWT]"


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
async def test_execute_project_chat_passes_abort_signal() -> None:
    """execute_project_chat should forward abort_signal into agent.execute_chat."""
    agent = _FakeAgent()
    request = ProjectChatRequest(
        conversation_id="conv-1",
        message_id="msg-1",
        user_message="hello",
        user_id="user-1",
        conversation_context=[],
        preferred_language="zh-CN",
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
    assert agent.execute_chat_kwargs["preferred_language"] == "zh-CN"


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
            "src.infrastructure.agent.state.agent_worker_state.get_agent_orchestrator",
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
async def test_persist_events_skips_complete_when_text_end_assistant_exists() -> None:
    """A persisted text_end assistant message should keep complete metadata as a complete event."""
    session = MagicMock()
    existing_result = MagicMock()
    existing_result.scalars.return_value.all.return_value = [{"source": "text_end"}]
    insert_result = MagicMock()
    insert_result.one_or_none.return_value = ("complete", 123)
    session.execute = AsyncMock(side_effect=[existing_result, insert_result, MagicMock()])

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

    assert session.execute.await_count == 3


@pytest.mark.unit
@pytest.mark.asyncio
async def test_persist_events_converts_complete_to_assistant_message() -> None:
    """_persist_events should persist complete content when no assistant exists."""
    session = MagicMock()
    existing_result = MagicMock()
    existing_result.scalars.return_value.all.return_value = []
    insert_result = MagicMock()
    insert_result.one_or_none.return_value = ("assistant_message", 123)
    session.execute = AsyncMock(side_effect=[existing_result, insert_result, MagicMock()])

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

    # Existing assistant check + insert + atomic projection update.
    assert session.execute.await_count == 3


@pytest.mark.unit
def test_prepare_complete_assistant_message_carries_execution_summary() -> None:
    """Complete synthesis should preserve trace and execution summary metadata."""
    persistable_event, has_text_end_messages, has_complete = (
        execution._prepare_event_for_persistence(
            {
                "type": "complete",
                "data": {
                    "content": "final answer",
                    "trace_url": "https://trace.example/123",
                    "execution_summary": {"step_count": 2, "artifact_count": 1},
                },
                "event_time_us": 100,
                "event_counter": 1,
            },
            has_text_end_messages=False,
            has_complete_assistant_message=False,
        )
    )

    assert persistable_event is not None
    assert persistable_event.event_type == "assistant_message"
    assert persistable_event.event_data["trace_url"] == "https://trace.example/123"
    assert persistable_event.event_data["execution_summary"] == {
        "step_count": 2,
        "artifact_count": 1,
    }
    assert has_text_end_messages is False
    assert has_complete is True


@pytest.mark.unit
def test_prepare_complete_assistant_message_without_content_keeps_metadata() -> None:
    """Metadata-only complete events should still persist as assistant history."""
    persistable_event, has_text_end_messages, has_complete = (
        execution._prepare_event_for_persistence(
            {
                "type": "complete",
                "data": {
                    "content": "",
                    "trace_url": "https://trace.example/empty",
                    "execution_summary": {"step_count": 2},
                },
                "event_time_us": 100,
                "event_counter": 1,
            },
            has_text_end_messages=False,
            has_complete_assistant_message=False,
        )
    )

    assert persistable_event is not None
    assert persistable_event.event_type == "assistant_message"
    assert persistable_event.event_data["content"] == ""
    assert persistable_event.event_data["trace_url"] == "https://trace.example/empty"
    assert persistable_event.event_data["execution_summary"] == {"step_count": 2}
    assert has_text_end_messages is False
    assert has_complete is True


@pytest.mark.unit
def test_prepare_terminal_workspace_status_creates_assistant_message() -> None:
    """Terminal workspace status should be visible after Redis stream replay."""
    persistable_event, has_text_end_messages, has_complete = (
        execution._prepare_event_for_persistence(
            {
                "type": "status",
                "data": {"status": "goal_achieved:workspace_contract_submitted"},
                "event_time_us": 100,
                "event_counter": 1,
            },
            has_text_end_messages=False,
            has_complete_assistant_message=False,
        )
    )

    assert persistable_event is not None
    assert persistable_event.event_type == "assistant_message"
    assert persistable_event.event_data["content"] == "Workspace contract submitted."
    assert persistable_event.event_data["source"] == "terminal_workspace_status"
    assert persistable_event.event_data["status"] == "goal_achieved:workspace_contract_submitted"
    assert has_text_end_messages is False
    assert has_complete is True


@pytest.mark.unit
def test_prepare_complete_persists_complete_event_when_text_end_exists() -> None:
    """Complete events should persist separately when text_end already created history."""
    persistable_event, has_text_end_messages, has_complete = (
        execution._prepare_event_for_persistence(
            {
                "type": "complete",
                "data": {
                    "content": "final answer",
                    "execution_summary": {"step_count": 2},
                },
                "event_time_us": 100,
                "event_counter": 1,
            },
            has_text_end_messages=True,
            has_complete_assistant_message=False,
        )
    )

    assert persistable_event is not None
    assert persistable_event.event_type == "complete"
    assert persistable_event.event_data["execution_summary"] == {"step_count": 2}
    assert has_text_end_messages is True
    assert has_complete is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_persist_events_uses_top_level_payload_for_legacy_dict_event() -> None:
    """Legacy dict events should persist top-level payload into event_data."""
    session = MagicMock()
    existing_result = MagicMock()
    existing_result.scalars.return_value.all.return_value = []
    insert_result = MagicMock()
    insert_result.one_or_none.return_value = ("assistant_message", 123)
    session.execute = AsyncMock(side_effect=[existing_result, insert_result, MagicMock()])

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
            events=[
                {
                    "type": "assistant_message",
                    "content": "legacy reply",
                    "role": "assistant",
                    "source": "legacy",
                    "event_time_us": 123,
                    "event_counter": 0,
                }
            ],
        )

    insert_stmt = session.execute.await_args_list[1].args[0]
    params = insert_stmt.compile().params
    assert "assistant_message" in params.values()
    assert {
        "content": "legacy reply",
        "role": "assistant",
        "source": "legacy",
    } in params.values()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_persist_events_updates_conversation_projection_fields() -> None:
    """Persisting events should refresh conversation message_count and updated_at."""
    session = MagicMock()
    existing_result = MagicMock()
    existing_result.scalars.return_value.all.return_value = []
    insert_result = MagicMock()
    insert_result.one_or_none.return_value = ("assistant_message", 123)
    session.execute = AsyncMock(side_effect=[existing_result, insert_result, MagicMock()])

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

    executed_sql = [str(call.args[0]) for call in session.execute.await_args_list]
    assert any("UPDATE conversations" in sql for sql in executed_sql)
    assert any("message_count" in sql for sql in executed_sql)
    assert any("updated_at" in sql for sql in executed_sql)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_persist_events_keeps_prefixed_correlation_id() -> None:
    """Actor persistence should pass through prefixed correlation IDs unchanged."""
    session = MagicMock()
    existing_result = MagicMock()
    existing_result.scalars.return_value.all.return_value = []
    insert_result = MagicMock()
    insert_result.one_or_none.return_value = ("assistant_message", 123)
    session.execute = AsyncMock(side_effect=[existing_result, insert_result, MagicMock()])

    begin_ctx = AsyncMock()
    begin_ctx.__aenter__.return_value = None
    begin_ctx.__aexit__.return_value = None
    session.begin.return_value = begin_ctx

    session_ctx = AsyncMock()
    session_ctx.__aenter__.return_value = session
    session_ctx.__aexit__.return_value = None

    correlation_id = "cron:0e464e94-b2e8-4dbe-8a13-08b203ba6667"

    with patch.object(execution, "async_session_factory", return_value=session_ctx):
        await execution._persist_events(
            conversation_id="conv-1",
            message_id="msg-1",
            events=[{"type": "complete", "data": {"content": "final answer"}}],
            correlation_id=correlation_id,
        )

    insert_stmt = session.execute.await_args_list[1].args[0]
    assert insert_stmt.compile().params["correlation_id"] == correlation_id


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
