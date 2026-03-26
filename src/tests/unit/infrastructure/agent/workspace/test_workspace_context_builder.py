from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from src.domain.model.workspace.blackboard_post import BlackboardPost, BlackboardPostStatus
from src.domain.model.workspace.workspace import Workspace
from src.domain.model.workspace.workspace_agent import WorkspaceAgent
from src.domain.model.workspace.workspace_member import WorkspaceMember
from src.domain.model.workspace.workspace_message import MessageSenderType, WorkspaceMessage
from src.domain.model.workspace.workspace_role import WorkspaceRole
from src.infrastructure.agent.workspace.workspace_context_builder import (
    build_workspace_context,
    format_timestamp,
    format_workspace_context,
    truncate,
)

_NOW = datetime(2025, 6, 15, 10, 30, 0, tzinfo=UTC)


def _make_workspace() -> Workspace:
    return Workspace(
        id="ws-1",
        tenant_id="t-1",
        project_id="p-1",
        name="Test Workspace",
        created_by="user-1",
    )


def _make_member(
    user_id: str = "user-1", role: WorkspaceRole = WorkspaceRole.OWNER
) -> WorkspaceMember:
    return WorkspaceMember(workspace_id="ws-1", user_id=user_id, role=role, created_at=_NOW)


def _make_agent(agent_id: str = "agent-1", name: str = "CodingBot") -> WorkspaceAgent:
    return WorkspaceAgent(
        workspace_id="ws-1",
        agent_id=agent_id,
        display_name=name,
        description="A coding assistant",
        status="idle",
        created_at=_NOW,
    )


def _make_message(
    sender_id: str = "user-1",
    content: str = "Hello team!",
    mentions: list[str] | None = None,
) -> WorkspaceMessage:
    return WorkspaceMessage(
        workspace_id="ws-1",
        sender_id=sender_id,
        sender_type=MessageSenderType.HUMAN,
        content=content,
        mentions=mentions or [],
        created_at=_NOW,
    )


def _make_post(title: str = "Sprint Plan", pinned: bool = False) -> BlackboardPost:
    return BlackboardPost(
        workspace_id="ws-1",
        author_id="user-1",
        title=title,
        content="This is the sprint plan content.",
        status=BlackboardPostStatus.OPEN,
        is_pinned=pinned,
        created_at=_NOW,
    )


@pytest.mark.unit
class TestFormatTimestamp:
    def test_formats_compact_iso(self) -> None:
        dt = datetime(2025, 1, 15, 9, 5, tzinfo=UTC)
        assert format_timestamp(dt) == "2025-01-15 09:05"


@pytest.mark.unit
class TestTruncate:
    def test_short_text_unchanged(self) -> None:
        assert truncate("hello", 10) == "hello"

    def test_exact_length_unchanged(self) -> None:
        assert truncate("hello", 5) == "hello"

    def test_long_text_truncated(self) -> None:
        result = truncate("a" * 50, 20)
        assert len(result) == 20
        assert result.endswith("...")


@pytest.mark.unit
class TestFormatWorkspaceContext:
    def test_empty_workspace(self) -> None:
        ws = _make_workspace()
        result = format_workspace_context(ws, [], [], [], [])
        assert '<cyber-workspace name="Test Workspace" id="ws-1">' in result
        assert "</cyber-workspace>" in result
        assert "<members>" not in result

    def test_with_members(self) -> None:
        ws = _make_workspace()
        members = [
            _make_member("user-1", WorkspaceRole.OWNER),
            _make_member("user-2", WorkspaceRole.VIEWER),
        ]
        result = format_workspace_context(ws, members, [], [], [])
        assert "<members>" in result
        assert 'user_id="user-1"' in result
        assert 'role="owner"' in result
        assert 'user_id="user-2"' in result

    def test_with_agents(self) -> None:
        ws = _make_workspace()
        agents = [_make_agent("agent-1", "CodingBot")]
        result = format_workspace_context(ws, [], agents, [], [])
        assert "<agents>" in result
        assert 'name="CodingBot"' in result
        assert 'description="A coding assistant"' in result

    def test_agent_with_non_idle_status(self) -> None:
        ws = _make_workspace()
        agent = _make_agent()
        agent.status = "busy"
        result = format_workspace_context(ws, [], [agent], [], [])
        assert 'status="busy"' in result

    def test_agent_idle_status_omitted(self) -> None:
        ws = _make_workspace()
        agent = _make_agent()
        result = format_workspace_context(ws, [], [agent], [], [])
        assert "status=" not in result

    def test_with_messages(self) -> None:
        ws = _make_workspace()
        messages = [_make_message("user-1", "Hello @CodingBot", ["CodingBot"])]
        result = format_workspace_context(ws, [], [], messages, [])
        assert "<recent-messages>" in result
        assert 'from="human:user-1"' in result
        assert 'mentions="CodingBot"' in result
        assert "Hello @CodingBot" in result

    def test_with_posts(self) -> None:
        ws = _make_workspace()
        posts = [_make_post("Sprint Plan", pinned=True)]
        result = format_workspace_context(ws, [], [], [], posts)
        assert "<blackboard>" in result
        assert 'title="Sprint Plan"' in result
        assert 'pinned="true"' in result

    def test_message_content_truncation(self) -> None:
        ws = _make_workspace()
        long_content = "x" * 500
        messages = [_make_message(content=long_content)]
        result = format_workspace_context(ws, [], [], messages, [])
        assert "..." in result
        assert "x" * 500 not in result

    def test_full_context(self) -> None:
        ws = _make_workspace()
        result = format_workspace_context(
            ws,
            [_make_member()],
            [_make_agent()],
            [_make_message()],
            [_make_post()],
        )
        assert "<members>" in result
        assert "<agents>" in result
        assert "<recent-messages>" in result
        assert "<blackboard>" in result


