"""Unit tests for chat WebSocket language propagation."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

import pytest

from src.infrastructure.adapters.primary.web.websocket.handlers.chat_handler import (
    StopSessionHandler,
    stream_agent_to_websocket,
)

pytestmark = pytest.mark.unit


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


class FakeMessageContext:
    session_id = "session-1"
    user_id = "user-1"
    tenant_id = "tenant-1"
    api_key = "ms_sk_" + ("a" * 64)

    def __init__(self) -> None:
        self.connection_manager = FakeConnectionManager()


class StopConnectionManager:
    def __init__(self, task: asyncio.Task[None]) -> None:
        self.bridge_tasks = {"session-1": {"conv-1": task}}


class StopContext:
    session_id = "session-1"
    tenant_id = "tenant-1"
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
        return SimpleNamespace(tenant_id="tenant-1", project_id="project-1")


class FakeCancelMethod:
    def __init__(self) -> None:
        self.conversation_ids: list[str] = []

    def remote(self, conversation_id: str) -> bool:
        self.conversation_ids.append(conversation_id)
        return False


async def test_stream_agent_to_websocket_passes_preferred_language() -> None:
    agent_service = FakeAgentService()
    context = FakeMessageContext()

    await stream_agent_to_websocket(
        agent_service=agent_service,  # type: ignore[arg-type]
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


async def test_stream_agent_to_websocket_strips_client_workspace_runtime_context() -> None:
    agent_service = FakeAgentService()
    context = FakeMessageContext()

    await stream_agent_to_websocket(
        agent_service=agent_service,  # type: ignore[arg-type]
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
    import src.infrastructure.adapters.secondary.persistence.sql_conversation_repository as conv_repo
    import src.infrastructure.adapters.secondary.ray.client as ray_client
    import src.infrastructure.agent.actor.actor_manager as actor_manager

    monkeypatch.setattr(conv_repo, "SqlConversationRepository", FakeConversationRepository)
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
