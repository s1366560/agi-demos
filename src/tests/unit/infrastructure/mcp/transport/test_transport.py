"""Unit tests for MCP transport layer."""

import asyncio
import logging
from typing import Any, cast

import pytest

from src.domain.model.mcp.transport import TransportConfig, TransportType
from src.infrastructure.mcp.transport.base import (
    MCPTransportClosedError,
    MCPTransportError,
)
from src.infrastructure.mcp.transport.factory import TransportFactory

STDIO_LOGGER_NAME = "src.infrastructure.mcp.transport.stdio"


class _ClosedStdout:
    async def readline(self) -> bytes:
        return b""


class _HangingStdout:
    async def readline(self) -> bytes:
        await asyncio.sleep(10)
        return b""


class _FakeStderr:
    def __init__(self, data: bytes) -> None:
        self._data = data

    async def read(self) -> bytes:
        return self._data


class _FakeProcess:
    def __init__(self, stdout: Any, stderr: Any, returncode: int | None = 1) -> None:
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


# ============================================================================
# TransportFactory Tests
# ============================================================================


class TestTransportFactory:
    """Tests for TransportFactory."""

    def test_get_supported_types(self):
        """Test getting supported transport types."""
        types = TransportFactory().get_supported_types()
        assert "local" in types
        assert "stdio" in types
        assert "http" in types
        assert "sse" in types
        assert "websocket" in types

    def test_supports_local(self):
        """Test supports returns True for local."""
        assert TransportFactory().supports("local") is True

    def test_supports_stdio(self):
        """Test supports returns True for stdio."""
        assert TransportFactory().supports("stdio") is True

    def test_supports_websocket(self):
        """Test supports returns True for websocket."""
        assert TransportFactory().supports("websocket") is True

    def test_supports_sse(self):
        """Test supports returns True for SSE."""
        assert TransportFactory().supports("sse") is True

    def test_supports_unknown(self):
        """Test supports returns False for unknown type."""
        assert TransportFactory().supports("unknown") is False

    def test_create_stdio_transport(self):
        """Test creating stdio transport."""
        from src.infrastructure.mcp.transport.stdio import StdioTransport

        config = TransportConfig.local(command=["uvx", "test"])
        transport = TransportFactory().create(config)

        assert isinstance(transport, StdioTransport)

    def test_create_http_transport(self):
        """Test creating HTTP transport."""
        from src.infrastructure.mcp.transport.http import HTTPTransport

        config = TransportConfig.http(url="http://localhost:8080")
        transport = TransportFactory().create(config)

        assert isinstance(transport, HTTPTransport)

    def test_create_sse_transport(self):
        """Test creating SSE transport."""
        from src.infrastructure.mcp.transport.sse import SSETransport

        config = TransportConfig.sse(url="http://localhost:8080/mcp")
        transport = TransportFactory().create(config)

        assert isinstance(transport, SSETransport)

    def test_create_websocket_transport(self):
        """Test creating WebSocket transport."""
        from src.infrastructure.mcp.transport.websocket import WebSocketTransport

        config = TransportConfig.websocket(url="ws://localhost:8765")
        transport = TransportFactory().create(config)

        assert isinstance(transport, WebSocketTransport)

    def test_create_from_type_stdio(self):
        """Test create_from_type with stdio."""
        from src.infrastructure.mcp.transport.stdio import StdioTransport

        transport = TransportFactory().create_from_type(
            "stdio",
            {"command": ["uvx", "test"]},
        )

        assert isinstance(transport, StdioTransport)

    def test_create_from_type_websocket(self):
        """Test create_from_type with websocket."""
        from src.infrastructure.mcp.transport.websocket import WebSocketTransport

        transport = TransportFactory().create_from_type(
            "websocket",
            {"url": "ws://localhost:8765"},
        )

        assert isinstance(transport, WebSocketTransport)

    def test_create_from_type_sse(self):
        """Test create_from_type with SSE."""
        from src.infrastructure.mcp.transport.sse import SSETransport

        transport = TransportFactory().create_from_type(
            "sse",
            {"url": "http://localhost:8080/mcp"},
        )

        assert isinstance(transport, SSETransport)


# ============================================================================
# StdioTransport Tests
# ============================================================================