@pytest.mark.unit
class TestBuildWorkspaceContext:
    async def test_returns_none_for_empty_project_id(self) -> None:
        result = await build_workspace_context("", "t-1")
        assert result is None

    async def test_returns_none_for_empty_tenant_id(self) -> None:
        result = await build_workspace_context("p-1", "")
        assert result is None

    async def test_returns_none_when_no_workspace(self) -> None:
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with (
            patch(
                "src.infrastructure.agent.workspace.workspace_context_builder.async_session_factory",
                return_value=mock_session,
            ),
            patch(
                "src.infrastructure.agent.workspace.workspace_context_builder.SqlWorkspaceRepository"
            ) as mock_repo_cls,
        ):
            mock_repo = mock_repo_cls.return_value
            mock_repo.find_by_project = AsyncMock(return_value=[])
            result = await build_workspace_context("p-1", "t-1")
            assert result is None

    async def test_returns_context_when_workspace_exists(self) -> None:
        ws = _make_workspace()
        members = [_make_member()]
        agents = [_make_agent()]
        messages = [_make_message()]
        posts = [_make_post()]

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with (
            patch(
                "src.infrastructure.agent.workspace.workspace_context_builder.async_session_factory",
                return_value=mock_session,
            ),
            patch(
                "src.infrastructure.agent.workspace.workspace_context_builder.SqlWorkspaceRepository"
            ) as mock_ws_repo_cls,
            patch(
                "src.infrastructure.agent.workspace.workspace_context_builder.SqlWorkspaceMemberRepository"
            ) as mock_member_repo_cls,
            patch(
                "src.infrastructure.agent.workspace.workspace_context_builder.SqlWorkspaceAgentRepository"
            ) as mock_agent_repo_cls,
            patch(
                "src.infrastructure.agent.workspace.workspace_context_builder.SqlWorkspaceMessageRepository"
            ) as mock_msg_repo_cls,
            patch(
                "src.infrastructure.agent.workspace.workspace_context_builder.SqlBlackboardRepository"
            ) as mock_bb_repo_cls,
        ):
            mock_ws_repo_cls.return_value.find_by_project = AsyncMock(return_value=[ws])
            mock_member_repo_cls.return_value.find_by_workspace = AsyncMock(return_value=members)
            mock_agent_repo_cls.return_value.find_by_workspace = AsyncMock(return_value=agents)
            mock_msg_repo_cls.return_value.find_by_workspace = AsyncMock(return_value=messages)
            mock_bb_repo_cls.return_value.list_posts_by_workspace = AsyncMock(return_value=posts)

            result = await build_workspace_context("p-1", "t-1")
            assert result is not None
            assert "Test Workspace" in result
            assert "<members>" in result
            assert "<agents>" in result

    async def test_returns_none_on_exception(self) -> None:
        with patch(
            "src.infrastructure.agent.workspace.workspace_context_builder.async_session_factory",
            side_effect=RuntimeError("DB down"),
        ):
            result = await build_workspace_context("p-1", "t-1")
            assert result is None
