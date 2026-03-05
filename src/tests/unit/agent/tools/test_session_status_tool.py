"""Tests for session_status tool."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from src.domain.model.agent.agent_mode import AgentMode
from src.domain.model.agent.conversation.conversation import (
    Conversation,
    ConversationStatus,
)
from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.session_status import (
    _build_status_card,
    _format_duration,
    configure_session_status,
    session_status_tool,
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
    mode: AgentMode = AgentMode.BUILD,
    message_count: int = 5,
    parent_conversation_id: str | None = None,
    current_plan_id: str | None = None,
    summary: str | None = None,
) -> Conversation:
    return Conversation(
        id=conv_id,
        project_id=project_id,
        tenant_id="tenant-1",
        user_id="user-1",
        title=title,
        status=status,
        current_mode=mode,
        message_count=message_count,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        parent_conversation_id=parent_conversation_id,
        current_plan_id=current_plan_id,
        summary=summary,
    )


def _make_ctx(
    *,
    project_id: str = "proj-1",
    conversation_id: str = "conv-1",
    agent_name: str = "test-agent",
) -> ToolContext:
    return ToolContext(
        session_id="sess-1",
        message_id="msg-x",
        call_id="call-x",
        agent_name=agent_name,
        conversation_id=conversation_id,
        project_id=project_id,
        user_id="user-1",
    )


def _configure_repo(conv_repo: AsyncMock) -> None:
    """Inject a mock conversation repository into the module-level DI."""
    configure_session_status(conversation_repo=conv_repo)


# ---------------------------------------------------------------------------
# _format_duration unit tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFormatDuration:
    """Tests for the _format_duration helper."""

    def test_seconds(self) -> None:
        start = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
        end = datetime(2026, 1, 1, 0, 0, 45, tzinfo=UTC)
        assert _format_duration(start, end) == "45s"

    def test_minutes_and_seconds(self) -> None:
        start = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
        end = datetime(2026, 1, 1, 0, 3, 15, tzinfo=UTC)
        assert _format_duration(start, end) == "3m 15s"

    def test_hours_and_minutes(self) -> None:
        start = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
        end = datetime(2026, 1, 1, 2, 30, 0, tzinfo=UTC)
        assert _format_duration(start, end) == "2h 30m"

    def test_days_and_hours(self) -> None:
        start = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
        end = datetime(2026, 1, 3, 5, 0, 0, tzinfo=UTC)
        assert _format_duration(start, end) == "2d 5h"

    def test_zero_duration(self) -> None:
        ts = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
        assert _format_duration(ts, ts) == "0s"


# ---------------------------------------------------------------------------
# _build_status_card unit tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBuildStatusCard:
    """Tests for the _build_status_card helper."""

    def test_basic_card_contains_required_fields(self) -> None:
        conv = _make_conversation()
        ctx = _make_ctx()
        card = _build_status_card(conv, ctx)

        assert "conv-1" in card
        assert "Test Session" in card
        assert "active" in card
        assert "build" in card
        assert "5" in card  # message_count
        assert "test-agent" in card
        assert "proj-1" in card

    def test_card_includes_summary_when_present(self) -> None:
        conv = _make_conversation(summary="A conversation about testing")
        ctx = _make_ctx()
        card = _build_status_card(conv, ctx)

        assert "A conversation about testing" in card

    def test_card_includes_parent_for_subagent(self) -> None:
        conv = _make_conversation(parent_conversation_id="parent-conv-1")
        ctx = _make_ctx()
        card = _build_status_card(conv, ctx)

        assert "parent-conv-1" in card

    def test_card_includes_plan_id(self) -> None:
        conv = _make_conversation(current_plan_id="plan-42")
        ctx = _make_ctx()
        card = _build_status_card(conv, ctx)

        assert "plan-42" in card


# ---------------------------------------------------------------------------
# session_status_tool tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSessionStatusTool:
    """Tests for the session_status @tool_define tool."""

    async def test_returns_status_for_current_conversation(self) -> None:
        conv = _make_conversation()
        conv_repo = AsyncMock()
        conv_repo.find_by_id.return_value = conv
        _configure_repo(conv_repo)
        ctx = _make_ctx()

        result = await session_status_tool.execute(ctx)

        assert not result.is_error
        assert "conv-1" in result.output
        assert "Test Session" in result.output
        assert result.metadata["conversation_id"] == "conv-1"
        assert result.metadata["status"] == "active"
        assert result.metadata["mode"] == "build"
        assert result.metadata["message_count"] == 5

    async def test_returns_status_for_specified_conversation(self) -> None:
        conv = _make_conversation(conv_id="other-conv")
        conv_repo = AsyncMock()
        conv_repo.find_by_id.return_value = conv
        _configure_repo(conv_repo)
        ctx = _make_ctx()

        result = await session_status_tool.execute(ctx, conversation_id="other-conv")

        assert not result.is_error
        assert "other-conv" in result.output
        conv_repo.find_by_id.assert_awaited_once_with("other-conv")

    async def test_error_when_conversation_not_found(self) -> None:
        conv_repo = AsyncMock()
        conv_repo.find_by_id.return_value = None
        _configure_repo(conv_repo)
        ctx = _make_ctx()

        result = await session_status_tool.execute(ctx)

        assert result.is_error
        data = json.loads(result.output)
        assert "not found" in data["error"]

    async def test_error_on_cross_project_access(self) -> None:
        conv = _make_conversation(project_id="other-project")
        conv_repo = AsyncMock()
        conv_repo.find_by_id.return_value = conv
        _configure_repo(conv_repo)
        ctx = _make_ctx(project_id="proj-1")

        result = await session_status_tool.execute(ctx)

        assert result.is_error
        data = json.loads(result.output)
        assert "different project" in data["error"]

    async def test_error_when_no_conversation_id(self) -> None:
        conv_repo = AsyncMock()
        _configure_repo(conv_repo)
        ctx = _make_ctx(conversation_id="")

        result = await session_status_tool.execute(ctx)

        assert result.is_error
        data = json.loads(result.output)
        assert "conversation_id" in data["error"].lower()

    async def test_error_on_repo_exception(self) -> None:
        conv_repo = AsyncMock()
        conv_repo.find_by_id.side_effect = RuntimeError("DB connection lost")
        _configure_repo(conv_repo)
        ctx = _make_ctx()

        result = await session_status_tool.execute(ctx)

        assert result.is_error
        data = json.loads(result.output)
        assert "DB connection lost" in data["error"]

    async def test_defaults_to_current_conversation_id(self) -> None:
        conv = _make_conversation(conv_id="current-conv")
        conv_repo = AsyncMock()
        conv_repo.find_by_id.return_value = conv
        _configure_repo(conv_repo)
        ctx = _make_ctx(conversation_id="current-conv")

        result = await session_status_tool.execute(ctx)

        assert not result.is_error
        conv_repo.find_by_id.assert_awaited_once_with("current-conv")

    async def test_plan_mode_shown(self) -> None:
        conv = _make_conversation(mode=AgentMode.PLAN)
        conv_repo = AsyncMock()
        conv_repo.find_by_id.return_value = conv
        _configure_repo(conv_repo)
        ctx = _make_ctx()

        result = await session_status_tool.execute(ctx)

        assert not result.is_error
        assert "plan" in result.output
        assert result.metadata["mode"] == "plan"

    async def test_skips_project_check_when_no_project_in_ctx(self) -> None:
        """When ctx.project_id is empty, skip cross-project check."""
        conv = _make_conversation(project_id="any-project")
        conv_repo = AsyncMock()
        conv_repo.find_by_id.return_value = conv
        _configure_repo(conv_repo)
        ctx = _make_ctx(project_id="")

        result = await session_status_tool.execute(ctx)

        assert not result.is_error
        assert "any-project" in result.output
