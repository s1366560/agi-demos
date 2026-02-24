"""Tests for tool system."""

import pytest

from memstack_agent.tools.converter import (
    function_to_tool,
    infer_type_schema,
)
from memstack_agent.tools.protocol import (
    SimpleTool,
    ToolDefinition,
    ToolMetadata,
)


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

    def test_metadata_defaults(self) -> None:
        """Test metadata has correct defaults."""
        metadata = ToolMetadata()
        assert metadata.tags == []
        assert metadata.visible_to_model is True
        assert metadata.timeout_seconds is None
        assert metadata.ui_category is None
        assert metadata.ui_component is None
        assert metadata.extra == {}

    def test_metadata_is_immutable(self) -> None:
        """Test metadata is frozen (immutable)."""
        from dataclasses import FrozenInstanceError

        metadata = ToolMetadata(tags=["test"])
        with pytest.raises(FrozenInstanceError):
            metadata.tags = ["another"]


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

    def test_definition_to_openai_format(self) -> None:
        """Test conversion to OpenAI format."""

        async def dummy_execute(**kwargs):
            return "result"

        definition = ToolDefinition(
            name="calculator",
            description="Performs calculations",
            parameters={
                "type": "object",
                "properties": {
                    "expression": {"type": "string"},
                },
                "required": ["expression"],
            },
            execute=dummy_execute,
        )

        openai_format = definition.to_openai_format()
        assert openai_format["type"] == "function"
        assert openai_format["function"]["name"] == "calculator"
        assert openai_format["function"]["description"] == "Performs calculations"
        assert "expression" in openai_format["function"]["parameters"]["properties"]

    def test_definition_to_anthropic_format(self) -> None:
        """Test conversion to Anthropic format."""

        async def dummy_execute(**kwargs):
            return "result"

        definition = ToolDefinition(
            name="search",
            description="Search the web",
            parameters={"type": "object", "properties": {}, "required": []},
            execute=dummy_execute,
        )

        anthropic_format = definition.to_anthropic_format()
        assert anthropic_format["name"] == "search"
        assert anthropic_format["description"] == "Search the web"
        assert anthropic_format["input_schema"] == {
            "type": "object",
            "properties": {},
            "required": [],
        }

    def test_definition_to_dict(self) -> None:
        """Test conversion to generic dict."""

        async def dummy_execute(**kwargs):
            return "result"

        metadata = ToolMetadata(tags=["test"])
        definition = ToolDefinition(
            name="my_tool",
            description="Test",
            parameters={"type": "object", "properties": {}, "required": []},
            execute=dummy_execute,
            permission="admin",
            metadata=metadata,
        )

        result = definition.to_dict()
        assert result["name"] == "my_tool"
        assert result["description"] == "Test"
        assert result["permission"] == "admin"
        assert result["metadata"]["tags"] == ["test"]
        assert result["metadata"]["visible_to_model"] is True


class TestSimpleTool:
    """Tests for SimpleTool base class."""

    def test_simple_tool_properties(self) -> None:
        """Test SimpleTool provides required properties."""

        class MyTool(SimpleTool):
            name = "my_tool"
            description = "Does something"

            async def execute(self, value: str) -> str:
                return f"Got: {value}"

        tool = MyTool()
        assert tool.name == "my_tool"
        assert tool.description == "Does something"
        assert tool.permission is None

    def test_simple_tool_get_parameters_schema(self) -> None:
        """Test default parameters schema."""
        tool = SimpleTool()
        schema = tool.get_parameters_schema()
        assert schema["type"] == "object"
        assert schema["properties"] == {}
        assert schema["required"] == []

    @pytest.mark.asyncio
    async def test_simple_tool_execute_raises(self) -> None:
        """Test base class execute raises NotImplementedError."""

        # Create a minimal tool subclass
        class MinimalTool(SimpleTool):
            name = "minimal_tool"
            description = "A minimal tool"

        tool = MinimalTool()

        with pytest.raises(NotImplementedError):
            await tool.execute()


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
        from typing import Optional

        schema = infer_type_schema(Optional[str])
        # The returned schema has type "string" and nullable: true
        # So we check both conditions
        assert schema["type"] == "string"
        assert schema["nullable"] is True

    def test_list_type(self) -> None:
        """Test schema inference for list types."""

        schema = infer_type_schema(list[str])
        assert schema["type"] == "array"
        assert schema["items"] == {"type": "string"}

    def test_dict_type(self) -> None:
        """Test schema inference for dict types."""

        schema = infer_type_schema(dict[str, int])
        assert schema["type"] == "object"
        assert schema["additionalProperties"] == {"type": "integer"}

    def test_union_type(self) -> None:
        """Test schema inference for union types."""
        from typing import Union

        schema = infer_type_schema(Union[str, int])
        assert "anyOf" in schema
        assert len(schema["anyOf"]) == 2

    def test_dataclass_type(self) -> None:
        """Test schema inference for dataclasses."""
        from dataclasses import dataclass

        @dataclass
        class Input:
            name: str
            count: int
            optional: str = "default"

        schema = infer_type_schema(Input)
        assert schema["type"] == "object"
        assert "name" in schema["properties"]
        assert "count" in schema["properties"]
        assert "optional" in schema["properties"]
        assert "required" in schema


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
        assert "Add two numbers" in tool.description
        assert tool.parameters["properties"]["a"]["type"] == "integer"
        assert tool.parameters["properties"]["b"]["type"] == "integer"

        # Test execution
        result = await tool.execute(a=1, b=2)
        assert result == 3

    @pytest.mark.asyncio
    async def test_convert_async_function(self) -> None:
        """Test converting an async function."""

        async def greet(name: str) -> str:
            """Greet a person.

            Args:
                name: Person's name
            """
            return f"Hello, {name}!"

        tool = function_to_tool(greet)
        assert tool.name == "greet"

        result = await tool.execute(name="World")
        assert result == "Hello, World!"

    @pytest.mark.asyncio
    async def test_convert_with_custom_name(self) -> None:
        """Test converting with custom name and description."""

        def func(x: int) -> int:
            return x * 2

        tool = function_to_tool(
            func,
            name="doubler",
            description="Doubles the input",
        )
        assert tool.name == "doubler"
        assert tool.description == "Doubles the input"

    @pytest.mark.asyncio
    async def test_convert_with_metadata(self) -> None:
        """Test converting with custom metadata."""

        def func(x: int) -> int:
            return x * 2

        metadata = ToolMetadata(
            tags=["math"],
            timeout_seconds=10,
        )
        tool = function_to_tool(func, metadata=metadata)
        assert tool.metadata.tags == ["math"]
        assert tool.metadata.timeout_seconds == 10

    @pytest.mark.asyncio
    async def test_execute_wraps_sync_function(self) -> None:
        """Test that sync functions are wrapped for async execution."""

        def sync_func(value: str) -> str:
            return f"processed: {value}"

        tool = function_to_tool(sync_func)
        result = await tool.execute(value="test")
        assert result == "processed: test"
