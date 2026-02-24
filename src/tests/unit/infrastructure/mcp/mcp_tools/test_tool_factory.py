"""Unit tests for MCP Tool Factory and Adapters (Phase 6)."""

from typing import Any

import pytest

from src.domain.model.mcp.tool import MCPTool, MCPToolResult, MCPToolSchema
from src.domain.model.mcp.transport import TransportType
from src.infrastructure.mcp.tools.base import (
    BaseMCPToolAdapter,
    LocalToolAdapter,
    WebSocketToolAdapter,
)
from src.infrastructure.mcp.tools.factory import MCPToolFactory

# ============================================================================
# BaseMCPToolAdapter Tests
# ============================================================================


class ConcreteTestAdapter(BaseMCPToolAdapter):
    """Concrete adapter for testing abstract base class."""

    def __init__(self, server_name: str) -> None:
        super().__init__(server_name)
        self.execute_calls = []
        self.list_calls = []
        self._test_tools = []
        self._test_result = MCPToolResult(content=[{"type": "text", "text": "test"}])

    def set_tools(self, tools: list[MCPToolSchema]):
        self._test_tools = tools

    def set_result(self, result: MCPToolResult):
        self._test_result = result

    async def _execute_tool_internal(
        self, tool_name: str, arguments: dict[str, Any], timeout_ms
    ) -> MCPToolResult:
        self.execute_calls.append((tool_name, arguments, timeout_ms))
        return self._test_result

    async def _list_tools_internal(self) -> list[MCPToolSchema]:
        self.list_calls.append(True)
        return self._test_tools

    async def _initialize_internal(self) -> None:
        pass

    async def _close_internal(self) -> None:
        pass


class TestBaseMCPToolAdapter:
    """Tests for BaseMCPToolAdapter."""

    def test_server_name(self):
        """Test server name property."""
        adapter = ConcreteTestAdapter("test-server")
        assert adapter.server_name == "test-server"

    def test_is_initialized_default_false(self):
        """Test is_initialized defaults to False."""
        adapter = ConcreteTestAdapter("test-server")
        assert adapter.is_initialized is False

    @pytest.mark.asyncio
    async def test_initialize(self):
        """Test initialize sets _initialized flag."""
        adapter = ConcreteTestAdapter("test-server")
        await adapter.initialize()
        assert adapter.is_initialized is True

    @pytest.mark.asyncio
    async def test_initialize_idempotent(self):
        """Test initialize is idempotent."""
        adapter = ConcreteTestAdapter("test-server")
        await adapter.initialize()
        await adapter.initialize()  # Should not raise
        assert adapter.is_initialized is True

    @pytest.mark.asyncio
    async def test_close(self):
        """Test close resets state."""
        adapter = ConcreteTestAdapter("test-server")
        await adapter.initialize()
        await adapter.close()
        assert adapter.is_initialized is False

    @pytest.mark.asyncio
    async def test_execute_tool(self):
        """Test execute_tool delegates to internal method."""
        adapter = ConcreteTestAdapter("test-server")
        result = await adapter.execute_tool("test_tool", {"arg": "value"}, 5000)

        assert len(adapter.execute_calls) == 1
        assert adapter.execute_calls[0] == ("test_tool", {"arg": "value"}, 5000)
        assert result.content == [{"type": "text", "text": "test"}]

    @pytest.mark.asyncio
    async def test_execute_tool_with_cache_validation(self):
        """Test execute_tool validates tool exists in cache."""
        adapter = ConcreteTestAdapter("test-server")
        adapter._tools_cache = {"known_tool": MCPToolSchema(name="known_tool")}

        result = await adapter.execute_tool("unknown_tool", {})

        assert result.is_error is True
        assert "not found" in result.error_message

    @pytest.mark.asyncio
    async def test_execute_tool_exception_handling(self):
        """Test execute_tool handles exceptions."""
        adapter = ConcreteTestAdapter("test-server")

        async def raise_error(*args):
            raise RuntimeError("Test error")

        adapter._execute_tool_internal = raise_error

        result = await adapter.execute_tool("test_tool", {})

        assert result.is_error is True
        assert "Test error" in result.error_message

    @pytest.mark.asyncio
    async def test_list_tools(self):
        """Test list_tools returns MCPTool entities."""
        adapter = ConcreteTestAdapter("test-server")
        adapter.set_tools([
            MCPToolSchema(name="tool1", description="First tool"),
            MCPToolSchema(name="tool2", description="Second tool"),
        ])

        tools = await adapter.list_tools()

        assert len(tools) == 2
        assert all(isinstance(t, MCPTool) for t in tools)
        assert tools[0].name == "tool1"
        assert tools[0].server_name == "test-server"
        assert tools[1].name == "tool2"

    @pytest.mark.asyncio
    async def test_list_tools_updates_cache(self):
        """Test list_tools updates internal cache."""
        adapter = ConcreteTestAdapter("test-server")
        adapter.set_tools([MCPToolSchema(name="cached_tool")])

        await adapter.list_tools()

        assert "cached_tool" in adapter._tools_cache


# ============================================================================
# MCPToolFactory Tests
# ============================================================================


