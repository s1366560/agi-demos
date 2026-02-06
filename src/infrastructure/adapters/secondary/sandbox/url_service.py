"""Sandbox URL Service - 统一的 URL 构建服务.

提供所有 Sandbox 相关 URL 的构建逻辑，包括:
- MCP WebSocket URL
- Desktop (noVNC) URL
- Terminal (ttyd) URL
- SSE 事件流 URL
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class SandboxInstanceInfo:
    """Sandbox 实例信息，用于 URL 构建."""
    mcp_port: Optional[int] = None
    desktop_port: Optional[int] = None
    terminal_port: Optional[int] = None
    sandbox_id: str = ""
    host: str = "localhost"


@dataclass
class SandboxUrls:
    """所有 Sandbox 相关的 URL."""
    mcp_url: Optional[str]
    desktop_url: Optional[str]
    desktop_url_with_token: Optional[str]
    terminal_url: Optional[str]
    sse_url: Optional[str]


class SandboxUrlService:
    """统一的 Sandbox URL 服务."""

    def __init__(self, default_host: str = "localhost", api_base: str = "/api/v1"):
        """初始化 URL 服务.

        Args:
            default_host: 默认主机名
            api_base: API 基础路径
        """
        self._default_host = default_host
        self._api_base = api_base

    def build_mcp_url(self, instance: SandboxInstanceInfo) -> Optional[str]:
        """构建 MCP WebSocket URL.

        Args:
            instance: Sandbox 实例信息

        Returns:
            MCP WebSocket URL 或 None
        """
        if instance.mcp_port is None:
            return None
        host = instance.host or self._default_host
        return f"ws://{host}:{instance.mcp_port}"

    def build_desktop_url(
        self, instance: SandboxInstanceInfo, token: Optional[str] = None
    ) -> Optional[str]:
        """构建 Desktop (noVNC) URL.

        Args:
            instance: Sandbox 实例信息
            token: 可选的认证 token

        Returns:
            Desktop URL 或 None
        """
        if instance.desktop_port is None:
            return None

        host = instance.host or self._default_host
        base_url = f"http://{host}:{instance.desktop_port}/vnc.html"

        if token:
            return f"{base_url}?token={token}"
        return base_url

    def build_terminal_url(self, instance: SandboxInstanceInfo) -> Optional[str]:
        """构建 Terminal (ttyd) WebSocket URL.

        Args:
            instance: Sandbox 实例信息

        Returns:
            Terminal WebSocket URL 或 None
        """
        if instance.terminal_port is None:
            return None
        host = instance.host or self._default_host
        return f"ws://{host}:{instance.terminal_port}"

    def build_sse_url(self, project_id: str, last_id: str = "0") -> str:
        """构建 SSE 事件流 URL.

        Args:
            project_id: 项目 ID
            last_id: 最后接收的事件 ID

        Returns:
            SSE URL
        """
        base = f"{self._api_base}/sandbox/events/{project_id}"
        if last_id != "0":
            return f"{base}?last_id={last_id}"
        return base

    def build_all_urls(
        self,
        instance: SandboxInstanceInfo,
        project_id: Optional[str] = None,
        token: Optional[str] = None,
    ) -> SandboxUrls:
        """构建所有 URL。

        Args:
            instance: Sandbox 实例信息
            project_id: 项目 ID（用于 SSE）
            token: 可选的认证 token

        Returns:
            所有 URL 的集合
        """
        sse_url = self.build_sse_url(project_id or "", last_id="0") if project_id else None

        return SandboxUrls(
            mcp_url=self.build_mcp_url(instance),
            desktop_url=self.build_desktop_url(instance),
            desktop_url_with_token=self.build_desktop_url(instance, token=token),
            terminal_url=self.build_terminal_url(instance),
            sse_url=sse_url,
        )
