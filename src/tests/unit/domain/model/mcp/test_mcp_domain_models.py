"""Unit tests for MCP domain models."""

import pytest

# ============================================================================
# Transport Tests
# ============================================================================


class TestTransportType:
    """Tests for TransportType enum."""

    def test_transport_type_values(self):
        """Test all transport type values exist."""
        from src.domain.model.mcp.transport import TransportType

        assert TransportType.LOCAL.value == "local"
        assert TransportType.STDIO.value == "stdio"
        assert TransportType.HTTP.value == "http"
        assert TransportType.SSE.value == "sse"
        assert TransportType.WEBSOCKET.value == "websocket"

    def test_normalize_local(self):
        """Test normalize converts stdio to local."""
        from src.domain.model.mcp.transport import TransportType

        assert TransportType.normalize("stdio") == TransportType.LOCAL
        assert TransportType.normalize("STDIO") == TransportType.LOCAL
        assert TransportType.normalize("local") == TransportType.LOCAL

    def test_normalize_other_types(self):
        """Test normalize handles other transport types."""
        from src.domain.model.mcp.transport import TransportType

        assert TransportType.normalize("http") == TransportType.HTTP
        assert TransportType.normalize("HTTP") == TransportType.HTTP
        assert TransportType.normalize("sse") == TransportType.SSE
        assert TransportType.normalize("websocket") == TransportType.WEBSOCKET


class TestTransportConfig:
    """Tests for TransportConfig value object."""

    def test_local_transport_requires_command(self):
        """Test local transport requires command."""
        from src.domain.model.mcp.transport import TransportConfig, TransportType

        with pytest.raises(ValueError, match="Command is required"):
            TransportConfig(transport_type=TransportType.LOCAL)

    def test_http_transport_requires_url(self):
        """Test HTTP transport requires URL."""
        from src.domain.model.mcp.transport import TransportConfig, TransportType

        with pytest.raises(ValueError, match="URL is required"):
            TransportConfig(transport_type=TransportType.HTTP)

    def test_websocket_transport_requires_url(self):
        """Test WebSocket transport requires URL."""
        from src.domain.model.mcp.transport import TransportConfig, TransportType

        with pytest.raises(ValueError, match="URL is required"):
            TransportConfig(transport_type=TransportType.WEBSOCKET)

    def test_local_factory_method(self):
        """Test local factory creates correct config."""
        from src.domain.model.mcp.transport import TransportConfig, TransportType

        config = TransportConfig.local(
            command=["uvx", "mcp-server-fetch"],
            environment={"DEBUG": "true"},
            timeout=60000,
        )

        assert config.transport_type == TransportType.LOCAL
        assert config.command == ["uvx", "mcp-server-fetch"]
        assert config.environment == {"DEBUG": "true"}
        assert config.timeout == 60000

    def test_websocket_factory_method(self):
        """Test websocket factory creates correct config."""
        from src.domain.model.mcp.transport import TransportConfig, TransportType

        config = TransportConfig.websocket(
            url="ws://localhost:8765",
            headers={"Authorization": "Bearer token"},
            heartbeat_interval=15,
            reconnect_attempts=5,
        )

        assert config.transport_type == TransportType.WEBSOCKET
        assert config.url == "ws://localhost:8765"
        assert config.heartbeat_interval == 15
        assert config.reconnect_attempts == 5

    def test_timeout_seconds_property(self):
        """Test timeout_seconds converts ms to seconds."""
        from src.domain.model.mcp.transport import TransportConfig

        config = TransportConfig.local(command=["test"], timeout=30000)
        assert config.timeout_seconds == 30.0

    def test_to_dict_and_from_dict(self):
        """Test serialization roundtrip."""
        from src.domain.model.mcp.transport import TransportConfig

        original = TransportConfig.websocket(
            url="ws://localhost:8765",
            headers={"X-Custom": "value"},
        )
        data = original.to_dict()
        restored = TransportConfig.from_dict(data)

        assert restored.transport_type == original.transport_type
        assert restored.url == original.url
        assert restored.headers == original.headers


# ============================================================================
# Tool Tests
# ============================================================================


