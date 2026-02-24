"""
预热池管理.

提供多级预热池，加速实例创建。
"""

import asyncio
import contextlib
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from ..config import AgentInstanceConfig, ResourceQuota
from ..instance import AgentInstance
from ..types import ProjectTier

logger = logging.getLogger(__name__)


@dataclass
class PrewarmConfig:
    """预热池配置."""

    # L1 池 (完整预热) - 工具+LLM+MCP全部就绪
    l1_pool_size: int = 2
    l1_ttl_seconds: int = 3600  # 1小时

    # L2 池 (部分预热) - 仅工具就绪
    l2_pool_size: int = 5
    l2_ttl_seconds: int = 7200  # 2小时

    # L3 池 (模板) - 仅配置就绪
    l3_pool_size: int = 10
    l3_ttl_seconds: int = 86400  # 24小时

    # 维护间隔
    maintenance_interval_seconds: int = 60

    # 预热触发阈值
    low_watermark_pct: float = 0.3  # 低于30%触发补充


@dataclass
class PrewarmedInstance:
    """预热实例."""

    instance: AgentInstance
    tier: ProjectTier
    level: int  # 1, 2, or 3
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    ttl_seconds: int = 3600

    def is_expired(self) -> bool:
        """是否过期."""
        elapsed = (datetime.now(UTC) - self.created_at).total_seconds()
        return elapsed > self.ttl_seconds


