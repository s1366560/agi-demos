"""Service Manager Service - Desktop 和 Terminal 服务管理.

管理 Sandbox 容器内的 Desktop (noVNC) 和 Terminal (ttyd) 服务。
通过 MCP 协议与 sandbox-mcp-server 通信来控制这些服务。
"""

import json
import logging
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ServiceType(str, Enum):
    """服务类型."""
    DESKTOP = "desktop"
    TERMINAL = "terminal"


class ServiceStatus(str, Enum):
    """服务状态."""
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    ERROR = "error"


@dataclass
class ServiceState:
    """服务状态信息."""
    service_type: ServiceType
    status: ServiceStatus
    running: bool
    url: Optional[str] = None
    port: Optional[int] = None
    pid: Optional[int] = None
    display: Optional[str] = None  # For desktop
    resolution: Optional[str] = None  # For desktop
    session_id: Optional[str] = None  # For terminal
    error: Optional[str] = None

    def to_dict(self) -> Dict:
        """转换为字典."""
        return {
            "service_type": self.service_type.value,
            "status": self.status.value,
            "running": self.running,
            "url": self.url,
            "port": self.port,
            "pid": self.pid,
            "display": self.display,
            "resolution": self.resolution,
            "session_id": self.session_id,
            "error": self.error,
        }


@dataclass
class DesktopConfig:
    """Desktop 服务配置."""
    resolution: str = "1280x720"
    display: str = ":1"
    port: int = 6080


@dataclass
class TerminalConfig:
    """Terminal 服务配置."""
    port: int = 7681
    shell: str = "/bin/bash"


