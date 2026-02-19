"""Unit tests for tool_converter module."""

import pytest
from unittest.mock import MagicMock, AsyncMock
from typing import Any, Dict

from src.infrastructure.agent.core.tool_converter import convert_tools
from src.infrastructure.agent.core.processor import ToolDefinition


class MockTool:
    """Mock tool for testing."""

    def __init__(
        self,
        name: str = "test_tool",
        description: str = "A test tool",
        is_model_visible: bool = True,
        permission: str = None,
    ):
        self._name = name
        self.description = description
        self.permission = permission
        self._is_model_visible = is_model_visible
        self._tool_schema = MagicMock()
        self._tool_schema.is_model_visible = is_model_visible

    def execute(self, **kwargs):
        """Execute the tool."""
        return f"Executed with {kwargs}"

    def get_parameters_schema(self):
        """Get parameters schema."""
        return {
            "type": "object",
            "properties": {
                "input": {"type": "string", "description": "Input value"},
            },
            "required": ["input"],
        }


class AsyncMockTool:
    """Mock async tool for testing."""

    def __init__(self, name: str = "async_tool"):
        self._name = name
        self.description = "An async tool"
        self._tool_schema = MagicMock()
        self._tool_schema.is_model_visible = True

    async def execute(self, **kwargs):
        """Async execute the tool."""
        return f"Async executed with {kwargs}"


class AppOnlyTool:
    """Mock app-only tool (not visible to model)."""

    def __init__(self):
        self.description = "App only tool"
        self._tool_schema = MagicMock()
        self._tool_schema.is_model_visible = False

    def execute(self, **kwargs):
        return "Should not be called"


class ToolWithSchemaDict:
    """Tool with raw schema dict."""

    def __init__(self, visibility: list):
        self.description = "Tool with schema dict"
        self._schema = {
            "_meta": {
                "ui": {
                    "visibility": visibility
                }
            }
        }

    def execute(self, **kwargs):
        return "Executed"


@pytest.fixture
def basic_tools():
    """Create basic tools dict for testing."""
    return {
        "test_tool": MockTool(),
    }


@pytest.fixture
def mixed_tools():
    """Create tools with mixed visibility."""
    return {
        "model_tool": MockTool(name="model_tool", is_model_visible=True),
        "app_only_tool": AppOnlyTool(),
    }