@dataclass
class InstanceTemplate:
    """实例模板 (L3级)."""

    tier: ProjectTier
    quota: ResourceQuota
    config_template: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class PrewarmPool:
    """预热池管理.

    提供三级预热策略:
    - L1: 完整预热实例 (工具+LLM+MCP全部就绪)
    - L2: 部分预热实例 (仅工具就绪)
    - L3: 实例模板 (仅配置就绪)

    获取优先级: L1 > L2 > L3 > 新建
    """

    def __init__(self, config: PrewarmConfig | None = None) -> None:
        """初始化预热池.

        Args:
            config: 预热池配置
        """
        self.config = config or PrewarmConfig()

        # L1 池: 完整预热实例
        self._l1_pool: dict[ProjectTier, list[PrewarmedInstance]] = {
            ProjectTier.HOT: [],
            ProjectTier.WARM: [],
            ProjectTier.COLD: [],
        }

        # L2 池: 部分预热实例
        self._l2_pool: dict[ProjectTier, list[PrewarmedInstance]] = {
            ProjectTier.HOT: [],
            ProjectTier.WARM: [],
            ProjectTier.COLD: [],
        }

        # L3 池: 实例模板
        self._l3_pool: list[InstanceTemplate] = []

        # 锁
        self._lock = asyncio.Lock()

        # 运行状态
        self._running = False
        self._maintenance_task: asyncio.Task | None = None

        # 统计
        self._stats = {
            "l1_hits": 0,
            "l2_hits": 0,
            "l3_hits": 0,
            "misses": 0,
            "total_prewarmed": 0,
            "total_expired": 0,
        }

        logger.info(
            f"[PrewarmPool] Initialized: "
            f"L1={self.config.l1_pool_size}, "
            f"L2={self.config.l2_pool_size}, "
            f"L3={self.config.l3_pool_size}"
        )

    async def start(self) -> None:
        """启动预热池."""
        self._running = True

        # 启动维护任务
        self._maintenance_task = asyncio.create_task(self._maintenance_loop())

        logger.info("[PrewarmPool] Started")

    async def stop(self) -> None:
        """停止预热池."""
        self._running = False

        # 停止维护任务
        if self._maintenance_task:
            self._maintenance_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._maintenance_task

        # 清理所有预热实例
        async with self._lock:
            for tier_pool in self._l1_pool.values():
                for prewarmed in tier_pool:
                    with contextlib.suppress(Exception):
                        await prewarmed.instance.stop(graceful=False)
                tier_pool.clear()

            for tier_pool in self._l2_pool.values():
                for prewarmed in tier_pool:
                    with contextlib.suppress(Exception):
                        await prewarmed.instance.stop(graceful=False)
                tier_pool.clear()

            self._l3_pool.clear()

        logger.info("[PrewarmPool] Stopped")

    async def get_prewarmed_instance(
        self,
        config: AgentInstanceConfig,
    ) -> AgentInstance | None:
        """获取预热实例.

        按优先级尝试: L1 > L2 > L3

        Args:
            config: 实例配置

        Returns:
            预热实例或None
        """
        async with self._lock:
            tier = config.tier

            # 尝试从 L1 池获取
            instance = await self._get_from_l1(tier, config)
            if instance:
                self._stats["l1_hits"] += 1
                logger.debug(f"[PrewarmPool] L1 hit: tier={tier.value}")
                return instance

            # 尝试从 L2 池获取
            instance = await self._get_from_l2(tier, config)
            if instance:
                self._stats["l2_hits"] += 1
                logger.debug(f"[PrewarmPool] L2 hit: tier={tier.value}")
                return instance

            # 尝试从 L3 池获取模板
            instance = await self._get_from_l3(tier, config)
            if instance:
                self._stats["l3_hits"] += 1
                logger.debug(f"[PrewarmPool] L3 hit: tier={tier.value}")
                return instance

            self._stats["misses"] += 1
            return None

    async def _get_from_l1(
        self,
        tier: ProjectTier,
        config: AgentInstanceConfig,
    ) -> AgentInstance | None:
        """从 L1 池获取.

        Args:
            tier: 项目分级
            config: 实例配置

        Returns:
            实例或None
        """
        pool = self._l1_pool[tier]

        # 查找匹配的未过期实例
        for i, prewarmed in enumerate(pool):
            if not prewarmed.is_expired():
                # 取出实例
                pool.pop(i)

                # 重新配置实例
                instance = prewarmed.instance
                instance.config = config

                return instance

        return None

    async def _get_from_l2(
        self,
        tier: ProjectTier,
        config: AgentInstanceConfig,
    ) -> AgentInstance | None:
        """从 L2 池获取.

        Args:
            tier: 项目分级
            config: 实例配置

        Returns:
            实例或None (需要完成初始化)
        """
        pool = self._l2_pool[tier]

        for i, prewarmed in enumerate(pool):
            if not prewarmed.is_expired():
                pool.pop(i)
                instance = prewarmed.instance
                instance.config = config
                # 注意: L2 实例需要调用者完成 LLM/MCP 初始化
                return instance

        return None

    async def _get_from_l3(
        self,
        tier: ProjectTier,
        config: AgentInstanceConfig,
    ) -> AgentInstance | None:
        """从 L3 池获取模板并创建实例.

        Args:
            tier: 项目分级
            config: 实例配置

        Returns:
            新创建的实例或None
        """
        # L3 只是模板，用于快速创建
        # 直接创建新实例但使用模板配置
        for template in self._l3_pool:
            if template.tier == tier:
                # 使用模板创建实例
                instance = AgentInstance(config=config)
                # 注意: 需要调用者完成初始化
                return instance

        return None

    async def return_instance(
        self,
        instance: AgentInstance,
        level: int = 1,
    ) -> bool:
        """归还实例到预热池.

        Args:
            instance: 要归还的实例
            level: 归还到哪一级 (1, 2, 或 3)

        Returns:
            是否成功归还
        """
        async with self._lock:
            tier = instance.config.tier

            if level == 1:
                pool = self._l1_pool[tier]
                max_size = self.config.l1_pool_size
                ttl = self.config.l1_ttl_seconds
            elif level == 2:
                pool = self._l2_pool[tier]
                max_size = self.config.l2_pool_size
                ttl = self.config.l2_ttl_seconds
            else:
                # L3 不接收实例，只接收模板
                return False

            # 检查池容量
            if len(pool) >= max_size:
                return False

            # 添加到池
            prewarmed = PrewarmedInstance(
                instance=instance,
                tier=tier,
                level=level,
                ttl_seconds=ttl,
            )
            pool.append(prewarmed)

            logger.debug(f"[PrewarmPool] Instance returned: tier={tier.value}, level=L{level}")
            return True

    async def add_template(self, template: InstanceTemplate) -> bool:
        """添加实例模板.

        Args:
            template: 实例模板

        Returns:
            是否成功添加
        """
        async with self._lock:
            if len(self._l3_pool) >= self.config.l3_pool_size:
                return False

            self._l3_pool.append(template)
            return True

    async def _maintenance_loop(self) -> None:
        """维护循环."""
        while self._running:
            try:
                await asyncio.sleep(self.config.maintenance_interval_seconds)
                await self._cleanup_expired()
                await self._replenish_pools()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[PrewarmPool] Maintenance error: {e}")

    async def _cleanup_expired(self) -> None:
        """清理过期实例."""
        async with self._lock:
            for tier in ProjectTier:
                # 清理 L1
                pool = self._l1_pool[tier]
                expired = [p for p in pool if p.is_expired()]
                for p in expired:
                    pool.remove(p)
                    with contextlib.suppress(Exception):
                        await p.instance.stop(graceful=False)
                    self._stats["total_expired"] += 1

                # 清理 L2
                pool = self._l2_pool[tier]
                expired = [p for p in pool if p.is_expired()]
                for p in expired:
                    pool.remove(p)
                    with contextlib.suppress(Exception):
                        await p.instance.stop(graceful=False)
                    self._stats["total_expired"] += 1

    async def _replenish_pools(self) -> None:
        """补充池水位.

        当池水位低于阈值时，预热新实例。
        """
        # 目前只记录日志，实际预热需要依赖外部创建逻辑
        for tier in ProjectTier:
            l1_count = len(self._l1_pool[tier])
            l1_target = self.config.l1_pool_size

            if l1_count < l1_target * self.config.low_watermark_pct:
                logger.debug(
                    f"[PrewarmPool] L1 pool low: tier={tier.value}, count={l1_count}/{l1_target}"
                )
                # TODO: 触发预热创建

    def get_stats(self) -> dict[str, Any]:
        """获取统计信息.

        Returns:
            统计信息
        """
        return {
            "config": {
                "l1_pool_size": self.config.l1_pool_size,
                "l2_pool_size": self.config.l2_pool_size,
                "l3_pool_size": self.config.l3_pool_size,
            },
            "pools": {
                "l1": {tier.value: len(self._l1_pool[tier]) for tier in ProjectTier},
                "l2": {tier.value: len(self._l2_pool[tier]) for tier in ProjectTier},
                "l3": len(self._l3_pool),
            },
            "hits": {
                "l1": self._stats["l1_hits"],
                "l2": self._stats["l2_hits"],
                "l3": self._stats["l3_hits"],
                "misses": self._stats["misses"],
            },
            "total_prewarmed": self._stats["total_prewarmed"],
            "total_expired": self._stats["total_expired"],
        }