class ServiceManagerService:
    """服务管理服务.

    通过 MCP 协议管理 Sandbox 容器内的 Desktop 和 Terminal 服务。
    """

    def __init__(self, mcp_adapter=None, default_timeout: float = 30.0):
        """初始化服务管理器.

        Args:
            mcp_adapter: MCP 适配器，用于与 sandbox 通信
            default_timeout: 默认超时时间（秒）
        """
        self._adapter = mcp_adapter
        self._default_timeout = default_timeout

    def _ensure_adapter(self) -> None:
        """确保适配器已配置."""
        if self._adapter is None:
            raise RuntimeError("MCP adapter not configured")

    async def start_desktop(
        self,
        sandbox_id: str,
        config: Optional[DesktopConfig] = None,
    ) -> ServiceState:
        """启动 Desktop 服务.

        Args:
            sandbox_id: Sandbox ID
            config: Desktop 配置

        Returns:
            ServiceState 服务状态
        """
        self._ensure_adapter()
        config = config or DesktopConfig()

        result = await self._adapter.call_tool(
            sandbox_id,
            "start_desktop",
            {
                "resolution": config.resolution,
                "display": config.display,
                "port": config.port,
                "_workspace_dir": "/workspace",
            },
            timeout=self._default_timeout,
        )

        return self._parse_desktop_result(result)

    async def stop_desktop(self, sandbox_id: str) -> bool:
        """停止 Desktop 服务.

        Args:
            sandbox_id: Sandbox ID

        Returns:
            True 如果成功
        """
        self._ensure_adapter()

        result = await self._adapter.call_tool(
            sandbox_id,
            "stop_desktop",
            {"_workspace_dir": "/workspace"},
            timeout=self._default_timeout,
        )

        if result.get("is_error"):
            return False

        content = result.get("content", [])
        if content:
            data = json.loads(content[0].get("text", "{}"))
            return data.get("success", False)

        return False

    async def get_desktop_status(self, sandbox_id: str) -> ServiceState:
        """获取 Desktop 服务状态.

        Args:
            sandbox_id: Sandbox ID

        Returns:
            ServiceState 服务状态
        """
        self._ensure_adapter()

        result = await self._adapter.call_tool(
            sandbox_id,
            "get_desktop_status",
            {"_workspace_dir": "/workspace"},
            timeout=self._default_timeout,
        )

        return self._parse_desktop_result(result)

    async def start_terminal(
        self,
        sandbox_id: str,
        config: Optional[TerminalConfig] = None,
    ) -> ServiceState:
        """启动 Terminal 服务.

        Args:
            sandbox_id: Sandbox ID
            config: Terminal 配置

        Returns:
            ServiceState 服务状态
        """
        self._ensure_adapter()
        config = config or TerminalConfig()

        result = await self._adapter.call_tool(
            sandbox_id,
            "start_terminal",
            {
                "port": config.port,
                "_workspace_dir": "/workspace",
            },
            timeout=self._default_timeout,
        )

        return self._parse_terminal_result(result)

    async def stop_terminal(self, sandbox_id: str) -> bool:
        """停止 Terminal 服务.

        Args:
            sandbox_id: Sandbox ID

        Returns:
            True 如果成功
        """
        self._ensure_adapter()

        result = await self._adapter.call_tool(
            sandbox_id,
            "stop_terminal",
            {"_workspace_dir": "/workspace"},
            timeout=self._default_timeout,
        )

        if result.get("is_error"):
            return False

        content = result.get("content", [])
        if content:
            data = json.loads(content[0].get("text", "{}"))
            return data.get("success", False)

        return False

    async def get_terminal_status(self, sandbox_id: str) -> ServiceState:
        """获取 Terminal 服务状态.

        Args:
            sandbox_id: Sandbox ID

        Returns:
            ServiceState 服务状态
        """
        self._ensure_adapter()

        result = await self._adapter.call_tool(
            sandbox_id,
            "get_terminal_status",
            {"_workspace_dir": "/workspace"},
            timeout=self._default_timeout,
        )

        return self._parse_terminal_result(result)

    async def get_all_status(self, sandbox_id: str) -> Dict[str, ServiceState]:
        """获取所有服务状态.

        Args:
            sandbox_id: Sandbox ID

        Returns:
            服务状态字典 {"desktop": ServiceState, "terminal": ServiceState}
        """
        desktop_state = await self.get_desktop_status(sandbox_id)
        terminal_state = await self.get_terminal_status(sandbox_id)

        return {
            "desktop": desktop_state,
            "terminal": terminal_state,
        }

    async def restart_desktop(
        self,
        sandbox_id: str,
        config: Optional[DesktopConfig] = None,
    ) -> ServiceState:
        """重启 Desktop 服务.

        Args:
            sandbox_id: Sandbox ID
            config: Desktop 配置

        Returns:
            ServiceState 服务状态
        """
        await self.stop_desktop(sandbox_id)
        return await self.start_desktop(sandbox_id, config)

    async def restart_terminal(
        self,
        sandbox_id: str,
        config: Optional[TerminalConfig] = None,
    ) -> ServiceState:
        """重启 Terminal 服务.

        Args:
            sandbox_id: Sandbox ID
            config: Terminal 配置

        Returns:
            ServiceState 服务状态
        """
        await self.stop_terminal(sandbox_id)
        return await self.start_terminal(sandbox_id, config)

    def _parse_desktop_result(self, result: Dict[str, Any]) -> ServiceState:
        """解析 Desktop MCP 工具结果."""
        if result.get("is_error"):
            content = result.get("content", [])
            error_msg = content[0].get("text", "Unknown error") if content else "Unknown error"
            return ServiceState(
                service_type=ServiceType.DESKTOP,
                status=ServiceStatus.ERROR,
                running=False,
                error=error_msg,
            )

        content = result.get("content", [])
        if not content:
            return ServiceState(
                service_type=ServiceType.DESKTOP,
                status=ServiceStatus.STOPPED,
                running=False,
            )

        try:
            data = json.loads(content[0].get("text", "{}"))
            running = data.get("running", data.get("success", False))
            status = ServiceStatus.RUNNING if running else ServiceStatus.STOPPED

            return ServiceState(
                service_type=ServiceType.DESKTOP,
                status=status,
                running=running,
                url=data.get("url"),
                port=data.get("port"),
                pid=data.get("xvfb_pid") or data.get("xvnc_pid") or data.get("pid"),
                display=data.get("display"),
                resolution=data.get("resolution"),
            )
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.error(f"Failed to parse desktop result: {e}")
            return ServiceState(
                service_type=ServiceType.DESKTOP,
                status=ServiceStatus.ERROR,
                running=False,
                error=f"Failed to parse result: {e}",
            )

    def _parse_terminal_result(self, result: Dict[str, Any]) -> ServiceState:
        """解析 Terminal MCP 工具结果."""
        if result.get("is_error"):
            content = result.get("content", [])
            error_msg = content[0].get("text", "Unknown error") if content else "Unknown error"
            return ServiceState(
                service_type=ServiceType.TERMINAL,
                status=ServiceStatus.ERROR,
                running=False,
                error=error_msg,
            )

        content = result.get("content", [])
        if not content:
            return ServiceState(
                service_type=ServiceType.TERMINAL,
                status=ServiceStatus.STOPPED,
                running=False,
            )

        try:
            data = json.loads(content[0].get("text", "{}"))
            running = data.get("running", data.get("success", False))
            status = ServiceStatus.RUNNING if running else ServiceStatus.STOPPED

            return ServiceState(
                service_type=ServiceType.TERMINAL,
                status=status,
                running=running,
                url=data.get("url"),
                port=data.get("port"),
                pid=data.get("pid"),
                session_id=data.get("session_id"),
            )
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.error(f"Failed to parse terminal result: {e}")
            return ServiceState(
                service_type=ServiceType.TERMINAL,
                status=ServiceStatus.ERROR,
                running=False,
                error=f"Failed to parse result: {e}",
            )
