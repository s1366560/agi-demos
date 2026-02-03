"""Unit tests for Temporal MCP Domain Adapter (Phase 5)."""


from src.domain.model.mcp.tool import MCPToolResult, MCPToolSchema
from src.infrastructure.adapters.secondary.temporal.mcp.domain_adapter import (
    TemporalMCPDomainAdapter,
    from_domain_tool_result,
    from_domain_tool_schema,
    to_domain_tool_result,
    to_domain_tool_schema,
)

# ============================================================================
# MCPToolResult Conversion Tests
# ============================================================================


class TestToolResultConversion:
    """Tests for MCPToolResult conversion."""

    def test_to_domain_with_is_error_format(self):
        """Test conversion with is_error format (internal)."""
        data = {
            "content": [{"type": "text", "text": "Hello"}],
            "is_error": False,
            "error_message": None,
        }

        result = to_domain_tool_result(data)

        assert isinstance(result, MCPToolResult)
        assert result.content == [{"type": "text", "text": "Hello"}]
        assert result.is_error is False

    def test_to_domain_with_isError_format(self):
        """Test conversion with isError format (MCP protocol)."""
        data = {
            "content": [{"type": "text", "text": "Error occurred"}],
            "isError": True,
            "error_message": "Something went wrong",
        }

        result = to_domain_tool_result(data)

        assert result.is_error is True
        assert result.error_message == "Something went wrong"

    def test_to_domain_with_artifact(self):
        """Test conversion preserves artifact."""
        data = {
            "content": [{"type": "text", "text": "Result"}],
            "isError": False,
            "artifact": {"type": "code", "code": "print('hello')"},
        }

        result = to_domain_tool_result(data)

        assert result.artifact == {"type": "code", "code": "print('hello')"}

    def test_to_domain_with_metadata(self):
        """Test conversion preserves metadata."""
        data = {
            "content": [{"type": "text", "text": "Result"}],
            "isError": False,
            "metadata": {"execution_id": "123"},
        }

        result = to_domain_tool_result(data)

        assert result.metadata == {"execution_id": "123"}

    def test_to_domain_with_execution_time(self):
        """Test conversion preserves execution_time_ms."""
        data = {
            "content": [],
            "isError": False,
            "execution_time_ms": 150,
        }

        result = to_domain_tool_result(data)

        assert result.execution_time_ms == 150

    def test_to_domain_empty_content(self):
        """Test conversion with empty content."""
        data = {}

        result = to_domain_tool_result(data)

        assert result.content == []
        assert result.is_error is False

    def test_from_domain_result(self):
        """Test conversion from domain to dict."""
        result = MCPToolResult(
            content=[{"type": "text", "text": "Hello"}],
            is_error=False,
            error_message=None,
            metadata={"key": "value"},
            artifact={"type": "code", "code": "x = 1"},
            execution_time_ms=100,
        )

        data = from_domain_tool_result(result)

        assert data["content"] == [{"type": "text", "text": "Hello"}]
        assert data["isError"] is False  # MCP protocol format
        assert data["metadata"] == {"key": "value"}
        assert data["artifact"] == {"type": "code", "code": "x = 1"}
        assert data["execution_time_ms"] == 100

    def test_from_domain_error_result(self):
        """Test conversion from error result."""
        result = MCPToolResult.error("Something failed")

        data = from_domain_tool_result(result)

        assert data["isError"] is True
        assert data["error_message"] == "Something failed"

    def test_roundtrip_conversion(self):
        """Test domain -> dict -> domain preserves data."""
        original = MCPToolResult(
            content=[{"type": "text", "text": "Hello"}],
            is_error=False,
            metadata={"key": "value"},
        )

        # Domain -> Dict -> Domain
        data = from_domain_tool_result(original)
        restored = to_domain_tool_result(data)

        assert restored.content == original.content
        assert restored.is_error == original.is_error
        assert restored.metadata == original.metadata


# ============================================================================
# MCPToolSchema Conversion Tests
# ============================================================================


