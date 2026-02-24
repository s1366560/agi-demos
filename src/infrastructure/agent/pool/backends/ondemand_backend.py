"""
按需创建后端.

实现 COLD tier 的按需创建策略。
"""

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from ..config import AgentInstanceConfig
from ..instance import AgentInstance, ChatRequest
from ..types import HealthCheckResult, HealthStatus
from .base import Backend, BackendType

logger = logging.getLogger(__name__)


@dataclass
class OnDemandConfig:
    """按需创建配置."""

    # 最大同时实例数
    max_instances: int = 10

    # 实例空闲超时 (秒)
    idle_timeout_seconds: int = 300  # 5分钟

    # 预热池大小 (可选)
    prewarm_pool_size: int = 0

    # 创建超时
    creation_timeout_seconds: int = 60


class OnDemandBackend(Backend):
    """按需创建后端.

    为 COLD tier 项目提供按需创建策略:
    - 请求到达时创建实例
    - 空闲超时后自动销毁
    - 可选预热池加速创建
    """

    def __init__(self, config: OnDemandConfig | None = None) -> None:
        """初始化按需创建后端.

        Args:
            config: 按需创建配置
        """
        self.config = config or OnDemandConfig()

        # 活跃实例
        self._instances: dict[str, AgentInstance] = {}

        # 锁
        self._lock = asyncio.Lock()

        # 运行状态
        self._running = False

        # 清理任务
        self._cleanup_task: asyncio.Task[None] | None = None

        logger.info(
            f"[OnDemandBackend] Initialized: "
            f"max_instances={self.config.max_instances}, "
            f"idle_timeout={self.config.idle_timeout_seconds}s"
        )

    @property
    def backend_type(self) -> BackendType:
        """后端类型."""
        return BackendType.ON_DEMAND

    async def start(self) -> None:
        """启动后端."""
        self._running = True

        # 启动清理任务
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())

        logger.info("[OnDemandBackend] Started")

    async def stop(self) -> None:
        """停止后端."""
        self._running = False

        # 停止清理任务
        if self._cleanup_task:
            self._cleanup_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._cleanup_task

        # 停止所有实例
        async with self._lock:
            for instance in list(self._instances.values()):
                try:
                    await instance.stop(graceful=True, timeout=10.0)
                except Exception as e:
                    logger.warning(
                        f"[OnDemandBackend] Error stopping instance: id={instance.id}, error={e}"
                    )

        self._instances.clear()
        logger.info("[OnDemandBackend] Stopped")

    async def create_instance(
        self,
        config: AgentInstanceConfig,
    ) -> AgentInstance:
        """创建实例.

        Args:
            config: 实例配置

        Returns:
            Agent实例
        """
        async with self._lock:
            project_key = config.instance_key

            # 检查是否已有实例
            if project_key in self._instances:
                instance = self._instances[project_key]
                if instance.is_active:
                    logger.debug(
                        f"[OnDemandBackend] Returning existing instance: "
                        f"project={config.project_id}"
                    )
                    return instance
                else:
                    # 移除不活跃的实例
                    del self._instances[project_key]

            # 检查实例数限制
            if len(self._instances) >= self.config.max_instances:
                # 尝试清理空闲实例
                cleaned = await self._cleanup_idle_instances()
                if not cleaned:
                    raise RuntimeError(f"Max instances reached: {self.config.max_instances}")

            # 创建新实例
            instance = AgentInstance(config=config)

            # 设置较短的空闲超时
            instance.config.idle_timeout_seconds = self.config.idle_timeout_seconds

            # 初始化实例
            try:
                success = await asyncio.wait_for(
                    instance.initialize(),
                    timeout=self.config.creation_timeout_seconds,
                )
            except TimeoutError:
                raise RuntimeError(
                    f"Instance creation timeout: project={config.project_id}"
                ) from None

            if not success:
                raise RuntimeError(f"Failed to initialize instance: project={config.project_id}")

            # 注册实例
            self._instances[project_key] = instance

            logger.info(
                f"[OnDemandBackend] Created instance: project={config.project_id}, id={instance.id}"
            )

            return instance

    async def destroy_instance(
        self,
        instance_id: str,
        graceful: bool = True,
    ) -> bool:
        """销毁实例.

        Args:
            instance_id: 实例ID
            graceful: 是否优雅停止

        Returns:
            是否成功
        """
        async with self._lock:
            # 查找实例
            target_key = None
            target_instance = None
            for key, instance in self._instances.items():
                if instance.id == instance_id:
                    target_key = key
                    target_instance = instance
                    break

            if not target_instance:
                return False

            # 停止实例
            try:
                await target_instance.stop(graceful=graceful)
            except Exception as e:
                logger.warning(f"[OnDemandBackend] Destroy error: {e}")

            # 移除实例
            del self._instances[target_key]

            logger.info(f"[OnDemandBackend] Destroyed instance: id={instance_id}")
            return True

    async def get_instance(
        self,
        instance_id: str,
    ) -> AgentInstance | None:
        """获取实例.

        Args:
            instance_id: 实例ID

        Returns:
            实例或None
        """
        for instance in self._instances.values():
            if instance.id == instance_id:
                return instance
        return None

    async def get_instance_by_project(
        self,
        tenant_id: str,
        project_id: str,
        agent_mode: str = "default",
    ) -> AgentInstance | None:
        """按项目获取实例.

        Args:
            tenant_id: 租户ID
            project_id: 项目ID
            agent_mode: Agent模式

        Returns:
            实例或None
        """
        project_key = f"{tenant_id}:{project_id}:{agent_mode}"
        return self._instances.get(project_key)

    async def list_instances(self) -> list[AgentInstance]:
        """列出所有实例.

        Returns:
            实例列表
        """
        return list(self._instances.values())

    async def execute(
        self,
        instance_id: str,
        request: ChatRequest,
    ) -> AsyncIterator[dict[str, Any]]:
        """在实例上执行请求.

        Args:
            instance_id: 实例ID
            request: 聊天请求

        Yields:
            Agent事件
        """
        instance = await self.get_instance(instance_id)
        if not instance:
            raise RuntimeError(f"Instance not found: id={instance_id}")

        # 执行请求
        async for event in instance.execute(request):
            yield event

    async def health_check(
        self,
        instance_id: str,
    ) -> HealthCheckResult:
        """对实例执行健康检查.

        Args:
            instance_id: 实例ID

        Returns:
            健康检查结果
        """
        instance = await self.get_instance(instance_id)
        if not instance:
            return HealthCheckResult(
                status=HealthStatus.UNKNOWN,
                error_message=f"Instance not found: id={instance_id}",
            )

        return await instance.health_check()

    async def _cleanup_loop(self) -> None:
        """清理循环 - 定期清理空闲实例."""
        while self._running:
            try:
                await asyncio.sleep(60)  # 每分钟检查一次
                await self._cleanup_idle_instances()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[OnDemandBackend] Cleanup error: {e}")

    async def _cleanup_idle_instances(self) -> int:
        """清理空闲实例.

        Returns:
            清理的实例数
        """
        cleaned = 0
        async with self._lock:
            to_remove = []
            for key, instance in self._instances.items():
                if instance.is_idle_expired():
                    to_remove.append((key, instance))

            for key, instance in to_remove:
                try:
                    await instance.stop(graceful=False, timeout=5.0)
                except Exception as e:
                    logger.warning(f"[OnDemandBackend] Cleanup error: id={instance.id}, error={e}")
                del self._instances[key]
                cleaned += 1

                logger.info(
                    f"[OnDemandBackend] Cleaned up idle instance: "
                    f"id={instance.id}, idle_seconds={instance.get_idle_seconds()}"
                )

        return cleaned

    def get_stats(self) -> dict[str, Any]:
        """获取后端统计信息.

        Returns:
            统计信息
        """
        active_count = len(self._instances)
        total_requests = sum(i.metrics.total_requests for i in self._instances.values())

        return {
            "backend_type": self.backend_type.value,
            "max_instances": self.config.max_instances,
            "active_instances": active_count,
            "available_slots": self.config.max_instances - active_count,
            "utilization_pct": (active_count / self.config.max_instances) * 100
            if self.config.max_instances > 0
            else 0,
            "total_requests": total_requests,
            "idle_timeout_seconds": self.config.idle_timeout_seconds,
            "instances": [
                {
                    "id": i.id,
                    "project_key": i.config.instance_key,
                    "status": i.status.value,
                    "idle_seconds": i.get_idle_seconds(),
                    "request_count": i.metrics.total_requests,
                }
                for i in self._instances.values()
            ],
        }
