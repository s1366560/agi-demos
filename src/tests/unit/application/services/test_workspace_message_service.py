from __future__ import annotations

from types import SimpleNamespace
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


class _FindByIdOnlyUserRepo:
    def __init__(self, users: dict[str, Any]) -> None:
        self._users = users
        self.find_by_id = AsyncMock(side_effect=lambda user_id: self._users.get(user_id))


def _build_service(
    *,
    agents: list[MagicMock] | None = None,
    members: list[MagicMock] | None = None,
    publisher: AsyncMock | None = AsyncMock(),
    user_repo: Any | None = None,
    allow_legacy_text_mentions: bool = False,
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
        user_repo=user_repo,
        allow_legacy_text_mentions=allow_legacy_text_mentions,
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

    async def test_uses_structured_agent_mentions(self) -> None:
        agents = [_make_agent("agent-abc", "CodeBot")]
        service, *_ = _build_service(agents=agents)
        msg = await service.send_message(
            workspace_id="ws-1",
            sender_id="user-1",
            sender_type=MessageSenderType.HUMAN,
            sender_name="Alice",
            content="Hey @CodeBot can you help?",
            mentions=["agent-abc"],
        )
        assert msg.mentions == ["agent-abc"]

    async def test_uses_multiple_structured_mentions(self) -> None:
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
            mentions=["a1", "a2"],
        )
        assert set(msg.mentions) == {"a1", "a2"}

    async def test_unstructured_text_mention_does_not_route_by_default(self) -> None:
        service, *_ = _build_service(agents=[], members=[])
        msg = await service.send_message(
            workspace_id="ws-1",
            sender_id="user-1",
            sender_type=MessageSenderType.HUMAN,
            sender_name="Alice",
            content="Hey @nonexistent check this",
        )
        assert msg.mentions == []

    async def test_unknown_structured_mention_rejected(self) -> None:
        service, *_ = _build_service(agents=[], members=[])

        with pytest.raises(ValueError, match="Unknown workspace mentions"):
            await service.send_message(
                workspace_id="ws-1",
                sender_id="user-1",
                sender_type=MessageSenderType.HUMAN,
                sender_name="Alice",
                content="Hey @nonexistent check this",
                mentions=["nonexistent"],
            )

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
        publisher.assert_not_awaited()
        await service.publish_pending_events()
        publisher.assert_awaited_once()
        call_args = publisher.call_args
        assert call_args[0][0] == "ws-1"
        assert call_args[0][1] == "workspace_message_created"
        payload: dict[str, Any] = call_args[0][2]
        message = payload["message"]
        assert message["sender_id"] == "user-1"
        assert message["content"] == "Hello"

    async def test_publish_pending_events_keeps_queue_when_publish_fails(self) -> None:
        publisher = AsyncMock(side_effect=RuntimeError("redis down"))
        service, *_ = _build_service(publisher=publisher)
        await service.send_message(
            workspace_id="ws-1",
            sender_id="user-1",
            sender_type=MessageSenderType.HUMAN,
            sender_name="Alice",
            content="Hello",
        )

        with pytest.raises(RuntimeError, match="redis down"):
            await service.publish_pending_events()

        assert len(service.consume_pending_events()) == 1

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
            mentions=["a1", "a1"],
        )
        assert msg.mentions == ["a1"]

    async def test_legacy_text_mentions_available_when_enabled(self) -> None:
        agents = [_make_agent("agent-abc", "CodeBot")]
        service, *_ = _build_service(agents=agents, allow_legacy_text_mentions=True)

        msg = await service.send_message(
            workspace_id="ws-1",
            sender_id="user-1",
            sender_type=MessageSenderType.HUMAN,
            sender_name="Alice",
            content="Hey @CodeBot can you help?",
        )

        assert msg.mentions == ["agent-abc"]

    async def test_legacy_text_mentions_bulk_load_member_aliases(self) -> None:
        members = [MagicMock(user_id="user-1"), MagicMock(user_id="user-2")]
        user_repo = MagicMock()
        user_repo.find_by_ids = AsyncMock(
            return_value=[
                SimpleNamespace(id="user-1", email="alice@example.com", name="Alice"),
                SimpleNamespace(id="user-2", email="bob@example.com", name="Bob"),
            ]
        )
        user_repo.find_by_id = AsyncMock()
        service, *_ = _build_service(
            members=members,
            user_repo=user_repo,
            allow_legacy_text_mentions=True,
        )

        msg = await service.send_message(
            workspace_id="ws-1",
            sender_id="user-0",
            sender_type=MessageSenderType.HUMAN,
            sender_name="Sender",
            content="Ping @alice and @Bob",
        )

        assert msg.mentions == ["user-1", "user-2"]
        user_repo.find_by_ids.assert_awaited_once_with(["user-1", "user-2"])
        user_repo.find_by_id.assert_not_called()

    async def test_legacy_text_mentions_fall_back_without_bulk_user_lookup(self) -> None:
        members = [MagicMock(user_id="user-1"), MagicMock(user_id="user-1")]
        user_repo = _FindByIdOnlyUserRepo(
            {"user-1": SimpleNamespace(id="user-1", email="alice@example.com", name="Alice")}
        )
        service, *_ = _build_service(
            members=members,
            user_repo=user_repo,
            allow_legacy_text_mentions=True,
        )

        msg = await service.send_message(
            workspace_id="ws-1",
            sender_id="user-0",
            sender_type=MessageSenderType.HUMAN,
            sender_name="Sender",
            content="Ping @Alice",
        )

        assert msg.mentions == ["user-1"]
        user_repo.find_by_id.assert_awaited_once_with("user-1")


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
    async def test_delegates_to_repo_mentions_query(self) -> None:
        msg_with = MagicMock(spec=WorkspaceMessage)
        msg_with.mentions = ["agent-1"]

        service, message_repo, *_ = _build_service()
        message_repo.find_mentions = AsyncMock(return_value=[msg_with])

        result = await service.get_mentions("ws-1", "agent-1", limit=25)
        assert len(result) == 1
        assert result[0] is msg_with
        message_repo.find_mentions.assert_awaited_once_with(
            workspace_id="ws-1",
            target_id="agent-1",
            limit=25,
        )
        message_repo.find_by_workspace.assert_not_called()
