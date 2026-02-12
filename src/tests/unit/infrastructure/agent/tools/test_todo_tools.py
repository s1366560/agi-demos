"""Tests for todo tools (DB-persistent).

Tests for todoread and todowrite tools. Without a real DB session factory,
the tools return graceful errors. We test validation and argument handling.

Note: session_id is injected by the processor at execution time, not by the LLM.
The tool schemas do not expose session_id to the LLM.
"""

import json

import pytest

from src.infrastructure.agent.tools.todo_tools import (
    TodoReadTool,
    TodoWriteTool,
)


class TestTodoReadTool:
    """Test suite for TodoReadTool."""

    @pytest.fixture
    def tool(self):
        """Provide a TodoReadTool instance (no DB)."""
        return TodoReadTool()

    @pytest.mark.asyncio
    async def test_read_without_session_factory(self, tool):
        """Without session_factory, returns error."""
        result = await tool.execute(session_id="session-1")
        data = json.loads(result)
        assert "error" in data
        assert data["todos"] == []

    def test_validate_args_valid(self, tool):
        assert tool.validate_args() is True
        assert tool.validate_args(status="pending") is True

    def test_validate_args_invalid_status(self, tool):
        assert tool.validate_args(status="invalid") is False

    def test_tool_name(self, tool):
        assert tool.name == "todoread"

    def test_parameters_schema_no_session_id(self, tool):
        """session_id is injected by processor, not exposed in LLM schema."""
        schema = tool.get_parameters_schema()
        assert "session_id" not in schema["properties"]
        assert "status" in schema["properties"]


class TestTodoWriteTool:
    """Test suite for TodoWriteTool."""

    @pytest.fixture
    def tool(self):
        """Provide a TodoWriteTool instance (no DB)."""
        return TodoWriteTool()

    @pytest.mark.asyncio
    async def test_write_without_session_factory(self, tool):
        """Without session_factory, returns error."""
        result = await tool.execute(session_id="s1", action="replace", todos=[])
        data = json.loads(result)
        assert "error" in data

    def test_validate_args_valid(self, tool):
        assert tool.validate_args(action="replace") is True
        assert tool.validate_args(action="add") is True
        assert tool.validate_args(action="update", todo_id="1") is True

    def test_validate_args_invalid_action(self, tool):
        assert tool.validate_args(action="invalid") is False

    def test_validate_args_update_without_todo_id(self, tool):
        assert tool.validate_args(action="update") is False

    def test_tool_name(self, tool):
        assert tool.name == "todowrite"

    def test_parameters_schema_no_session_id(self, tool):
        """session_id is injected by processor, not exposed in LLM schema."""
        schema = tool.get_parameters_schema()
        assert "session_id" not in schema["properties"]
        assert "action" in schema["properties"]
        assert "todos" in schema["properties"]

    def test_consume_pending_events_empty(self, tool):
        """No events before execute."""
        events = tool.consume_pending_events()
        assert events == []
