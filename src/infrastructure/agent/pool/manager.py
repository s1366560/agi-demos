"""
Agent池管理器.

管理 Agent 实例的创建、获取、分级和生命周期。
"""

import asyncio
import contextlib
import logging
from collections.abc import Callable
from typing import Any

from .config import AgentInstanceConfig, PoolConfig
from .health import HealthMonitor, HealthMonitorConfig
from .instance import AgentInstance
from .resource import ResourceManager
from .types import (
    AgentInstanceStatus,
    HealthCheckResult,
    PoolStats,
    ProjectMetrics,
    ProjectTier,
    RecoveryAction,
)

logger = logging.getLogger(__name__)


class AgentPoolManager:
    """Agent池管理器.

    管理整个 Agent 实例池:
    - 实例的创建、获取、销毁
    - 项目分级 (HOT/WARM/COLD)
    - 资源配额管理
    - 健康监控
    - 自动扩缩容
    """

    def __init__(
        self,
        config: PoolConfig | None = None,
        resource_manager: ResourceManager | None = None,
        health_monitor: HealthMonitor | None = None,
    ) -> None:
        """初始化池管理器.

        Args:
            config: 池配置
            resource_manager: 资源管理器 (可选，自动创建)
            health_monitor: 健康监控器 (可选，自动创建)
        """
        self.config = config or PoolConfig()
        self._resource_manager = resource_manager or ResourceManager(self.config)
        self._health_monitor = health_monitor or HealthMonitor(
            config=HealthMonitorConfig(
                check_interval_seconds=self.config.health_check_interval_seconds,
                check_timeout_seconds=self.config.health_check_timeout_seconds,
                unhealthy_threshold=self.config.unhealthy_threshold,
                healthy_threshold=self.config.healthy_threshold,
            ),
            on_unhealthy=self._on_instance_unhealthy,
            on_recovered=self._on_instance_recovered,
        )

        # 实例存储
        self._instances: dict[str, AgentInstance] = {}
        self._instances_lock = asyncio.Lock()

        # 项目到实例的映射 (一个项目可能有多个实例)
        self._project_instances: dict[str, set[str]] = {}

        # 后台任务
        self._cleanup_task: asyncio.Task | None = None
        self._running = False
        self._background_tasks: set[asyncio.Task[Any]] = set()

        # 事件回调
        self._on_instance_created: list[Callable[[AgentInstance], None]] = []
        self._on_instance_terminated: list[Callable[[AgentInstance], None]] = []

        logger.info(
            f"[AgentPoolManager] Initialized: "
            f"max_instances={self.config.max_total_instances}, "
            f"max_memory={self.config.max_total_memory_mb}MB"
        )

    async def start(self) -> None:
        """启动池管理器."""
        if self._running:
            return

        self._running = True

        # 启动清理任务
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())

        logger.info("[AgentPoolManager] Started")

    async def stop(self) -> None:
        """停止池管理器."""
        if not self._running:
            return

        self._running = False

        # 停止清理任务
        if self._cleanup_task:
            self._cleanup_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._cleanup_task

        # 停止所有健康监控
        await self._health_monitor.stop_all_monitoring()

        # 停止所有实例
        async with self._instances_lock:
            for instance in list(self._instances.values()):
                try:
                    await instance.stop(graceful=True, timeout=10.0)
                except Exception as e:
                    logger.warning(
                        f"[AgentPoolManager] Error stopping instance: id={instance.id}, error={e}"
                    )

        logger.info("[AgentPoolManager] Stopped")

    async def get_or_create_instance(
        self,
        tenant_id: str,
        project_id: str,
        agent_mode: str = "default",
        config_override: AgentInstanceConfig | None = None,
    ) -> AgentInstance:
        """获取或创建Agent实例.

        Args:
            tenant_id: 租户ID
            project_id: 项目ID
            agent_mode: Agent模式
            config_override: 配置覆盖

        Returns:
            Agent实例
        """
        instance_key = f"{tenant_id}:{project_id}:{agent_mode}"

        async with self._instances_lock:
            # 检查是否已有活跃实例
            if instance_key in self._instances:
                instance = self._instances[instance_key]
                if instance.is_active:
                    logger.debug(f"[AgentPoolManager] Returning cached instance: id={instance.id}")
                    return instance
                else:
                    # 实例不活跃，移除
                    await self._remove_instance(instance)

            # 创建新实例
            instance = await self._create_instance(
                tenant_id=tenant_id,
                project_id=project_id,
                agent_mode=agent_mode,
                config_override=config_override,
            )

            return instance

    async def _create_instance(
        self,
        tenant_id: str,
        project_id: str,
        agent_mode: str,
        config_override: AgentInstanceConfig | None = None,
    ) -> AgentInstance:
        """创建新实例.

        Args:
            tenant_id: 租户ID
            project_id: 项目ID
            agent_mode: Agent模式
            config_override: 配置覆盖

        Returns:
            新创建的实例
        """
        # 获取或创建配置
        if config_override:
            config = config_override
        else:
            # 分类项目获取默认配置
            tier = await self.classify_project(tenant_id, project_id)
            tier_config = self.config.get_tier_config(tier)
            config = AgentInstanceConfig(
                project_id=project_id,
                tenant_id=tenant_id,
                agent_mode=agent_mode,
                tier=tier,
                quota=tier_config.default_quota,
            )

        # 分配资源
        await self._resource_manager.allocate(config)
        await self._resource_manager.acquire_instance(
            tenant_id=tenant_id,
            project_id=project_id,
            memory_mb=config.quota.memory_request_mb,
            cpu_cores=config.quota.cpu_request_cores,
        )

        # 创建实例
        instance = AgentInstance(config=config)

        # 初始化实例
        success = await instance.initialize()
        if not success:
            # 释放资源
            await self._resource_manager.release_instance(
                tenant_id=tenant_id,
                project_id=project_id,
                memory_mb=config.quota.memory_request_mb,
                cpu_cores=config.quota.cpu_request_cores,
            )
            raise RuntimeError(f"Failed to initialize instance: project={project_id}")

        # 注册实例
        instance_key = config.instance_key
        self._instances[instance_key] = instance

        # 更新项目映射
        if instance_key not in self._project_instances:
            self._project_instances[instance_key] = set()
        self._project_instances[instance_key].add(instance.id)

        # 启动健康监控
        await self._health_monitor.start_monitoring(
            instance,
            interval_seconds=config.health_check_interval_seconds,
        )

        # 触发回调
        for callback in self._on_instance_created:
            try:
                callback(instance)
            except Exception as e:
                logger.warning(f"[AgentPoolManager] Callback error: {e}")

        logger.info(
            f"[AgentPoolManager] Created instance: "
            f"id={instance.id}, project={project_id}, tier={config.tier.value}"
        )

        return instance

    async def _remove_instance(self, instance: AgentInstance) -> None:
        """移除实例.

        Args:
            instance: 要移除的实例
        """
        instance_key = instance.config.instance_key

        # 停止健康监控
        await self._health_monitor.stop_monitoring(instance.id)

        # 停止实例
        if instance.status not in {
            AgentInstanceStatus.TERMINATED,
            AgentInstanceStatus.TERMINATING,
        }:
            await instance.stop(graceful=False)

        # 释放资源
        await self._resource_manager.release_instance(
            tenant_id=instance.config.tenant_id,
            project_id=instance.config.project_id,
            memory_mb=instance.config.quota.memory_request_mb,
            cpu_cores=instance.config.quota.cpu_request_cores,
        )

        # 从存储中移除
        self._instances.pop(instance_key, None)
        if instance_key in self._project_instances:
            self._project_instances[instance_key].discard(instance.id)

        # 触发回调
        for callback in self._on_instance_terminated:
            try:
                callback(instance)
            except Exception as e:
                logger.warning(f"[AgentPoolManager] Callback error: {e}")

        logger.info(f"[AgentPoolManager] Removed instance: id={instance.id}")

    async def classify_project(
        self,
        tenant_id: str,
        project_id: str,
        metrics: ProjectMetrics | None = None,
    ) -> ProjectTier:
        """对项目进行分级.
        Args:
            tenant_id: 租户ID
            project_id: 项目ID
            metrics: 项目指标 (可选)
            项目分级
        """
        if metrics is None:
            # 使用默认分级
            # TODO: 从数据库获取历史指标
            return ProjectTier.WARM

        score = self._compute_project_score(metrics)

        # 分级
        if score >= 80:
            return ProjectTier.HOT
        elif score >= 50:
            return ProjectTier.WARM
        else:
            return ProjectTier.COLD
    @staticmethod
    def _compute_project_score(metrics: ProjectMetrics) -> int:
        """Compute composite score from project metrics."""
        score = 0
        if metrics.daily_requests > 1000:
            score += 40
        elif metrics.daily_requests > 100:
            score += 25
        else:
            score += 10
        # 付费等级 (权重 30%)
        subscription_scores = {
            "enterprise": 30,
            "professional": 20,
            "basic": 10,
            "free": 5,
        }
        score += subscription_scores.get(metrics.subscription_tier, 5)
        if metrics.sla_requirement >= 0.999:
            score += 20
        elif metrics.sla_requirement >= 0.995:
            score += 15
        else:
            score += 5
        if metrics.max_concurrent > 10:
            score += 10
        elif metrics.max_concurrent > 3:
            score += 7
        else:
            score += 3
        return score

    async def get_instance(
        self,
        tenant_id: str,
        project_id: str,
        agent_mode: str = "default",
    ) -> AgentInstance | None:
        """获取实例 (不创建).

        Args:
            tenant_id: 租户ID
            project_id: 项目ID
            agent_mode: Agent模式

        Returns:
            实例或None
        """
        instance_key = f"{tenant_id}:{project_id}:{agent_mode}"
        return self._instances.get(instance_key)

    async def terminate_instance(
        self,
        tenant_id: str,
        project_id: str,
        agent_mode: str = "default",
        graceful: bool = True,
    ) -> bool:
        """终止实例.

        Args:
            tenant_id: 租户ID
            project_id: 项目ID
            agent_mode: Agent模式
            graceful: 是否优雅终止

        Returns:
            是否成功
        """
        async with self._instances_lock:
            instance_key = f"{tenant_id}:{project_id}:{agent_mode}"
            instance = self._instances.get(instance_key)

            if not instance:
                return False

            await self._remove_instance(instance)
            return True

    async def pause_instance(
        self,
        tenant_id: str,
        project_id: str,
        agent_mode: str = "default",
    ) -> bool:
        """暂停实例.

        Args:
            tenant_id: 租户ID
            project_id: 项目ID
            agent_mode: Agent模式

        Returns:
            是否成功
        """
        instance = await self.get_instance(tenant_id, project_id, agent_mode)
        if not instance:
            return False

        await instance.pause()
        return True

    async def resume_instance(
        self,
        tenant_id: str,
        project_id: str,
        agent_mode: str = "default",
    ) -> bool:
        """恢复实例.

        Args:
            tenant_id: 租户ID
            project_id: 项目ID
            agent_mode: Agent模式

        Returns:
            是否成功
        """
        instance = await self.get_instance(tenant_id, project_id, agent_mode)
        if not instance:
            return False

        await instance.resume()
        return True

    async def health_check(
        self,
        tenant_id: str,
        project_id: str,
        agent_mode: str = "default",
    ) -> HealthCheckResult | None:
        """对实例执行健康检查.

        Args:
            tenant_id: 租户ID
            project_id: 项目ID
            agent_mode: Agent模式

        Returns:
            健康检查结果或None
        """
        instance = await self.get_instance(tenant_id, project_id, agent_mode)
        if not instance:
            return None

        return await self._health_monitor.check_instance(instance)

    def _on_instance_unhealthy(
        self,
        instance: AgentInstance,
        result: HealthCheckResult,
    ) -> None:
        """处理实例不健康事件.

        Args:
            instance: 不健康的实例
            result: 健康检查结果
        """
        logger.warning(
            f"[AgentPoolManager] Instance unhealthy: "
            f"id={instance.id}, project={instance.config.project_id}, "
            f"error={result.error_message}"
        )

        # 决定恢复策略
        action = self._health_monitor.determine_recovery_action(instance, result)

        # 异步执行恢复
        _recovery_task = asyncio.create_task(self._execute_recovery(instance, action))
        self._background_tasks.add(_recovery_task)
        _recovery_task.add_done_callback(self._background_tasks.discard)

    def _on_instance_recovered(self, instance: AgentInstance) -> None:
        """处理实例恢复事件.

        Args:
            instance: 恢复的实例
        """
        logger.info(
            f"[AgentPoolManager] Instance recovered: "
            f"id={instance.id}, project={instance.config.project_id}"
        )

    async def _execute_recovery(
        self,
        instance: AgentInstance,
        action: RecoveryAction,
    ) -> None:
        """执行恢复策略.

        Args:
            instance: 要恢复的实例
            action: 恢复动作
        """
        try:
            if action == RecoveryAction.RESTART:
                logger.info(f"[AgentPoolManager] Restarting instance: id={instance.id}")
                # 重新初始化
                success = await instance.initialize(force_refresh=True)
                if success:
                    instance.mark_recovered()

            elif action == RecoveryAction.TERMINATE:
                logger.info(f"[AgentPoolManager] Terminating instance: id={instance.id}")
                async with self._instances_lock:
                    await self._remove_instance(instance)

            elif action == RecoveryAction.DEGRADE:
                logger.info(f"[AgentPoolManager] Degrading instance: id={instance.id}")
                # 降级模式 - 禁用部分功能

            elif action == RecoveryAction.MIGRATE:
                logger.info(f"[AgentPoolManager] Migrating instance: id={instance.id}")
                # TODO: 实现迁移逻辑

            elif action == RecoveryAction.ALERT:
                logger.warning(f"[AgentPoolManager] Alert: Instance unhealthy: id={instance.id}")

        except Exception as e:
            logger.error(
                f"[AgentPoolManager] Recovery failed: "
                f"id={instance.id}, action={action.value}, error={e}"
            )

    async def _cleanup_loop(self) -> None:
        """清理循环 - 定期清理过期实例."""
        while self._running:
            try:
                await asyncio.sleep(self.config.cleanup_interval_seconds)
                await self._cleanup_expired_instances()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[AgentPoolManager] Cleanup error: {e}")

    async def _cleanup_expired_instances(self) -> None:
        """清理过期实例."""
        async with self._instances_lock:
            expired = []
            for _instance_key, instance in self._instances.items():
                # 检查空闲超时
                if instance.is_idle_expired():
                    expired.append(instance)
                    continue

                # 检查已终止的实例
                if instance.status == AgentInstanceStatus.TERMINATED:
                    expired.append(instance)

            for instance in expired:
                logger.info(
                    f"[AgentPoolManager] Cleaning up expired instance: "
                    f"id={instance.id}, idle_seconds={instance.get_idle_seconds()}"
                )
                await self._remove_instance(instance)

    def get_stats(self) -> PoolStats:
        """获取池统计信息.

        Returns:
            池统计
        """
        stats = PoolStats()

        for instance in self._instances.values():
            stats.total_instances += 1

            # 按分级统计
            if instance.config.tier == ProjectTier.HOT:
                stats.hot_instances += 1
            elif instance.config.tier == ProjectTier.WARM:
                stats.warm_instances += 1
            else:
                stats.cold_instances += 1

            # 按状态统计
            if instance.status == AgentInstanceStatus.READY:
                stats.ready_instances += 1
            elif instance.status == AgentInstanceStatus.EXECUTING:
                stats.executing_instances += 1
            elif instance.status == AgentInstanceStatus.UNHEALTHY:
                stats.unhealthy_instances += 1

            # 请求统计
            stats.active_requests += instance.active_requests
            stats.total_requests += instance.metrics.total_requests

        return stats

    def list_instances(self) -> list[dict[str, Any]]:
        """列出所有实例.

        Returns:
            实例信息列表
        """
        return [instance.to_dict() for instance in self._instances.values()]

    async def set_project_tier(
        self,
        tenant_id: str,
        project_id: str,
        tier: ProjectTier,
        agent_mode: str = "default",
    ) -> bool:
        """手动设置项目分级.

        用于管理员手动覆盖自动分级结果。
        如果存在实例，会触发实例迁移到新分级。

        Args:
            tenant_id: 租户ID
            project_id: 项目ID
            tier: 目标分级
            agent_mode: Agent模式

        Returns:
            是否成功
        """
        instance_key = f"{tenant_id}:{project_id}:{agent_mode}"

        async with self._instances_lock:
            instance = self._instances.get(instance_key)

            if instance:
                # 如果实例存在且分级不同，需要迁移
                if instance.config.tier != tier:
                    logger.info(
                        f"[AgentPoolManager] Tier migration: "
                        f"project={project_id}, "
                        f"{instance.config.tier.value} -> {tier.value}"
                    )

                    # 更新配置
                    old_config = instance.config
                    new_config = old_config.with_tier(tier)
                    new_config.tier_override = True

                    # 简单策略: 标记配置变更，下次请求时重建实例
                    # 复杂策略: 立即迁移实例 (需要更多实现)
                    instance.config = new_config

        # 记录分级覆盖 (用于分级算法学习)
        # TODO: 持久化分级覆盖记录

        logger.info(f"[AgentPoolManager] Project tier set: project={project_id}, tier={tier.value}")

        return True

    def to_dict(self) -> dict[str, Any]:
        """转换为字典."""
        stats = self.get_stats()
        return {
            "config": {
                "max_total_instances": self.config.max_total_instances,
                "max_total_memory_mb": self.config.max_total_memory_mb,
                "max_total_cpu_cores": self.config.max_total_cpu_cores,
            },
            "stats": {
                "total_instances": stats.total_instances,
                "hot_instances": stats.hot_instances,
                "warm_instances": stats.warm_instances,
                "cold_instances": stats.cold_instances,
                "ready_instances": stats.ready_instances,
                "executing_instances": stats.executing_instances,
                "unhealthy_instances": stats.unhealthy_instances,
                "active_requests": stats.active_requests,
            },
            "resource_manager": self._resource_manager.to_dict(),
            "health_monitor": self._health_monitor.to_dict(),
        }
