"""Tests for todo tools (@tool_define version).

Tests for todoread and todowrite tools. Without a real DB session factory,
the tools return graceful errors. We test metadata, parameter schemas, and
error handling.

Note: session_id comes from ToolContext, not as a kwarg.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.todo_tools import (
    todoread_tool,
    todowrite_tool,
)


def _make_ctx(**overrides: Any) -> ToolContext:
    """Create a minimal ToolContext for testing."""
    defaults: dict[str, Any] = {
        "session_id": "session-1",
        "message_id": "msg-1",
        "call_id": "call-1",
        "agent_name": "test-agent",
        "conversation_id": "conv-1",
    }
    defaults.update(overrides)
    return ToolContext(**defaults)


class TestTodoReadTool:
    """Test suite for todoread tool (@tool_define)."""

    @pytest.mark.asyncio
    async def test_read_without_session_factory(self) -> None:
        """Without session_factory, returns error."""
        ctx = _make_ctx()
        result = await todoread_tool.execute(ctx)
        data = json.loads(result.output)
        assert "error" in data
        assert data["todos"] == []
        assert result.is_error is True

    def test_tool_name(self) -> None:
        assert todoread_tool.name == "todoread"

    def test_parameters_schema_no_session_id(self) -> None:
        """session_id is injected by processor via ToolContext, not exposed in LLM schema."""
        schema = todoread_tool.parameters
        assert "session_id" not in schema["properties"]
        assert "status" in schema["properties"]

    def test_valid_status_enum_in_schema(self) -> None:
        """Status parameter should list valid enum values."""
        schema = todoread_tool.parameters
        status_prop = schema["properties"]["status"]
        assert "enum" in status_prop
        assert "pending" in status_prop["enum"]
        assert "in_progress" in status_prop["enum"]

    @pytest.mark.asyncio
    async def test_read_uses_conversation_id_scope(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Read path should query tasks by conversation scope, not ephemeral session scope."""
        import src.infrastructure.agent.tools.todo_tools as todo_tools_module

        captured: dict[str, Any] = {}

        class _DummySession:
            async def __aenter__(self) -> _DummySession:
                return self

            async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
                return False

            async def commit(self) -> None:
                return None

        class _FakeRepo:
            def __init__(self, session: Any) -> None:
                _ = session

            async def find_by_conversation(
                self, conversation_id: str, status: str | None = None
            ) -> list[Any]:
                captured["conversation_id"] = conversation_id
                captured["status"] = status
                return []

        monkeypatch.setattr(
            todo_tools_module,
            "_todoread_session_factory",
            lambda: _DummySession(),
        )
        monkeypatch.setattr(
            "src.infrastructure.adapters.secondary.persistence.sql_agent_task_repository."
            "SqlAgentTaskRepository",
            _FakeRepo,
        )

        ctx = _make_ctx(session_id="session-ephemeral", conversation_id="conv-persisted")
        result = await todoread_tool.execute(ctx)

        assert result.is_error is False
        assert captured["conversation_id"] == "conv-persisted"


class TestTodoWriteTool:
    """Test suite for todowrite tool (@tool_define)."""

    @pytest.mark.asyncio
    async def test_write_without_session_factory(self) -> None:
        """Without session_factory, returns error."""
        ctx = _make_ctx()
        result = await todowrite_tool.execute(ctx, action="replace", todos=[])
        data = json.loads(result.output)
        assert "error" in data
        assert result.is_error is True

    def test_tool_name(self) -> None:
        assert todowrite_tool.name == "todowrite"

    def test_parameters_schema_no_session_id(self) -> None:
        """session_id is injected by processor via ToolContext, not exposed in LLM schema."""
        schema = todowrite_tool.parameters
        assert "session_id" not in schema["properties"]
        assert "action" in schema["properties"]
        assert "todos" in schema["properties"]

    def test_action_enum_in_schema(self) -> None:
        """Action parameter should list valid enum values."""
        schema = todowrite_tool.parameters
        action_prop = schema["properties"]["action"]
        assert "enum" in action_prop
        assert "replace" in action_prop["enum"]
        assert "add" in action_prop["enum"]
        assert "update" in action_prop["enum"]

    def test_consume_pending_events_via_context(self) -> None:
        """Events are consumed from ToolContext, not from the tool itself."""
        ctx = _make_ctx()
        events = ctx.consume_pending_events()
        assert events == []

    @pytest.mark.asyncio
    async def test_write_uses_conversation_id_scope(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Write path should persist tasks under conversation scope, not ephemeral session scope."""
        import src.infrastructure.agent.tools.todo_tools as todo_tools_module

        captured: dict[str, Any] = {}

        class _DummySession:
            async def __aenter__(self) -> _DummySession:
                return self

            async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
                return False

            async def commit(self) -> None:
                return None

        class _FakeRepo:
            def __init__(self, session: Any) -> None:
                _ = session

            async def save_all(self, conversation_id: str, tasks: list[Any]) -> None:
                captured["conversation_id"] = conversation_id
                captured["task_count"] = len(tasks)

        monkeypatch.setattr(
            todo_tools_module,
            "_todowrite_session_factory",
            lambda: _DummySession(),
        )
        monkeypatch.setattr(
            "src.infrastructure.adapters.secondary.persistence.sql_agent_task_repository."
            "SqlAgentTaskRepository",
            _FakeRepo,
        )

        ctx = _make_ctx(session_id="session-ephemeral", conversation_id="conv-persisted")
        result = await todowrite_tool.execute(
            ctx,
            action="replace",
            todos=[{"content": "Task A", "status": "pending", "priority": "high"}],
        )

        assert result.is_error is False
        assert captured["task_count"] == 1
        assert captured["conversation_id"] == "conv-persisted"

    @pytest.mark.asyncio
    async def test_update_rejects_task_from_other_conversation(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Update should not modify a task outside current conversation scope."""
        import src.infrastructure.agent.tools.todo_tools as todo_tools_module

        captured: dict[str, Any] = {"update_called": False}

        class _DummySession:
            async def __aenter__(self) -> _DummySession:
                return self

            async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
                return False

            async def commit(self) -> None:
                return None

        class _FakeRepo:
            def __init__(self, session: Any) -> None:
                _ = session

            async def find_by_id(self, task_id: str) -> Any:
                _ = task_id
                return type("Task", (), {"conversation_id": "another-conversation"})()

            async def update(self, task_id: str, **updates: Any) -> Any:
                _ = task_id
                _ = updates
                captured["update_called"] = True
                return None

        monkeypatch.setattr(
            todo_tools_module,
            "_todowrite_session_factory",
            lambda: _DummySession(),
        )
        monkeypatch.setattr(
            "src.infrastructure.adapters.secondary.persistence.sql_agent_task_repository."
            "SqlAgentTaskRepository",
            _FakeRepo,
        )

        ctx = _make_ctx(session_id="session-ephemeral", conversation_id="conv-persisted")
        result = await todowrite_tool.execute(
            ctx,
            action="update",
            todo_id="task-1",
            todos=[{"status": "completed"}],
        )
        data = json.loads(result.output)

        assert data["success"] is False
        assert "not found" in data["message"].lower()
        assert captured["update_called"] is False
