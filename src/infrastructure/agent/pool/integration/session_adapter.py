"""
Pooled Agent Session Adapter.

桥接新的 AgentPoolManager 与现有的 AgentSessionPool 缓存机制。
提供向后兼容的接口，同时利用池化管理的优势。

集成策略:
1. 现有 AgentSessionContext 缓存继续保留 (工具定义、SubAgentRouter等)
2. 新增 AgentInstance 生命周期管理
3. 资源配额和健康监控由 AgentPoolManager 管理
4. 逐步迁移，支持特性开关控制
"""

import asyncio
import logging
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Any

from ..config import AgentInstanceConfig, PoolConfig
from ..instance import AgentInstance, ChatRequest
from ..manager import AgentPoolManager
from ..types import (
    HealthCheckResult,
    ProjectTier,
)

logger = logging.getLogger(__name__)


@dataclass
class AdapterConfig:
    """适配器配置."""

    # 是否启用池化管理
    enable_pool_management: bool = True

    # 是否启用资源隔离
    enable_resource_isolation: bool = True

    # 是否启用健康监控
    enable_health_monitoring: bool = True

    # 是否启用自动分级
    enable_auto_classification: bool = True

    # 回退到传统模式的条件
    fallback_on_pool_error: bool = True

    # 预热配置
    enable_prewarming: bool = True
    prewarm_on_startup: bool = False

    # 指标收集
    enable_metrics: bool = True


@dataclass
class SessionRequest:
    """会话请求上下文."""

    tenant_id: str
    project_id: str
    agent_mode: str = "default"
    user_id: str | None = None
    conversation_id: str | None = None

    # 可选的 LLM 配置覆盖
    model: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    max_steps: int | None = None

    # 请求元数据
    metadata: dict[str, Any] = field(default_factory=dict)


