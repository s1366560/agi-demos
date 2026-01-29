"""MCP Bridge Service - MCP 协议适配层.

提供统一的 MCP 协议适配接口，处理：
- WebSocket 连接管理
- 工具调用
- 连接重试和错误处理
"""

import asyncio
import logging
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, AsyncIterator, Dict, List, Optional

logger = logging.getLogger(__name__)


class ConnectionState(str, Enum):
    """MCP 连接状态."""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"


@dataclass
class MCPTool:
    """MCP 工具定义."""
    name: str
    description: str
    input_schema: Dict[str, Any]


@dataclass
class MCPToolResult:
    """MCP 工具执行结果."""
    content: List[Dict[str, Any]]
    is_error: bool
    tool_name: str
    execution_time_ms: int = 0
    error_message: Optional[str] = None

    def to_dict(self) -> Dict:
        """转换为字典."""
        return {
            "content": self.content,
            "is_error": self.is_error,
            "tool_name": self.tool_name,
            "execution_time_ms": self.execution_time_ms,
            "error_message": self.error_message,
        }


@dataclass
class MCPConnectionInfo:
    """MCP 连接信息."""
    sandbox_id: str
    websocket_url: str
    state: ConnectionState
    connected_at: Optional[datetime] = None
    last_ping: Optional[datetime] = None
    tools: List[MCPTool] = field(default_factory=list)
    error_message: Optional[str] = None

    def to_dict(self) -> Dict:
        """转换为字典."""
        return {
            "sandbox_id": self.sandbox_id,
            "websocket_url": self.websocket_url,
            "state": self.state.value,
            "connected_at": self.connected_at.isoformat() if self.connected_at else None,
            "last_ping": self.last_ping.isoformat() if self.last_ping else None,
            "tools": [asdict(t) for t in self.tools],
            "error_message": self.error_message,
        }


