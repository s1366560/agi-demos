"""Unit tests for AgentTool base class."""

from typing import Any

import pytest

from src.infrastructure.agent.tools.base import AgentTool


class ConcreteAgentTool(AgentTool):
    """Concrete implementation of AgentTool for testing."""

    def __init__(self, name: str = "test_tool", description: str = "A test tool"):
        super().__init__(name=name, description=description)
        self._should_raise = False
        self._return_value = "test result"

    def set_should_raise(self, should_raise: bool, error_msg: str = "Test error"):
        """Configure the tool to raise an exception on execute."""
        self._should_raise = should_raise
        self._error_msg = error_msg

    def set_return_value(self, value: str):
        """Set the return value for execute."""
        self._return_value = value

    async def execute(self, **kwargs: Any) -> str:
        if self._should_raise:
            raise Exception(self._error_msg)
        return self._return_value


class ConcreteToolWithValidation(AgentTool):
    """Concrete tool with custom validation."""

    def __init__(self):
        super().__init__(name="validated_tool", description="Tool with validation")

    def validate_args(self, **kwargs: Any) -> bool:
        """Require 'query' argument to be a non-empty string."""
        query = kwargs.get("query")
        return isinstance(query, str) and len(query.strip()) > 0

    async def execute(self, **kwargs: Any) -> str:
        return f"Executed with query: {kwargs.get('query')}"


class TestAgentToolInit:
    """Test AgentTool initialization."""

    def test_init_with_name_and_description(self):
        """Test tool initializes with name and description."""
        tool = ConcreteAgentTool(name="my_tool", description="My description")
        assert tool.name == "my_tool"
        assert tool.description == "My description"

    def test_name_property_readonly(self):
        """Test that name property is read-only (no setter)."""
        tool = ConcreteAgentTool()
        # Property doesn't have a setter, so direct assignment should fail
        with pytest.raises(AttributeError):
            tool.name = "new_name"

    def test_description_property_readonly(self):
        """Test that description property is read-only (no setter)."""
        tool = ConcreteAgentTool()
        with pytest.raises(AttributeError):
            tool.description = "new_description"


class TestAgentToolValidation:
    """Test AgentTool argument validation."""

    def test_validate_args_default_returns_true(self):
        """Test default validate_args returns True for any input."""
        tool = ConcreteAgentTool()
        assert tool.validate_args() is True
        assert tool.validate_args(foo="bar") is True
        assert tool.validate_args(a=1, b=2, c=3) is True

    def test_custom_validation_valid_args(self):
        """Test custom validation with valid arguments."""
        tool = ConcreteToolWithValidation()
        assert tool.validate_args(query="test query") is True

    def test_custom_validation_empty_query(self):
        """Test custom validation rejects empty query."""
        tool = ConcreteToolWithValidation()
        assert tool.validate_args(query="") is False

    def test_custom_validation_whitespace_only(self):
        """Test custom validation rejects whitespace-only query."""
        tool = ConcreteToolWithValidation()
        assert tool.validate_args(query="   ") is False

    def test_custom_validation_missing_query(self):
        """Test custom validation rejects missing query."""
        tool = ConcreteToolWithValidation()
        assert tool.validate_args() is False
        assert tool.validate_args(other="value") is False

    def test_custom_validation_non_string_query(self):
        """Test custom validation rejects non-string query."""
        tool = ConcreteToolWithValidation()
        assert tool.validate_args(query=123) is False
        assert tool.validate_args(query=None) is False


class TestAgentToolSafeExecute:
    """Test AgentTool safe_execute method."""

    @pytest.mark.asyncio
    async def test_safe_execute_success(self):
        """Test safe_execute returns result on success."""
        tool = ConcreteAgentTool()
        tool.set_return_value("success result")

        result = await tool.safe_execute()
        assert result == "success result"

    @pytest.mark.asyncio
    async def test_safe_execute_returns_error_on_invalid_args(self):
        """Test safe_execute returns error when validation fails."""
        tool = ConcreteToolWithValidation()

        result = await tool.safe_execute(query="")
        assert "Error: Invalid arguments" in result
        assert "validated_tool" in result

    @pytest.mark.asyncio
    async def test_safe_execute_catches_exception(self):
        """Test safe_execute catches and returns exception message."""
        tool = ConcreteAgentTool()
        tool.set_should_raise(True, "Something went wrong")

        result = await tool.safe_execute()
        assert "Error executing tool test_tool" in result
        assert "Something went wrong" in result

    @pytest.mark.asyncio
    async def test_safe_execute_passes_kwargs(self):
        """Test safe_execute passes kwargs to execute."""
        received_kwargs = {}

        class KwargsCaptureTool(AgentTool):
            def __init__(self):
                super().__init__(name="capture", description="Capture kwargs")

            async def execute(self, **kwargs):
                received_kwargs.update(kwargs)
                return "captured"

        tool = KwargsCaptureTool()
        await tool.safe_execute(a=1, b="two", c=[3])

        assert received_kwargs == {"a": 1, "b": "two", "c": [3]}


