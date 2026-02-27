"""Unit tests for SandboxMCPToolWrapper.

TDD Phase 1: Write failing tests first (RED).
Tests the sandbox MCP tool wrapper that handles tool schema conversion
"""

from unittest.mock import AsyncMock

import pytest

from src.infrastructure.agent.tools.sandbox_tool_wrapper import (
    SandboxMCPToolWrapper,
    _convert_mcp_schema,
)


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
                "properties": {"command": {"type": "string", "description": "Command to execute"}},
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
                "properties": {"optional": {"type": "string"}},
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

    def test_get_parameters_schema_preserves_array_items(
        self, mock_adapter
    ):
        """Test schema with array property preserves nested items schema.

        Verifies that array properties with complex item schemas
        (e.g. batch_edit's edits field) preserve the full items definition.
        """
        tool_schema = {
            "name": "batch_edit",
            "description": "Batch edit files",
            "input_schema": {
                "type": "object",
                "properties": {
                    "edits": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "file_path": {"type": "string"},
                                "content": {"type": "string"},
                            },
                            "required": ["file_path"],
                        },
                    }
                },
                "required": ["edits"],
            },
        }

        wrapper = SandboxMCPToolWrapper(
            sandbox_id="abc123",
            tool_name="batch_edit",
            tool_schema=tool_schema,
            sandbox_adapter=mock_adapter,
        )

        schema = wrapper.get_parameters_schema()

        # Verify array items structure is preserved
        assert "edits" in schema["properties"]
        edits_prop = schema["properties"]["edits"]
        assert edits_prop["type"] == "array"
        assert "items" in edits_prop
        assert edits_prop["items"]["type"] == "object"
        assert "file_path" in edits_prop["items"]["properties"]
        assert (
            edits_prop["items"]["properties"]["file_path"]["type"] == "string"
        )
        assert edits_prop["items"]["required"] == ["file_path"]

    def test_get_parameters_schema_preserves_nested_objects(
        self, mock_adapter
    ):
        """Test schema with nested object properties are fully preserved."""
        tool_schema = {
            "name": "test_nested",
            "description": "Test nested objects",
            "input_schema": {
                "type": "object",
                "properties": {
                    "config": {
                        "type": "object",
                        "properties": {
                            "timeout": {"type": "integer"},
                            "retries": {"type": "integer"},
                        },
                        "required": ["timeout"],
                    }
                },
                "required": ["config"],
            },
        }

        wrapper = SandboxMCPToolWrapper(
            sandbox_id="abc123",
            tool_name="test_nested",
            tool_schema=tool_schema,
            sandbox_adapter=mock_adapter,
        )

        schema = wrapper.get_parameters_schema()

        # Verify nested properties and required are preserved
        assert "config" in schema["properties"]
        config_prop = schema["properties"]["config"]
        assert config_prop["type"] == "object"
        assert "timeout" in config_prop["properties"]
        assert "retries" in config_prop["properties"]
        assert config_prop["required"] == ["timeout"]

    def test_get_parameters_schema_preserves_enum(self, mock_adapter):
        """Test schema with enum values is fully preserved."""
        tool_schema = {
            "name": "test_enum",
            "description": "Test enum property",
            "input_schema": {
                "type": "object",
                "properties": {
                    "mode": {
                        "type": "string",
                        "enum": ["read", "write", "append"],
                        "description": "File mode",
                    }
                },
                "required": ["mode"],
            },
        }

        wrapper = SandboxMCPToolWrapper(
            sandbox_id="abc123",
            tool_name="test_enum",
            tool_schema=tool_schema,
            sandbox_adapter=mock_adapter,
        )

        schema = wrapper.get_parameters_schema()

        # Verify enum is preserved
        assert "mode" in schema["properties"]
        mode_prop = schema["properties"]["mode"]
        assert mode_prop["type"] == "string"
        assert "enum" in mode_prop
        assert mode_prop["enum"] == ["read", "write", "append"]
        assert mode_prop["description"] == "File mode"


@pytest.mark.unit
class TestConvertMcpSchema:
    """Test suite for _convert_mcp_schema function."""

    def test_convert_preserves_full_schema(self):
        """Test that conversion preserves the full JSON Schema structure."""
        input_schema = {
            "type": "object",
            "properties": {"command": {"type": "string"}},
            "required": ["command"],
        }

        result = _convert_mcp_schema(input_schema)

        assert result["type"] == "object"
        assert "command" in result["properties"]
        assert result["required"] == ["command"]

    def test_convert_batch_edit_schema(self):
        """Test conversion with exact batch_edit schema structure.

        Verifies that the full edits array schema with nested object items
        is preserved through conversion.
        """
        input_schema = {
            "type": "object",
            "properties": {
                "edits": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "file_path": {"type": "string"},
                            "old_string": {"type": "string"},
                            "new_string": {"type": "string"},
                            "replace_all": {"type": "boolean", "default": False},
                        },
                        "required": [
                            "file_path",
                            "old_string",
                            "new_string",
                        ],
                    },
                }
            },
            "required": ["edits"],
        }

        result = _convert_mcp_schema(input_schema)

        # Verify top-level structure
        assert result["type"] == "object"
        assert "edits" in result["properties"]
        assert "edits" in result["required"]

        # Verify array items structure is fully preserved
        edits_prop = result["properties"]["edits"]
        assert edits_prop["type"] == "array"
        assert "items" in edits_prop
        assert edits_prop["items"]["type"] == "object"

        # Verify nested properties
        items_props = edits_prop["items"]["properties"]
        assert "file_path" in items_props
        assert "old_string" in items_props
        assert "new_string" in items_props
        assert "replace_all" in items_props
        assert items_props["replace_all"]["default"] is False

        # Verify required fields in items
        assert "file_path" in edits_prop["items"]["required"]
        assert "old_string" in edits_prop["items"]["required"]
        assert "new_string" in edits_prop["items"]["required"]

    def test_convert_empty_schema(self):
        """Test conversion of empty schema dict."""
        input_schema = {}

        result = _convert_mcp_schema(input_schema)

        assert result["type"] == "object"
        assert result["properties"] == {}
        assert result["required"] == []

    def test_convert_preserves_anyof(self):
        """Test that conversion preserves anyOf in schema properties."""
        input_schema = {
            "type": "object",
            "properties": {
                "value": {
                    "anyOf": [
                        {"type": "string"},
                        {"type": "integer"},
                    ]
                }
            },
        }

        result = _convert_mcp_schema(input_schema)

        # Verify anyOf structure is preserved in properties
        assert "value" in result["properties"]
        assert "anyOf" in result["properties"]["value"]
        assert len(result["properties"]["value"]["anyOf"]) == 2
        assert result["properties"]["value"]["anyOf"][0]["type"] == "string"
        assert result["properties"]["value"]["anyOf"][1]["type"] == "integer"
