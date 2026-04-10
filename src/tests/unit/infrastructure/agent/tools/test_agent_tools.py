"""Tests for A2A (Agent-to-Agent) multi-agent tools."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, Mock

import pytest

from src.domain.model.agent.spawn_mode import SpawnMode
from src.domain.model.agent.spawn_record import SpawnRecord
from src.domain.ports.services.agent_message_bus_port import AgentMessageType
from src.infrastructure.agent.orchestration.orchestrator import SendResult
from src.infrastructure.agent.tools.agent_history import agent_history_tool
from src.infrastructure.agent.tools.agent_list import agent_list_tool
from src.infrastructure.agent.tools.agent_send import agent_send_tool
from src.infrastructure.agent.tools.agent_sessions import agent_sessions_tool
from src.infrastructure.agent.tools.agent_spawn import agent_spawn_tool
from src.infrastructure.agent.tools.agent_stop import agent_stop_tool
from src.infrastructure.agent.tools.context import ToolContext


def _make_ctx(**overrides: Any) -> ToolContext:
    """Create a minimal ToolContext for testing."""
    defaults: dict[str, Any] = {
        "session_id": "session-1",
        "message_id": "msg-1",
        "call_id": "call-1",
        "agent_name": "test-agent",
        "conversation_id": "conv-1",
        "project_id": "proj-1",
        "tenant_id": "tenant-1",
        "user_id": "user-1",
    }
    defaults.update(overrides)
    return ToolContext(**defaults)


@pytest.mark.unit
class TestAgentListTool:
    """Test suite for agent_list tool."""

    def test_tool_name(self) -> None:
        assert agent_list_tool.name == "agent_list"

    def test_tool_category(self) -> None:
        assert agent_list_tool.category == "multi_agent"

    @pytest.mark.asyncio
    async def test_no_orchestrator(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Without orchestrator, returns error."""
        import src.infrastructure.agent.tools.agent_list as mod

        monkeypatch.setattr(mod, "_orchestrator", None)
        ctx = _make_ctx()
        result = await agent_list_tool.execute(ctx)
        data = json.loads(result.output)
        assert result.is_error is True
        assert "Multi-agent not configured" in data["error"]

    @pytest.mark.asyncio
    async def test_happy_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Returns agent list on success."""
        import src.infrastructure.agent.tools.agent_list as mod

        mock_agent = Mock()
        mock_agent.id = "agent-1"
        mock_agent.name = "test-worker"
        mock_agent.display_name = "Test Worker"
        mock_agent.description = "A test agent"
        mock_agent.can_spawn = True
        mock_agent.agent_to_agent_enabled = True
        mock_agent.discoverable = True
        mock_agent.tags = ["worker"]

        orchestrator = Mock()
        orchestrator.list_agents = AsyncMock(return_value=[mock_agent])
        monkeypatch.setattr(mod, "_orchestrator", orchestrator)

        ctx = _make_ctx()
        result = await agent_list_tool.execute(ctx, discoverable_only=True)
        assert result.is_error is False
        data = json.loads(result.output)
        assert len(data) == 1
        assert data[0]["id"] == "agent-1"
        assert data[0]["name"] == "test-worker"
        assert data[0]["can_spawn"] is True

    @pytest.mark.asyncio
    async def test_value_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """ValueError from orchestrator is surfaced."""
        import src.infrastructure.agent.tools.agent_list as mod

        orchestrator = Mock()
        orchestrator.list_agents = AsyncMock(side_effect=ValueError("Test error"))
        monkeypatch.setattr(mod, "_orchestrator", orchestrator)

        ctx = _make_ctx()
        result = await agent_list_tool.execute(ctx)
        assert result.is_error is True
        data = json.loads(result.output)
        assert "Test error" in data["error"]

    @pytest.mark.asyncio
    async def test_unexpected_exception(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Unexpected exception returns internal error."""
        import src.infrastructure.agent.tools.agent_list as mod

        orchestrator = Mock()
        orchestrator.list_agents = AsyncMock(side_effect=RuntimeError("Unexpected"))
        monkeypatch.setattr(mod, "_orchestrator", orchestrator)

        ctx = _make_ctx()
        result = await agent_list_tool.execute(ctx)
        assert result.is_error is True
        data = json.loads(result.output)
        assert "Internal error" in data["error"]


