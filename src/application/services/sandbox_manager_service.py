"""Sandbox Manager Service - Sandbox 容器生命周期管理.

提供 Sandbox 容器的完整生命周期管理：
- 创建和删除 Sandbox
- 查询 Sandbox 状态
- 列出所有 Sandbox
- 清理过期 Sandbox
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from src.application.services.sandbox_profile import SandboxProfileType
from src.application.services.sandbox_profile import get_profile as get_sandbox_profile
from src.domain.ports.services.sandbox_port import SandboxConfig, SandboxStatus

logger = logging.getLogger(__name__)


class SandboxCreateResult:
    """Sandbox 创建结果."""

    def __init__(
        self,
        sandbox_id: str,
        status: SandboxStatus,
        project_path: str,
        endpoint: Optional[str] = None,
        websocket_url: Optional[str] = None,
        mcp_port: Optional[int] = None,
        desktop_port: Optional[int] = None,
        terminal_port: Optional[int] = None,
        created_at: Optional[datetime] = None,
        tools: List[str] = None,
    ):
        self.sandbox_id = sandbox_id
        self.status = status
        self.project_path = project_path
        self.endpoint = endpoint
        self.websocket_url = websocket_url
        self.mcp_port = mcp_port
        self.desktop_port = desktop_port
        self.terminal_port = terminal_port
        self.created_at = created_at or datetime.now()
        self.tools = tools or []

    def to_dict(self) -> Dict:
        """转换为字典."""
        return {
            "id": self.sandbox_id,
            "status": self.status.value if isinstance(self.status, SandboxStatus) else self.status,
            "project_path": self.project_path,
            "endpoint": self.endpoint,
            "websocket_url": self.websocket_url,
            "mcp_port": self.mcp_port,
            "desktop_port": self.desktop_port,
            "terminal_port": self.terminal_port,
            "created_at": self.created_at.isoformat(),
            "tools": self.tools,
        }


class SandboxManagerService:
    """Sandbox 管理服务.

    统一的 Sandbox 容器生命周期管理入口。
    """

    def __init__(
        self,
        sandbox_adapter=None,
        default_timeout: float = 300.0,
        default_profile: SandboxProfileType = SandboxProfileType.STANDARD,
    ):
        """初始化 Sandbox 管理器.

        Args:
            sandbox_adapter: Sandbox 适配器
            default_timeout: 默认超时时间
            default_profile: 默认配置类型
        """
        self._adapter = sandbox_adapter
        self._default_timeout = default_timeout
        self._default_profile = default_profile

    def _ensure_adapter(self) -> None:
        """确保适配器已配置."""
        if self._adapter is None:
            raise RuntimeError("Sandbox adapter not configured")

    async def create_sandbox(
        self,
        project_id: str,
        project_path: Optional[str] = None,
        profile: Optional[SandboxProfileType] = None,
        config_override: Optional[Dict[str, Any]] = None,
        tenant_id: Optional[str] = None,
    ) -> SandboxCreateResult:
        """创建一个新的 Sandbox.

        Args:
            project_id: 项目 ID
            project_path: 项目路径（自动生成）
            profile: 配置类型
            config_override: 配置覆盖
            tenant_id: 租户 ID（可选）

        Returns:
            SandboxCreateResult 创建结果
        """
        self._ensure_adapter()

        # 解析项目路径
        resolved_path = self._resolve_project_path(project_id, project_path)

        # 解析配置
        config = self._resolve_config(profile, config_override)

        # 创建 sandbox with project/tenant identification
        sandbox = await self._adapter.create_sandbox(
            project_path=resolved_path,
            config=config,
            project_id=project_id,
            tenant_id=tenant_id,
        )

        # 连接 MCP
        tools: List[str] = []
        if hasattr(self._adapter, "connect_mcp"):
            connected = await self._adapter.connect_mcp(sandbox.id)
            if connected and hasattr(self._adapter, "list_tools"):
                tools_data = await self._adapter.list_tools(sandbox.id)
                tools = [t.get("name", "") for t in tools_data]

        return SandboxCreateResult(
            sandbox_id=sandbox.id,
            status=sandbox.status,
            project_path=resolved_path,
            endpoint=getattr(sandbox, "endpoint", None),
            websocket_url=getattr(sandbox, "websocket_url", None),
            mcp_port=getattr(sandbox, "mcp_port", None),
            desktop_port=getattr(sandbox, "desktop_port", None),
            terminal_port=getattr(sandbox, "terminal_port", None),
            created_at=getattr(sandbox, "created_at", datetime.now()),
            tools=tools,
        )

    async def terminate_sandbox(self, sandbox_id: str) -> bool:
        """终止一个 Sandbox.

        Args:
            sandbox_id: Sandbox ID

        Returns:
            True 如果成功
        """
        self._ensure_adapter()
        return await self._adapter.terminate_sandbox(sandbox_id)

    async def get_sandbox(self, sandbox_id: str) -> Optional[Any]:
        """获取 Sandbox 信息.

        Args:
            sandbox_id: Sandbox ID

        Returns:
            Sandbox 实例或 None
        """
        self._ensure_adapter()
        return await self._adapter.get_sandbox(sandbox_id)

    async def list_sandboxes(
        self,
        status: Optional[SandboxStatus] = None,
    ) -> List[Any]:
        """列出所有 Sandbox.

        Args:
            status: 可选的状态过滤

        Returns:
            Sandbox 列表
        """
        self._ensure_adapter()

        all_sandboxes = await self._adapter.list_sandboxes()

        if status is None:
            return all_sandboxes

        return [sb for sb in all_sandboxes if sb.status == status]

    async def cleanup_expired(
        self,
        max_age_seconds: int = 3600,
    ) -> int:
        """清理过期的 Sandbox.

        Args:
            max_age_seconds: 最大存活时间（秒）

        Returns:
            清理的数量
        """
        self._ensure_adapter()
        return await self._adapter.cleanup_expired(max_age_seconds=max_age_seconds)

    async def get_sandbox_stats(self, sandbox_id: str) -> Dict[str, Any]:
        """获取 Sandbox 统计信息.

        Args:
            sandbox_id: Sandbox ID

        Returns:
            统计信息字典
        """
        self._ensure_adapter()
        return await self._adapter.get_sandbox_stats(sandbox_id)

    async def health_check(self, sandbox_id: str) -> bool:
        """检查 Sandbox 健康状态.

        Args:
            sandbox_id: Sandbox ID

        Returns:
            True 如果健康
        """
        self._ensure_adapter()
        return await self._adapter.health_check(sandbox_id)

    async def batch_create(
        self,
        requests: List[Dict[str, Any]],
    ) -> List[SandboxCreateResult]:
        """批量创建 Sandbox.

        Args:
            requests: 创建请求列表

        Returns:
            创建结果列表
        """
        results = []

        for request in requests:
            project_id = request.get("project_id", "")
            project_path = request.get("project_path")

            try:
                result = await self.create_sandbox(project_id, project_path)
                results.append(result)
            except Exception as e:
                logger.warning(f"Batch create failed for {project_id}: {e}")
                # 返回错误结果
                results.append(
                    SandboxCreateResult(
                        sandbox_id="",
                        status=SandboxStatus.ERROR,
                        project_path=project_path or "",
                    )
                )

        return results

    def _resolve_project_path(
        self,
        project_id: str,
        project_path: Optional[str],
    ) -> str:
        """解析项目路径."""
        if project_path is None:
            project_path = f"/tmp/memstack_{project_id}"
        return project_path

    def _resolve_config(
        self,
        profile: Optional[SandboxProfileType],
        config_override: Optional[Dict[str, Any]],
    ) -> SandboxConfig:
        """解析 Sandbox 配置."""
        profile_type = profile or self._default_profile
        sandbox_profile = get_sandbox_profile(profile_type)

        # 使用 profile 的配置创建 SandboxConfig
        config = SandboxConfig(
            memory_limit=sandbox_profile.memory_limit,
            cpu_limit=sandbox_profile.cpu_limit,
            timeout_seconds=sandbox_profile.timeout_seconds,
            environment=config_override.get("environment") if config_override else None,
        )

        # 应用覆盖配置
        if config_override:
            if "memory_limit" in config_override:
                config.memory_limit = config_override["memory_limit"]
            if "cpu_limit" in config_override:
                config.cpu_limit = config_override["cpu_limit"]
            if "timeout_seconds" in config_override:
                config.timeout_seconds = config_override["timeout_seconds"]

        return config