class TestToolSchemaConversion:
    """Tests for MCPToolSchema conversion."""

    def test_to_domain_schema_basic(self):
        """Test basic schema conversion."""
        data = {
            "name": "fetch",
            "description": "Fetch a URL",
            "inputSchema": {
                "type": "object",
                "properties": {"url": {"type": "string"}},
            },
        }

        schema = to_domain_tool_schema(data)

        assert isinstance(schema, MCPToolSchema)
        assert schema.name == "fetch"
        assert schema.description == "Fetch a URL"
        assert "properties" in schema.input_schema

    def test_to_domain_schema_with_input_schema_snake_case(self):
        """Test conversion with input_schema (snake_case)."""
        data = {
            "name": "execute",
            "input_schema": {"type": "object"},
        }

        schema = to_domain_tool_schema(data)

        assert schema.input_schema == {"type": "object"}

    def test_to_domain_schema_no_description(self):
        """Test schema without description."""
        data = {"name": "simple_tool"}

        schema = to_domain_tool_schema(data)

        assert schema.name == "simple_tool"
        assert schema.description is None

    def test_from_domain_schema(self):
        """Test conversion from domain schema to dict."""
        schema = MCPToolSchema(
            name="search",
            description="Search the web",
            input_schema={
                "type": "object",
                "properties": {"query": {"type": "string"}},
            },
        )

        data = from_domain_tool_schema(schema)

        assert data["name"] == "search"
        assert data["description"] == "Search the web"
        assert data["inputSchema"]["type"] == "object"

    def test_roundtrip_schema_conversion(self):
        """Test schema domain -> dict -> domain preserves data."""
        original = MCPToolSchema(
            name="calculator",
            description="Perform math operations",
            input_schema={"type": "object", "properties": {"expression": {"type": "string"}}},
        )

        data = from_domain_tool_schema(original)
        restored = to_domain_tool_schema(data)

        assert restored.name == original.name
        assert restored.description == original.description
        assert restored.input_schema == original.input_schema


# ============================================================================
# List Conversion Tests
# ============================================================================


class TestListConversion:
    """Tests for list conversion."""

    def test_convert_tools_list(self):
        """Test converting list of tool dicts."""
        tools = [
            {"name": "tool1", "description": "First tool"},
            {"name": "tool2", "description": "Second tool"},
            {"name": "tool3", "description": "Third tool"},
        ]

        result = TemporalMCPDomainAdapter.convert_tools_list(tools)

        assert len(result) == 3
        assert all(isinstance(t, MCPToolSchema) for t in result)
        assert result[0].name == "tool1"
        assert result[1].name == "tool2"
        assert result[2].name == "tool3"

    def test_convert_empty_tools_list(self):
        """Test converting empty list."""
        result = TemporalMCPDomainAdapter.convert_tools_list([])

        assert result == []

    def test_convert_tools_with_schemas(self):
        """Test converting tools with input schemas."""
        tools = [
            {
                "name": "fetch",
                "description": "Fetch URL",
                "inputSchema": {"type": "object", "properties": {"url": {"type": "string"}}},
            }
        ]

        result = TemporalMCPDomainAdapter.convert_tools_list(tools)

        assert result[0].input_schema["type"] == "object"
        assert "url" in result[0].input_schema["properties"]


# ============================================================================
# Edge Cases and Error Handling
# ============================================================================


class TestEdgeCases:
    """Tests for edge cases."""

    def test_to_domain_with_none_values(self):
        """Test conversion handles None values gracefully."""
        data = {
            "content": None,
            "is_error": None,
        }

        # Should not raise, content should be []
        result = to_domain_tool_result(data)

        assert result.content == []  # None converted to []
        assert result.is_error is False  # None treated as False

    def test_to_domain_both_error_formats(self):
        """Test is_error takes precedence over isError."""
        data = {
            "content": [],
            "is_error": True,
            "isError": False,  # Both present, is_error wins
        }

        result = to_domain_tool_result(data)

        assert result.is_error is True

    def test_from_domain_with_empty_result(self):
        """Test from_domain with minimal result."""
        result = MCPToolResult()

        data = from_domain_tool_result(result)

        assert data["content"] == []
        assert data["isError"] is False
        assert data["error_message"] is None
