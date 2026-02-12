"""Tests for todo tools (DB-persistent).

Tests for todoread and todowrite tools. Without a real DB session factory,
the tools return graceful errors. We test validation and argument handling.
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
        assert tool.validate_args(session_id="test-session") is True
        assert tool.validate_args(session_id="test", status="pending") is True

    def test_validate_args_invalid_session_id(self, tool):
        assert tool.validate_args(session_id="") is False
        assert tool.validate_args(session_id=None) is False

    def test_validate_args_invalid_status(self, tool):
        assert tool.validate_args(session_id="test", status="invalid") is False

    def test_tool_name(self, tool):
        assert tool.name == "todoread"

    def test_parameters_schema(self, tool):
        schema = tool.get_parameters_schema()
        assert "session_id" in schema["properties"]
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
        assert tool.validate_args(session_id="test", action="replace") is True
        assert tool.validate_args(session_id="test", action="add") is True
        assert tool.validate_args(session_id="test", action="update", todo_id="1") is True

    def test_validate_args_invalid_session_id(self, tool):
        assert tool.validate_args(session_id="", action="replace") is False

    def test_validate_args_invalid_action(self, tool):
        assert tool.validate_args(session_id="test", action="invalid") is False

    def test_validate_args_update_without_todo_id(self, tool):
        assert tool.validate_args(session_id="test", action="update") is False

    def test_tool_name(self, tool):
        assert tool.name == "todowrite"

    def test_parameters_schema(self, tool):
        schema = tool.get_parameters_schema()
        assert "session_id" in schema["properties"]
        assert "action" in schema["properties"]
        assert "todos" in schema["properties"]

    def test_consume_pending_events_empty(self, tool):
        """No events before execute."""
        events = tool.consume_pending_events()
        assert events == []
