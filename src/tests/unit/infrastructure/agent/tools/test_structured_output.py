"""Unit tests for structured_output tool.

pyright is configured to exclude src/tests/ so private-usage and
unused-function diagnostics are suppressed at the file level.
"""
# pyright: reportPrivateUsage=false, reportUnusedFunction=false, reportUnusedImport=false, reportUnusedVariable=false

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import BaseModel

from src.infrastructure.agent.tools import (
    structured_output as so_mod,
)
from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.structured_output import (
    configure_structured_output,
    structured_output_tool,
)


def _make_ctx() -> ToolContext:
    """Create a minimal ToolContext for testing."""
    return ToolContext(
        session_id="test-session",
        message_id="test-msg",
        call_id="test-call",
        agent_name="test-agent",
        conversation_id="test-conv",
    )


def _simple_schema() -> dict[str, Any]:
    """Return a simple schema with one required field."""
    return {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
        },
        "required": ["name"],
    }


def _make_mock_llm(
    response_data: dict[str, Any],
) -> AsyncMock:
    """Create a mock LLMClient that returns valid JSON."""
    mock = AsyncMock()
    mock.generate_response = AsyncMock(
        return_value={"content": json.dumps(response_data)},
    )
    return mock


@pytest.mark.unit
class TestConfigureStructuredOutput:
    """Test configure_structured_output function."""

    def test_configure_sets_client(self) -> None:
        """Test that configure stores the LLM client."""
        mock_client = AsyncMock()
        with patch(
            "src.infrastructure.agent.tools.structured_output._so_llm_client",
            None,
        ):
            configure_structured_output(mock_client)
            # After configure, the module-level var is set via global
            # We verify by importing again
            from src.infrastructure.agent.tools import (
                structured_output as mod,
            )

            assert mod._so_llm_client is mock_client
            # Restore
            mod._so_llm_client = None


@pytest.mark.unit
class TestJsonTypeToPython:
    """Test _json_type_to_python mapping."""

    def test_string_maps_to_str(self) -> None:
        assert so_mod._json_type_to_python("string") is str

    def test_integer_maps_to_int(self) -> None:
        assert so_mod._json_type_to_python("integer") is int

    def test_number_maps_to_float(self) -> None:
        assert so_mod._json_type_to_python("number") is float

    def test_boolean_maps_to_bool(self) -> None:
        assert so_mod._json_type_to_python("boolean") is bool

    def test_array_maps_to_list(self) -> None:
        assert so_mod._json_type_to_python("array") is list

    def test_object_maps_to_dict(self) -> None:
        assert so_mod._json_type_to_python("object") is dict

    def test_unknown_maps_to_any(self) -> None:
        from typing import Any as TypingAny

        result = so_mod._json_type_to_python("foobar")
        assert result is TypingAny


@pytest.mark.unit
class TestSchemaToPydantic:
    """Test _schema_to_pydantic model creation."""

    def test_creates_model_with_required_field(self) -> None:
        """Test model has required field (no default)."""
        model = so_mod._schema_to_pydantic(_simple_schema())
        instance = model(name="Alice")
        assert instance.name == "Alice"  # type: ignore[attr-defined]

    def test_creates_model_with_optional_field(self) -> None:
        """Test optional fields default to None."""
        schema: dict[str, Any] = {
            "properties": {
                "title": {"type": "string"},
                "age": {"type": "integer"},
            },
            "required": ["title"],
        }
        model = so_mod._schema_to_pydantic(schema)
        instance = model(title="test")
        assert instance.age is None  # type: ignore[attr-defined]

    def test_empty_schema_creates_model(self) -> None:
        """Test empty properties still produces a valid model."""
        model = so_mod._schema_to_pydantic({"properties": {}})
        instance = model()
        assert isinstance(instance, BaseModel)

    def test_custom_model_name(self) -> None:
        """Test model_name parameter is respected."""
        model = so_mod._schema_to_pydantic(
            _simple_schema(),
            model_name="PersonModel",
        )
        assert model.__name__ == "PersonModel"


@pytest.mark.unit
class TestStructuredOutputToolNotConfigured:
    """Test tool behaviour when LLM client is not configured."""

    async def test_not_configured_returns_error(self) -> None:
        """Tool should return is_error=True when not configured."""
        ctx = _make_ctx()
        with patch(
            "src.infrastructure.agent.tools.structured_output._so_llm_client",
            None,
        ):
            result = await structured_output_tool.execute(
                ctx,
                prompt="Extract name",
                schema=_simple_schema(),
            )
        assert result.is_error
        assert "not configured" in result.output