class TestMCPToolSchema:
    """Tests for MCPToolSchema value object."""

    def test_create_minimal(self):
        """Test creating schema with minimal data."""
        from src.domain.model.mcp.tool import MCPToolSchema

        schema = MCPToolSchema(name="read_file")

        assert schema.name == "read_file"
        assert schema.description is None
        assert schema.input_schema == {}

    def test_create_full(self):
        """Test creating schema with full data."""
        from src.domain.model.mcp.tool import MCPToolSchema

        schema = MCPToolSchema(
            name="read_file",
            description="Read a file from the filesystem",
            input_schema={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        )

        assert schema.name == "read_file"
        assert schema.description == "Read a file from the filesystem"
        assert "path" in schema.input_schema["properties"]

    def test_from_dict_with_inputSchema(self):
        """Test from_dict handles MCP protocol format (inputSchema)."""
        from src.domain.model.mcp.tool import MCPToolSchema

        data = {
            "name": "bash",
            "description": "Run bash command",
            "inputSchema": {"type": "object", "properties": {"command": {"type": "string"}}},
        }
        schema = MCPToolSchema.from_dict(data)

        assert schema.name == "bash"
        assert schema.input_schema["type"] == "object"

    def test_from_dict_with_input_schema(self):
        """Test from_dict handles snake_case format."""
        from src.domain.model.mcp.tool import MCPToolSchema

        data = {
            "name": "bash",
            "input_schema": {"type": "object"},
        }
        schema = MCPToolSchema.from_dict(data)
        assert schema.input_schema["type"] == "object"


class TestMCPToolResult:
    """Tests for MCPToolResult value object."""

    def test_success_factory(self):
        """Test success factory method."""
        from src.domain.model.mcp.tool import MCPToolResult

        result = MCPToolResult.success(
            content=[{"type": "text", "text": "Hello, World!"}],
            execution_time_ms=100,
        )

        assert not result.is_error
        assert result.error_message is None
        assert result.execution_time_ms == 100
        assert len(result.content) == 1

    def test_error_factory(self):
        """Test error factory method."""
        from src.domain.model.mcp.tool import MCPToolResult

        result = MCPToolResult.error("File not found", execution_time_ms=50)

        assert result.is_error
        assert result.error_message == "File not found"
        assert result.content[0]["text"] == "File not found"

    def test_get_text_content(self):
        """Test extracting text content."""
        from src.domain.model.mcp.tool import MCPToolResult

        result = MCPToolResult(
            content=[
                {"type": "text", "text": "Line 1"},
                {"type": "text", "text": "Line 2"},
            ]
        )

        text = result.get_text_content()
        assert text == "Line 1\nLine 2"

    def test_from_dict_handles_isError(self):
        """Test from_dict handles MCP protocol format (isError)."""
        from src.domain.model.mcp.tool import MCPToolResult

        data = {
            "content": [{"type": "text", "text": "Error occurred"}],
            "isError": True,
        }
        result = MCPToolResult.from_dict(data)
        assert result.is_error is True


class TestMCPTool:
    """Tests for MCPTool entity."""

    def test_full_name_generation(self):
        """Test full name includes server prefix."""
        from src.domain.model.mcp.tool import MCPTool, MCPToolSchema

        tool = MCPTool(
            server_id="srv-123",
            server_name="filesystem",
            schema=MCPToolSchema(name="read_file"),
        )

        assert tool.full_name == "mcp__filesystem__read_file"

    def test_full_name_replaces_dashes(self):
        """Test full name replaces dashes with underscores."""
        from src.domain.model.mcp.tool import MCPTool, MCPToolSchema

        tool = MCPTool(
            server_id="srv-123",
            server_name="my-server",
            schema=MCPToolSchema(name="do_something"),
        )

        assert tool.full_name == "mcp__my_server__do_something"

    def test_description_fallback(self):
        """Test description uses fallback when not provided."""
        from src.domain.model.mcp.tool import MCPTool, MCPToolSchema

        tool = MCPTool(
            server_id="srv-123",
            server_name="fetch",
            schema=MCPToolSchema(name="get_url"),
        )

        assert "MCP tool get_url from fetch" in tool.description


# ============================================================================
# Connection Tests
# ============================================================================


class TestConnectionState:
    """Tests for ConnectionState enum."""

    def test_is_active_for_connected(self):
        """Test is_active returns True for connected state."""
        from src.domain.model.mcp.connection import ConnectionState

        assert ConnectionState.CONNECTED.is_active is True

    def test_is_active_for_connecting(self):
        """Test is_active returns True for connecting state."""
        from src.domain.model.mcp.connection import ConnectionState

        assert ConnectionState.CONNECTING.is_active is True

    def test_is_active_for_disconnected(self):
        """Test is_active returns False for disconnected state."""
        from src.domain.model.mcp.connection import ConnectionState

        assert ConnectionState.DISCONNECTED.is_active is False

    def test_is_active_for_error(self):
        """Test is_active returns False for error state."""
        from src.domain.model.mcp.connection import ConnectionState

        assert ConnectionState.ERROR.is_active is False


class TestConnectionInfo:
    """Tests for ConnectionInfo value object."""

    def test_create_default(self):
        """Test creating with default values."""
        from src.domain.model.mcp.connection import ConnectionInfo, ConnectionState

        info = ConnectionInfo(endpoint="ws://localhost:8765")

        assert info.endpoint == "ws://localhost:8765"
        assert info.state == ConnectionState.DISCONNECTED
        assert not info.is_connected
        assert info.tools == []

    def test_mark_connected(self):
        """Test marking as connected."""
        from src.domain.model.mcp.connection import ConnectionInfo, ConnectionState

        info = ConnectionInfo(endpoint="ws://localhost:8765")
        connected = info.mark_connected(server_info={"name": "test"})

        assert connected.state == ConnectionState.CONNECTED
        assert connected.is_connected
        assert connected.connected_at is not None
        assert connected.server_info == {"name": "test"}

    def test_mark_disconnected_with_error(self):
        """Test marking as disconnected with error."""
        from src.domain.model.mcp.connection import ConnectionInfo, ConnectionState

        info = ConnectionInfo(endpoint="ws://localhost:8765")
        connected = info.mark_connected()
        disconnected = connected.mark_disconnected(error_message="Connection lost")

        assert disconnected.state == ConnectionState.ERROR
        assert disconnected.error_message == "Connection lost"
        assert disconnected.disconnected_at is not None

    def test_increment_reconnect(self):
        """Test incrementing reconnect count."""
        from src.domain.model.mcp.connection import ConnectionInfo, ConnectionState

        info = ConnectionInfo(endpoint="ws://localhost:8765")
        reconnecting = info.increment_reconnect()

        assert reconnecting.state == ConnectionState.RECONNECTING
        assert reconnecting.reconnect_count == 1

        reconnecting2 = reconnecting.increment_reconnect()
        assert reconnecting2.reconnect_count == 2


class TestConnectionMetrics:
    """Tests for ConnectionMetrics."""

    def test_record_connection_success(self):
        """Test recording successful connection."""
        from src.domain.model.mcp.connection import ConnectionMetrics

        metrics = ConnectionMetrics()
        metrics.record_connection_success()

        assert metrics.total_connections == 1
        assert metrics.successful_connections == 1
        assert metrics.connection_success_rate == 1.0

    def test_record_connection_failure(self):
        """Test recording failed connection."""
        from src.domain.model.mcp.connection import ConnectionMetrics

        metrics = ConnectionMetrics()
        metrics.record_connection_failure("Connection refused")

        assert metrics.total_connections == 1
        assert metrics.failed_connections == 1
        assert metrics.connection_success_rate == 0.0
        assert metrics.last_error == "Connection refused"

    def test_record_tool_call(self):
        """Test recording tool calls."""
        from src.domain.model.mcp.connection import ConnectionMetrics

        metrics = ConnectionMetrics()
        metrics.record_tool_call(success=True, latency_ms=100)
        metrics.record_tool_call(success=True, latency_ms=200)
        metrics.record_tool_call(success=False, latency_ms=50)

        assert metrics.total_tool_calls == 3
        assert metrics.successful_tool_calls == 2
        assert metrics.failed_tool_calls == 1
        assert metrics.tool_call_success_rate == pytest.approx(2 / 3, rel=0.01)


# ============================================================================
# Server Tests
# ============================================================================


class TestMCPServerStatus:
    """Tests for MCPServerStatus value object."""

    def test_connected_status_factory(self):
        """Test connected_status factory."""
        from src.domain.model.mcp.server import MCPServerStatus, MCPServerStatusType

        status = MCPServerStatus.connected_status(tool_count=5)

        assert status.status == MCPServerStatusType.CONNECTED
        assert status.connected is True
        assert status.tool_count == 5
        assert status.last_check_at is not None

    def test_failed_status_factory(self):
        """Test failed_status factory."""
        from src.domain.model.mcp.server import MCPServerStatus, MCPServerStatusType

        status = MCPServerStatus.failed_status("Connection timeout")

        assert status.status == MCPServerStatusType.FAILED
        assert status.connected is False
        assert status.error == "Connection timeout"

    def test_status_is_immutable(self):
        """Test status is immutable (frozen dataclass)."""
        from src.domain.model.mcp.server import MCPServerStatus

        status = MCPServerStatus.disconnected_status()

        with pytest.raises(Exception):  # FrozenInstanceError
            status.connected = True


class TestMCPServerConfig:
    """Tests for MCPServerConfig."""

    def test_local_config_validation(self):
        """Test local config requires command."""
        from src.domain.model.mcp.server import MCPServerConfig
        from src.domain.model.mcp.transport import TransportType

        with pytest.raises(ValueError, match="Command is required"):
            MCPServerConfig(
                server_name="test",
                tenant_id="tenant-1",
                transport_type=TransportType.LOCAL,
            )

    def test_remote_config_validation(self):
        """Test remote config requires URL."""
        from src.domain.model.mcp.server import MCPServerConfig
        from src.domain.model.mcp.transport import TransportType

        with pytest.raises(ValueError, match="URL is required"):
            MCPServerConfig(
                server_name="test",
                tenant_id="tenant-1",
                transport_type=TransportType.HTTP,
            )

    def test_valid_local_config(self):
        """Test creating valid local config."""
        from src.domain.model.mcp.server import MCPServerConfig
        from src.domain.model.mcp.transport import TransportType

        config = MCPServerConfig(
            server_name="fetch",
            tenant_id="tenant-1",
            transport_type=TransportType.LOCAL,
            command=["uvx", "mcp-server-fetch"],
        )

        assert config.server_name == "fetch"
        assert config.command == ["uvx", "mcp-server-fetch"]

    def test_to_transport_config(self):
        """Test converting to TransportConfig."""
        from src.domain.model.mcp.server import MCPServerConfig
        from src.domain.model.mcp.transport import TransportType

        config = MCPServerConfig(
            server_name="fetch",
            tenant_id="tenant-1",
            transport_type=TransportType.LOCAL,
            command=["uvx", "mcp-server-fetch"],
            timeout=60000,
        )

        transport = config.to_transport_config()

        assert transport.transport_type == TransportType.LOCAL
        assert transport.command == ["uvx", "mcp-server-fetch"]
        assert transport.timeout == 60000


class TestMCPServer:
    """Tests for MCPServer entity."""

    def test_create_server(self):
        """Test creating server entity."""
        from src.domain.model.mcp.server import MCPServer

        server = MCPServer(
            id="srv-123",
            tenant_id="tenant-1",
            name="fetch",
            description="Fetch server for HTTP requests",
        )

        assert server.id == "srv-123"
        assert server.name == "fetch"
        assert not server.is_connected
        assert server.tool_count == 0

    def test_update_status(self):
        """Test updating server status."""
        from src.domain.model.mcp.server import MCPServer, MCPServerStatus

        server = MCPServer(id="srv-123", tenant_id="tenant-1", name="fetch")
        new_status = MCPServerStatus.connected_status(tool_count=3)
        server.update_status(new_status)

        assert server.is_connected
        assert server.status.tool_count == 3

    def test_update_tools(self):
        """Test updating discovered tools."""
        from src.domain.model.mcp.server import MCPServer
        from src.domain.model.mcp.tool import MCPToolSchema

        server = MCPServer(id="srv-123", tenant_id="tenant-1", name="fetch")
        tools = [
            MCPToolSchema(name="fetch"),
            MCPToolSchema(name="get_html"),
        ]
        server.update_tools(tools)

        assert server.tool_count == 2
        assert server.last_sync_at is not None

    def test_to_dict(self):
        """Test converting to dictionary."""
        from src.domain.model.mcp.server import MCPServer, MCPServerStatus
        from src.domain.model.mcp.tool import MCPToolSchema

        server = MCPServer(
            id="srv-123",
            tenant_id="tenant-1",
            name="fetch",
            workflow_id="wf-456",
        )
        server.update_status(MCPServerStatus.connected_status(tool_count=2))
        server.update_tools([MCPToolSchema(name="tool1"), MCPToolSchema(name="tool2")])

        data = server.to_dict()

        assert data["id"] == "srv-123"
        assert data["name"] == "fetch"
        assert data["status"] == "connected"
        assert data["connected"] is True
        assert data["tool_count"] == 2
        assert data["workflow_id"] == "wf-456"