class TestStdioTransport:
    """Tests for StdioTransport."""

    def test_init(self):
        """Test initialization."""
        from src.infrastructure.mcp.transport.stdio import StdioTransport

        transport = StdioTransport()
        assert not transport.is_open
        assert transport.config is None

    def test_init_with_config(self):
        """Test initialization with config."""
        from src.infrastructure.mcp.transport.stdio import StdioTransport

        config = TransportConfig.local(command=["test"])
        transport = StdioTransport(config)

        assert transport.config == config

    @pytest.mark.asyncio
    async def test_start_requires_command(self):
        """Test start fails without command."""
        from src.infrastructure.mcp.transport.stdio import StdioTransport

        transport = StdioTransport()
        config = TransportConfig(transport_type=TransportType.HTTP, url="http://test")

        with pytest.raises(MCPTransportError, match="Invalid transport type"):
            await transport.start(config)

    @pytest.mark.asyncio
    async def test_send_when_not_connected(self):
        """Test send raises when not connected."""
        from src.infrastructure.mcp.transport.stdio import StdioTransport

        transport = StdioTransport()

        with pytest.raises(MCPTransportClosedError):
            await transport.send({"test": "message"})

    @pytest.mark.asyncio
    async def test_receive_when_not_connected(self):
        """Test receive raises when not connected."""
        from src.infrastructure.mcp.transport.stdio import StdioTransport

        transport = StdioTransport()

        with pytest.raises(MCPTransportClosedError):
            await transport.receive()

    @pytest.mark.asyncio
    async def test_receive_closed_connection_log_redacts_stderr(self, caplog):
        """Closed subprocess stderr should not be copied into logs."""
        from src.infrastructure.mcp.transport.stdio import StdioTransport

        secret_stderr = b"API_KEY=stdio-secret-token\ntraceback details"
        transport = StdioTransport()
        transport._process = cast(
            Any,
            _FakeProcess(
                stdout=_ClosedStdout(),
                stderr=_FakeStderr(secret_stderr),
                returncode=1,
            ),
        )

        with (
            caplog.at_level(logging.ERROR, logger=STDIO_LOGGER_NAME),
            pytest.raises(MCPTransportClosedError, match="Process closed connection"),
        ):
            await transport.receive(timeout=0.01)

        assert "Process closed connection" in caplog.text
        assert "stderr_bytes=" in caplog.text
        assert "API_KEY" not in caplog.text
        assert "stdio-secret-token" not in caplog.text
        assert "traceback details" not in caplog.text

    @pytest.mark.asyncio
    async def test_receive_timeout_after_exit_log_redacts_stderr(self, caplog):
        """Timed-out exited subprocess stderr should not be copied into logs."""
        from src.infrastructure.mcp.transport.stdio import StdioTransport

        secret_stderr = b"password=stdio-secret-token\nrequest payload"
        transport = StdioTransport()
        transport._process = cast(
            Any,
            _FakeProcess(
                stdout=_HangingStdout(),
                stderr=_FakeStderr(secret_stderr),
                returncode=2,
            ),
        )

        with (
            caplog.at_level(logging.ERROR, logger=STDIO_LOGGER_NAME),
            pytest.raises(TimeoutError),
        ):
            await transport.receive(timeout=0.001)

        assert "Process exited with code 2" in caplog.text
        assert "stderr_bytes=" in caplog.text
        assert "password" not in caplog.text
        assert "stdio-secret-token" not in caplog.text
        assert "request payload" not in caplog.text


# ============================================================================
# HTTPTransport Tests
# ============================================================================


class TestHTTPTransport:
    """Tests for HTTPTransport."""

    def test_init(self):
        """Test initialization."""
        from src.infrastructure.mcp.transport.http import HTTPTransport

        transport = HTTPTransport()
        assert not transport.is_open

    @pytest.mark.asyncio
    async def test_start_requires_url(self):
        """Test start fails without URL."""
        from src.infrastructure.mcp.transport.http import HTTPTransport

        transport = HTTPTransport()
        config = TransportConfig.local(command=["test"])

        with pytest.raises(MCPTransportError, match="Invalid transport type"):
            await transport.start(config)

    @pytest.mark.asyncio
    async def test_stop_when_not_started(self):
        """Test stop is idempotent."""
        from src.infrastructure.mcp.transport.http import HTTPTransport

        transport = HTTPTransport()
        await transport.stop()  # Should not raise

    @pytest.mark.asyncio
    async def test_receive_raises_error(self):
        """Test standalone receive raises error."""
        from src.infrastructure.mcp.transport.http import HTTPTransport

        transport = HTTPTransport()

        with pytest.raises(NotImplementedError, match="request-response pattern"):
            await transport.receive()


# ============================================================================
# WebSocketTransport Tests
# ============================================================================


class TestWebSocketTransport:
    """Tests for WebSocketTransport."""

    def test_init(self):
        """Test initialization."""
        from src.infrastructure.mcp.transport.websocket import WebSocketTransport

        transport = WebSocketTransport()
        assert not transport.is_open

    @pytest.mark.asyncio
    async def test_start_requires_url(self):
        """Test start fails without URL."""
        from src.infrastructure.mcp.transport.websocket import WebSocketTransport

        transport = WebSocketTransport()
        config = TransportConfig.local(command=["test"])

        with pytest.raises(MCPTransportError, match="Invalid transport type"):
            await transport.start(config)

    @pytest.mark.asyncio
    async def test_stop_when_not_started(self):
        """Test stop is idempotent."""
        from src.infrastructure.mcp.transport.websocket import WebSocketTransport

        transport = WebSocketTransport()
        await transport.stop()  # Should not raise

    @pytest.mark.asyncio
    async def test_send_when_not_connected(self):
        """Test send raises when not connected."""
        from src.infrastructure.mcp.transport.websocket import WebSocketTransport

        transport = WebSocketTransport()

        with pytest.raises(NotImplementedError, match="request-response pattern"):
            await transport.send({"test": "message"})


# ============================================================================
# BaseTransport Tests
# ============================================================================


class TestBaseTransport:
    """Tests for BaseTransport."""

    def test_next_request_id_increments(self):
        """Test request ID increments."""
        from src.infrastructure.mcp.transport.stdio import StdioTransport

        transport = StdioTransport()

        id1 = transport._next_request_id()
        id2 = transport._next_request_id()
        id3 = transport._next_request_id()

        assert id1 == 1
        assert id2 == 2
        assert id3 == 3

    def test_is_open_default_false(self):
        """Test is_open defaults to False."""
        from src.infrastructure.mcp.transport.stdio import StdioTransport

        transport = StdioTransport()
        assert transport.is_open is False


# ============================================================================
# Exception Tests
# ============================================================================


class TestExceptions:
    """Tests for transport exceptions."""

    def test_transport_error_message(self):
        """Test MCPTransportError has message."""
        error = MCPTransportError("Test error")
        assert str(error) == "Test error"

    def test_transport_closed_error_inheritance(self):
        """Test MCPTransportClosedError inherits from MCPTransportError."""
        error = MCPTransportClosedError("Closed")
        assert isinstance(error, MCPTransportError)