class PooledAgentSessionAdapter:
    """池化 Agent 会话适配器.

    提供与现有 AgentSessionPool 兼容的接口，同时集成新的池化管理能力。

    Usage:
        adapter = PooledAgentSessionAdapter()
        await adapter.start()

        # 获取或创建会话
        instance = await adapter.get_session(
            SessionRequest(tenant_id="t1", project_id="p1")
        )

        # 执行请求
        async for event in adapter.execute(instance, chat_request):
            yield event

        await adapter.stop()
    """

    def __init__(
        self,
        pool_config: PoolConfig | None = None,
        adapter_config: AdapterConfig | None = None,
        agent_factory: Callable[..., Any] | None = None,
    ) -> None:
        """初始化适配器.

        Args:
            pool_config: 池配置
            adapter_config: 适配器配置
            agent_factory: Agent 工厂函数 (用于创建 ReActAgent)
        """
        self.pool_config = pool_config or PoolConfig()
        self.adapter_config = adapter_config or AdapterConfig()
        self._agent_factory = agent_factory

        # 池管理器
        self._pool_manager: AgentPoolManager | None = None

        # 传统会话池引用 (延迟加载)
        self._legacy_session_pool: Any | None = None

        # 运行状态
        self._running = False
        self._lock = asyncio.Lock()

        logger.info(
            f"[PooledAgentSessionAdapter] Created: "
            f"pool_management={self.adapter_config.enable_pool_management}, "
            f"resource_isolation={self.adapter_config.enable_resource_isolation}"
        )

    async def start(self) -> None:
        """启动适配器."""
        if self._running:
            return

        async with self._lock:
            if self._running:
                return  # type: ignore[unreachable]

            logger.info("[PooledAgentSessionAdapter] Starting...")

            # 初始化池管理器
            if self.adapter_config.enable_pool_management:
                self._pool_manager = AgentPoolManager(config=self.pool_config)
                await self._pool_manager.start()

            # 预热 (如果启用)
            if self.adapter_config.enable_prewarming and self.adapter_config.prewarm_on_startup:
                await self._prewarm_pool()

            self._running = True
            logger.info("[PooledAgentSessionAdapter] Started")

    async def stop(self) -> None:
        """停止适配器."""
        if not self._running:
            return

        async with self._lock:
            if not self._running:
                return  # type: ignore[unreachable]

            logger.info("[PooledAgentSessionAdapter] Stopping...")

            if self._pool_manager:
                await self._pool_manager.stop()

            self._running = False
            logger.info("[PooledAgentSessionAdapter] Stopped")

    async def get_session(
        self,
        request: SessionRequest,
    ) -> AgentInstance:
        """获取或创建 Agent 会话实例.

        Args:
            request: 会话请求

        Returns:
            AgentInstance
        """
        if not self._running:
            raise RuntimeError("Adapter not started")

        try:
            if self.adapter_config.enable_pool_management and self._pool_manager is not None:
                return await self._get_pooled_instance(request)
            else:
                return await self._get_legacy_instance(request)

        except Exception as e:
            logger.error(f"[PooledAgentSessionAdapter] Get session error: {e}")

            if self.adapter_config.fallback_on_pool_error:
                logger.warning("[PooledAgentSessionAdapter] Falling back to legacy mode")
                return await self._get_legacy_instance(request)

            raise

    async def _get_pooled_instance(
        self,
        request: SessionRequest,
    ) -> AgentInstance:
        """从池获取实例."""
        assert self._pool_manager is not None

        # 构建实例配置
        config = AgentInstanceConfig(
            project_id=request.project_id,
            tenant_id=request.tenant_id,
            agent_mode=request.agent_mode,
            model=request.model,
            temperature=request.temperature or 0.7,
            max_tokens=request.max_tokens or 4096,
            max_steps=request.max_steps or 20,
        )

        # 从池获取或创建实例
        instance = await self._pool_manager.get_or_create_instance(
            tenant_id=request.tenant_id,
            project_id=request.project_id,
            agent_mode=request.agent_mode,
            config_override=config,
        )

        return instance

    async def _get_legacy_instance(
        self,
        request: SessionRequest,
    ) -> AgentInstance:
        """使用传统方式创建实例 (回退模式)."""
        # 创建基本配置
        config = AgentInstanceConfig(
            project_id=request.project_id,
            tenant_id=request.tenant_id,
            agent_mode=request.agent_mode,
            tier=ProjectTier.COLD,  # 传统模式使用 COLD tier
            model=request.model,
            temperature=request.temperature or 0.7,
            max_tokens=request.max_tokens or 4096,
            max_steps=request.max_steps or 20,
        )

        # 创建 Agent (如果有工厂函数)
        react_agent = None
        if self._agent_factory:
            react_agent = await self._agent_factory(
                tenant_id=request.tenant_id,
                project_id=request.project_id,
                agent_mode=request.agent_mode,
            )

        # 创建实例
        instance = AgentInstance(config=config, react_agent=react_agent)
        await instance.initialize()

        return instance

    async def execute(
        self,
        instance: AgentInstance,
        request: ChatRequest,
    ) -> AsyncIterator[dict[str, Any]]:
        """执行聊天请求.

        Args:
            instance: Agent 实例
            request: 聊天请求

        Yields:
            Agent 事件
        """
        if not self._running:
            raise RuntimeError("Adapter not started")

        async for event in instance.execute(request):
            yield event

    async def release_session(
        self,
        instance: AgentInstance,
        force: bool = False,
    ) -> None:
        """释放会话实例.

        Args:
            instance: Agent 实例
            force: 是否强制释放
        """
        if self._pool_manager and self.adapter_config.enable_pool_management:
            # 池管理的实例由池管理器管理生命周期
            # 这里只是标记为空闲，不需要立即释放
            pass
        else:
            # 传统模式下直接停止实例
            await instance.stop(graceful=not force)

    async def get_stats(self) -> dict[str, Any]:
        """获取适配器统计信息."""
        stats: dict[str, Any] = {
            "running": self._running,
            "mode": "pooled" if self.adapter_config.enable_pool_management else "legacy",
        }

        if self._pool_manager:
            pool_stats = self._pool_manager.get_stats()
            stats["pool"] = {
                "total_instances": pool_stats.total_instances,
                "hot_instances": pool_stats.hot_instances,
                "warm_instances": pool_stats.warm_instances,
                "cold_instances": pool_stats.cold_instances,
                "ready_instances": pool_stats.ready_instances,
                "executing_instances": pool_stats.executing_instances,
                "unhealthy_instances": pool_stats.unhealthy_instances,
                "total_requests": pool_stats.total_requests,
                "active_requests": pool_stats.active_requests,
            }

        return stats

    async def health_check(
        self,
        tenant_id: str,
        project_id: str,
        agent_mode: str = "default",
    ) -> HealthCheckResult | None:
        """检查指定会话的健康状态.

        Args:
            tenant_id: 租户 ID
            project_id: 项目 ID
            agent_mode: Agent 模式

        Returns:
            健康检查结果，如果实例不存在则返回 None
        """
        if not self._pool_manager:
            return None

        instance = await self._pool_manager.get_instance(
            tenant_id=tenant_id,
            project_id=project_id,
            agent_mode=agent_mode,
        )

        if not instance:
            return None

        return await instance.health_check()

    async def _prewarm_pool(self) -> None:
        """预热池."""
        logger.info("[PooledAgentSessionAdapter] Prewarming pool...")

        # TODO: 实现基于历史数据的预热逻辑
        # 1. 查询最近活跃的项目
        # 2. 为高频项目预创建实例

        logger.info("[PooledAgentSessionAdapter] Prewarm complete")

    async def classify_project(
        self,
        tenant_id: str,
        project_id: str,
    ) -> ProjectTier:
        """获取项目分级.

        Args:
            tenant_id: 租户 ID
            project_id: 项目 ID

        Returns:
            项目分级
        """
        if self._pool_manager:
            return await self._pool_manager.classify_project(
                tenant_id=tenant_id,
                project_id=project_id,
            )

        return ProjectTier.COLD

    async def set_project_tier(
        self,
        tenant_id: str,
        project_id: str,
        tier: ProjectTier,
    ) -> bool:
        """手动设置项目分级.

        Args:
            tenant_id: 租户 ID
            project_id: 项目 ID
            tier: 目标分级

        Returns:
            是否成功
        """
        if self._pool_manager:
            return await self._pool_manager.set_project_tier(
                tenant_id=tenant_id,
                project_id=project_id,
                tier=tier,
            )

        return False


