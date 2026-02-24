"""
共享Worker池后端.

实现 WARM tier 的共享Worker池策略。
"""

import asyncio
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from ..config import AgentInstanceConfig
from ..instance import AgentInstance, ChatRequest
from ..types import HealthCheckResult, HealthStatus
from .base import Backend, BackendType

logger = logging.getLogger(__name__)


@dataclass
class WorkerSlot:
    """Worker槽位.

    代表共享Worker池中的一个槽位，可以容纳一个Agent实例。
    """

    slot_id: int
    instance: AgentInstance | None = None
    project_key: str | None = None  # tenant_id:project_id:agent_mode

    # 使用统计
    assigned_at: datetime | None = None
    last_used_at: datetime | None = None
    request_count: int = 0

    def is_free(self) -> bool:
        """是否空闲."""
        return self.instance is None

    def assign(self, instance: AgentInstance) -> None:
        """分配实例到槽位."""
        self.instance = instance
        self.project_key = instance.config.instance_key
        self.assigned_at = datetime.now(UTC)
        self.last_used_at = datetime.now(UTC)
        self.request_count = 0

    def release(self) -> AgentInstance | None:
        """释放槽位."""
        instance = self.instance
        self.instance = None
        self.project_key = None
        self.assigned_at = None
        return instance

    def touch(self) -> None:
        """更新使用时间."""
        self.last_used_at = datetime.now(UTC)
        self.request_count += 1


@dataclass
class SharedPoolConfig:
    """共享池配置."""

    # 池大小
    pool_size: int = 4  # Worker槽位数量
    max_instances_per_slot: int = 1  # 每个槽位最大实例数

    # 驱逐策略
    eviction_policy: str = "lru"  # lru, lfu, fifo
    eviction_idle_seconds: int = 1800  # 30分钟空闲后可被驱逐

    # 负载均衡
    load_balance_strategy: str = "least_loaded"  # least_loaded, round_robin


