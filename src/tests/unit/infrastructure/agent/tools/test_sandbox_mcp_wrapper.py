"""Unit tests for SandboxMCPToolWrapper.

TDD: Tests written first (RED phase).
"""

import pytest

from src.infrastructure.agent.tools.mcp_errors import RetryConfig
from src.infrastructure.agent.tools.sandbox_tool_wrapper import SandboxMCPToolWrapper


class MockSandboxAdapter:
    """Mock sandbox adapter for testing."""

    def __init__(self, fail_count=0, error_message="Test error"):
        """Initialize mock with failure simulation.

        Args:
            fail_count: Number of times to fail before succeeding
            error_message: Error message to return on failure
        """
        self.fail_count = fail_count
        self.call_count = 0
        self.error_message = error_message

    async def call_tool(self, sandbox_id: str, tool_name: str, kwargs: dict):
        """Mock call_tool method with optional failure simulation."""
        self.call_count += 1

        if self.call_count <= self.fail_count:
            # Simulate connection error (retryable)
            return {
                "content": [{"text": f"{self.error_message}"}],
                "is_error": True,
            }

        return {
            "content": [{"text": f"Mock result from {tool_name}"}],
            "is_error": False,
        }


class TestSandboxMCPToolWrapperPermission:
    """Test SandboxMCPToolWrapper permission attribute."""

    def test_read_tool_has_read_permission(self):
        """Test that read tools have 'read' permission."""
        adapter = MockSandboxAdapter()
        tool = SandboxMCPToolWrapper(
            sandbox_id="abc123def",
            tool_name="file_read",
            tool_schema={
                "name": "file_read",
                "description": "Read a file",
                "input_schema": {"type": "object", "properties": {}},
            },
            sandbox_adapter=adapter,
        )

        assert tool.permission == "read"
        assert tool.name == "file_read"
        assert tool.sandbox_id == "abc123def"

    def test_write_tool_has_write_permission(self):
        """Test that write tools have 'write' permission."""
        adapter = MockSandboxAdapter()
        tool = SandboxMCPToolWrapper(
            sandbox_id="abc123def",
            tool_name="file_write",
            tool_schema={
                "name": "file_write",
                "description": "Write a file",
                "input_schema": {"type": "object", "properties": {}},
            },
            sandbox_adapter=adapter,
        )

        assert tool.permission == "write"
        assert tool.name == "file_write"
        assert tool.sandbox_id == "abc123def"

    def test_bash_tool_has_bash_permission(self):
        """Test that bash tools have 'bash' permission."""
        adapter = MockSandboxAdapter()
        tool = SandboxMCPToolWrapper(
            sandbox_id="abc123def",
            tool_name="bash",
            tool_schema={
                "name": "bash",
                "description": "Execute bash command",
                "input_schema": {"type": "object", "properties": {}},
            },
            sandbox_adapter=adapter,
        )

        assert tool.permission == "bash"
        assert tool.name == "bash"
        assert tool.sandbox_id == "abc123def"

    def test_unknown_tool_has_ask_permission(self):
        """Test that unknown tools default to 'ask' permission."""
        adapter = MockSandboxAdapter()
        tool = SandboxMCPToolWrapper(
            sandbox_id="abc123def",
            tool_name="unknown_custom_tool",
            tool_schema={
                "name": "unknown_custom_tool",
                "description": "Unknown tool",
                "input_schema": {"type": "object", "properties": {}},
            },
            sandbox_adapter=adapter,
        )

        assert tool.permission == "ask"

    def test_create_file_has_write_permission(self):
        """Test that create_file tool has 'write' permission."""
        adapter = MockSandboxAdapter()
        tool = SandboxMCPToolWrapper(
            sandbox_id="xyz789",
            tool_name="create_file",
            tool_schema={
                "name": "create_file",
                "description": "Create a file",
                "input_schema": {"type": "object", "properties": {}},
            },
            sandbox_adapter=adapter,
        )

        assert tool.permission == "write"

    def test_list_files_has_read_permission(self):
        """Test that list_files tool has 'read' permission."""
        adapter = MockSandboxAdapter()
        tool = SandboxMCPToolWrapper(
            sandbox_id="xyz789",
            tool_name="list_files",
            tool_schema={
                "name": "list_files",
                "description": "List files",
                "input_schema": {"type": "object", "properties": {}},
            },
            sandbox_adapter=adapter,
        )

        assert tool.permission == "read"