@pytest.mark.unit
class TestAgentSpawnTool:
    """Test suite for agent_spawn tool."""

    def test_tool_name(self) -> None:
        assert agent_spawn_tool.name == "agent_spawn"

    def test_tool_category(self) -> None:
        assert agent_spawn_tool.category == "multi_agent"

    @pytest.mark.asyncio
    async def test_no_orchestrator(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Without orchestrator, returns error."""
        import src.infrastructure.agent.tools.agent_spawn as mod

        monkeypatch.setattr(mod, "_orchestrator", None)
        ctx = _make_ctx()
        result = await agent_spawn_tool.execute(
            ctx, agent_id="target-agent", message="do task", mode="run"
        )
        data = json.loads(result.output)
        assert result.is_error is True
        assert "Multi-agent not configured" in data["error"]

    @pytest.mark.asyncio
    async def test_happy_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Returns spawn info on success."""
        import src.infrastructure.agent.tools.agent_spawn as mod

        mock_record = SpawnRecord(
            parent_agent_id="test-agent",
            child_agent_id="target-agent",
            child_session_id="child-session-1",
            project_id="proj-1",
            mode=SpawnMode.RUN,
            status="running",
        )
        mock_agent = Mock()
        mock_agent.display_name = "Target Agent"
        mock_agent.name = "target-agent"

        mock_result = Mock()
        mock_result.spawn_record = mock_record
        mock_result.agent = mock_agent

        orchestrator = Mock()
        orchestrator.spawn_agent = AsyncMock(return_value=mock_result)
        monkeypatch.setattr(mod, "_orchestrator", orchestrator)

        ctx = _make_ctx()
        result = await agent_spawn_tool.execute(
            ctx, agent_id="target-agent", message="do task", mode="run"
        )
        assert result.is_error is False
        data = json.loads(result.output)
        assert data["agent_id"] == "target-agent"
        assert data["session_id"] == "child-session-1"
        assert data["child_session_id"] == "child-session-1"
        assert data["parent_conversation_id"] == "conv-1"
        assert data["spawn_id"] == mock_record.id
        assert data["run_id"] == mock_record.id
        assert data["trace_id"] == ""
        assert data["task_summary"] == "do task"
        assert data["status"] == "running"
        assert data["mode"] == "run"

    @pytest.mark.asyncio
    async def test_passes_trace_context_from_runtime_context(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """For traced requests, spawn registration receives the parent trace id."""
        import src.infrastructure.agent.tools.agent_spawn as mod

        mock_record = SpawnRecord(
            parent_agent_id="test-agent",
            child_agent_id="target-agent",
            child_session_id="child-session-1",
            project_id="proj-1",
            mode=SpawnMode.RUN,
            status="running",
            trace_id="trace-123",
        )
        mock_agent = Mock()
        mock_agent.display_name = "Target Agent"
        mock_agent.name = "target-agent"

        mock_result = Mock()
        mock_result.spawn_record = mock_record
        mock_result.agent = mock_agent

        orchestrator = Mock()
        orchestrator.spawn_agent = AsyncMock(return_value=mock_result)
        monkeypatch.setattr(mod, "_orchestrator", orchestrator)

        ctx = _make_ctx(
            runtime_context={
                "selected_agent_id": "builtin:sisyphus",
                "trace_id": "trace-123",
                "route_id": "route-456",
            }
        )
        result = await agent_spawn_tool.execute(
            ctx, agent_id="target-agent", message="do task", mode="run"
        )

        assert result.is_error is False
        data = json.loads(result.output)
        assert data["spawn_id"] == mock_record.id
        assert data["run_id"] == mock_record.id
        assert data["trace_id"] == "trace-123"
        assert data["session_id"] == "child-session-1"
        assert data["child_session_id"] == "child-session-1"
        assert data["parent_conversation_id"] == "conv-1"
        orchestrator.spawn_agent.assert_awaited_once_with(
            parent_agent_id="builtin:sisyphus",
            target_agent_id="target-agent",
            message="do task",
            mode=SpawnMode.RUN,
            parent_session_id="session-1",
            project_id="proj-1",
            conversation_id="conv-1",
            tenant_id="tenant-1",
            user_id="user-1",
            trace_id="trace-123",
            span_id="",
        )

    @pytest.mark.asyncio
    async def test_value_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """ValueError from orchestrator is surfaced."""
        import src.infrastructure.agent.tools.agent_spawn as mod

        orchestrator = Mock()
        orchestrator.spawn_agent = AsyncMock(side_effect=ValueError("Test error"))
        monkeypatch.setattr(mod, "_orchestrator", orchestrator)

        ctx = _make_ctx()
        result = await agent_spawn_tool.execute(
            ctx, agent_id="target-agent", message="do task", mode="run"
        )
        assert result.is_error is True
        data = json.loads(result.output)
        assert "Test error" in data["error"]

    @pytest.mark.asyncio
    async def test_unexpected_exception(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Unexpected exception returns internal error."""
        import src.infrastructure.agent.tools.agent_spawn as mod

        orchestrator = Mock()
        orchestrator.spawn_agent = AsyncMock(side_effect=RuntimeError("Unexpected"))
        monkeypatch.setattr(mod, "_orchestrator", orchestrator)

        ctx = _make_ctx()
        result = await agent_spawn_tool.execute(
            ctx, agent_id="target-agent", message="do task", mode="run"
        )
        assert result.is_error is True
        data = json.loads(result.output)
        assert "Internal error" in data["error"]


@pytest.mark.unit
class TestAgentSendTool:
    """Test suite for agent_send tool."""

    def test_tool_name(self) -> None:
        assert agent_send_tool.name == "agent_send"

    def test_tool_category(self) -> None:
        assert agent_send_tool.category == "multi_agent"

    @pytest.mark.asyncio
    async def test_no_orchestrator(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Without orchestrator, returns error."""
        import src.infrastructure.agent.tools.agent_send as mod

        monkeypatch.setattr(mod, "_orchestrator", None)
        ctx = _make_ctx()
        result = await agent_send_tool.execute(ctx, agent_id="target-agent", message="hello")
        data = json.loads(result.output)
        assert result.is_error is True
        assert "Multi-agent not configured" in data["error"]

    @pytest.mark.asyncio
    async def test_happy_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Returns send info on success."""
        import src.infrastructure.agent.tools.agent_send as mod

        send_result = SendResult(
            message_id="msg-001",
            from_agent_id="test-agent",
            to_agent_id="target-agent",
            session_id="sess-1",
        )
        orchestrator = Mock()
        orchestrator.send_message = AsyncMock(return_value=send_result)
        monkeypatch.setattr(mod, "_orchestrator", orchestrator)

        ctx = _make_ctx()
        result = await agent_send_tool.execute(ctx, agent_id="target-agent", message="hello")
        assert result.is_error is False
        data = json.loads(result.output)
        assert data["message_id"] == "msg-001"
        assert data["from_agent_id"] == "test-agent"
        assert data["to_agent_id"] == "target-agent"
        assert data["session_id"] == "sess-1"

    @pytest.mark.asyncio
    async def test_happy_path_prefers_selected_agent_id_from_runtime_context(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Runtime selected_agent_id is forwarded to the orchestrator and event payload."""
        import src.infrastructure.agent.tools.agent_send as mod

        send_result = SendResult(
            message_id="msg-001",
            from_agent_id="agent-123",
            to_agent_id="target-agent",
            session_id="sess-1",
        )
        orchestrator = Mock()
        orchestrator.send_message = AsyncMock(return_value=send_result)
        monkeypatch.setattr(mod, "_orchestrator", orchestrator)

        ctx = _make_ctx(
            agent_name="fallback-name",
            runtime_context={
                "selected_agent_id": "agent-123",
                "selected_agent_name": "selected-name",
            },
        )
        result = await agent_send_tool.execute(ctx, agent_id="target-agent", message="hello")

        assert result.is_error is False
        orchestrator.send_message.assert_awaited_once_with(
            from_agent_id="agent-123",
            to_agent_id="target-agent",
            message="hello",
            session_id=None,
            sender_session_id="session-1",
            project_id="proj-1",
            tenant_id="tenant-1",
        )
        assert ctx._pending_events[0]["data"]["from_agent_id"] == "agent-123"
        assert ctx._pending_events[0]["data"]["from_agent_name"] == "selected-name"

    @pytest.mark.asyncio
    async def test_value_error_does_not_emit_message_sent_event(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Denied sends should not emit a success event."""
        import src.infrastructure.agent.tools.agent_send as mod
        from src.infrastructure.agent.orchestration.send_denied import (
            SendDenied,
            SendDeniedCode,
        )

        orchestrator = Mock()
        # Orchestrator now returns SendDenied instead of raising ValueError.
        orchestrator.send_message = AsyncMock(
            return_value=SendDenied(
                ok=False,
                code=SendDeniedCode.TARGET_NOT_ALLOWED,
                message="not allowed",
                from_agent_ref="agent-123",
                to_agent_ref="target-agent",
                resolved_from_agent_id="agent-123",
                resolved_to_agent_id=None,
                sender_session_id="session-1",
                target_session_id=None,
                project_id="proj-1",
                tenant_id="tenant-1",
                allowlist=["allowed-sender"],
            )
        )
        monkeypatch.setattr(mod, "_orchestrator", orchestrator)

        ctx = _make_ctx(runtime_context={"selected_agent_id": "agent-123"})
        result = await agent_send_tool.execute(ctx, agent_id="target-agent", message="hello")

        assert result.is_error is True
        data = json.loads(result.output)
        assert data["ok"] is False
        assert data["code"] == "target_not_allowed"
        assert ctx._pending_events == []

    @pytest.mark.asyncio
    async def test_value_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """ValueError from orchestrator surfaces as structured denial."""
        import src.infrastructure.agent.tools.agent_send as mod
        from src.infrastructure.agent.orchestration.send_denied import (
            SendDenied,
            SendDeniedCode,
        )

        orchestrator = Mock()
        # Orchestrator catches ValueError and returns SendDenied.
        orchestrator.send_message = AsyncMock(
            return_value=SendDenied(
                ok=False,
                code=SendDeniedCode.SENDER_NOT_FOUND,
                message="Test error",
                from_agent_ref="test-agent",
                to_agent_ref="target-agent",
                resolved_from_agent_id=None,
                resolved_to_agent_id=None,
                sender_session_id="session-1",
                target_session_id=None,
                project_id="proj-1",
                tenant_id="tenant-1",
                allowlist=None,
            )
        )
        monkeypatch.setattr(mod, "_orchestrator", orchestrator)

        ctx = _make_ctx()
        result = await agent_send_tool.execute(ctx, agent_id="target-agent", message="hello")
        assert result.is_error is True
        data = json.loads(result.output)
        assert data["ok"] is False
        assert data["code"] == "sender_not_found"
        assert "Test error" in data["message"]
        assert data["allowlist"] is None

    @pytest.mark.asyncio
    async def test_unexpected_exception(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Unexpected exception returns internal error."""
        import src.infrastructure.agent.tools.agent_send as mod

        orchestrator = Mock()
        orchestrator.send_message = AsyncMock(side_effect=RuntimeError("Unexpected"))
        monkeypatch.setattr(mod, "_orchestrator", orchestrator)

        ctx = _make_ctx()
        result = await agent_send_tool.execute(ctx, agent_id="target-agent", message="hello")
        assert result.is_error is True
        data = json.loads(result.output)
        assert "Internal error" in data["error"]


@pytest.mark.unit
class TestAgentHistoryTool:
    """Test suite for agent_history tool."""

    def test_tool_name(self) -> None:
        assert agent_history_tool.name == "agent_history"

    def test_tool_category(self) -> None:
        assert agent_history_tool.category == "multi_agent"

    @pytest.mark.asyncio
    async def test_no_orchestrator(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Without orchestrator, returns error."""
        import src.infrastructure.agent.tools.agent_history as mod

        monkeypatch.setattr(mod, "_orchestrator", None)
        ctx = _make_ctx()
        result = await agent_history_tool.execute(ctx, session_id="sess-1")
        data = json.loads(result.output)
        assert result.is_error is True
        assert "Multi-agent not configured" in data["error"]

    @pytest.mark.asyncio
    async def test_happy_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Returns message history on success."""
        import src.infrastructure.agent.tools.agent_history as mod

        mock_msg = Mock()
        mock_msg.message_id = "msg-1"
        mock_msg.from_agent_id = "agent-a"
        mock_msg.to_agent_id = "agent-b"
        mock_msg.content = "hello"
        mock_msg.message_type = AgentMessageType.REQUEST
        mock_msg.timestamp = datetime(2026, 1, 1, tzinfo=UTC)

        orchestrator = Mock()
        orchestrator.get_agent_history = AsyncMock(return_value=[mock_msg])
        monkeypatch.setattr(mod, "_orchestrator", orchestrator)

        ctx = _make_ctx()
        result = await agent_history_tool.execute(ctx, session_id="sess-1")
        assert result.is_error is False
        data = json.loads(result.output)
        assert len(data) == 1
        assert data[0]["id"] == "msg-1"
        assert data[0]["from_agent_id"] == "agent-a"
        assert data[0]["message_type"] == "request"
        assert data[0]["timestamp"] == "2026-01-01T00:00:00+00:00"

    @pytest.mark.asyncio
    async def test_value_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """ValueError from orchestrator is surfaced."""
        import src.infrastructure.agent.tools.agent_history as mod

        orchestrator = Mock()
        orchestrator.get_agent_history = AsyncMock(side_effect=ValueError("Test error"))
        monkeypatch.setattr(mod, "_orchestrator", orchestrator)

        ctx = _make_ctx()
        result = await agent_history_tool.execute(ctx, session_id="sess-1")
        assert result.is_error is True
        data = json.loads(result.output)
        assert "Test error" in data["error"]

    @pytest.mark.asyncio
    async def test_unexpected_exception(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Unexpected exception returns internal error."""
        import src.infrastructure.agent.tools.agent_history as mod

        orchestrator = Mock()
        orchestrator.get_agent_history = AsyncMock(side_effect=RuntimeError("Unexpected"))
        monkeypatch.setattr(mod, "_orchestrator", orchestrator)

        ctx = _make_ctx()
        result = await agent_history_tool.execute(ctx, session_id="sess-1")
        assert result.is_error is True
        data = json.loads(result.output)
        assert "Internal error" in data["error"]


@pytest.mark.unit
class TestAgentStopTool:
    """Test suite for agent_stop tool."""

    def test_tool_name(self) -> None:
        assert agent_stop_tool.name == "agent_stop"

    def test_tool_category(self) -> None:
        assert agent_stop_tool.category == "multi_agent"

    @pytest.mark.asyncio
    async def test_no_orchestrator(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Without orchestrator, returns error."""
        import src.infrastructure.agent.tools.agent_stop as mod

        monkeypatch.setattr(mod, "_orchestrator", None)
        ctx = _make_ctx()
        result = await agent_stop_tool.execute(ctx, session_id="sess-1")
        data = json.loads(result.output)
        assert result.is_error is True
        assert "Multi-agent not configured" in data["error"]

    @pytest.mark.asyncio
    async def test_happy_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Returns stopped sessions on success."""
        import src.infrastructure.agent.tools.agent_stop as mod

        orchestrator = Mock()
        orchestrator.stop_agent = AsyncMock(return_value=["sess-1", "sess-2"])
        monkeypatch.setattr(mod, "_orchestrator", orchestrator)

        ctx = _make_ctx()
        result = await agent_stop_tool.execute(ctx, session_id="sess-1")
        assert result.is_error is False
        data = json.loads(result.output)
        assert data["stopped_sessions"] == ["sess-1", "sess-2"]
        assert data["count"] == 2

    @pytest.mark.asyncio
    async def test_value_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """ValueError from orchestrator is surfaced."""
        import src.infrastructure.agent.tools.agent_stop as mod

        orchestrator = Mock()
        orchestrator.stop_agent = AsyncMock(side_effect=ValueError("Test error"))
        monkeypatch.setattr(mod, "_orchestrator", orchestrator)

        ctx = _make_ctx()
        result = await agent_stop_tool.execute(ctx, session_id="sess-1")
        assert result.is_error is True
        data = json.loads(result.output)
        assert "Test error" in data["error"]

    @pytest.mark.asyncio
    async def test_unexpected_exception(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Unexpected exception returns internal error."""
        import src.infrastructure.agent.tools.agent_stop as mod

        orchestrator = Mock()
        orchestrator.stop_agent = AsyncMock(side_effect=RuntimeError("Unexpected"))
        monkeypatch.setattr(mod, "_orchestrator", orchestrator)

        ctx = _make_ctx()
        result = await agent_stop_tool.execute(ctx, session_id="sess-1")
        assert result.is_error is True
        data = json.loads(result.output)
        assert "Internal error" in data["error"]


@pytest.mark.unit
class TestAgentSessionsTool:
    """Test suite for agent_sessions tool."""

    def test_tool_name(self) -> None:
        assert agent_sessions_tool.name == "agent_sessions"

    def test_tool_category(self) -> None:
        assert agent_sessions_tool.category == "multi_agent"

    @pytest.mark.asyncio
    async def test_no_orchestrator(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Without orchestrator, returns error."""
        import src.infrastructure.agent.tools.agent_sessions as mod

        monkeypatch.setattr(mod, "_orchestrator", None)
        ctx = _make_ctx()
        result = await agent_sessions_tool.execute(ctx)
        data = json.loads(result.output)
        assert result.is_error is True
        assert "Multi-agent not configured" in data["error"]

    @pytest.mark.asyncio
    async def test_happy_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Returns session records on success."""
        import src.infrastructure.agent.tools.agent_sessions as mod

        record = SpawnRecord(
            parent_agent_id="test-agent",
            child_agent_id="child-1",
            child_session_id="child-sess-1",
            project_id="proj-1",
            mode=SpawnMode.RUN,
            task_summary="do something",
            status="running",
        )
        orchestrator = Mock()
        orchestrator.get_agent_sessions = AsyncMock(return_value=[record])
        monkeypatch.setattr(mod, "_orchestrator", orchestrator)

        ctx = _make_ctx()
        result = await agent_sessions_tool.execute(ctx)
        assert result.is_error is False
        data = json.loads(result.output)
        assert len(data) == 1
        assert data[0]["child_session_id"] == "child-sess-1"
        assert data[0]["child_agent_id"] == "child-1"
        assert data[0]["status"] == "running"
        assert data[0]["mode"] == "run"
        assert data[0]["task_summary"] == "do something"

    @pytest.mark.asyncio
    async def test_happy_path_preserves_unicode_output(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Unicode task summaries should stay readable in raw JSON output."""
        import src.infrastructure.agent.tools.agent_sessions as mod

        record = SpawnRecord(
            parent_agent_id="test-agent",
            child_agent_id="child-1",
            child_session_id="child-sess-1",
            project_id="proj-1",
            mode=SpawnMode.RUN,
            task_summary="分析 🔥",
            status="running",
        )
        orchestrator = Mock()
        orchestrator.get_agent_sessions = AsyncMock(return_value=[record])
        monkeypatch.setattr(mod, "_orchestrator", orchestrator)

        result = await agent_sessions_tool.execute(_make_ctx())

        assert result.is_error is False
        assert "分析 🔥" in result.output
        assert "\\u5206" not in result.output

    @pytest.mark.asyncio
    async def test_value_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """ValueError from orchestrator is surfaced."""
        import src.infrastructure.agent.tools.agent_sessions as mod

        orchestrator = Mock()
        orchestrator.get_agent_sessions = AsyncMock(side_effect=ValueError("Test error"))
        monkeypatch.setattr(mod, "_orchestrator", orchestrator)

        ctx = _make_ctx()
        result = await agent_sessions_tool.execute(ctx)
        assert result.is_error is True
        data = json.loads(result.output)
        assert "Test error" in data["error"]

    @pytest.mark.asyncio
    async def test_unexpected_exception(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Unexpected exception returns internal error."""
        import src.infrastructure.agent.tools.agent_sessions as mod

        orchestrator = Mock()
        orchestrator.get_agent_sessions = AsyncMock(side_effect=RuntimeError("Unexpected"))
        monkeypatch.setattr(mod, "_orchestrator", orchestrator)

        ctx = _make_ctx()
        result = await agent_sessions_tool.execute(ctx)
        assert result.is_error is True
        data = json.loads(result.output)
        assert "Internal error" in data["error"]