class SharedPoolBackend(Backend):
    """共享Worker池后端.

    为 WARM tier 项目提供共享Worker池:
    - 多个项目共享固定数量的Worker槽位
    - LRU驱逐策略管理槽位分配
    - 负载均衡分配新请求
    """

    def __init__(self, config: SharedPoolConfig | None = None) -> None:
        """初始化共享池后端.

        Args:
            config: 共享池配置
        """
        self.config = config or SharedPoolConfig()

        # Worker槽位
        self._slots: list[WorkerSlot] = [
            WorkerSlot(slot_id=i) for i in range(self.config.pool_size)
        ]

        # 项目到槽位的映射
        self._project_slots: dict[str, int] = {}

        # 锁
        self._lock = asyncio.Lock()

        # 运行状态
        self._running = False

        # 轮询计数器 (用于round_robin)
        self._round_robin_index = 0

        logger.info(
            f"[SharedPoolBackend] Initialized: "
            f"pool_size={self.config.pool_size}, "
            f"eviction_policy={self.config.eviction_policy}"
        )

    @property
    def backend_type(self) -> BackendType:
        """后端类型."""
        return BackendType.SHARED_POOL

    async def start(self) -> None:
        """启动后端."""
        self._running = True
        logger.info("[SharedPoolBackend] Started")

    async def stop(self) -> None:
        """停止后端."""
        self._running = False

        # 停止所有实例
        async with self._lock:
            for slot in self._slots:
                if slot.instance:
                    try:
                        await slot.instance.stop(graceful=True, timeout=10.0)
                    except Exception as e:
                        logger.warning(
                            f"[SharedPoolBackend] Error stopping instance: "
                            f"slot={slot.slot_id}, error={e}"
                        )
                    slot.release()

        self._project_slots.clear()
        logger.info("[SharedPoolBackend] Stopped")

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
            if project_key in self._project_slots:
                slot_id = self._project_slots[project_key]
                slot = self._slots[slot_id]
                if slot.instance and slot.instance.is_active:
                    logger.debug(
                        f"[SharedPoolBackend] Returning existing instance: "
                        f"project={config.project_id}, slot={slot_id}"
                    )
                    return slot.instance

            # 获取空闲槽位或驱逐
            slot = await self._get_available_slot()

            # 创建新实例
            instance = AgentInstance(config=config)
            success = await instance.initialize()

            if not success:
                raise RuntimeError(f"Failed to initialize instance: project={config.project_id}")

            # 分配到槽位
            slot.assign(instance)
            self._project_slots[project_key] = slot.slot_id

            logger.info(
                f"[SharedPoolBackend] Created instance: "
                f"project={config.project_id}, slot={slot.slot_id}"
            )

            return instance

    async def _get_available_slot(self) -> WorkerSlot:
        """获取可用槽位.

        如果没有空闲槽位，按策略驱逐一个。

        Returns:
            可用槽位
        """
        # 查找空闲槽位
        for slot in self._slots:
            if slot.is_free():
                return slot

        # 没有空闲槽位，执行驱逐
        slot = self._select_eviction_target()
        await self._evict_slot(slot)
        return slot

    def _select_eviction_target(self) -> WorkerSlot:
        """选择驱逐目标.

        Returns:
            要驱逐的槽位
        """
        if self.config.eviction_policy == "lru":
            # 最近最少使用
            return min(
                [s for s in self._slots if s.instance],
                key=lambda s: s.last_used_at or datetime.min,
            )
        elif self.config.eviction_policy == "lfu":
            # 最不经常使用
            return min(
                [s for s in self._slots if s.instance],
                key=lambda s: s.request_count,
            )
        else:  # fifo
            # 先进先出
            return min(
                [s for s in self._slots if s.instance],
                key=lambda s: s.assigned_at or datetime.min,
            )

    async def _evict_slot(self, slot: WorkerSlot) -> None:
        """驱逐槽位中的实例.

        Args:
            slot: 要驱逐的槽位
        """
        if slot.instance:
            project_key = slot.project_key
            instance = slot.instance

            logger.info(
                f"[SharedPoolBackend] Evicting instance: "
                f"project_key={project_key}, slot={slot.slot_id}"
            )

            # 停止实例
            try:
                await instance.stop(graceful=True, timeout=5.0)
            except Exception as e:
                logger.warning(f"[SharedPoolBackend] Eviction error: {e}")

            # 释放槽位
            slot.release()

            # 更新映射
            if project_key and project_key in self._project_slots:
                del self._project_slots[project_key]

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
            for slot in self._slots:
                if slot.instance and slot.instance.id == instance_id:
                    project_key = slot.project_key

                    # 停止实例
                    try:
                        await slot.instance.stop(graceful=graceful)
                    except Exception as e:
                        logger.warning(f"[SharedPoolBackend] Destroy error: {e}")

                    # 释放槽位
                    slot.release()

                    # 更新映射
                    if project_key and project_key in self._project_slots:
                        del self._project_slots[project_key]

                    logger.info(f"[SharedPoolBackend] Destroyed instance: id={instance_id}")
                    return True

            return False

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
        for slot in self._slots:
            if slot.instance and slot.instance.id == instance_id:
                return slot.instance
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
        if project_key in self._project_slots:
            slot_id = self._project_slots[project_key]
            slot = self._slots[slot_id]
            return slot.instance
        return None

    async def list_instances(self) -> list[AgentInstance]:
        """列出所有实例.

        Returns:
            实例列表
        """
        return [slot.instance for slot in self._slots if slot.instance]

    async def execute(  # type: ignore[override]
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

        # 更新槽位使用时间
        for slot in self._slots:
            if slot.instance and slot.instance.id == instance_id:
                slot.touch()
                break

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

    def get_stats(self) -> dict[str, Any]:
        """获取后端统计信息.

        Returns:
            统计信息
        """
        used_slots = sum(1 for s in self._slots if s.instance)
        total_requests = sum(s.request_count for s in self._slots)

        return {
            "backend_type": self.backend_type.value,
            "pool_size": self.config.pool_size,
            "used_slots": used_slots,
            "free_slots": self.config.pool_size - used_slots,
            "utilization_pct": (used_slots / self.config.pool_size) * 100,
            "total_requests": total_requests,
            "eviction_policy": self.config.eviction_policy,
            "slots": [
                {
                    "slot_id": s.slot_id,
                    "project_key": s.project_key,
                    "is_free": s.is_free(),
                    "request_count": s.request_count,
                    "assigned_at": s.assigned_at.isoformat() if s.assigned_at else None,
                    "last_used_at": s.last_used_at.isoformat() if s.last_used_at else None,
                }
                for s in self._slots
            ],
        }