@pytest.mark.unit
class TestStructuredOutputToolSuccess:
    """Test successful structured output generation."""

    async def test_simple_schema_success(self) -> None:
        """Tool returns valid JSON for a simple schema."""
        mock_llm = _make_mock_llm({"name": "Alice"})
        ctx = _make_ctx()
        with patch(
            "src.infrastructure.agent.tools.structured_output._so_llm_client",
            mock_llm,
        ):
            result = await structured_output_tool.execute(
                ctx,
                prompt="Extract the name",
                schema=_simple_schema(),
            )
        assert not result.is_error
        data = json.loads(result.output)
        assert data["name"] == "Alice"

    async def test_schema_with_required_fields(self) -> None:
        """Tool validates required fields correctly."""
        schema: dict[str, Any] = {
            "properties": {
                "city": {"type": "string"},
                "population": {"type": "integer"},
            },
            "required": ["city", "population"],
        }
        mock_llm = _make_mock_llm(
            {"city": "Tokyo", "population": 14000000},
        )
        ctx = _make_ctx()
        with patch(
            "src.infrastructure.agent.tools.structured_output._so_llm_client",
            mock_llm,
        ):
            result = await structured_output_tool.execute(
                ctx,
                prompt="City info",
                schema=schema,
            )
        assert not result.is_error
        data = json.loads(result.output)
        assert data["city"] == "Tokyo"
        assert data["population"] == 14000000

    async def test_optional_fields_default_none(self) -> None:
        """Optional fields that the LLM omits appear as None."""
        schema: dict[str, Any] = {
            "properties": {
                "name": {"type": "string"},
                "nickname": {"type": "string"},
            },
            "required": ["name"],
        }
        mock_llm = _make_mock_llm({"name": "Bob"})
        ctx = _make_ctx()
        with patch(
            "src.infrastructure.agent.tools.structured_output._so_llm_client",
            mock_llm,
        ):
            result = await structured_output_tool.execute(
                ctx,
                prompt="Extract name",
                schema=schema,
            )
        assert not result.is_error
        data = json.loads(result.output)
        assert data["name"] == "Bob"
        assert data.get("nickname") is None

    async def test_data_parameter_included_in_prompt(self) -> None:
        """When data is supplied it should be sent to the LLM."""
        mock_llm = _make_mock_llm({"name": "Carol"})
        ctx = _make_ctx()
        with patch(
            "src.infrastructure.agent.tools.structured_output._so_llm_client",
            mock_llm,
        ):
            result = await structured_output_tool.execute(
                ctx,
                prompt="Extract name",
                schema=_simple_schema(),
                data="The person is Carol.",
            )
        assert not result.is_error
        # Verify generate_response was called and user message
        # contained the data
        call_args = mock_llm.generate_response.call_args
        messages = call_args.kwargs.get(
            "messages",
            call_args.args[0] if call_args.args else [],
        )
        user_msgs = [m for m in messages if getattr(m, "role", "") == "user"]
        assert any("Carol" in m.content for m in user_msgs)


@pytest.mark.unit
class TestStructuredOutputToolFailure:
    """Test failure and error handling paths."""

    async def test_validation_failure_returns_error(self) -> None:
        """When LLM returns invalid data, tool returns error."""
        mock_llm = AsyncMock()
        # Return content that cannot match the schema
        mock_llm.generate_response = AsyncMock(
            return_value={"content": "not json at all"},
        )
        ctx = _make_ctx()
        with patch(
            "src.infrastructure.agent.tools.structured_output._so_llm_client",
            mock_llm,
        ):
            result = await structured_output_tool.execute(
                ctx,
                prompt="Extract name",
                schema=_simple_schema(),
            )
        assert result.is_error
        assert "failed" in result.output.lower() or "error" in result.output.lower()

    async def test_max_retries_respected(self) -> None:
        """max_retries is clamped to [0, 5]."""
        mock_llm = _make_mock_llm({"name": "Test"})
        ctx = _make_ctx()
        with patch(
            "src.infrastructure.agent.tools.structured_output._so_llm_client",
            mock_llm,
        ):
            # Passing 10 should be clamped to 5
            result = await structured_output_tool.execute(
                ctx,
                prompt="Extract",
                schema=_simple_schema(),
                max_retries=10,
            )
        assert not result.is_error

    async def test_exception_handling(self) -> None:
        """Unexpected exception is caught and returned as error."""
        mock_llm = AsyncMock()
        mock_llm.generate_response = AsyncMock(
            side_effect=RuntimeError("boom"),
        )
        ctx = _make_ctx()
        with patch(
            "src.infrastructure.agent.tools.structured_output._so_llm_client",
            mock_llm,
        ):
            result = await structured_output_tool.execute(
                ctx,
                prompt="Extract",
                schema=_simple_schema(),
            )
        assert result.is_error
        assert "boom" in result.output or "unexpected" in result.output.lower()

    async def test_empty_schema_handled(self) -> None:
        """An empty schema should still produce a valid result."""
        mock_llm = _make_mock_llm({})
        ctx = _make_ctx()
        with patch(
            "src.infrastructure.agent.tools.structured_output._so_llm_client",
            mock_llm,
        ):
            result = await structured_output_tool.execute(
                ctx,
                prompt="Extract nothing",
                schema={"properties": {}},
            )
        assert not result.is_error


@pytest.mark.unit
class TestStructuredOutputToolMetadata:
    """Test metadata in successful responses."""

    async def test_metadata_contains_attempts(self) -> None:
        """Successful result metadata includes attempt count."""
        mock_llm = _make_mock_llm({"name": "Dave"})
        ctx = _make_ctx()
        with patch(
            "src.infrastructure.agent.tools.structured_output._so_llm_client",
            mock_llm,
        ):
            result = await structured_output_tool.execute(
                ctx,
                prompt="Extract name",
                schema=_simple_schema(),
            )
        assert "attempts" in result.metadata

    async def test_metadata_contains_schema_keys(self) -> None:
        """Successful result metadata includes schema property keys."""
        mock_llm = _make_mock_llm({"name": "Eve"})
        ctx = _make_ctx()
        with patch(
            "src.infrastructure.agent.tools.structured_output._so_llm_client",
            mock_llm,
        ):
            result = await structured_output_tool.execute(
                ctx,
                prompt="Extract name",
                schema=_simple_schema(),
            )
        assert "schema_keys" in result.metadata
        assert "name" in result.metadata["schema_keys"]