class TestToolConverter:
    """Tests for tool_converter module."""

    @pytest.mark.unit
    def test_convert_tools_basic(self, basic_tools):
        """Test basic tool conversion."""
        definitions = convert_tools(basic_tools)

        assert len(definitions) == 1
        assert definitions[0].name == "test_tool"
        assert definitions[0].description == "A test tool"

    @pytest.mark.unit
    def test_convert_tools_filters_app_only(self, mixed_tools):
        """Test app-only tools are filtered out."""
        definitions = convert_tools(mixed_tools)

        assert len(definitions) == 1
        assert definitions[0].name == "model_tool"

    @pytest.mark.unit
    def test_convert_tools_empty_dict(self):
        """Test empty tools dict returns empty list."""
        definitions = convert_tools({})

        assert definitions == []

    @pytest.mark.unit
    def test_convert_tools_extracts_parameters_schema(self, basic_tools):
        """Test parameters schema is extracted."""
        definitions = convert_tools(basic_tools)

        assert definitions[0].parameters is not None
        assert "properties" in definitions[0].parameters
        assert "input" in definitions[0].parameters["properties"]

    @pytest.mark.unit
    def test_convert_tools_extracts_permission(self):
        """Test permission is extracted."""
        tools = {
            "restricted_tool": MockTool(permission="user:write"),
        }

        definitions = convert_tools(tools)

        assert definitions[0].permission == "user:write"

    @pytest.mark.unit
    def test_convert_tools_stores_original_instance(self, basic_tools):
        """Test original tool instance is stored."""
        definitions = convert_tools(basic_tools)

        assert hasattr(definitions[0], "_tool_instance")
        assert definitions[0]._tool_instance is basic_tools["test_tool"]

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_execute_wrapper_handles_sync(self, basic_tools):
        """Test execute wrapper handles sync tools."""
        definitions = convert_tools(basic_tools)

        result = await definitions[0].execute(input="test")

        assert result == "Executed with {'input': 'test'}"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_execute_wrapper_handles_async(self):
        """Test execute wrapper handles async tools."""
        tools = {
            "async_tool": AsyncMockTool(),
        }

        definitions = convert_tools(tools)

        result = await definitions[0].execute(input="test")

        assert result == "Async executed with {'input': 'test'}"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_execute_wrapper_handles_error(self):
        """Test execute wrapper handles errors gracefully."""
        class ErrorTool:
            description = "Error tool"
            _tool_schema = MagicMock()
            _tool_schema.is_model_visible = True

            def execute(self, **kwargs):
                raise ValueError("Tool error")

        tools = {"error_tool": ErrorTool()}
        definitions = convert_tools(tools)

        result = await definitions[0].execute(input="test")

        assert "Error executing tool error_tool" in result
        assert "Tool error" in result

    @pytest.mark.unit
    def test_convert_tools_schema_dict_visibility_model(self):
        """Test schema dict with model visibility is included."""
        tools = {
            "visible_tool": ToolWithSchemaDict(visibility=["model", "app"]),
        }

        definitions = convert_tools(tools)

        assert len(definitions) == 1

    @pytest.mark.unit
    def test_convert_tools_schema_dict_visibility_app_only(self):
        """Test schema dict with app-only visibility is excluded."""
        tools = {
            "hidden_tool": ToolWithSchemaDict(visibility=["app"]),
        }

        definitions = convert_tools(tools)

        assert len(definitions) == 0

    @pytest.mark.unit
    def test_convert_tools_default_description(self):
        """Test default description when tool has none."""
        class NoDescTool:
            _tool_schema = MagicMock()
            _tool_schema.is_model_visible = True

        tools = {"nodesc_tool": NoDescTool()}
        definitions = convert_tools(tools)

        assert definitions[0].description == "Tool: nodesc_tool"

    @pytest.mark.unit
    def test_convert_tools_args_schema_fallback(self):
        """Test fallback to args_schema for parameters."""
        class ArgsSchemaTool:
            description = "Args schema tool"
            _tool_schema = MagicMock()
            _tool_schema.is_model_visible = True

            class ArgsSchema:
                @staticmethod
                def model_json_schema():
                    return {
                        "type": "object",
                        "properties": {"arg1": {"type": "string"}},
                    }

            args_schema = ArgsSchema

        tools = {"args_tool": ArgsSchemaTool()}
        definitions = convert_tools(tools)

        assert definitions[0].parameters["properties"]["arg1"]["type"] == "string"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_execute_wrapper_ainvoke_fallback(self):
        """Test fallback to ainvoke method."""
        class AinvokeTool:
            description = "Ainvoke tool"
            _tool_schema = MagicMock()
            _tool_schema.is_model_visible = True

            async def ainvoke(self, kwargs):
                return f"ainvoke: {kwargs}"

        tools = {"ainvoke_tool": AinvokeTool()}
        definitions = convert_tools(tools)

        result = await definitions[0].execute(input="test")

        assert result == "ainvoke: {'input': 'test'}"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_execute_wrapper_run_fallback(self):
        """Test fallback to run method."""
        class RunTool:
            description = "Run tool"
            _tool_schema = MagicMock()
            _tool_schema.is_model_visible = True

            def run(self, **kwargs):
                return f"run: {kwargs}"

        tools = {"run_tool": RunTool()}
        definitions = convert_tools(tools)

        result = await definitions[0].execute(input="test")

        assert "run:" in result

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_execute_wrapper_no_execute_method_error(self):
        """Test error when tool has no execute method."""
        class NoMethodTool:
            description = "No method tool"
            _tool_schema = MagicMock()
            _tool_schema.is_model_visible = True
            # No execute, ainvoke, _run, run methods

        tools = {"nomethod_tool": NoMethodTool()}
        definitions = convert_tools(tools)

        result = await definitions[0].execute(input="test")

        assert "Error executing tool nomethod_tool" in result
        assert "has no execute method" in result
