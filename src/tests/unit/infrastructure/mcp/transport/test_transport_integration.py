"""Integration tests for MCP Transport Factory (Phase 7)."""


import pytest

from src.domain.model.mcp.transport import TransportConfig, TransportType
from src.infrastructure.mcp.transport.base import MCPTransportError
from src.infrastructure.mcp.transport.factory import TransportFactory
from src.infrastructure.mcp.transport.http import HTTPTransport
from src.infrastructure.mcp.transport.stdio import StdioTransport
from src.infrastructure.mcp.transport.websocket import WebSocketTransport

# ============================================================================
# TransportFactory Integration Tests
# ============================================================================


class TestTransportFactoryIntegration:
    """Integration tests for TransportFactory."""

    def test_factory_creates_stdio_transport(self):
        """Test factory creates StdioTransport for LOCAL type."""
        config = TransportConfig(
            transport_type=TransportType.LOCAL,
            command=["uvx", "mcp-server-fetch"],
        )

        transport = TransportFactory.create(config)

        assert isinstance(transport, StdioTransport)

    def test_factory_creates_http_transport(self):
        """Test factory creates HTTPTransport for HTTP type."""
        config = TransportConfig(
            transport_type=TransportType.HTTP,
            url="http://localhost:8080/mcp",
        )

        transport = TransportFactory.create(config)

        assert isinstance(transport, HTTPTransport)

    def test_factory_creates_websocket_transport(self):
        """Test factory creates WebSocketTransport for WEBSOCKET type."""
        config = TransportConfig(
            transport_type=TransportType.WEBSOCKET,
            url="ws://localhost:8765/mcp",
        )

        transport = TransportFactory.create(config)

        assert isinstance(transport, WebSocketTransport)

    def test_factory_handles_stdio_alias(self):
        """Test factory handles 'stdio' as alias for LOCAL."""
        config = TransportConfig(
            transport_type=TransportType.STDIO,
            command=["python", "-m", "mcp_server"],
        )

        transport = TransportFactory.create(config)

        assert isinstance(transport, StdioTransport)

    def test_factory_validates_local_requires_command(self):
        """Test factory validates LOCAL transport requires command."""
        # Validation happens in TransportConfig.__post_init__
        with pytest.raises(ValueError, match="Command is required"):
            TransportConfig(
                transport_type=TransportType.LOCAL,
                command=None,  # Missing command
            )

    def test_factory_validates_http_requires_url(self):
        """Test factory validates HTTP transport requires URL."""
        # Validation happens in TransportConfig.__post_init__
        with pytest.raises(ValueError, match="URL is required"):
            TransportConfig(
                transport_type=TransportType.HTTP,
                url=None,  # Missing URL
            )

    def test_factory_validates_websocket_requires_url(self):
        """Test factory validates WebSocket transport requires URL."""
        # Validation happens in TransportConfig.__post_init__
        with pytest.raises(ValueError, match="URL is required"):
            TransportConfig(
                transport_type=TransportType.WEBSOCKET,
                url=None,  # Missing URL
            )


# ============================================================================
# Transport Config Integration Tests
# ============================================================================


class TestTransportConfigIntegration:
    """Integration tests for TransportConfig."""

    def test_config_for_local_mcp_server(self):
        """Test creating config for local MCP server."""
        config = TransportConfig(
            transport_type=TransportType.LOCAL,
            command=["uvx", "mcp-server-filesystem"],
            environment={"HOME": "/home/user"},
            timeout=60000,
        )

        assert config.transport_type == TransportType.LOCAL
        assert config.command == ["uvx", "mcp-server-filesystem"]
        assert config.environment == {"HOME": "/home/user"}
        assert config.timeout == 60000

    def test_config_for_remote_http_server(self):
        """Test creating config for remote HTTP MCP server."""
        config = TransportConfig(
            transport_type=TransportType.HTTP,
            url="https://mcp.example.com/api",
            headers={"Authorization": "Bearer token123"},
            timeout=30000,
        )

        assert config.transport_type == TransportType.HTTP
        assert config.url == "https://mcp.example.com/api"
        assert config.headers == {"Authorization": "Bearer token123"}

    def test_config_for_websocket_sandbox(self):
        """Test creating config for WebSocket sandbox connection."""
        config = TransportConfig(
            transport_type=TransportType.WEBSOCKET,
            url="ws://localhost:18765/mcp/sandbox-123",
            heartbeat_interval=15,
            reconnect_attempts=5,
        )

        assert config.transport_type == TransportType.WEBSOCKET
        assert config.url == "ws://localhost:18765/mcp/sandbox-123"
        assert config.heartbeat_interval == 15
        assert config.reconnect_attempts == 5

    def test_config_immutability(self):
        """Test TransportConfig is immutable (frozen)."""
        config = TransportConfig(
            transport_type=TransportType.LOCAL,
            command=["cmd"],
        )

        with pytest.raises(Exception):  # FrozenInstanceError
            config.timeout = 5000


