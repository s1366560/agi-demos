"""Tests for tool system - fixed imports."""

import pytest
from typing import Optional
import inspect

from memstack_agent.tools.converter import (
    function_to_tool,
    infer_type_schema,
)
from memstack_agent.tools.protocol import ToolDefinition, ToolMetadata


class TestToolMetadata:
    """Tests for ToolMetadata."""

    def test_create_metadata(self) -> None:
        """Test creating metadata."""
        metadata = ToolMetadata(
            tags=["search", "web"],
            timeout_seconds=30,
        )
        assert metadata.tags == ["search", "web"]
        assert metadata.visible_to_model is True
        assert metadata.timeout_seconds == 30
        assert metadata.ui_category is None


class TestToolDefinition:
    """Tests for ToolDefinition."""

    def test_create_definition(self) -> None:
        """Test creating a tool definition."""
        async def dummy_execute(**kwargs):
            return "result"

        definition = ToolDefinition(
            name="test_tool",
            description="A test tool",
            parameters={"type": "object", "properties": {}, "required": []},
            execute=dummy_execute,
        )
        assert definition.name == "test_tool"
        assert definition.description == "A test tool"
        assert definition.permission is None


class TestInferTypeSchema:
    """Tests for infer_type_schema function."""

    def test_primitive_types(self) -> None:
        """Test schema inference for primitive types."""
        assert infer_type_schema(str) == {"type": "string"}
        assert infer_type_schema(int) == {"type": "integer"}
        assert infer_type_schema(float) == {"type": "number"}
        assert infer_type_schema(bool) == {"type": "boolean"}

    def test_optional_type(self) -> None:
        """Test schema inference for Optional types."""
        schema = infer_type_schema(Optional[str])
        assert schema["type"] == "string"
        assert schema["nullable"] is True


class TestFunctionToTool:
    """Tests for function_to_tool converter."""

    @pytest.mark.asyncio
    async def test_convert_sync_function(self) -> None:
        """Test converting a synchronous function."""
        def add(a: int, b: int) -> int:
            """Add two numbers.

            Args:
                a: First number
                b: Second number
            """
            return a + b

        tool = function_to_tool(add)
        assert tool.name == "add"
        result = await tool.execute(a=1, b=2)
        assert result == 3