class TestSandboxMCPToolWrapperAttributes:
    """Test SandboxMCPToolWrapper attributes."""

    def test_tool_name_is_original_name(self):
        """Test that tool name uses original name without prefix."""
        adapter = MockSandboxAdapter()
        tool = SandboxMCPToolWrapper(
            sandbox_id="test123",
            tool_name="bash",
            tool_schema={
                "name": "bash",
                "description": "Execute bash",
                "input_schema": {"type": "object", "properties": {}},
            },
            sandbox_adapter=adapter,
        )

        assert tool.name == "bash"
        assert tool.sandbox_id == "test123"

    def test_sandbox_id_attribute(self):
        """Test that sandbox_id is stored as attribute."""
        adapter = MockSandboxAdapter()
        tool = SandboxMCPToolWrapper(
            sandbox_id="verylongsandboxid123",
            tool_name="bash",
            tool_schema={
                "name": "bash",
                "description": "Execute bash commands",
                "input_schema": {"type": "object", "properties": {}},
            },
            sandbox_adapter=adapter,
        )

        assert tool.sandbox_id == "verylongsandboxid123"


class TestSandboxMCPToolWrapperParameters:
    """Test SandboxMCPToolWrapper parameter schema conversion."""

    def test_get_parameters_schema_from_mcp_schema(self):
        """Test parameter schema conversion from MCP format."""
        adapter = MockSandboxAdapter()
        tool = SandboxMCPToolWrapper(
            sandbox_id="test123",
            tool_name="file_read",
            tool_schema={
                "name": "file_read",
                "description": "Read file",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "File path",
                        },
                        "offset": {
                            "type": "integer",
                            "description": "Byte offset",
                            "default": 0,
                        },
                    },
                    "required": ["path"],
                },
            },
            sandbox_adapter=adapter,
        )

        schema = tool.get_parameters_schema()

        assert schema["type"] == "object"
        assert "path" in schema["properties"]
        assert schema["properties"]["path"]["type"] == "string"
        assert "path" in schema["required"]
        assert "offset" in schema["properties"]

    def test_validate_args_with_required_params(self):
        """Test argument validation with required parameters."""
        adapter = MockSandboxAdapter()
        tool = SandboxMCPToolWrapper(
            sandbox_id="test123",
            tool_name="file_read",
            tool_schema={
                "name": "file_read",
                "description": "Read file",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                    },
                    "required": ["path"],
                },
            },
            sandbox_adapter=adapter,
        )

        # Valid args
        assert tool.validate_args(path="/tmp/test") is True

        # Missing required arg
        assert tool.validate_args() is False
        assert tool.validate_args(offset=100) is False


class TestSandboxMCPToolWrapperExecute:
    """Test SandboxMCPToolWrapper execution."""

    @pytest.mark.asyncio
    async def test_execute_success(self):
        """Test successful tool execution."""
        adapter = MockSandboxAdapter()
        tool = SandboxMCPToolWrapper(
            sandbox_id="test123",
            tool_name="file_read",
            tool_schema={
                "name": "file_read",
                "description": "Read file",
                "input_schema": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
            },
            sandbox_adapter=adapter,
        )

        result = await tool.execute(path="/tmp/test")

        assert "Mock result from file_read" in result

    @pytest.mark.asyncio
    async def test_execute_error_response(self):
        """Test tool execution with error response."""

        class ErrorAdapter:
            async def call_tool(self, sandbox_id: str, tool_name: str, kwargs: dict):
                return {
                    "content": [{"text": "File not found"}],
                    "is_error": True,
                }

        adapter = ErrorAdapter()
        tool = SandboxMCPToolWrapper(
            sandbox_id="test123",
            tool_name="file_read",
            tool_schema={
                "name": "file_read",
                "description": "Read file",
                "input_schema": {"type": "object", "properties": {}},
            },
            sandbox_adapter=adapter,
        )

        # Should raise RuntimeError for non-retryable errors
        with pytest.raises(RuntimeError) as excinfo:
            await tool.execute(path="/nonexistent")

        assert "Tool execution failed" in str(excinfo.value)
        assert "File not found" in str(excinfo.value)