# ============================================================================
# Transport Type Normalization Tests
# ============================================================================


class TestTransportTypeNormalization:
    """Tests for TransportType normalization."""

    def test_normalize_stdio_to_local(self):
        """Test 'stdio' normalizes to LOCAL."""
        result = TransportType.normalize("stdio")
        assert result == TransportType.LOCAL

    def test_normalize_local_unchanged(self):
        """Test 'local' stays as LOCAL."""
        result = TransportType.normalize("local")
        assert result == TransportType.LOCAL

    def test_normalize_http(self):
        """Test 'http' normalizes correctly."""
        result = TransportType.normalize("http")
        assert result == TransportType.HTTP

    def test_normalize_websocket(self):
        """Test 'websocket' normalizes correctly."""
        result = TransportType.normalize("websocket")
        assert result == TransportType.WEBSOCKET

    def test_normalize_case_insensitive(self):
        """Test normalization is case insensitive."""
        assert TransportType.normalize("LOCAL") == TransportType.LOCAL
        assert TransportType.normalize("HTTP") == TransportType.HTTP
        assert TransportType.normalize("WebSocket") == TransportType.WEBSOCKET

    def test_normalize_with_whitespace(self):
        """Test normalization handles whitespace."""
        assert TransportType.normalize("  local  ") == TransportType.LOCAL
        assert TransportType.normalize("  http  ") == TransportType.HTTP


# ============================================================================
# BaseTransport Protocol Tests
# ============================================================================


class TestBaseTransportProtocol:
    """Tests for BaseTransport protocol compliance."""

    def test_stdio_transport_has_required_methods(self):
        """Test StdioTransport implements required methods."""
        config = TransportConfig(
            transport_type=TransportType.LOCAL,
            command=["echo", "test"],
        )
        transport = StdioTransport(config)

        # Transport uses start/stop instead of connect/disconnect
        assert hasattr(transport, "start")
        assert hasattr(transport, "stop")
        assert hasattr(transport, "send")
        assert hasattr(transport, "receive")
        assert hasattr(transport, "list_tools")
        assert hasattr(transport, "call_tool")

    def test_http_transport_has_required_methods(self):
        """Test HTTPTransport implements required methods."""
        config = TransportConfig(
            transport_type=TransportType.HTTP,
            url="http://localhost:8080",
        )
        transport = HTTPTransport(config)

        # Check for core HTTP transport methods
        assert hasattr(transport, "start")
        assert hasattr(transport, "stop")

    def test_websocket_transport_has_required_methods(self):
        """Test WebSocketTransport implements required methods."""
        config = TransportConfig(
            transport_type=TransportType.WEBSOCKET,
            url="ws://localhost:8765",
        )
        transport = WebSocketTransport(config)

        # Check for core WebSocket transport methods
        assert hasattr(transport, "start")
        assert hasattr(transport, "stop")


# ============================================================================
# Error Handling Tests
# ============================================================================


class TestTransportErrorHandling:
    """Tests for transport error handling."""

    def test_mcp_transport_error_inherits_exception(self):
        """Test MCPTransportError is an Exception."""
        error = MCPTransportError("Test error")
        assert isinstance(error, Exception)
        assert str(error) == "Test error"

    @pytest.mark.asyncio
    async def test_stdio_transport_handles_invalid_command(self):
        """Test StdioTransport handles invalid command gracefully."""
        config = TransportConfig(
            transport_type=TransportType.LOCAL,
            command=["nonexistent_command_xyz_12345"],
        )
        transport = StdioTransport(config)

        with pytest.raises(Exception):  # Should raise on start
            await transport.start(config)

    def test_http_transport_initial_state(self):
        """Test HTTPTransport initial state."""
        config = TransportConfig(
            transport_type=TransportType.HTTP,
            url="http://localhost:9999",
        )
        transport = HTTPTransport(config)

        # Verify transport was created successfully
        assert transport is not None
        assert transport._config == config

    def test_websocket_transport_initial_state(self):
        """Test WebSocketTransport initial state."""
        config = TransportConfig(
            transport_type=TransportType.WEBSOCKET,
            url="ws://localhost:9999",
        )
        transport = WebSocketTransport(config)

        # Verify transport was created successfully
        assert transport is not None
        assert transport._config == config
