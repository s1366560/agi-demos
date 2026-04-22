"""Unit tests for actor execution helpers."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from src.domain.model.agent.hitl.hitl_types import HITLPendingException, HITLType
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


def _make_finalization_redis_client() -> MagicMock:
    redis_client = MagicMock()
    redis_client.set = AsyncMock(return_value=True)
    redis_client.get = AsyncMock(return_value=None)
    redis_client.delete = AsyncMock(return_value=1)
    return redis_client


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
