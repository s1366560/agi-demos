"""Unit tests for SandboxMCPToolWrapper.

TDD Phase 1: Write failing tests first (RED).
Tests the sandbox MCP tool wrapper that namespacing and routing.
"""

from unittest.mock import AsyncMock

import pytest

from src.infrastructure.agent.tools.sandbox_tool_wrapper import SandboxMCPToolWrapper


class TestSandboxMCPToolWrapper:
    """Test suite for SandboxMCPToolWrapper."""

    @pytest.fixture
    def mock_adapter(self):
        """Create a mock sandbox adapter."""
        adapter = AsyncMock()
        adapter.call_tool = AsyncMock()
        return adapter

    @pytest.fixture
    def tool_schema(self):
        """Sample MCP tool schema."""
        return {
            "name": "bash",
            "description": "Execute bash commands",
            "input_schema": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Command to execute"
                    }
                },
                "required": ["command"],
            },
        }

    def test_initialization_with_namespacing(self, tool_schema, mock_adapter):
        """Test tool is initialized with original name (no namespace prefix)."""
        wrapper = SandboxMCPToolWrapper(
            sandbox_id="abc123def",
            tool_name="bash",
            tool_schema=tool_schema,
            sandbox_adapter=mock_adapter,
        )

        assert wrapper.name == "bash"
        assert wrapper.sandbox_id == "abc123def"
        assert wrapper.tool_name == "bash"

    def test_initialization_short_sandbox_id(self, tool_schema, mock_adapter):
        """Test with short sandbox ID."""
        wrapper = SandboxMCPToolWrapper(
            sandbox_id="short",
            tool_name="bash",
            tool_schema=tool_schema,
            sandbox_adapter=mock_adapter,
        )

        assert wrapper.name == "bash"

    def test_get_parameters_schema(self, tool_schema, mock_adapter):
        """Test parameters schema conversion from MCP schema."""
        wrapper = SandboxMCPToolWrapper(
            sandbox_id="abc123",
            tool_name="bash",
            tool_schema=tool_schema,
            sandbox_adapter=mock_adapter,
        )

        schema = wrapper.get_parameters_schema()

        assert schema["type"] == "object"
        assert "command" in schema["properties"]
        assert schema["properties"]["command"]["type"] == "string"
        assert "command" in schema["required"]

    def test_get_parameters_schema_with_default(self, mock_adapter):
        """Test parameters schema with default value."""
        tool_schema = {
            "name": "tool_with_default",
            "description": "Tool with default",
            "input_schema": {
                "type": "object",
                "properties": {
                    "timeout": {
                        "type": "integer",
                        "default": 30,
                    }
                },
            },
        }

        wrapper = SandboxMCPToolWrapper(
            sandbox_id="abc123",
            tool_name="tool_with_default",
            tool_schema=tool_schema,
            sandbox_adapter=mock_adapter,
        )

        schema = wrapper.get_parameters_schema()

        assert "timeout" in schema["properties"]
        assert schema["properties"]["timeout"]["default"] == 30
        assert "timeout" not in schema["required"]

    def test_validate_args_with_required_params(self, tool_schema, mock_adapter):
        """Test argument validation with required parameters."""
        wrapper = SandboxMCPToolWrapper(
            sandbox_id="abc123",
            tool_name="bash",
            tool_schema=tool_schema,
            sandbox_adapter=mock_adapter,
        )

        # Valid arguments
        assert wrapper.validate_args(command="ls -la") is True

        # Missing required argument
        assert wrapper.validate_args() is False

    def test_validate_args_no_required(self, mock_adapter):
        """Test argument validation when no required parameters."""
        tool_schema = {
            "name": "optional_tool",
            "description": "Tool with optional params",
            "input_schema": {
                "type": "object",
                "properties": {
                    "optional": {"type": "string"}
                },
            },
        }

        wrapper = SandboxMCPToolWrapper(
            sandbox_id="abc123",
            tool_name="optional_tool",
            tool_schema=tool_schema,
            sandbox_adapter=mock_adapter,
        )

        # Should pass even without arguments
        assert wrapper.validate_args() is True
        assert wrapper.validate_args(optional="value") is True

    @pytest.mark.asyncio
    async def test_execute_success(self, tool_schema, mock_adapter):
        """Test successful tool execution."""
        # Mock successful response
        mock_adapter.call_tool.return_value = {
            "content": [{"text": "file1.txt\nfile2.txt"}],
            "is_error": False,
        }

        wrapper = SandboxMCPToolWrapper(
            sandbox_id="abc123",
            tool_name="bash",
            tool_schema=tool_schema,
            sandbox_adapter=mock_adapter,
        )

        result = await wrapper.execute(command="ls")

        assert "file1.txt" in result
        mock_adapter.call_tool.assert_called_once_with(
            "abc123",
            "bash",
            {"command": "ls"},
        )

    @pytest.mark.asyncio
    async def test_execute_with_error(self, tool_schema, mock_adapter):
        """Test tool execution that returns error."""
        mock_adapter.call_tool.return_value = {
            "content": [{"text": "Command not found"}],
            "is_error": True,
        }

        wrapper = SandboxMCPToolWrapper(
            sandbox_id="abc123",
            tool_name="bash",
            tool_schema=tool_schema,
            sandbox_adapter=mock_adapter,
        )

        with pytest.raises(RuntimeError, match="Tool execution failed"):
            await wrapper.execute(command="xyz")

    @pytest.mark.asyncio
    async def test_execute_empty_content(self, tool_schema, mock_adapter):
        """Test tool execution with empty content."""
        mock_adapter.call_tool.return_value = {
            "content": [],
            "is_error": False,
        }

        wrapper = SandboxMCPToolWrapper(
            sandbox_id="abc123",
            tool_name="bash",
            tool_schema=tool_schema,
            sandbox_adapter=mock_adapter,
        )

        result = await wrapper.execute(command="echo hi")

        assert result == "Success"

    @pytest.mark.asyncio
    async def test_execute_exception(self, tool_schema, mock_adapter):
        """Test tool execution when adapter raises exception."""
        mock_adapter.call_tool.side_effect = Exception("Connection lost")

        wrapper = SandboxMCPToolWrapper(
            sandbox_id="abc123",
            tool_name="bash",
            tool_schema=tool_schema,
            sandbox_adapter=mock_adapter,
        )

        with pytest.raises(RuntimeError, match="Tool execution failed"):
            await wrapper.execute(command="ls")

    def test_tool_schema_none(self, mock_adapter):
        """Test handling of None tool schema."""
        wrapper = SandboxMCPToolWrapper(
            sandbox_id="abc123",
            tool_name="unknown_tool",
            tool_schema={},
            sandbox_adapter=mock_adapter,
        )

        schema = wrapper.get_parameters_schema()
        assert schema["type"] == "object"
        assert schema["properties"] == {}
        assert schema["required"] == []