class TestMCPToolFactory:
    """Tests for MCPToolFactory."""

    def setup_method(self):
        """Clear factory cache before each test."""
        MCPToolFactory.clear_all()

    def test_create_local_adapter(self):
        """Test creating local adapter."""
        adapter = MCPToolFactory.create_adapter(
            server_name="fetch",
            transport_type=TransportType.LOCAL,
            command="uvx",
            args=["mcp-server-fetch"],
        )

        assert isinstance(adapter, LocalToolAdapter)
        assert adapter.server_name == "fetch"

    def test_create_stdio_adapter(self):
        """Test creating stdio adapter (alias for local)."""
        adapter = MCPToolFactory.create_adapter(
            server_name="fetch",
            transport_type=TransportType.STDIO,
            command="uvx",
        )

        assert isinstance(adapter, LocalToolAdapter)

    def test_create_websocket_adapter(self):
        """Test creating WebSocket adapter."""
        adapter = MCPToolFactory.create_adapter(
            server_name="sandbox",
            transport_type=TransportType.WEBSOCKET,
            websocket_url="ws://localhost:8765/mcp",
        )

        assert isinstance(adapter, WebSocketToolAdapter)
        assert adapter.server_name == "sandbox"

    def test_create_local_missing_command(self):
        """Test local adapter requires command."""
        with pytest.raises(ValueError, match="command"):
            MCPToolFactory.create_adapter(
                server_name="test",
                transport_type=TransportType.LOCAL,
            )

    def test_create_websocket_missing_url(self):
        """Test WebSocket adapter requires URL."""
        with pytest.raises(ValueError, match="websocket_url"):
            MCPToolFactory.create_adapter(
                server_name="test",
                transport_type=TransportType.WEBSOCKET,
            )

    def test_unsupported_transport(self):
        """Test unsupported transport raises error."""
        with pytest.raises(ValueError, match="Unsupported"):
            MCPToolFactory.create_adapter(
                server_name="test",
                transport_type=TransportType.SSE,  # SSE not fully supported
            )

    def test_get_or_create_caches_adapter(self):
        """Test get_or_create caches adapters."""
        adapter1 = MCPToolFactory.get_or_create(
            server_name="fetch",
            transport_type=TransportType.LOCAL,
            command="uvx",
        )

        adapter2 = MCPToolFactory.get_or_create(
            server_name="fetch",
            transport_type=TransportType.LOCAL,
            command="uvx",
        )

        assert adapter1 is adapter2

    def test_remove_adapter(self):
        """Test removing adapter from cache."""
        MCPToolFactory.get_or_create(
            server_name="fetch",
            transport_type=TransportType.LOCAL,
            command="uvx",
        )

        removed = MCPToolFactory.remove_adapter("fetch")

        assert removed is not None
        assert "fetch" not in MCPToolFactory.list_adapters()

    def test_remove_nonexistent_adapter(self):
        """Test removing nonexistent adapter returns None."""
        removed = MCPToolFactory.remove_adapter("nonexistent")
        assert removed is None

    def test_list_adapters(self):
        """Test listing cached adapters."""
        MCPToolFactory.get_or_create("server1", TransportType.LOCAL, command="cmd1")
        MCPToolFactory.get_or_create("server2", TransportType.LOCAL, command="cmd2")

        adapters = MCPToolFactory.list_adapters()

        assert "server1" in adapters
        assert "server2" in adapters

    def test_clear_all(self):
        """Test clearing all cached adapters."""
        MCPToolFactory.get_or_create("server1", TransportType.LOCAL, command="cmd1")
        MCPToolFactory.get_or_create("server2", TransportType.LOCAL, command="cmd2")

        MCPToolFactory.clear_all()

        assert MCPToolFactory.list_adapters() == []


# ============================================================================
# LocalToolAdapter Tests
# ============================================================================


class TestLocalToolAdapter:
    """Tests for LocalToolAdapter."""

    def test_init(self):
        """Test adapter initialization."""
        adapter = LocalToolAdapter(
            server_name="fetch",
            command="uvx",
            args=["mcp-server-fetch"],
            env={"API_KEY": "xxx"},
        )

        assert adapter.server_name == "fetch"
        assert adapter._command == "uvx"
        assert adapter._args == ["mcp-server-fetch"]
        assert adapter._env == {"API_KEY": "xxx"}

    def test_init_defaults(self):
        """Test adapter with default values."""
        adapter = LocalToolAdapter(server_name="test", command="cmd")

        assert adapter._args == []
        assert adapter._env == {}


# ============================================================================
# WebSocketToolAdapter Tests
# ============================================================================


class TestWebSocketToolAdapter:
    """Tests for WebSocketToolAdapter."""

    def test_init(self):
        """Test adapter initialization."""
        adapter = WebSocketToolAdapter(
            server_name="sandbox",
            websocket_url="ws://localhost:8765/mcp",
        )

        assert adapter.server_name == "sandbox"
        assert adapter._websocket_url == "ws://localhost:8765/mcp"

    @pytest.mark.asyncio
    async def test_execute_without_client(self):
        """Test execute returns error when client not initialized."""
        adapter = WebSocketToolAdapter("test", "ws://localhost:8765")

        result = await adapter._execute_tool_internal("tool", {}, None)

        assert result.is_error is True
        assert "not initialized" in result.error_message

    @pytest.mark.asyncio
    async def test_list_tools_without_client(self):
        """Test list_tools returns empty when client not initialized."""
        adapter = WebSocketToolAdapter("test", "ws://localhost:8765")

        tools = await adapter._list_tools_internal()

        assert tools == []