# ============================================================================
# 便捷工厂函数
# ============================================================================


def create_pooled_adapter(
    enable_pool_management: bool = True,
    enable_resource_isolation: bool = True,
    enable_health_monitoring: bool = True,
) -> PooledAgentSessionAdapter:
    """创建池化适配器的便捷工厂函数.

    Args:
        enable_pool_management: 是否启用池化管理
        enable_resource_isolation: 是否启用资源隔离
        enable_health_monitoring: 是否启用健康监控

    Returns:
        配置好的适配器实例
    """
    adapter_config = AdapterConfig(
        enable_pool_management=enable_pool_management,
        enable_resource_isolation=enable_resource_isolation,
        enable_health_monitoring=enable_health_monitoring,
    )

    return PooledAgentSessionAdapter(adapter_config=adapter_config)


# ============================================================================
# 全局适配器实例 (单例模式)
# ============================================================================

_global_adapter: PooledAgentSessionAdapter | None = None
_global_adapter_lock = asyncio.Lock()


async def get_global_adapter() -> PooledAgentSessionAdapter:
    """获取全局适配器实例.

    Returns:
        全局适配器实例
    """
    global _global_adapter

    if _global_adapter is None:
        async with _global_adapter_lock:
            if _global_adapter is None:
                _global_adapter = PooledAgentSessionAdapter()
                await _global_adapter.start()

    return _global_adapter


async def shutdown_global_adapter() -> None:
    """关闭全局适配器."""
    global _global_adapter

    if _global_adapter is not None:
        async with _global_adapter_lock:
            if _global_adapter is not None:
                await _global_adapter.stop()
                _global_adapter = None
