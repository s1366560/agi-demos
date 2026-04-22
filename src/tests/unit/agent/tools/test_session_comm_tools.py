"""Tests for session communication tools and service."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from src.application.services.session_comm_service import (
    SessionCommService,
)
from src.domain.model.agent import (
    AgentExecutionEvent,
    Conversation,
    ConversationStatus,
    Message,
    MessageRole,
    MessageType,
)
from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.session_comm_tools import (
    configure_session_comm,
    sessions_history_tool,
    sessions_list_tool,
    sessions_send_tool,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_conversation(
    *,
    conv_id: str = "conv-1",
    project_id: str = "proj-1",
    title: str = "Test Session",
    status: ConversationStatus = ConversationStatus.ACTIVE,
    message_count: int = 5,
    updated_at: datetime | None = None,
) -> Conversation:
    return Conversation(
        id=conv_id,
        project_id=project_id,
        tenant_id="tenant-1",
        user_id="user-1",
        title=title,
        status=status,
        message_count=message_count,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        updated_at=updated_at or datetime(2026, 1, 1, tzinfo=UTC),
    )


def _make_message(
    *,
    msg_id: str = "msg-1",
    conv_id: str = "conv-1",
    role: MessageRole = MessageRole.USER,
    content: str = "Hello",
    created_at: datetime | None = None,
) -> Message:
    return Message(
        id=msg_id,
        conversation_id=conv_id,
        role=role,
        content=content,
        message_type=MessageType.TEXT,
        created_at=created_at or datetime(2026, 1, 1, tzinfo=UTC),
    )


def _make_ctx(
    *,
    project_id: str = "proj-1",
    conversation_id: str = "current-conv",
) -> ToolContext:
    return ToolContext(
        session_id="sess-1",
        message_id="msg-x",
        call_id="call-x",
        agent_name="test-agent",
        conversation_id=conversation_id,
        project_id=project_id,
        user_id="user-1",
    )


def _build_service(
    *,
    conv_repo: AsyncMock | None = None,
    msg_repo: AsyncMock | None = None,
    event_repo: AsyncMock | None = None,
) -> SessionCommService:
    conv_repo = conv_repo or AsyncMock()
    msg_repo = msg_repo or AsyncMock()
    return SessionCommService(
        conversation_repo=conv_repo,
        message_repo=msg_repo,
        agent_execution_event_repo=event_repo,
    )


def _make_event(
    *,
    event_id: str = "evt-1",
    message_id: str = "msg-1",
    conv_id: str = "conv-1",
    event_type: str = "user_message",
    role: str = "user",
    content: str = "Hello",
    created_at: datetime | None = None,
) -> AgentExecutionEvent:
    created_at = created_at or datetime(2026, 1, 1, tzinfo=UTC)
    return AgentExecutionEvent(
        id=event_id,
        conversation_id=conv_id,
        message_id=message_id,
        event_type=event_type,
        event_data={
            "message_id": message_id,
            "role": role,
            "content": content,
        },
        event_time_us=int(created_at.timestamp() * 1_000_000),
        event_counter=0,
        created_at=created_at,
    )


# ---------------------------------------------------------------------------
# SessionCommService unit tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSessionCommServiceListSessions:
    """Tests for SessionCommService.list_sessions."""

    async def test_list_returns_conversations(self) -> None:
        conv_repo = AsyncMock()
        conv_repo.list_by_project.return_value = [
            _make_conversation(conv_id="c1", title="Session A"),
            _make_conversation(conv_id="c2", title="Session B"),
        ]
        svc = _build_service(conv_repo=conv_repo)

        result = await svc.list_sessions("proj-1")

        assert len(result) == 2
        assert result[0]["id"] == "c1"
        assert result[1]["title"] == "Session B"
        conv_repo.list_by_project.assert_awaited_once()

    async def test_list_excludes_current_conversation(self) -> None:
        conv_repo = AsyncMock()
        conv_repo.list_by_project.return_value = [
            _make_conversation(conv_id="c1"),
            _make_conversation(conv_id="current-conv"),
        ]
        svc = _build_service(conv_repo=conv_repo)

        result = await svc.list_sessions("proj-1", exclude_conversation_id="current-conv")

        assert len(result) == 1
        assert result[0]["id"] == "c1"

    async def test_list_with_status_filter(self) -> None:
        conv_repo = AsyncMock()
        conv_repo.list_by_project.return_value = []
        svc = _build_service(conv_repo=conv_repo)

        await svc.list_sessions("proj-1", status_filter="active")

        conv_repo.list_by_project.assert_awaited_once_with(
            "proj-1",
            status=ConversationStatus.ACTIVE,
            limit=20,
            offset=0,
        )

    async def test_list_with_invalid_status_ignores(self) -> None:
        conv_repo = AsyncMock()
        conv_repo.list_by_project.return_value = []
        svc = _build_service(conv_repo=conv_repo)

        await svc.list_sessions("proj-1", status_filter="nonexistent")

        conv_repo.list_by_project.assert_awaited_once_with(
            "proj-1", status=None, limit=20, offset=0
        )


@pytest.mark.unit
class TestSessionCommServiceGetHistory:
    """Tests for SessionCommService.get_session_history."""

    async def test_returns_history(self) -> None:
        conv = _make_conversation()
        conv_repo = AsyncMock()
        conv_repo.find_by_id.return_value = conv
        msg_repo = AsyncMock()
        msg_repo.list_by_conversation.return_value = [
            _make_message(msg_id="m1", content="Hi"),
            _make_message(
                msg_id="m2",
                role=MessageRole.ASSISTANT,
                content="Hello",
            ),
        ]
        svc = _build_service(conv_repo=conv_repo, msg_repo=msg_repo)

        result = await svc.get_session_history("proj-1", "conv-1", limit=2)

        assert result["conversation"]["id"] == "conv-1"
        assert len(result["messages"]) == 2
        assert result["messages"][0]["content"] == "Hi"

    async def test_raises_on_not_found(self) -> None:
        conv_repo = AsyncMock()
        conv_repo.find_by_id.return_value = None
        svc = _build_service(conv_repo=conv_repo)

        with pytest.raises(ValueError, match="not found"):
            await svc.get_session_history("proj-1", "no-such-conv")

    async def test_raises_on_cross_project_access(self) -> None:
        conv = _make_conversation(project_id="other-project")
        conv_repo = AsyncMock()
        conv_repo.find_by_id.return_value = conv
        svc = _build_service(conv_repo=conv_repo)

        with pytest.raises(PermissionError, match="different project"):
            await svc.get_session_history("proj-1", "conv-1")

    async def test_reads_event_history_when_message_table_is_empty(self) -> None:
        conv = _make_conversation(message_count=2)
        conv_repo = AsyncMock()
        conv_repo.find_by_id.return_value = conv
        msg_repo = AsyncMock()
        msg_repo.list_by_conversation.return_value = []
        event_repo = AsyncMock()
        event_repo.get_message_events.return_value = [
            _make_event(message_id="evt-user", content="Hi"),
            _make_event(
                event_id="evt-2",
                message_id="evt-assistant",
                event_type="assistant_message",
                role="assistant",
                content="Hello",
                created_at=datetime(2026, 1, 1, 0, 0, 1, tzinfo=UTC),
            ),
        ]
        svc = _build_service(conv_repo=conv_repo, msg_repo=msg_repo, event_repo=event_repo)

        result = await svc.get_session_history("proj-1", "conv-1", limit=2)

        assert [message["role"] for message in result["messages"]] == ["user", "assistant"]
        assert [message["content"] for message in result["messages"]] == ["Hi", "Hello"]
        event_repo.get_message_events.assert_awaited_once_with(
            conversation_id="conv-1",
            limit=2,
        )

    async def test_merges_system_messages_with_event_history(self) -> None:
        conv = _make_conversation(message_count=3)
        conv_repo = AsyncMock()
        conv_repo.find_by_id.return_value = conv
        msg_repo = AsyncMock()
        msg_repo.list_by_conversation.return_value = [
            _make_message(
                msg_id="system-msg",
                role=MessageRole.SYSTEM,
                content="Peer note",
                created_at=datetime(2026, 1, 1, 0, 0, 2, tzinfo=UTC),
            )
        ]
        event_repo = AsyncMock()
        event_repo.get_message_events.return_value = [
            _make_event(message_id="evt-user", content="Hi"),
            _make_event(
                event_id="evt-2",
                message_id="evt-assistant",
                event_type="assistant_message",
                role="assistant",
                content="Hello",
                created_at=datetime(2026, 1, 1, 0, 0, 1, tzinfo=UTC),
            ),
        ]
        svc = _build_service(conv_repo=conv_repo, msg_repo=msg_repo, event_repo=event_repo)

        result = await svc.get_session_history("proj-1", "conv-1")

        assert [message["role"] for message in result["messages"]] == [
            "user",
            "assistant",
            "system",
        ]
        assert result["messages"][-1]["content"] == "Peer note"


@pytest.mark.unit
class TestSessionCommServiceSend:
    """Tests for SessionCommService.send_to_session."""

    async def test_sends_message(self) -> None:
        conv = _make_conversation()
        conv_repo = AsyncMock()
        conv_repo.find_by_id.return_value = conv
        msg_repo = AsyncMock()
        saved_msg = _make_message(msg_id="new-msg")
        msg_repo.save.return_value = saved_msg
        svc = _build_service(conv_repo=conv_repo, msg_repo=msg_repo)

        result = await svc.send_to_session(
            "proj-1",
            "conv-1",
            "Hello peer!",
            sender_conversation_id="my-conv",
        )

        assert result["status"] == "sent"
        assert result["message_id"] == "new-msg"
        msg_repo.save.assert_awaited_once()
        saved_call = msg_repo.save.call_args[0][0]
        assert saved_call.role == MessageRole.SYSTEM
        assert saved_call.content == "Hello peer!"
        assert saved_call.metadata["sender_conversation_id"] == "my-conv"

    async def test_rejects_empty_content(self) -> None:
        svc = _build_service()

        with pytest.raises(ValueError, match="cannot be empty"):
            await svc.send_to_session("proj-1", "conv-1", "  ")

    async def test_rejects_cross_project(self) -> None:
        conv = _make_conversation(project_id="other-project")
        conv_repo = AsyncMock()
        conv_repo.find_by_id.return_value = conv
        svc = _build_service(conv_repo=conv_repo)

        with pytest.raises(PermissionError, match="different project"):
            await svc.send_to_session("proj-1", "conv-1", "sneaky")

    async def test_rejects_not_found(self) -> None:
        conv_repo = AsyncMock()
        conv_repo.find_by_id.return_value = None
        svc = _build_service(conv_repo=conv_repo)

        with pytest.raises(ValueError, match="not found"):
            await svc.send_to_session("proj-1", "missing-conv", "hello")

    async def test_sends_message_and_increments_conversation_message_count(self) -> None:
        """send_to_session persists an incremented Conversation so sessions_history reflects it."""
        conv = _make_conversation(message_count=5)
        conv_repo = AsyncMock()
        conv_repo.find_by_id.return_value = conv
        saved_msg = _make_message(msg_id="new-msg")
        msg_repo = AsyncMock()
        msg_repo.save.return_value = saved_msg
        svc = _build_service(conv_repo=conv_repo, msg_repo=msg_repo)

        result = await svc.send_to_session(
            "proj-1",
            "conv-1",
            "Hello peer!",
            sender_conversation_id="my-conv",
        )

        assert result["status"] == "sent"
        msg_repo.save.assert_awaited_once()
        conv_repo.save.assert_awaited_once()
        saved_conv = conv_repo.save.call_args[0][0]
        assert saved_conv.message_count == 6

    async def test_sends_message_and_updates_conversation_updated_at(self) -> None:
        """send_to_session updates conversation.updated_at so sessions_history reflects recency."""
        conv = _make_conversation()
        original_updated_at = conv.updated_at
        conv_repo = AsyncMock()
        conv_repo.find_by_id.return_value = conv
        saved_msg = _make_message(msg_id="new-msg")
        msg_repo = AsyncMock()
        msg_repo.save.return_value = saved_msg
        svc = _build_service(conv_repo=conv_repo, msg_repo=msg_repo)

        await svc.send_to_session("proj-1", "conv-1", "ping")

        saved_conv = conv_repo.save.call_args[0][0]
        assert saved_conv.updated_at is not None
        assert saved_conv.updated_at != original_updated_at


@pytest.mark.unit
class TestSessionsHistoryMetadataConsistency:
    """sessions_history() returns conversation metadata consistent with new session-comm writes."""

    async def test_history_returns_message_count_in_conversation_metadata(self) -> None:
        conv = _make_conversation(message_count=42)
        conv_repo = AsyncMock()
        conv_repo.find_by_id.return_value = conv
        msg_repo = AsyncMock()
        msg_repo.list_by_conversation.return_value = [_make_message(msg_id="m1")]
        svc = _build_service(conv_repo=conv_repo, msg_repo=msg_repo)
        configure_session_comm(svc)
        ctx = _make_ctx()

        result = await sessions_history_tool.execute(ctx, conversation_id="conv-1")

        assert not result.is_error
        data = json.loads(result.output)
        assert data["conversation"]["message_count"] == 42

    async def test_history_returns_updated_at_in_conversation_metadata(self) -> None:
        conv = _make_conversation()
        conv_repo = AsyncMock()
        conv_repo.find_by_id.return_value = conv
        msg_repo = AsyncMock()
        msg_repo.list_by_conversation.return_value = [_make_message(msg_id="m1")]
        svc = _build_service(conv_repo=conv_repo, msg_repo=msg_repo)
        configure_session_comm(svc)
        ctx = _make_ctx()

        result = await sessions_history_tool.execute(ctx, conversation_id="conv-1")

        assert not result.is_error
        data = json.loads(result.output)
        assert data["conversation"]["updated_at"] is not None

    async def test_history_after_send_reflects_incremented_count(self) -> None:
        conv = _make_conversation(message_count=2)
        conv_repo = AsyncMock()
        conv_repo.find_by_id.return_value = conv
        saved_msg = _make_message(msg_id="msg-new")
        msg_repo = AsyncMock()
        msg_repo.save.return_value = saved_msg
        svc = _build_service(conv_repo=conv_repo, msg_repo=msg_repo)

        await svc.send_to_session("proj-1", "conv-1", "ping")

        conv_repo.find_by_id.return_value = conv
        msg_repo.list_by_conversation.return_value = [
            _make_message(msg_id="m1"),
            _make_message(msg_id="m2"),
            _make_message(msg_id="msg-new"),
        ]

        history = await svc.get_session_history("proj-1", "conv-1")

        assert history["conversation"]["message_count"] == 3


# ---------------------------------------------------------------------------
# Tool-level tests (sessions_list_tool, etc.)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSessionsListTool:
    """Tests for the sessions_list @tool_define tool."""

    async def test_returns_sessions(self) -> None:
        conv_repo = AsyncMock()
        conv_repo.list_by_project.return_value = [
            _make_conversation(conv_id="c1"),
        ]
        svc = _build_service(conv_repo=conv_repo)
        configure_session_comm(svc)
        ctx = _make_ctx()

        result = await sessions_list_tool.execute(ctx)

        assert not result.is_error
        data = json.loads(result.output)
        assert data["count"] == 1
        assert data["sessions"][0]["id"] == "c1"

    async def test_error_when_no_project_id(self) -> None:
        svc = _build_service()
        configure_session_comm(svc)
        ctx = _make_ctx(project_id="")

        result = await sessions_list_tool.execute(ctx)

        assert result.is_error
        data = json.loads(result.output)
        assert "project_id" in data["error"]


@pytest.mark.unit
class TestSessionsHistoryTool:
    """Tests for the sessions_history @tool_define tool."""

    async def test_returns_history(self) -> None:
        conv = _make_conversation()
        conv_repo = AsyncMock()
        conv_repo.find_by_id.return_value = conv
        msg_repo = AsyncMock()
        msg_repo.list_by_conversation.return_value = [
            _make_message(msg_id="m1"),
        ]
        svc = _build_service(conv_repo=conv_repo, msg_repo=msg_repo)
        configure_session_comm(svc)
        ctx = _make_ctx()

        result = await sessions_history_tool.execute(ctx, conversation_id="conv-1")

        assert not result.is_error
        data = json.loads(result.output)
        assert data["conversation"]["id"] == "conv-1"
        assert len(data["messages"]) == 1

    async def test_returns_event_history_when_message_table_is_empty(self) -> None:
        conv = _make_conversation(message_count=1)
        conv_repo = AsyncMock()
        conv_repo.find_by_id.return_value = conv
        msg_repo = AsyncMock()
        msg_repo.list_by_conversation.return_value = []
        event_repo = AsyncMock()
        event_repo.get_message_events.return_value = [
            _make_event(message_id="evt-user", content="Hi from events")
        ]
        svc = _build_service(conv_repo=conv_repo, msg_repo=msg_repo, event_repo=event_repo)
        configure_session_comm(svc)
        ctx = _make_ctx()

        result = await sessions_history_tool.execute(ctx, conversation_id="conv-1")

        assert not result.is_error
        data = json.loads(result.output)
        assert data["messages"][0]["content"] == "Hi from events"

    async def test_error_on_cross_project(self) -> None:
        conv = _make_conversation(project_id="other-proj")
        conv_repo = AsyncMock()
        conv_repo.find_by_id.return_value = conv
        svc = _build_service(conv_repo=conv_repo)
        configure_session_comm(svc)
        ctx = _make_ctx()

        result = await sessions_history_tool.execute(ctx, conversation_id="conv-1")

        assert result.is_error
        data = json.loads(result.output)
        assert "different project" in data["error"]

    async def test_error_when_missing_conversation_id(self) -> None:
        svc = _build_service()
        configure_session_comm(svc)
        ctx = _make_ctx()

        result = await sessions_history_tool.execute(ctx, conversation_id="")

        assert result.is_error


@pytest.mark.unit
class TestSessionsSendTool:
    """Tests for the sessions_send @tool_define tool."""

    async def test_sends_message(self) -> None:
        conv = _make_conversation()
        conv_repo = AsyncMock()
        conv_repo.find_by_id.return_value = conv
        msg_repo = AsyncMock()
        msg_repo.save.return_value = _make_message(msg_id="new")
        svc = _build_service(conv_repo=conv_repo, msg_repo=msg_repo)
        configure_session_comm(svc)
        ctx = _make_ctx()

        result = await sessions_send_tool.execute(ctx, conversation_id="conv-1", content="Hi!")

        assert not result.is_error
        data = json.loads(result.output)
        assert data["status"] == "sent"

    async def test_error_on_empty_content(self) -> None:
        svc = _build_service()
        configure_session_comm(svc)
        ctx = _make_ctx()

        result = await sessions_send_tool.execute(ctx, conversation_id="conv-1", content="   ")

        assert result.is_error
        data = json.loads(result.output)
        assert "empty" in data["error"]

    async def test_error_on_cross_project(self) -> None:
        conv = _make_conversation(project_id="other-proj")
        conv_repo = AsyncMock()
        conv_repo.find_by_id.return_value = conv
        svc = _build_service(conv_repo=conv_repo)
        configure_session_comm(svc)
        ctx = _make_ctx()

        result = await sessions_send_tool.execute(ctx, conversation_id="conv-1", content="sneaky")

        assert result.is_error
        data = json.loads(result.output)
        assert "different project" in data["error"]
