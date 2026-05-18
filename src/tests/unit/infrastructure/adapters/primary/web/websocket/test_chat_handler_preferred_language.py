"""Unit tests for chat WebSocket language propagation."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest

from src.infrastructure.adapters.primary.web.websocket.handlers.chat_handler import (
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
