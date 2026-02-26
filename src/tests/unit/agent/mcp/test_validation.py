"""Tests for MCPValidator and MCPValidationError."""

import pytest

from src.infrastructure.mcp.validation import MCPValidationError, MCPValidator


@pytest.mark.unit
class TestMCPValidationError:
    """Tests for MCPValidationError exception."""

    def test_stores_tool_name_and_errors(self) -> None:
        errors = [{"loc": ["field1"], "msg": "required"}]
        exc = MCPValidationError(tool_name="my_tool", errors=errors)

        assert exc.tool_name == "my_tool"
        assert exc.errors == errors
        assert "my_tool" in str(exc)
        assert "required" in str(exc)

    def test_is_exception(self) -> None:
        exc = MCPValidationError(tool_name="t", errors=[])
        assert isinstance(exc, Exception)

    def test_multiple_errors_formatted(self) -> None:
        errors = [
            {"loc": ["name"], "msg": "field required"},
            {"loc": ["age"], "msg": "not a valid integer"},
        ]
        exc = MCPValidationError(tool_name="test", errors=errors)
        msg = str(exc)
        assert "name" in msg
        assert "age" in msg


@pytest.mark.unit
class TestMCPValidator:
    """Tests for MCPValidator."""

    def test_initial_state(self) -> None:
        v = MCPValidator()
        assert v.has_schema("nonexistent") is False
        assert v.get_model("nonexistent") is None

    def test_register_simple_schema(self) -> None:
        v = MCPValidator()
        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "User name"},
                "age": {"type": "integer", "description": "User age"},
            },
            "required": ["name"],
        }

        model = v.register_schema("user_tool", schema)

        assert v.has_schema("user_tool")
        assert v.get_model("user_tool") is model

    def test_validate_valid_args(self) -> None:
        v = MCPValidator()
        v.register_schema(
            "greeting",
            {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                },
                "required": ["name"],
            },
        )

        result = v.validate("greeting", {"name": "Alice"})
        assert result["name"] == "Alice"

    def test_validate_coerces_types(self) -> None:
        v = MCPValidator()
        v.register_schema(
            "numbers",
            {
                "type": "object",
                "properties": {
                    "count": {"type": "integer"},
                    "ratio": {"type": "number"},
                },
                "required": ["count"],
            },
        )

        # Pydantic should coerce string "5" to int 5
        result = v.validate("numbers", {"count": 5, "ratio": 3.14})
        assert result["count"] == 5
        assert result["ratio"] == 3.14

    def test_validate_missing_required_raises(self) -> None:
        v = MCPValidator()
        v.register_schema(
            "required_test",
            {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                },
                "required": ["name"],
            },
        )

        with pytest.raises(MCPValidationError) as exc_info:
            v.validate("required_test", {})

        assert exc_info.value.tool_name == "required_test"
        assert len(exc_info.value.errors) > 0

    def test_validate_optional_field_defaults_to_none(self) -> None:
        v = MCPValidator()
        v.register_schema(
            "optional_test",
            {
                "type": "object",
                "properties": {
                    "required_field": {"type": "string"},
                    "optional_field": {"type": "string"},
                },
                "required": ["required_field"],
            },
        )

        result = v.validate("optional_test", {"required_field": "hello"})
        assert result["required_field"] == "hello"
        assert result.get("optional_field") is None

    def test_validate_with_default_value(self) -> None:
        v = MCPValidator()
        v.register_schema(
            "default_test",
            {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "default": "world"},
                },
                "required": ["name"],
            },
        )

        result = v.validate("default_test", {})
        assert result["name"] == "world"

    def test_validate_unregistered_tool_returns_args(self) -> None:
        v = MCPValidator()
        args = {"anything": "goes"}
        result = v.validate("unregistered", args)
        assert result is args

    def test_validate_boolean_field(self) -> None:
        v = MCPValidator()
        v.register_schema(
            "bool_test",
            {
                "type": "object",
                "properties": {
                    "flag": {"type": "boolean"},
                },
                "required": ["flag"],
            },
        )

        result = v.validate("bool_test", {"flag": True})
        assert result["flag"] is True

    def test_validate_array_field(self) -> None:
        v = MCPValidator()
        v.register_schema(
            "array_test",
            {
                "type": "object",
                "properties": {
                    "items": {"type": "array"},
                },
                "required": ["items"],
            },
        )

        result = v.validate("array_test", {"items": [1, 2, 3]})
        assert result["items"] == [1, 2, 3]

    def test_schema_name_sanitized(self) -> None:
        v = MCPValidator()
        model = v.register_schema(
            "mcp__server__tool",
            {"type": "object", "properties": {}},
        )
        # Class name should have underscores replacing non-alnum
        assert "mcp__server__tool" not in model.__name__ or "_" in model.__name__

    def test_multiple_schemas_registered(self) -> None:
        v = MCPValidator()
        v.register_schema(
            "tool_a", {"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]}
        )
        v.register_schema(
            "tool_b",
            {"type": "object", "properties": {"y": {"type": "integer"}}, "required": ["y"]},
        )

        assert v.has_schema("tool_a")
        assert v.has_schema("tool_b")

        result_a = v.validate("tool_a", {"x": "hello"})
        assert result_a["x"] == "hello"

        result_b = v.validate("tool_b", {"y": 42})
        assert result_b["y"] == 42
