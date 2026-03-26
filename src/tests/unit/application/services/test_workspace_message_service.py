from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.application.services.workspace_message_service import WorkspaceMessageService
from src.domain.model.workspace.workspace_message import (
    MessageSenderType,
    WorkspaceMessage,
)


def _make_agent(agent_id: str, display_name: str) -> MagicMock:
    agent = MagicMock()
    agent.agent_id = agent_id
    agent.display_name = display_name
    return agent


def _build_service(
    *,
    agents: list[MagicMock] | None = None,
    members: list[MagicMock] | None = None,
    publisher: AsyncMock | None = AsyncMock(),
) -> tuple[WorkspaceMessageService, AsyncMock, AsyncMock, AsyncMock]:
    message_repo = AsyncMock()
    member_repo = AsyncMock()
    agent_repo = AsyncMock()

    member_repo.find_by_workspace = AsyncMock(return_value=members or [])
    agent_repo.find_by_workspace = AsyncMock(return_value=agents or [])

    async def _save_passthrough(msg: WorkspaceMessage) -> WorkspaceMessage:
        return msg

    message_repo.save = AsyncMock(side_effect=_save_passthrough)

    service = WorkspaceMessageService(
        message_repo=message_repo,
        member_repo=member_repo,
        agent_repo=agent_repo,
        workspace_event_publisher=publisher,
    )
    return service, message_repo, member_repo, agent_repo


@pytest.mark.unit
class TestSendMessage:
    async def test_basic_send_returns_message(self) -> None:
        service, *_ = _build_service()
        msg = await service.send_message(
            workspace_id="ws-1",
            sender_id="user-1",
            sender_type=MessageSenderType.HUMAN,
            sender_name="Alice",
            content="Hello team",
        )
        assert isinstance(msg, WorkspaceMessage)
        assert msg.workspace_id == "ws-1"
        assert msg.sender_id == "user-1"
        assert msg.content == "Hello team"
        assert msg.metadata == {"sender_name": "Alice"}

    async def test_parses_agent_mentions(self) -> None:
        agents = [_make_agent("agent-abc", "CodeBot")]
        service, *_ = _build_service(agents=agents)
        msg = await service.send_message(
            workspace_id="ws-1",
            sender_id="user-1",
            sender_type=MessageSenderType.HUMAN,
            sender_name="Alice",
            content="Hey @CodeBot can you help?",
        )
        assert msg.mentions == ["agent-abc"]

    async def test_parses_multiple_mentions(self) -> None:
        agents = [
            _make_agent("a1", "Bot-A"),
            _make_agent("a2", "Bot-B"),
        ]
        service, *_ = _build_service(agents=agents)
        msg = await service.send_message(
            workspace_id="ws-1",
            sender_id="user-1",
            sender_type=MessageSenderType.HUMAN,
            sender_name="Alice",
            content="@Bot-A and @Bot-B please review",
        )
        assert set(msg.mentions) == {"a1", "a2"}

    async def test_unknown_mention_ignored(self) -> None:
        service, *_ = _build_service(agents=[], members=[])
        msg = await service.send_message(
            workspace_id="ws-1",
            sender_id="user-1",
            sender_type=MessageSenderType.HUMAN,
            sender_name="Alice",
            content="Hey @nonexistent check this",
        )
        assert msg.mentions == []

    async def test_publishes_event(self) -> None:
        publisher = AsyncMock()
        service, *_ = _build_service(publisher=publisher)
        await service.send_message(
            workspace_id="ws-1",
            sender_id="user-1",
            sender_type=MessageSenderType.HUMAN,
            sender_name="Alice",
            content="Hello",
        )
        publisher.assert_awaited_once()
        call_args = publisher.call_args
        assert call_args[0][0] == "ws-1"
        assert call_args[0][1] == "workspace_message_created"
        payload: dict[str, Any] = call_args[0][2]
        assert payload["sender_id"] == "user-1"
        assert payload["content"] == "Hello"

    async def test_no_publisher_does_not_raise(self) -> None:
        service, *_ = _build_service(publisher=None)
        msg = await service.send_message(
            workspace_id="ws-1",
            sender_id="user-1",
            sender_type=MessageSenderType.HUMAN,
            sender_name="Alice",
            content="Hello",
        )
        assert msg.content == "Hello"

    async def test_agent_sender_type(self) -> None:
        service, *_ = _build_service()
        msg = await service.send_message(
            workspace_id="ws-1",
            sender_id="agent-1",
            sender_type=MessageSenderType.AGENT,
            sender_name="Bot",
            content="Done",
        )
        assert msg.sender_type == MessageSenderType.AGENT

    async def test_thread_reply(self) -> None:
        service, *_ = _build_service()
        msg = await service.send_message(
            workspace_id="ws-1",
            sender_id="user-1",
            sender_type=MessageSenderType.HUMAN,
            sender_name="Alice",
            content="Reply here",
            parent_message_id="parent-msg-1",
        )
        assert msg.parent_message_id == "parent-msg-1"

    async def test_deduplicates_mentions(self) -> None:
        agents = [_make_agent("a1", "Bot")]
        service, *_ = _build_service(agents=agents)
        msg = await service.send_message(
            workspace_id="ws-1",
            sender_id="user-1",
            sender_type=MessageSenderType.HUMAN,
            sender_name="Alice",
            content="@Bot hey @Bot again",
        )
        assert msg.mentions == ["a1"]


@pytest.mark.unit
class TestListMessages:
    async def test_delegates_to_repo(self) -> None:
        service, message_repo, *_ = _build_service()
        message_repo.find_by_workspace = AsyncMock(return_value=[])
        result = await service.list_messages("ws-1", limit=10)
        assert result == []
        message_repo.find_by_workspace.assert_awaited_once_with("ws-1", limit=10, before=None)

    async def test_passes_before_cursor(self) -> None:
        service, message_repo, *_ = _build_service()
        message_repo.find_by_workspace = AsyncMock(return_value=[])
        await service.list_messages("ws-1", limit=20, before="msg-5")
        message_repo.find_by_workspace.assert_awaited_once_with("ws-1", limit=20, before="msg-5")


@pytest.mark.unit
class TestGetMentions:
    async def test_filters_by_target_id(self) -> None:
        msg_with = MagicMock(spec=WorkspaceMessage)
        msg_with.mentions = ["agent-1"]
        msg_without = MagicMock(spec=WorkspaceMessage)
        msg_without.mentions = ["agent-2"]

        service, message_repo, *_ = _build_service()
        message_repo.find_by_workspace = AsyncMock(return_value=[msg_with, msg_without])

        result = await service.get_mentions("ws-1", "agent-1")
        assert len(result) == 1
        assert result[0] is msg_with