class TestSandboxMCPToolWrapperRetry:
    """Test SandboxMCPToolWrapper retry mechanism."""

    @pytest.mark.asyncio
    async def test_retry_on_connection_error(self):
        """Test that connection errors trigger retry."""
        # Adapter that fails once then succeeds
        adapter = MockSandboxAdapter(fail_count=1, error_message="connection refused")

        retry_config = RetryConfig(
            max_retries=2,
            base_delay=0.01,  # Short delay for testing
            jitter=False,
        )

        tool = SandboxMCPToolWrapper(
            sandbox_id="test123",
            tool_name="file_read",
            tool_schema={
                "name": "file_read",
                "description": "Read file",
                "input_schema": {"type": "object", "properties": {}},
            },
            sandbox_adapter=adapter,
            retry_config=retry_config,
        )

        result = await tool.execute(path="/tmp/test")

        # Should succeed after retry
        assert "Mock result from file_read" in result
        assert adapter.call_count == 2  # First fail, then success

    @pytest.mark.asyncio
    async def test_no_retry_on_parameter_error(self):
        """Test that parameter errors don't trigger retry."""
        # Adapter that returns parameter error
        adapter = MockSandboxAdapter(
            fail_count=999,  # Always fail
            error_message="missing required parameter: file_path",
        )

        retry_config = RetryConfig(
            max_retries=2,
            base_delay=0.01,
            jitter=False,
        )

        tool = SandboxMCPToolWrapper(
            sandbox_id="test123",
            tool_name="file_read",
            tool_schema={
                "name": "file_read",
                "description": "Read file",
                "input_schema": {"type": "object", "properties": {}},
            },
            sandbox_adapter=adapter,
            retry_config=retry_config,
        )

        # Should raise RuntimeError immediately without retry (parameter error is not retryable)
        with pytest.raises(RuntimeError) as excinfo:
            await tool.execute(path="/tmp/test")

        assert "Tool execution failed" in str(excinfo.value)
        assert adapter.call_count == 1  # No retry

    @pytest.mark.asyncio
    async def test_retry_exhaustion(self):
        """Test behavior when max retries is exhausted."""
        # Adapter that always fails with connection error
        adapter = MockSandboxAdapter(fail_count=999, error_message="connection refused")

        retry_config = RetryConfig(
            max_retries=2,
            base_delay=0.01,
            jitter=False,
        )

        tool = SandboxMCPToolWrapper(
            sandbox_id="test123",
            tool_name="file_read",
            tool_schema={
                "name": "file_read",
                "description": "Read file",
                "input_schema": {"type": "object", "properties": {}},
            },
            sandbox_adapter=adapter,
            retry_config=retry_config,
        )

        # Should raise RuntimeError after exhausting retries
        with pytest.raises(RuntimeError) as excinfo:
            await tool.execute(path="/tmp/test")

        assert "Tool execution failed" in str(excinfo.value)
        # max_retries=2 means 1 initial + 2 retries = 3 total attempts
        assert adapter.call_count == 3

    @pytest.mark.asyncio
    async def test_custom_retry_config(self):
        """Test custom retry configuration."""
        adapter = MockSandboxAdapter(fail_count=2, error_message="connection reset")

        retry_config = RetryConfig(
            max_retries=3,
            base_delay=0.01,
            jitter=False,
        )

        tool = SandboxMCPToolWrapper(
            sandbox_id="test123",
            tool_name="file_read",
            tool_schema={
                "name": "file_read",
                "description": "Read file",
                "input_schema": {"type": "object", "properties": {}},
            },
            sandbox_adapter=adapter,
            retry_config=retry_config,
        )

        result = await tool.execute(path="/tmp/test")

        assert "Mock result from file_read" in result
        assert adapter.call_count == 3  # 2 failures + 1 success


