"""Unit tests for chat WebSocket language propagation."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

import src.infrastructure.adapters.primary.web.websocket.handlers.chat_handler as chat_handler_module
from src.infrastructure.adapters.primary.web.websocket.handlers.chat_handler import (
    StopSessionHandler,
    _append_external_acp_update_event,
    _build_external_acp_prompt_text,
    _ExternalACPExecutionState,
    _format_external_acp_prompt_with_history,
    _persist_external_acp_completion,
    _text_from_external_acp_content,
    stream_agent_to_websocket,
)
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error

pytestmark = pytest.mark.unit


@asynccontextmanager
async def _noop_agent_turn_operation(**_kwargs: object) -> AsyncIterator[None]:
    yield None


@pytest.fixture(autouse=True)
def _isolate_language_tests_from_generation_admission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        chat_handler_module,
        "pin_agent_turn_operation_v2",
        _noop_agent_turn_operation,
    )


def test_format_external_acp_prompt_with_history_includes_recent_turns() -> None:
    prompt = _format_external_acp_prompt_with_history(
        user_message="上一轮 marker 是什么？",
        history=[
            ("user", "请记住 marker ACP-STABILITY-742"),
            ("assistant", "MARKER STORED ACP-STABILITY-742"),
        ],
    )

    assert "Conversation context from previous MemStack turns" in prompt
    assert "User: 请记住 marker ACP-STABILITY-742" in prompt
    assert "Assistant: MARKER STORED ACP-STABILITY-742" in prompt
    assert prompt.endswith("Current user request:\n上一轮 marker 是什么？")


def test_format_external_acp_prompt_without_history_returns_user_message() -> None:
    assert _format_external_acp_prompt_with_history(user_message="hello", history=[]) == "hello"


async def test_external_acp_history_includes_typed_v2_admission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_event_types: set[str] | None = None

    class _TypedHistoryRepository:
        def __init__(self, _db: object) -> None:
            pass

        async def get_events(self, **kwargs: Any) -> list[Any]:
            nonlocal captured_event_types
            captured_event_types = kwargs["event_types"]
            return [
                SimpleNamespace(
                    event_type="turn_admitted",
                    event_data={"role": "user", "content": "remember V2-HISTORY-42"},
                ),
                SimpleNamespace(
                    event_type="assistant_message",
                    event_data={"role": "assistant", "content": "stored V2-HISTORY-42"},
                ),
            ]

    monkeypatch.setattr(
        "src.infrastructure.adapters.secondary.persistence."
        "sql_agent_execution_event_repository.SqlAgentExecutionEventRepository",
        _TypedHistoryRepository,
    )

    prompt = await _build_external_acp_prompt_text(
        SimpleNamespace(db=object()),  # type: ignore[arg-type]
        conversation_id="conversation-1",
        user_message="what was the marker?",
    )

    assert captured_event_types == {
        "assistant_message",
        "turn_admitted",
        "user_message",
    }
    assert "User: remember V2-HISTORY-42" in prompt
    assert "Assistant: stored V2-HISTORY-42" in prompt


def test_text_from_external_acp_content_extracts_nested_list_blocks() -> None:
    content = [
        {"content": {"type": "text", "text": "first "}},
        {"type": "text", "text": "second"},
    ]

    assert _text_from_external_acp_content(content) == "first second"


def test_external_acp_tool_update_uses_readable_result_without_raw_update() -> None:
    live_events: list[tuple[str, dict[str, Any]]] = []
    assistant_text_chunks: list[str] = []

    _append_external_acp_update_event(
        live_events=live_events,
        assistant_text_chunks=assistant_text_chunks,
        update={
            "sessionUpdate": "tool_call_update",
            "toolCallId": "tool-1",
            "title": "read",
            "status": "completed",
            "content": [{"content": {"type": "text", "text": "read output"}}],
        },
        agent_id="agent-1",
        user_msg_id="message-1",
    )

    assert live_events == [
        (
            "observe",
            {
                "tool_name": "read",
                "tool_execution_id": "tool-1",
                "observation": "read output",
                "result": "read output",
                "message_id": "message-1",
                "_meta": {
                    "acp": {
                        "sessionUpdate": "tool_call_update",
                        "toolCallId": "tool-1",
                        "status": "completed",
                        "title": "read",
                    }
                },
            },
        )
    ]


class FakeAgentService:
    def __init__(self) -> None:
        self.stream_kwargs: dict[str, Any] | None = None

    async def stream_chat_v2(self, **kwargs: Any) -> AsyncIterator[dict[str, Any]]:
        self.stream_kwargs = kwargs
        yield {
            "type": "complete",
            "data": {"content": "done"},
            "id": "event-1",
            "timestamp": "2026-05-07T00:00:00Z",
        }


class FakeConnectionManager:
    def __init__(self) -> None:
        self.broadcasts: list[tuple[str, dict[str, Any]]] = []

    def is_subscribed(self, session_id: str, conversation_id: str) -> bool:
        return session_id == "session-1" and conversation_id == "conv-1"

    async def broadcast_to_conversation(
        self,
        conversation_id: str,
        event: dict[str, Any],
    ) -> None:
        self.broadcasts.append((conversation_id, event))

    async def send_to_session(self, session_id: str, event: dict[str, Any]) -> None:
        self.broadcasts.append((session_id, event))


class FakeEventRepository:
    def __init__(self) -> None:
        self.saved_batches: list[list[Any]] = []

    async def save_batch(self, events: list[Any]) -> None:
        self.saved_batches.append(events)


class FakeDb:
    def __init__(self) -> None:
        self.committed = False

    async def commit(self) -> None:
        self.committed = True


class FakeTimeGenerator:
    def __init__(self) -> None:
        self.counter = 0

    def next(self) -> tuple[int, int]:
        self.counter += 1
        return 1_000_000 + self.counter, self.counter


class FakeMessageContext:
    session_id = "session-1"
    user_id = "user-1"
    tenant_id = "tenant-1"
    api_key = "ms_sk_" + ("a" * 64)
    db = object()

    def __init__(self) -> None:
        self.connection_manager = FakeConnectionManager()


async def test_external_acp_completion_does_not_emit_empty_execution_summary() -> None:
    event_repo = FakeEventRepository()
    db = FakeDb()
    context = SimpleNamespace(connection_manager=FakeConnectionManager(), db=db)
    state = _ExternalACPExecutionState(
        event_repo=event_repo,  # type: ignore[arg-type]
        time_gen=FakeTimeGenerator(),  # type: ignore[arg-type]
        user_msg_id="user-message-1",
        assistant_msg_id="assistant-message-1",
    )

    await _persist_external_acp_completion(
        context,  # type: ignore[arg-type]
        conversation_id="conversation-1",
        state=state,
        live_events=[],
        assistant_text="done",
        agent=SimpleNamespace(id="agent-1"),  # type: ignore[arg-type]
        acp_agent_key="opencode-local",
    )

    broadcast_events = [event for _, event in context.connection_manager.broadcasts]
    complete_broadcast = next(event for event in broadcast_events if event["type"] == "complete")
    assert "execution_summary" not in complete_broadcast["data"]

    saved_events = event_repo.saved_batches[0]
    complete_event = next(event for event in saved_events if event.event_type == "complete")
    assistant_event = next(
        event for event in saved_events if event.event_type == "assistant_message"
    )
    assert "execution_summary" not in complete_event.event_data
    assert assistant_event.event_data["metadata"] == {
        "source": "acp_external",
        "acp_agent_key": "opencode-local",
    }
    assert db.committed is True


class StopConnectionManager:
    def __init__(self, task: asyncio.Task[None]) -> None:
        self.bridge_tasks = {"session-1": {"conv-1": task}}


class StopContext:
    session_id = "session-1"
    tenant_id = "tenant-1"
    user_id = "user-1"
    db = object()

    def __init__(self, task: asyncio.Task[None]) -> None:
        self.connection_manager = StopConnectionManager(task)
        self.sent: list[dict[str, Any]] = []

    async def send_json(self, message: dict[str, Any]) -> None:
        self.sent.append(message)

    async def send_ack(self, action: str, **kwargs: Any) -> None:
        self.sent.append({"type": "ack", "action": action, **kwargs})

    async def send_error(
        self,
        message: str,
        code: str | None = None,
        conversation_id: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        self.sent.append(
            {
                "type": "error",
                "data": {"message": message, "code": code, **(extra or {})},
                "conversation_id": conversation_id,
            }
        )


class FakeConversationRepository:
    def __init__(self, _db: object) -> None:
        pass

    async def find_by_id(self, conversation_id: str) -> Any:
        assert conversation_id == "conv-1"
        return SimpleNamespace(
            id=conversation_id,
            tenant_id="tenant-1",
            project_id="project-1",
            user_id="user-1",
        )


class FakeCancelMethod:
    def __init__(self) -> None:
        self.conversation_ids: list[str] = []

    def remote(self, conversation_id: str) -> bool:
        self.conversation_ids.append(conversation_id)
        return False


async def test_stream_agent_to_websocket_passes_preferred_language(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent_service = FakeAgentService()
    context = FakeMessageContext()
    monkeypatch.setattr(
        chat_handler_module,
        "current_agent_turn_service_v2",
        AsyncMock(return_value=agent_service),
    )

    await stream_agent_to_websocket(
        context=context,  # type: ignore[arg-type]
        conversation_id="conv-1",
        user_message="你好",
        project_id="project-1",
        preferred_language="zh-CN",
    )

    assert agent_service.stream_kwargs is not None
    assert agent_service.stream_kwargs["preferred_language"] == "zh-CN"
    assert agent_service.stream_kwargs["api_auth_token"] == context.api_key
    assert context.connection_manager.broadcasts[0][0] == "conv-1"


async def test_stream_agent_to_websocket_strips_client_workspace_runtime_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent_service = FakeAgentService()
    context = FakeMessageContext()
    monkeypatch.setattr(
        chat_handler_module,
        "current_agent_turn_service_v2",
        AsyncMock(return_value=agent_service),
    )

    await stream_agent_to_websocket(
        context=context,  # type: ignore[arg-type]
        conversation_id="conv-1",
        user_message="hello",
        project_id="project-1",
        app_model_context={
            "llm_overrides": {"temperature": 0.2},
            "context_type": "workspace_worker_runtime",
            "workspace_session_role": "contract",
            "workspace_binding": {"workspace_id": "ws-1"},
            "runtime_limits": {"max_steps": 9999, "max_tokens": 999999},
        },
    )

    assert agent_service.stream_kwargs is not None
    assert agent_service.stream_kwargs["app_model_context"] == {
        "llm_overrides": {"temperature": 0.2}
    }


async def test_stop_session_cancels_local_worker_when_ray_actor_exists(monkeypatch: Any) -> None:
    async def bridge_task() -> None:
        await asyncio.Event().wait()

    task = asyncio.create_task(bridge_task())
    fake_cancel = FakeCancelMethod()
    local_cancelled: list[str] = []

    async def fake_get_actor_if_exists(**_kwargs: Any) -> Any:
        return SimpleNamespace(cancel=fake_cancel)

    async def fake_await_ray(value: Any) -> Any:
        return value

    async def fake_cancel_local_chat(conversation_id: str) -> bool:
        local_cancelled.append(conversation_id)
        return True

    import src.application.services.agent.runtime_bootstrapper as runtime_bootstrapper
    import src.infrastructure.adapters.secondary.ray.client as ray_client
    import src.infrastructure.agent.actor.actor_manager as actor_manager

    @asynccontextmanager
    async def fake_conversation_access_authority(
        _context: StopContext,
        *,
        conversation_id: str,
    ) -> AsyncIterator[Any]:
        yield SimpleNamespace(
            operation=object(),
            service=FakeConversationRepository(object()),
        )

    monkeypatch.setattr(
        chat_handler_module,
        "conversation_access_application_authority_v2",
        fake_conversation_access_authority,
    )
    monkeypatch.setattr(actor_manager, "get_actor_if_exists", fake_get_actor_if_exists)
    monkeypatch.setattr(ray_client, "await_ray", fake_await_ray)
    monkeypatch.setattr(
        runtime_bootstrapper.AgentRuntimeBootstrapper,
        "cancel_local_chat",
        fake_cancel_local_chat,
    )

    context = StopContext(task)

    try:
        await StopSessionHandler().handle(context, {"conversation_id": "conv-1"})  # type: ignore[arg-type]
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    assert task.cancelled()
    assert fake_cancel.conversation_ids == ["conv-1"]
    assert local_cancelled == ["conv-1"]
    assert context.sent == [{"type": "ack", "action": "stop_session", "conversation_id": "conv-1"}]


@pytest.mark.parametrize(
    ("conversation_tenant_id", "conversation_user_id"),
    [
        ("other-tenant", "user-1"),
        ("tenant-1", "other-user"),
    ],
)
async def test_stop_session_rejects_wrong_scope_before_cancellation(
    monkeypatch: pytest.MonkeyPatch,
    conversation_tenant_id: str,
    conversation_user_id: str,
) -> None:
    async def bridge_task() -> None:
        await asyncio.Event().wait()

    task = asyncio.create_task(bridge_task())

    service = SimpleNamespace(
        find_by_id=AsyncMock(
            return_value=SimpleNamespace(
                id="conv-1",
                tenant_id=conversation_tenant_id,
                project_id="project-1",
                user_id=conversation_user_id,
            )
        )
    )

    @asynccontextmanager
    async def authority_with_wrong_scope(
        _context: StopContext,
        *,
        conversation_id: str,
    ) -> AsyncIterator[Any]:
        assert conversation_id == "conv-1"
        yield SimpleNamespace(operation=object(), service=service)

    monkeypatch.setattr(
        chat_handler_module,
        "conversation_access_application_authority_v2",
        authority_with_wrong_scope,
    )
    context = StopContext(task)

    try:
        await StopSessionHandler().handle(context, {"conversation_id": "conv-1"})  # type: ignore[arg-type]

        assert not task.done()
        assert context.connection_manager.bridge_tasks == {"session-1": {"conv-1": task}}
        assert context.sent == [
            {
                "type": "error",
                "data": {"message": "Access denied", "code": None},
                "conversation_id": "conv-1",
            }
        ]
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_stop_session_reports_v2_authority_error_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def bridge_task() -> None:
        await asyncio.Event().wait()

    task = asyncio.create_task(bridge_task())

    @asynccontextmanager
    async def missing_conversation_access_authority(
        *_args: object,
        **_kwargs: object,
    ) -> AsyncIterator[Any]:
        if _kwargs.get("conversation_id") == "conv-1":
            raise RuntimeV2Error(
                "missing_service_provider",
                "conversation access service is unavailable",
            )
        yield SimpleNamespace(operation=object(), service=object())

    monkeypatch.setattr(
        chat_handler_module,
        "conversation_access_application_authority_v2",
        missing_conversation_access_authority,
    )
    context = StopContext(task)

    try:
        await StopSessionHandler().handle(context, {"conversation_id": "conv-1"})  # type: ignore[arg-type]

        assert not task.done()
        assert context.sent == [
            {
                "type": "error",
                "data": {
                    "message": "conversation access service is unavailable",
                    "code": "missing_service_provider",
                },
                "conversation_id": "conv-1",
            }
        ]
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


def test_stop_session_conversation_lookup_has_no_static_sql_fallback() -> None:
    source = inspect.getsource(StopSessionHandler.handle)

    assert "conversation_access_application_authority_v2" in source
    assert "SqlConversationRepository" not in source
