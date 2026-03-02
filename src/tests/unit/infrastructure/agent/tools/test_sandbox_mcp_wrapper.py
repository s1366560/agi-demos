"""Unit tests for create_sandbox_mcp_tool.

TDD: Tests written first (RED phase).
"""


from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.mcp_errors import RetryConfig
from src.infrastructure.agent.tools.sandbox_tool_wrapper import (
    create_sandbox_mcp_tool,
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


class MockSandboxAdapter:
    """Mock sandbox adapter for testing."""

    def __init__(self, fail_count=0, error_message="Test error") -> None:
        """Initialize mock with failure simulation.

        Args:
            fail_count: Number of times to fail before succeeding
            error_message: Error message to return on failure
        """
        self.fail_count = fail_count
        self.call_count = 0
        self.error_message = error_message

    async def call_tool(self, sandbox_id: str, tool_name: str, kwargs: dict, **kw):
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


class TestSandboxMCPToolPermission:
    """Test create_sandbox_mcp_tool permission attribute."""

    def test_read_tool_has_read_permission(self):
        """Test that read tools have 'read' permission."""
        adapter = MockSandboxAdapter()
        tool = create_sandbox_mcp_tool(
            sandbox_id="abc123def",
            tool_name="file_read",
            tool_schema={
                "name": "file_read",
                "description": "Read a file",
                "input_schema": {
                    "type": "object",
                    "properties": {},
                },
            },
            sandbox_port=adapter,
        )

        assert tool.permission == "read"
        assert tool.name == "file_read"

    def test_write_tool_has_write_permission(self):
        """Test that write tools have 'write' permission."""
        adapter = MockSandboxAdapter()
        tool = create_sandbox_mcp_tool(
            sandbox_id="abc123def",
            tool_name="file_write",
            tool_schema={
                "name": "file_write",
                "description": "Write a file",
                "input_schema": {
                    "type": "object",
                    "properties": {},
                },
            },
            sandbox_port=adapter,
        )

        assert tool.permission == "write"
        assert tool.name == "file_write"

    def test_bash_tool_has_bash_permission(self):
        """Test that bash tools have 'bash' permission."""
        adapter = MockSandboxAdapter()
        tool = create_sandbox_mcp_tool(
            sandbox_id="abc123def",
            tool_name="bash",
            tool_schema={
                "name": "bash",
                "description": "Execute bash command",
                "input_schema": {
                    "type": "object",
                    "properties": {},
                },
            },
            sandbox_port=adapter,
        )

        assert tool.permission == "bash"
        assert tool.name == "bash"

    def test_unknown_tool_has_ask_permission(self):
        """Test that unknown tools default to 'ask' permission."""
        adapter = MockSandboxAdapter()
        tool = create_sandbox_mcp_tool(
            sandbox_id="abc123def",
            tool_name="unknown_custom_tool",
            tool_schema={
                "name": "unknown_custom_tool",
                "description": "Unknown tool",
                "input_schema": {
                    "type": "object",
                    "properties": {},
                },
            },
            sandbox_port=adapter,
        )

        assert tool.permission == "ask"

    def test_create_file_has_write_permission(self):
        """Test that create_file tool has 'write' permission."""
        adapter = MockSandboxAdapter()
        tool = create_sandbox_mcp_tool(
            sandbox_id="xyz789",
            tool_name="create_file",
            tool_schema={
                "name": "create_file",
                "description": "Create a file",
                "input_schema": {
                    "type": "object",
                    "properties": {},
                },
            },
            sandbox_port=adapter,
        )

        assert tool.permission == "write"

    def test_list_files_has_read_permission(self):
        """Test that list_files tool has 'read' permission."""
        adapter = MockSandboxAdapter()
        tool = create_sandbox_mcp_tool(
            sandbox_id="xyz789",
            tool_name="list_files",
            tool_schema={
                "name": "list_files",
                "description": "List files",
                "input_schema": {
                    "type": "object",
                    "properties": {},
                },
            },
            sandbox_port=adapter,
        )

        assert tool.permission == "read"


class TestSandboxMCPToolAttributes:
    """Test create_sandbox_mcp_tool attributes."""

    def test_tool_name_is_original_name(self):
        """Test that tool name uses original name without prefix."""
        adapter = MockSandboxAdapter()
        tool = create_sandbox_mcp_tool(
            sandbox_id="test123",
            tool_name="bash",
            tool_schema={
                "name": "bash",
                "description": "Execute bash",
                "input_schema": {
                    "type": "object",
                    "properties": {},
                },
            },
            sandbox_port=adapter,
        )

        assert tool.name == "bash"

    def test_tool_description_from_schema(self):
        """Test that tool description comes from schema."""
        adapter = MockSandboxAdapter()
        tool = create_sandbox_mcp_tool(
            sandbox_id="test123",
            tool_name="bash",
            tool_schema={
                "name": "bash",
                "description": "Execute bash commands",
                "input_schema": {
                    "type": "object",
                    "properties": {},
                },
            },
            sandbox_port=adapter,
        )

        assert tool.description == "Execute bash commands"


class TestSandboxMCPToolParameters:
    """Test create_sandbox_mcp_tool parameter schema conversion."""

    def test_parameters_from_mcp_schema(self):
        """Test parameter schema conversion from MCP format."""
        adapter = MockSandboxAdapter()
        tool = create_sandbox_mcp_tool(
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
            sandbox_port=adapter,
        )

        schema = tool.parameters

        assert schema["type"] == "object"
        assert "path" in schema["properties"]
        assert schema["properties"]["path"]["type"] == "string"
        assert "path" in schema["required"]
        assert "offset" in schema["properties"]


class TestSandboxMCPToolExecute:
    """Test create_sandbox_mcp_tool execution."""

    async def test_execute_success(self):
        """Test successful tool execution."""
        adapter = MockSandboxAdapter()
        tool = create_sandbox_mcp_tool(
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
            sandbox_port=adapter,
        )

        ctx = _make_ctx()
        result = await tool.execute(ctx, path="/tmp/test")

        assert "Mock result from file_read" in result.output

    async def test_execute_error_response(self):
        """Test tool execution with error response."""

        class ErrorAdapter:
            async def call_tool(
                self,
                sandbox_id: str,
                tool_name: str,
                kwargs: dict,
                **kw,
            ):
                return {
                    "content": [{"text": "File not found"}],
                    "is_error": True,
                }

        adapter = ErrorAdapter()
        tool = create_sandbox_mcp_tool(
            sandbox_id="test123",
            tool_name="file_read",
            tool_schema={
                "name": "file_read",
                "description": "Read file",
                "input_schema": {
                    "type": "object",
                    "properties": {},
                },
            },
            sandbox_port=adapter,
        )

        ctx = _make_ctx()
        result = await tool.execute(ctx, path="/nonexistent")

        # New API catches RuntimeError and returns ToolResult
        assert result.is_error is True
        assert "Tool execution failed" in result.output
        assert "File not found" in result.output


class TestSandboxMCPToolRetry:
    """Test create_sandbox_mcp_tool retry mechanism."""

    async def test_retry_on_connection_error(self):
        """Test that connection errors trigger retry."""
        # Adapter that fails once then succeeds
        adapter = MockSandboxAdapter(fail_count=1, error_message="connection refused")

        retry_config = RetryConfig(
            max_retries=2,
            base_delay=0.01,  # Short delay for testing
            jitter=False,
        )

        tool = create_sandbox_mcp_tool(
            sandbox_id="test123",
            tool_name="file_read",
            tool_schema={
                "name": "file_read",
                "description": "Read file",
                "input_schema": {
                    "type": "object",
                    "properties": {},
                },
            },
            sandbox_port=adapter,
            retry_config=retry_config,
        )

        ctx = _make_ctx()
        result = await tool.execute(ctx, path="/tmp/test")

        # Should succeed after retry
        assert "Mock result from file_read" in result.output
        assert adapter.call_count == 2  # First fail, then success

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

        tool = create_sandbox_mcp_tool(
            sandbox_id="test123",
            tool_name="file_read",
            tool_schema={
                "name": "file_read",
                "description": "Read file",
                "input_schema": {
                    "type": "object",
                    "properties": {},
                },
            },
            sandbox_port=adapter,
            retry_config=retry_config,
        )

        ctx = _make_ctx()
        result = await tool.execute(ctx, path="/tmp/test")

        # New API returns ToolResult with is_error=True
        assert result.is_error is True
        assert "Tool execution failed" in result.output
        assert adapter.call_count == 1  # No retry

    async def test_retry_exhaustion(self):
        """Test behavior when max retries is exhausted."""
        # Adapter that always fails with connection error
        adapter = MockSandboxAdapter(fail_count=999, error_message="connection refused")

        retry_config = RetryConfig(
            max_retries=2,
            base_delay=0.01,
            jitter=False,
        )

        tool = create_sandbox_mcp_tool(
            sandbox_id="test123",
            tool_name="file_read",
            tool_schema={
                "name": "file_read",
                "description": "Read file",
                "input_schema": {
                    "type": "object",
                    "properties": {},
                },
            },
            sandbox_port=adapter,
            retry_config=retry_config,
        )

        ctx = _make_ctx()
        result = await tool.execute(ctx, path="/tmp/test")

        # New API returns ToolResult with is_error=True
        assert result.is_error is True
        assert "Tool execution failed" in result.output
        # max_retries=2 means 1 initial + 2 retries = 3 total
        assert adapter.call_count == 3

    async def test_custom_retry_config(self):
        """Test custom retry configuration."""
        adapter = MockSandboxAdapter(fail_count=2, error_message="connection reset")

        retry_config = RetryConfig(
            max_retries=3,
            base_delay=0.01,
            jitter=False,
        )

        tool = create_sandbox_mcp_tool(
            sandbox_id="test123",
            tool_name="file_read",
            tool_schema={
                "name": "file_read",
                "description": "Read file",
                "input_schema": {
                    "type": "object",
                    "properties": {},
                },
            },
            sandbox_port=adapter,
            retry_config=retry_config,
        )

        ctx = _make_ctx()
        result = await tool.execute(ctx, path="/tmp/test")

        assert "Mock result from file_read" in result.output
        assert adapter.call_count == 3  # 2 failures + 1 success


class TestSandboxMCPToolErrorFieldHandling:
    """Test create_sandbox_mcp_tool error field handling."""

    async def test_handles_mcp_isError_field(self):
        """Test that wrapper handles MCP-style isError field."""

        class MCPStyleErrorAdapter:
            async def call_tool(
                self,
                sandbox_id: str,
                tool_name: str,
                kwargs: dict,
                **kw,
            ):
                # Return MCP-style response with isError (camelCase)
                return {
                    "content": [{"text": "File not found"}],
                    "isError": True,  # MCP standard uses camelCase
                }

        adapter = MCPStyleErrorAdapter()
        tool = create_sandbox_mcp_tool(
            sandbox_id="test123",
            tool_name="export_artifact",
            tool_schema={
                "name": "export_artifact",
                "description": "Export artifact",
                "input_schema": {
                    "type": "object",
                    "properties": {},
                },
            },
            sandbox_port=adapter,
        )

        ctx = _make_ctx()
        result = await tool.execute(ctx, file_path="/nonexistent.txt")

        # New API returns ToolResult with is_error=True
        assert result.is_error is True
        assert "Tool execution failed" in result.output
        assert "File not found" in result.output

    async def test_handles_snake_case_is_error_field(self):
        """Test that wrapper handles snake_case is_error field."""

        class SnakeCaseErrorAdapter:
            async def call_tool(
                self,
                sandbox_id: str,
                tool_name: str,
                kwargs: dict,
                **kw,
            ):
                # Return response with snake_case is_error
                return {
                    "content": [{"text": "Permission denied"}],
                    "is_error": True,
                }

        adapter = SnakeCaseErrorAdapter()
        tool = create_sandbox_mcp_tool(
            sandbox_id="test123",
            tool_name="file_read",
            tool_schema={
                "name": "file_read",
                "description": "Read file",
                "input_schema": {
                    "type": "object",
                    "properties": {},
                },
            },
            sandbox_port=adapter,
        )

        ctx = _make_ctx()
        result = await tool.execute(ctx, path="/etc/passwd")

        # New API returns ToolResult with is_error=True
        assert result.is_error is True
        assert "Tool execution failed" in result.output

    async def test_artifact_result_returned_on_success(self):
        """Test that artifact data is returned on success."""

        class ArtifactSuccessAdapter:
            async def call_tool(
                self,
                sandbox_id: str,
                tool_name: str,
                kwargs: dict,
                **kw,
            ):
                return {
                    "content": [
                        {"type": "text", "text": "File exported"},
                    ],
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
        tool = create_sandbox_mcp_tool(
            sandbox_id="test123",
            tool_name="export_artifact",
            tool_schema={
                "name": "export_artifact",
                "description": "Export artifact",
                "input_schema": {
                    "type": "object",
                    "properties": {},
                },
            },
            sandbox_port=adapter,
        )

        ctx = _make_ctx()
        result = await tool.execute(ctx, file_path="/workspace/test.png")

        # New API returns ToolResult with artifact info string
        assert result.is_error is False
        assert "test.png" in result.output
        assert "image/png" in result.output
        assert "1234" in result.output
        assert "image" in result.output
