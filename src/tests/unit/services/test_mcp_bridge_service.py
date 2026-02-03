"""Tests for MCPBridgeService."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.application.services.mcp_bridge_service import (
    ConnectionState,
    MCPBridgeService,
    MCPConnectionInfo,
    MCPTool,
    MCPToolResult,
)


class TestMCPToolResult:
    """测试 MCPToolResult."""

    def test_to_dict(self) -> None:
        """应该转换为字典."""
        result = MCPToolResult(
            content=[{"type": "text", "text": "output"}],
            is_error=False,
            tool_name="bash",
            execution_time_ms=100,
        )

        data = result.to_dict()

        assert data["content"] == [{"type": "text", "text": "output"}]
        assert data["is_error"] is False
        assert data["tool_name"] == "bash"
        assert data["execution_time_ms"] == 100


class TestMCPConnectionInfo:
    """测试 MCPConnectionInfo."""

    def test_to_dict(self) -> None:
        """应该转换为字典."""
        info = MCPConnectionInfo(
            sandbox_id="test-sandbox",
            websocket_url="ws://localhost:8765",
            state=ConnectionState.CONNECTED,
            connected_at=None,
            last_ping=None,
            tools=[MCPTool(name="bash", description="Run bash", input_schema={})],
        )

        info.connected_at = datetime.now()
        info.last_ping = datetime.now()

        data = info.to_dict()

        assert data["sandbox_id"] == "test-sandbox"
        assert data["websocket_url"] == "ws://localhost:8765"
        assert data["state"] == "connected"
        assert data["connected_at"] is not None
        assert data["tools"] == [{"name": "bash", "description": "Run bash", "input_schema": {}}]


class TestMCPBridgeService:
    """测试 MCPBridgeService."""

    @pytest.fixture
    def mock_adapter(self):
        """创建 mock 适配器."""
        adapter = MagicMock()
        adapter.call_tool = AsyncMock()
        adapter.connect_mcp = AsyncMock()
        adapter.disconnect_mcp = AsyncMock()
        adapter.list_tools = AsyncMock()
        adapter.get_sandbox = AsyncMock()
        return adapter

    @pytest.fixture
    def service(self, mock_adapter):
        """创建 MCP Bridge 服务实例."""
        return MCPBridgeService(
            mcp_adapter=mock_adapter,
            default_timeout=30.0,
            max_retries=3,
        )

    @pytest.mark.asyncio
    async def test_connect(self, service: MCPBridgeService, mock_adapter) -> None:
        """应该连接到 MCP 服务器."""
        mock_adapter.connect_mcp.return_value = True
        mock_adapter.get_sandbox.return_value = MagicMock(
            id="test-sandbox",
            websocket_url="ws://localhost:8765",
        )

        result = await service.connect("test-sandbox")

        assert result.sandbox_id == "test-sandbox"
        assert result.websocket_url == "ws://localhost:8765"
        assert result.state == ConnectionState.CONNECTED

        mock_adapter.connect_mcp.assert_called_once_with("test-sandbox", timeout=30.0)

    @pytest.mark.asyncio
    async def test_connect_failure(self, service: MCPBridgeService, mock_adapter) -> None:
        """连接失败应该返回错误状态."""
        mock_adapter.connect_mcp.return_value = False
        mock_adapter.get_sandbox.return_value = MagicMock(
            id="test-sandbox",
            websocket_url="ws://localhost:8765",
        )

        result = await service.connect("test-sandbox")

        assert result.state == ConnectionState.ERROR

    @pytest.mark.asyncio
    async def test_disconnect(self, service: MCPBridgeService, mock_adapter) -> None:
        """应该断开连接."""
        mock_adapter.disconnect_mcp.return_value = True

        result = await service.disconnect("test-sandbox")

        assert result is True

    @pytest.mark.asyncio
    async def test_call_tool(self, service: MCPBridgeService, mock_adapter) -> None:
        """应该调用 MCP 工具."""
        mock_adapter.call_tool.return_value = {
            "content": [{"text": "Hello World"}],
            "is_error": False,
        }

        result = await service.call_tool("test-sandbox", "bash", {"command": "ls"})

        assert result.tool_name == "bash"
        assert result.content == [{"text": "Hello World"}]
        assert result.is_error is False

        mock_adapter.call_tool.assert_called_once_with(
            "test-sandbox",
            "bash",
            {"command": "ls"},
            timeout=30.0,
        )

    @pytest.mark.asyncio
    async def test_call_tool_with_error(self, service: MCPBridgeService, mock_adapter) -> None:
        """工具调用错误应该返回错误结果."""
        mock_adapter.call_tool.return_value = {
            "content": [{"text": "Command failed"}],
            "is_error": True,
        }

        result = await service.call_tool("test-sandbox", "bash", {"command": "false"})

        assert result.is_error is True
        assert result.error_message == "Command failed"

    @pytest.mark.asyncio
    async def test_list_tools(self, service: MCPBridgeService, mock_adapter) -> None:
        """应该列出可用工具."""
        mock_adapter.list_tools.return_value = [
            {"name": "bash", "description": "Run bash", "input_schema": {}},
            {"name": "read", "description": "Read file", "input_schema": {}},
        ]

        tools = await service.list_tools("test-sandbox")

        assert len(tools) == 2
        assert tools[0].name == "bash"
        assert tools[1].name == "read"

    @pytest.mark.asyncio
    async def test_get_connection_info(self, service: MCPBridgeService, mock_adapter) -> None:
        """应该获取连接信息."""
        mock_adapter.get_sandbox.return_value = MagicMock(
            id="test-sandbox",
            websocket_url="ws://localhost:8765",
            mcp_client=MagicMock(is_connected=True),
        )

        info = await service.get_connection_info("test-sandbox")

        assert info.sandbox_id == "test-sandbox"
        assert info.websocket_url == "ws://localhost:8765"
        assert info.state == ConnectionState.CONNECTED

    @pytest.mark.asyncio
    async def test_health_check(self, service: MCPBridgeService, mock_adapter) -> None:
        """应该检查连接健康状态."""
        mock_adapter.get_sandbox.return_value = MagicMock(
            id="test-sandbox",
            mcp_client=MagicMock(is_connected=True),
        )

        result = await service.health_check("test-sandbox")

        assert result is True

    @pytest.mark.asyncio
    async def test_health_check_disconnected(self, service: MCPBridgeService, mock_adapter) -> None:
        """断开的连接应该返回不健康."""
        mock_adapter.get_sandbox.return_value = MagicMock(
            id="test-sandbox",
            mcp_client=None,
        )

        result = await service.health_check("test-sandbox")

        assert result is False

    @pytest.mark.asyncio
    async def test_reconnect_if_needed(self, service: MCPBridgeService, mock_adapter) -> None:
        """应该在需要时重新连接."""
        # 第一次检查返回未连接
        mock_adapter.get_sandbox.return_value = MagicMock(
            id="test-sandbox",
            mcp_client=None,
        )
        mock_adapter.connect_mcp.return_value = True

        result = await service.reconnect_if_needed("test-sandbox")

        assert result is True
        mock_adapter.connect_mcp.assert_called_once()

    @pytest.mark.asyncio
    async def test_reconnect_if_needed_connected(self, service: MCPBridgeService, mock_adapter) -> None:
        """已连接的不应该重连."""
        mock_adapter.get_sandbox.return_value = MagicMock(
            id="test-sandbox",
            mcp_client=MagicMock(is_connected=True),
        )

        result = await service.reconnect_if_needed("test-sandbox", force=False)

        assert result is True
        mock_adapter.connect_mcp.assert_not_called()

    @pytest.mark.asyncio
    async def test_batch_call(self, service: MCPBridgeService, mock_adapter) -> None:
        """应该批量调用工具."""
        mock_adapter.call_tool.return_value = {
            "content": [{"text": "OK"}],
            "is_error": False,
        }

        calls = [
            {"tool_name": "bash", "arguments": {"command": "ls"}},
            {"tool_name": "bash", "arguments": {"command": "pwd"}},
        ]

        results = await service.batch_call("test-sandbox", calls)

        assert len(results) == 2
        assert all(r.is_error is False for r in results)

        assert mock_adapter.call_tool.call_count == 2

    @pytest.mark.asyncio
    async def test_batch_call_with_error(self, service: MCPBridgeService, mock_adapter) -> None:
        """批量调用中某个工具失败应该继续执行其他."""
        call_count = [0]

        async def side_effect(sid, tool, args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 2:
                return {"content": [{"text": "Error"}], "is_error": True}
            return {"content": [{"text": "OK"}], "is_error": False}

        mock_adapter.call_tool.side_effect = side_effect

        calls = [
            {"tool_name": "bash", "arguments": {"command": "ls"}},
            {"tool_name": "bash", "arguments": {"command": "pwd"}},
            {"tool_name": "bash", "arguments": {"command": "echo hi"}},
        ]

        results = await service.batch_call("test-sandbox", calls)

        assert len(results) == 3
        # 第二个调用应该失败
        assert results[1].is_error is True
        assert results[0].is_error is False
        assert results[2].is_error is False

    @pytest.mark.asyncio
    async def test_no_adapter(self) -> None:
        """没有 adapter 时应该抛出错误."""
        service = MCPBridgeService(mcp_adapter=None)

        with pytest.raises(RuntimeError, match="MCP adapter not configured"):
            await service.connect("test-sandbox")
