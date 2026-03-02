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