class MCPBridgeService:
    """MCP 协议适配服务.

    提供 MCP WebSocket 连接管理和工具调用的统一接口。
    """

    def __init__(
        self,
        mcp_adapter=None,
        default_timeout: float = 30.0,
        max_retries: int = 3,
    ):
        """初始化 MCP Bridge 服务.

        Args:
            mcp_adapter: MCP Sandbox 适配器
            default_timeout: 默认超时时间（秒）
            max_retries: 最大重试次数
        """
        self._adapter = mcp_adapter
        self._default_timeout = default_timeout
        self._max_retries = max_retries

    def _ensure_adapter(self) -> None:
        """确保适配器已配置."""
        if self._adapter is None:
            raise RuntimeError("MCP adapter not configured")

    async def connect(
        self,
        sandbox_id: str,
        timeout: float = 30.0,
    ) -> MCPConnectionInfo:
        """连接到 Sandbox MCP 服务器.

        Args:
            sandbox_id: Sandbox ID
            timeout: 连接超时时间

        Returns:
            MCPConnectionInfo 连接信息
        """
        self._ensure_adapter()

        sandbox = await self._adapter.get_sandbox(sandbox_id)
        if sandbox is None:
            return MCPConnectionInfo(
                sandbox_id=sandbox_id,
                websocket_url="",
                state=ConnectionState.ERROR,
                error_message="Sandbox not found",
            )

        connected = await self._adapter.connect_mcp(sandbox_id, timeout=timeout)

        info = MCPConnectionInfo(
            sandbox_id=sandbox_id,
            websocket_url=sandbox.websocket_url,
            state=ConnectionState.CONNECTED if connected else ConnectionState.ERROR,
            connected_at=datetime.now() if connected else None,
        )

        # 如果连接成功，列出可用工具
        if connected:
            tools_data = await self._adapter.list_tools(sandbox_id)
            info.tools = [
                MCPTool(
                    name=t.get("name", ""),
                    description=t.get("description", ""),
                    input_schema=t.get("input_schema", {}),
                )
                for t in tools_data
            ]

        return info

    async def disconnect(self, sandbox_id: str) -> bool:
        """断开 Sandbox MCP 连接.

        Args:
            sandbox_id: Sandbox ID

        Returns:
            True 如果成功断开
        """
        self._ensure_adapter()
        return await self._adapter.disconnect_mcp(sandbox_id)

    async def call_tool(
        self,
        sandbox_id: str,
        tool_name: str,
        arguments: Dict[str, Any],
        timeout: Optional[float] = None,
    ) -> MCPToolResult:
        """调用 MCP 工具.

        Args:
            sandbox_id: Sandbox ID
            tool_name: 工具名称
            arguments: 工具参数
            timeout: 执行超时时间

        Returns:
            MCPToolResult 工具执行结果
        """
        self._ensure_adapter()

        if timeout is None:
            timeout = self._default_timeout

        start_time = time.time()
        response = await self._adapter.call_tool(
            sandbox_id,
            tool_name,
            arguments,
            timeout=timeout,
        )
        elapsed_ms = int((time.time() - start_time) * 1000)

        content = response.get("content", [])
        is_error = response.get("is_error", False)

        error_message = None
        if is_error and content:
            # 尝试从 content 中提取错误消息
            for item in content:
                if isinstance(item, dict):
                    error_message = item.get("text", str(item))
                    break

        return MCPToolResult(
            content=content,
            is_error=is_error,
            tool_name=tool_name,
            execution_time_ms=elapsed_ms,
            error_message=error_message,
        )

    async def list_tools(
        self,
        sandbox_id: str,
    ) -> List[MCPTool]:
        """列出可用的 MCP 工具.

        Args:
            sandbox_id: Sandbox ID

        Returns:
            MCP 工具列表
        """
        self._ensure_adapter()

        tools_data = await self._adapter.list_tools(sandbox_id)
        return [
            MCPTool(
                name=t.get("name", ""),
                description=t.get("description", ""),
                input_schema=t.get("input_schema", {}),
            )
            for t in tools_data
        ]

    async def get_connection_info(
        self,
        sandbox_id: str,
    ) -> MCPConnectionInfo:
        """获取 MCP 连接信息.

        Args:
            sandbox_id: Sandbox ID

        Returns:
            MCPConnectionInfo 连接信息
        """
        self._ensure_adapter()

        sandbox = await self._adapter.get_sandbox(sandbox_id)
        if sandbox is None:
            return MCPConnectionInfo(
                sandbox_id=sandbox_id,
                websocket_url="",
                state=ConnectionState.ERROR,
                error_message="Sandbox not found",
            )

        is_connected = (
            hasattr(sandbox, "mcp_client") and
            sandbox.mcp_client is not None and
            getattr(sandbox.mcp_client, "is_connected", False)
        )

        return MCPConnectionInfo(
            sandbox_id=sandbox_id,
            websocket_url=sandbox.websocket_url,
            state=ConnectionState.CONNECTED if is_connected else ConnectionState.DISCONNECTED,
        )

    async def stream_call(
        self,
        sandbox_id: str,
        tool_name: str,
        arguments: Dict[str, Any],
    ) -> AsyncIterator[Dict[str, Any]]:
        """流式调用 MCP 工具（用于长时间运行的工具）.

        Args:
            sandbox_id: Sandbox ID
            tool_name: 工具名称
            arguments: 工具参数

        Yields:
            工具输出事件
        """
        self._ensure_adapter()

        # 流式调用需要适配器支持
        if hasattr(self._adapter, "stream_call_tool"):
            async for event in self._adapter.stream_call_tool(sandbox_id, tool_name, arguments):
                yield event
        else:
            # 回退到普通调用
            result = await self.call_tool(sandbox_id, tool_name, arguments)
            yield {"type": "result", "data": result.to_dict()}

    async def health_check(self, sandbox_id: str) -> bool:
        """检查 MCP 连接健康状态.

        Args:
            sandbox_id: Sandbox ID

        Returns:
            True 如果连接健康
        """
        self._ensure_adapter()

        sandbox = await self._adapter.get_sandbox(sandbox_id)
        if sandbox is None:
            return False

        mcp_client = getattr(sandbox, "mcp_client", None)
        if mcp_client is None:
            return False

        return getattr(mcp_client, "is_connected", False)

    async def reconnect_if_needed(
        self,
        sandbox_id: str,
        force: bool = False,
    ) -> bool:
        """在需要时重新连接 MCP.

        Args:
            sandbox_id: Sandbox ID
            force: 是否强制重连

        Returns:
            True 如果连接成功
        """
        self._ensure_adapter()

        if not force:
            # 检查当前连接状态
            if await self.health_check(sandbox_id):
                return True

        # 尝试重新连接
        result = await self.connect(sandbox_id)
        return result.state == ConnectionState.CONNECTED

    async def batch_call(
        self,
        sandbox_id: str,
        calls: List[Dict[str, Any]],
    ) -> List[MCPToolResult]:
        """批量调用多个 MCP 工具.

        Args:
            sandbox_id: Sandbox ID
            calls: 调用列表，每项包含 tool_name 和 arguments

        Returns:
            MCPToolResult 结果列表
        """
        results = []

        for call_spec in calls:
            tool_name = call_spec.get("tool_name", "")
            arguments = call_spec.get("arguments", {})

            try:
                result = await self.call_tool(sandbox_id, tool_name, arguments)
                results.append(result)
            except Exception as e:
                # 单个调用失败不应中断批量操作
                logger.warning(f"Batch call failed for {tool_name}: {e}")
                results.append(MCPToolResult(
                    content=[],
                    is_error=True,
                    tool_name=tool_name,
                    error_message=str(e),
                ))

        return results
