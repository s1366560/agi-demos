"""Tests for workspace chat tools (@tool_define version)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock

import pytest

import src.infrastructure.agent.tools.workspace_chat_tool as wc_mod
from src.domain.model.workspace.workspace_message import (
    MessageSenderType,
    WorkspaceMessage,
)
from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.workspace_chat_tool import (
    configure_workspace_chat,
    workspace_chat_read_tool,
    workspace_chat_send_tool,
)


def _make_ctx(**overrides: Any) -> ToolContext:
    defaults: dict[str, Any] = {
        "session_id": "s",
        "message_id": "m",
        "call_id": "c",
        "agent_name": "TestBot",
        "conversation_id": "conv-1",
    }
    defaults.update(overrides)
    return ToolContext(**defaults)


def _make_message(
    *,
    msg_id: str = "msg-1",
    sender_id: str = "sender-1",
    sender_name: str = "Alice",
    content: str = "hello",
) -> WorkspaceMessage:
    return WorkspaceMessage(
        id=msg_id,
        workspace_id="ws-1",
        sender_id=sender_id,
        sender_type=MessageSenderType.HUMAN,
        content=content,
        mentions=[],
        metadata={"sender_name": sender_name},
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


@pytest.fixture(autouse=True)
def _reset_workspace_chat_state() -> Any:  # pyright: ignore[reportUnusedFunction]
    wc_mod._workspace_message_service = None
    wc_mod._workspace_id = None
    yield
    wc_mod._workspace_message_service = None
    wc_mod._workspace_id = None


@pytest.fixture
def mock_service() -> AsyncMock:
    svc = AsyncMock()
    svc.send_message = AsyncMock(return_value=_make_message())
    svc.list_messages = AsyncMock(return_value=[_make_message()])
    return svc


@pytest.mark.unit
class TestConfigureWorkspaceChat:
    def test_sets_module_state(self, mock_service: AsyncMock) -> None:
        configure_workspace_chat(mock_service, "ws-42")
        assert wc_mod._workspace_message_service is mock_service
        assert wc_mod._workspace_id == "ws-42"

    def test_overwrites_previous_state(
        self,
        mock_service: AsyncMock,
    ) -> None:
        other = AsyncMock()
        configure_workspace_chat(mock_service, "ws-1")
        configure_workspace_chat(other, "ws-2")
        assert wc_mod._workspace_message_service is other
        assert wc_mod._workspace_id == "ws-2"


@pytest.mark.unit
class TestWorkspaceChatSendTool:
    async def test_tool_metadata(self) -> None:
        assert workspace_chat_send_tool.name == "workspace_chat_send"
        assert workspace_chat_send_tool.category == "workspace_chat"
        assert "content" in workspace_chat_send_tool.parameters["properties"]
        assert "content" in workspace_chat_send_tool.parameters["required"]

    async def test_send_success(self, mock_service: AsyncMock) -> None:
        configure_workspace_chat(mock_service, "ws-1")
        ctx = _make_ctx()

        result = await workspace_chat_send_tool.execute(
            ctx,
            content="hi team",
        )

        assert result.is_error is False
        data = json.loads(result.output)
        assert data["status"] == "sent"
        assert data["message_id"] == "msg-1"
        mock_service.send_message.assert_awaited_once_with(
            workspace_id="ws-1",
            sender_id="conv-1",
            sender_type=MessageSenderType.AGENT,
            sender_name="TestBot",
            content="hi team",
            parent_message_id=None,
        )

    async def test_send_with_parent_id(
        self,
        mock_service: AsyncMock,
    ) -> None:
        configure_workspace_chat(mock_service, "ws-1")
        ctx = _make_ctx()

        await workspace_chat_send_tool.execute(
            ctx,
            content="reply",
            parent_message_id="parent-99",
        )

        mock_service.send_message.assert_awaited_once()
        call_kwargs = mock_service.send_message.call_args.kwargs
        assert call_kwargs["parent_message_id"] == "parent-99"

    async def test_send_error_not_configured(self) -> None:
        ctx = _make_ctx()
        result = await workspace_chat_send_tool.execute(
            ctx,
            content="hi",
        )
        assert result.is_error is True
        data = json.loads(result.output)
        assert "not configured" in data["error"]

    async def test_send_error_empty_content(
        self,
        mock_service: AsyncMock,
    ) -> None:
        configure_workspace_chat(mock_service, "ws-1")
        ctx = _make_ctx()

        result = await workspace_chat_send_tool.execute(
            ctx,
            content="",
        )
        assert result.is_error is True
        data = json.loads(result.output)
        assert "empty" in data["error"]

    async def test_send_error_whitespace_content(
        self,
        mock_service: AsyncMock,
    ) -> None:
        configure_workspace_chat(mock_service, "ws-1")
        ctx = _make_ctx()

        result = await workspace_chat_send_tool.execute(
            ctx,
            content="   ",
        )
        assert result.is_error is True

    async def test_send_handles_service_exception(
        self,
        mock_service: AsyncMock,
    ) -> None:
        configure_workspace_chat(mock_service, "ws-1")
        mock_service.send_message.side_effect = ValueError("db down")
        ctx = _make_ctx()

        result = await workspace_chat_send_tool.execute(
            ctx,
            content="hi",
        )
        assert result.is_error is True
        data = json.loads(result.output)
        assert "db down" in data["error"]


@pytest.mark.unit
class TestWorkspaceChatReadTool:
    async def test_tool_metadata(self) -> None:
        assert workspace_chat_read_tool.name == "workspace_chat_read"
        assert workspace_chat_read_tool.category == "workspace_chat"

    async def test_read_success(self, mock_service: AsyncMock) -> None:
        configure_workspace_chat(mock_service, "ws-1")
        ctx = _make_ctx()

        result = await workspace_chat_read_tool.execute(ctx)

        assert result.is_error is False
        data = json.loads(result.output)
        assert data["count"] == 1
        msg = data["messages"][0]
        assert msg["sender_id"] == "sender-1"
        assert msg["sender_name"] == "Alice"
        assert msg["content"] == "hello"
        assert msg["sender_type"] == "human"

    async def test_read_error_not_configured(self) -> None:
        ctx = _make_ctx()
        result = await workspace_chat_read_tool.execute(ctx)
        assert result.is_error is True
        data = json.loads(result.output)
        assert "not configured" in data["error"]

    async def test_read_default_limit(
        self,
        mock_service: AsyncMock,
    ) -> None:
        configure_workspace_chat(mock_service, "ws-1")
        ctx = _make_ctx()

        await workspace_chat_read_tool.execute(ctx)

        mock_service.list_messages.assert_awaited_once_with(
            workspace_id="ws-1",
            limit=20,
        )

    async def test_read_clamps_limit_to_max_50(
        self,
        mock_service: AsyncMock,
    ) -> None:
        configure_workspace_chat(mock_service, "ws-1")
        ctx = _make_ctx()

        await workspace_chat_read_tool.execute(ctx, limit=999)

        call_kwargs = mock_service.list_messages.call_args.kwargs
        assert call_kwargs["limit"] == 50

    async def test_read_clamps_limit_to_min_1(
        self,
        mock_service: AsyncMock,
    ) -> None:
        configure_workspace_chat(mock_service, "ws-1")
        ctx = _make_ctx()

        await workspace_chat_read_tool.execute(ctx, limit=-5)

        call_kwargs = mock_service.list_messages.call_args.kwargs
        assert call_kwargs["limit"] == 1

    async def test_read_handles_service_exception(
        self,
        mock_service: AsyncMock,
    ) -> None:
        configure_workspace_chat(mock_service, "ws-1")
        mock_service.list_messages.side_effect = RuntimeError("timeout")
        ctx = _make_ctx()

        result = await workspace_chat_read_tool.execute(ctx)
        assert result.is_error is True
        data = json.loads(result.output)
        assert "not configured" in data["error"] or "timeout" in data["error"]

    async def test_read_empty_messages(
        self,
        mock_service: AsyncMock,
    ) -> None:
        configure_workspace_chat(mock_service, "ws-1")
        mock_service.list_messages.return_value = []
        ctx = _make_ctx()

        result = await workspace_chat_read_tool.execute(ctx)
        data = json.loads(result.output)
        assert data["count"] == 0
        assert data["messages"] == []
