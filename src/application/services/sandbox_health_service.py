"""Sandbox Health Service - 分级健康检查服务.

提供不同级别的健康检查:
- BASIC: 容器是否运行
- MCP: MCP 连接是否正常
- SERVICES: Desktop 和 Terminal 服务状态
- FULL: 所有检查
"""

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from src.infrastructure.adapters.secondary.sandbox.mcp_sandbox_adapter import MCPSandboxAdapter

logger = logging.getLogger(__name__)


class HealthCheckLevel(Enum):
    """健康检查级别."""

    BASIC = "basic"  # 容器运行
    MCP = "mcp"  # MCP 连接
    SERVICES = "services"  # Desktop + Terminal
    FULL = "full"  # 以上全部


class HealthStatus(Enum):
    """健康状态."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


@dataclass
class HealthCheckResult:
    """健康检查结果."""

    level: HealthCheckLevel
    status: HealthStatus
    healthy: bool
    details: dict[str, Any]
    timestamp: datetime | None
    sandbox_id: str
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """转换为字典."""
        return {
            "level": self.level.value,
            "status": self.status.value,
            "healthy": self.healthy,
            "details": self.details,
            "timestamp": (self.timestamp or datetime.now()).isoformat(),
            "sandbox_id": self.sandbox_id,
            "errors": self.errors,
        }


@dataclass
class ComponentHealth:
    """组件健康状态."""

    container: bool = False
    mcp_connection: bool = False
    desktop_service: bool = False
    terminal_service: bool = False
    container_status: str = "unknown"
    mcp_port: int | None = None
    desktop_port: int | None = None
    terminal_port: int | None = None


class SandboxHealthService:
    """Sandbox 健康检查服务.

    执行不同级别的健康检查并返回结果。
    """

    def __init__(
        self, sandbox_adapter: MCPSandboxAdapter | None = None, default_timeout: float = 5.0
    ) -> None:
        """初始化健康检查服务.

        Args:
            sandbox_adapter: Sandbox 适配器实例
            default_timeout: 默认超时时间（秒）
        """
        self._adapter = sandbox_adapter
        self._default_timeout = default_timeout

    async def check_health(
        self,
        sandbox_id: str,
        level: HealthCheckLevel = HealthCheckLevel.BASIC,
    ) -> HealthCheckResult:
        """执行健康检查.

        Args:
            sandbox_id: Sandbox ID
            level: 检查级别

        Returns:
            HealthCheckResult 结果
        """
        timestamp = datetime.now()
        errors: list[str] = []
        details: dict[str, Any] = {}

        # 基础检查 - 容器状态
        if self._adapter is None:
            return HealthCheckResult(
                level=level,
                status=HealthStatus.UNKNOWN,
                healthy=False,
                details={},
                timestamp=timestamp,
                sandbox_id=sandbox_id,
                errors=["Adapter not configured"],
            )

        try:
            sandbox = await self._adapter.get_sandbox(sandbox_id)
        except Exception as e:
            return HealthCheckResult(
                level=level,
                status=HealthStatus.UNHEALTHY,
                healthy=False,
                details={},
                timestamp=timestamp,
                sandbox_id=sandbox_id,
                errors=[f"Failed to get sandbox: {e}"],
            )

        if sandbox is None:
            return HealthCheckResult(
                level=level,
                status=HealthStatus.UNHEALTHY,
                healthy=False,
                details={"container_running": False},
                timestamp=timestamp,
                sandbox_id=sandbox_id,
                errors=["Sandbox not found"],
            )

        container_running = sandbox.status == "running"
        details["container_running"] = container_running
        details["container_status"] = sandbox.status

        if not container_running:
            return HealthCheckResult(
                level=level,
                status=HealthStatus.UNHEALTHY,
                healthy=False,
                details=details,
                timestamp=timestamp,
                sandbox_id=sandbox_id,
                errors=["Container not running"],
            )

        # MCP 检查
        if level in (HealthCheckLevel.MCP, HealthCheckLevel.FULL):
            mcp_connected = await self.check_mcp_health(sandbox_id)
            details["mcp_connected"] = mcp_connected
            if not mcp_connected:
                errors.append("MCP not connected")

        # Services 检查
        if level in (HealthCheckLevel.SERVICES, HealthCheckLevel.FULL):
            services = await self.check_services_health(sandbox_id)
            details["desktop_running"] = services.get("desktop", False)
            details["terminal_running"] = services.get("terminal", False)
            if not services.get("desktop", True) and hasattr(sandbox, "desktop_port"):
                errors.append("Desktop service not running")
            if not services.get("terminal", True):
                errors.append("Terminal service not running")

        # 端口信息
        details["mcp_port"] = getattr(sandbox, "mcp_port", None)
        details["desktop_port"] = getattr(sandbox, "desktop_port", None)
        details["terminal_port"] = getattr(sandbox, "terminal_port", None)

        # 确定整体健康状态
        if errors:
            status = HealthStatus.DEGRADED if len(errors) == 1 else HealthStatus.UNHEALTHY
            healthy = len(errors) == 1  # 允许一个组件失败
        else:
            status = HealthStatus.HEALTHY
            healthy = True

        return HealthCheckResult(
            level=level,
            status=status,
            healthy=healthy,
            details=details,
            timestamp=timestamp,
            sandbox_id=sandbox_id,
            errors=errors,
        )

    async def check_basic_health(self, sandbox_id: str) -> ComponentHealth:
        """检查基础健康状态（容器是否运行）.

        Args:
            sandbox_id: Sandbox ID

        Returns:
            ComponentHealth 组件健康状态
        """
        if self._adapter is None:
            return ComponentHealth()

        try:
            sandbox = await self._adapter.get_sandbox(sandbox_id)
            if sandbox is None:
                return ComponentHealth(container_status="not_found")

            return ComponentHealth(
                container=sandbox.status == "running",
                container_status=sandbox.status,
                mcp_port=getattr(sandbox, "mcp_port", None),
                desktop_port=getattr(sandbox, "desktop_port", None),
                terminal_port=getattr(sandbox, "terminal_port", None),
            )
        except Exception as e:
            logger.error(f"Error checking basic health: {e}")
            return ComponentHealth(container_status="error")

    async def check_mcp_health(self, sandbox_id: str) -> bool:
        """检查 MCP 连接健康状态.

        Args:
            sandbox_id: Sandbox ID

        Returns:
            True 如果 MCP 连接正常
        """
        if self._adapter is None:
            return False

        try:
            sandbox = await self._adapter.get_sandbox(sandbox_id)
            if sandbox is None:
                return False

            # 检查 MCP 客户端连接状态
            mcp_client = getattr(sandbox, "mcp_client", None)
            if mcp_client is None:
                return False

            return getattr(mcp_client, "is_connected", False)
        except Exception as e:
            logger.error(f"Error checking MCP health: {e}")
            return False

    async def check_services_health(self, sandbox_id: str) -> dict[str, bool]:
        """检查 Desktop 和 Terminal 服务健康状态.

        Args:
            sandbox_id: Sandbox ID

        Returns:
            服务状态字典 {"desktop": bool, "terminal": bool}
        """
        result = {"desktop": False, "terminal": False}

        if self._adapter is None:
            return result

        try:
            # 尝试调用 MCP 工具检查服务状态
            try:
                desktop_result = await self._adapter.call_tool(
                    sandbox_id,
                    "get_desktop_status",
                    {"_workspace_dir": "/workspace"},
                    timeout=3.0,
                )
                if desktop_result and not desktop_result.get("is_error"):
                    content = desktop_result.get("content", [])
                    if content:
                        data = json.loads(content[0].get("text", "{}"))
                        result["desktop"] = data.get("running", False)
            except Exception:
                pass  # Desktop 可能不可用

            try:
                terminal_result = await self._adapter.call_tool(
                    sandbox_id,
                    "get_terminal_status",
                    {"_workspace_dir": "/workspace"},
                    timeout=3.0,
                )
                if terminal_result and not terminal_result.get("is_error"):
                    content = terminal_result.get("content", [])
                    if content:
                        data = json.loads(content[0].get("text", "{}"))
                        result["terminal"] = data.get("running", False)
            except Exception:
                pass  # Terminal 可能不可用

        except Exception as e:
            logger.error(f"Error checking services health: {e}")

        return result

    async def check_all_sandboxes(
        self,
        sandbox_ids: list[str],
        level: HealthCheckLevel = HealthCheckLevel.BASIC,
    ) -> list[HealthCheckResult]:
        """批量检查多个 Sandbox 健康状态.

        Args:
            sandbox_ids: Sandbox ID 列表
            level: 检查级别

        Returns:
            健康检查结果列表
        """
        tasks = [self.check_health(sid, level) for sid in sandbox_ids]
        return await asyncio.gather(*tasks, return_exceptions=True)