class TestSandboxMCPToolWrapperErrorFieldHandling:
    """Test SandboxMCPToolWrapper error field handling (is_error vs isError)."""

    @pytest.mark.asyncio
    async def test_handles_mcp_isError_field(self):
        """Test that wrapper correctly handles MCP-style isError field."""

        class MCPStyleErrorAdapter:
            async def call_tool(self, sandbox_id: str, tool_name: str, kwargs: dict):
                # Return MCP-style response with isError (camelCase)
                return {
                    "content": [{"text": "File not found"}],
                    "isError": True,  # MCP standard uses camelCase
                }

        adapter = MCPStyleErrorAdapter()
        tool = SandboxMCPToolWrapper(
            sandbox_id="test123",
            tool_name="export_artifact",
            tool_schema={
                "name": "export_artifact",
                "description": "Export artifact",
                "input_schema": {"type": "object", "properties": {}},
            },
            sandbox_adapter=adapter,
        )

        # Should raise RuntimeError when isError=True
        with pytest.raises(RuntimeError) as excinfo:
            await tool.execute(file_path="/nonexistent.txt")

        assert "Tool execution failed" in str(excinfo.value)
        assert "File not found" in str(excinfo.value)

    @pytest.mark.asyncio
    async def test_handles_snake_case_is_error_field(self):
        """Test that wrapper correctly handles snake_case is_error field."""

        class SnakeCaseErrorAdapter:
            async def call_tool(self, sandbox_id: str, tool_name: str, kwargs: dict):
                # Return response with snake_case is_error
                return {
                    "content": [{"text": "Permission denied"}],
                    "is_error": True,  # Some internal code might use snake_case
                }

        adapter = SnakeCaseErrorAdapter()
        tool = SandboxMCPToolWrapper(
            sandbox_id="test123",
            tool_name="file_read",
            tool_schema={
                "name": "file_read",
                "description": "Read file",
                "input_schema": {"type": "object", "properties": {}},
            },
            sandbox_adapter=adapter,
        )

        # Should raise RuntimeError when is_error=True
        with pytest.raises(RuntimeError) as excinfo:
            await tool.execute(path="/etc/passwd")

        assert "Tool execution failed" in str(excinfo.value)

    @pytest.mark.asyncio
    async def test_artifact_result_returned_on_success(self):
        """Test that artifact data is returned on successful export_artifact."""

        class ArtifactSuccessAdapter:
            async def call_tool(self, sandbox_id: str, tool_name: str, kwargs: dict):
                return {
                    "content": [{"type": "text", "text": "File exported"}],
                    "isError": False,
                    "artifact": {
                        "filename": "test.png",
                        "path": "/workspace/test.png",
                        "mime_type": "image/png",
                        "category": "image",
                        "size": 1234,
                        "encoding": "base64",
                        "data": "iVBORw0KGgo=",
                    },
                }

        adapter = ArtifactSuccessAdapter()
        tool = SandboxMCPToolWrapper(
            sandbox_id="test123",
            tool_name="export_artifact",
            tool_schema={
                "name": "export_artifact",
                "description": "Export artifact",
                "input_schema": {"type": "object", "properties": {}},
            },
            sandbox_adapter=adapter,
        )

        result = await tool.execute(file_path="/workspace/test.png")

        # Should return dict with artifact info
        assert isinstance(result, dict)
        assert "artifact" in result
        assert result["artifact"]["filename"] == "test.png"
        assert result["artifact"]["encoding"] == "base64"