class TestAgentToolComposition:
    """Test AgentTool composition methods (T109-T111)."""

    def test_get_output_schema_default(self):
        """Test default output schema is generic string."""
        tool = ConcreteAgentTool(name="my_tool")
        schema = tool.get_output_schema()

        assert schema["type"] == "string"
        assert "my_tool" in schema["description"]

    def test_get_input_schema_default(self):
        """Test default input schema is generic object."""
        tool = ConcreteAgentTool(name="my_tool")
        schema = tool.get_input_schema()

        assert schema["type"] == "object"
        assert "my_tool" in schema["description"]

    def test_can_compose_with_default_returns_true(self):
        """Test default can_compose_with returns True."""
        tool1 = ConcreteAgentTool(name="tool1")
        tool2 = ConcreteAgentTool(name="tool2")

        assert tool1.can_compose_with(tool2) is True
        assert tool2.can_compose_with(tool1) is True

    def test_compose_output_parses_json_dict(self):
        """Test compose_output parses JSON dict correctly."""
        tool1 = ConcreteAgentTool()
        tool2 = ConcreteAgentTool()

        output = '{"key": "value", "count": 42}'
        result = tool1.compose_output(output, tool2)

        assert result == {"key": "value", "count": 42}

    def test_compose_output_parses_json_list(self):
        """Test compose_output wraps JSON list in data key."""
        tool1 = ConcreteAgentTool()
        tool2 = ConcreteAgentTool()

        output = "[1, 2, 3]"
        result = tool1.compose_output(output, tool2)

        assert result == {"data": [1, 2, 3]}

    def test_compose_output_wraps_non_json(self):
        """Test compose_output wraps non-JSON string in raw_output key."""
        tool1 = ConcreteAgentTool()
        tool2 = ConcreteAgentTool()

        output = "plain text output"
        result = tool1.compose_output(output, tool2)

        assert result == {"raw_output": "plain text output"}

    def test_compose_output_handles_invalid_json(self):
        """Test compose_output handles malformed JSON gracefully."""
        tool1 = ConcreteAgentTool()
        tool2 = ConcreteAgentTool()

        output = '{"unclosed": "brace'
        result = tool1.compose_output(output, tool2)

        assert result == {"raw_output": '{"unclosed": "brace'}


class TestAgentToolExtractOutputField:
    """Test AgentTool.extract_output_field method."""

    def test_extract_simple_field(self):
        """Test extracting a simple top-level field."""
        tool = ConcreteAgentTool()
        output = '{"name": "Alice", "age": 30}'

        assert tool.extract_output_field(output, "name") == "Alice"
        assert tool.extract_output_field(output, "age") == 30

    def test_extract_nested_field(self):
        """Test extracting a nested field using dot notation."""
        tool = ConcreteAgentTool()
        output = '{"user": {"profile": {"name": "Bob"}}}'

        assert tool.extract_output_field(output, "user.profile.name") == "Bob"
        assert tool.extract_output_field(output, "user.profile") == {"name": "Bob"}

    def test_extract_array_index(self):
        """Test extracting array element by index."""
        tool = ConcreteAgentTool()
        output = '{"results": ["first", "second", "third"]}'

        assert tool.extract_output_field(output, "results.0") == "first"
        assert tool.extract_output_field(output, "results.1") == "second"
        assert tool.extract_output_field(output, "results.2") == "third"

    def test_extract_nested_array(self):
        """Test extracting nested field within array element."""
        tool = ConcreteAgentTool()
        output = '{"items": [{"id": 1, "name": "A"}, {"id": 2, "name": "B"}]}'

        assert tool.extract_output_field(output, "items.0.id") == 1
        assert tool.extract_output_field(output, "items.1.name") == "B"

    def test_extract_invalid_path_returns_none(self):
        """Test extracting non-existent path returns None."""
        tool = ConcreteAgentTool()
        output = '{"key": "value"}'

        assert tool.extract_output_field(output, "nonexistent") is None
        assert tool.extract_output_field(output, "key.nested") is None
        assert tool.extract_output_field(output, "deep.nested.path") is None

    def test_extract_out_of_bounds_array_returns_none(self):
        """Test extracting out-of-bounds array index returns None."""
        tool = ConcreteAgentTool()
        output = '{"arr": [1, 2, 3]}'

        assert tool.extract_output_field(output, "arr.10") is None
        assert tool.extract_output_field(output, "arr.-1") is None

    def test_extract_from_invalid_json_returns_none(self):
        """Test extracting from invalid JSON returns None."""
        tool = ConcreteAgentTool()

        assert tool.extract_output_field("not json", "key") is None
        assert tool.extract_output_field("{invalid}", "key") is None

    def test_extract_none_value(self):
        """Test extracting a field with null value."""
        tool = ConcreteAgentTool()
        output = '{"key": null}'

        # Returns None for null value (same as missing)
        assert tool.extract_output_field(output, "key") is None

    def test_extract_empty_path(self):
        """Test extracting with empty path."""
        tool = ConcreteAgentTool()
        output = '{"key": "value"}'

        # Empty path should return empty string key lookup
        result = tool.extract_output_field(output, "")
        assert result is None
