"""
资源配额管理器.

管理项目和实例的资源配额分配、使用追踪和限制执行。
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional

from ..config import AgentInstanceConfig, PoolConfig, ResourceQuota
from ..types import ProjectTier, ResourceUsage

logger = logging.getLogger(__name__)


@dataclass
class ProjectResourceAllocation:
    """项目资源分配记录."""

    project_id: str
    tenant_id: str
    tier: ProjectTier

    # 分配的配额
    quota: ResourceQuota

    # 当前使用
    memory_used_mb: float = 0.0
    cpu_used_cores: float = 0.0
    active_instances: int = 0
    active_requests: int = 0

    # 时间戳
    allocated_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

    @property
    def allocation_key(self) -> str:
        """分配键."""
        return f"{self.tenant_id}:{self.project_id}"

    def can_allocate_instance(self) -> bool:
        """是否可以分配新实例."""
        return self.active_instances < self.quota.max_instances

    def can_accept_request(self) -> bool:
        """是否可以接受新请求."""
        max_total_requests = self.quota.max_instances * self.quota.max_concurrent_requests
        return self.active_requests < max_total_requests


class ResourceAllocationError(Exception):
    """资源分配错误."""

    pass


class QuotaExceededError(ResourceAllocationError):
    """配额超限错误."""

    pass


class ResourceManager:
    """资源管理器.

    管理整个池的资源分配和使用:
    - 项目级配额分配
    - 资源使用追踪
    - 限制执行
    - 资源回收
    """

    def __init__(self, config: PoolConfig):
        """初始化资源管理器.

        Args:
            config: 池配置
        """
        self.config = config
        self._allocations: Dict[str, ProjectResourceAllocation] = {}
        self._lock = asyncio.Lock()

        # 全局资源追踪
        self._total_memory_used_mb: float = 0.0
        self._total_cpu_used_cores: float = 0.0
        self._total_instances: int = 0

        logger.info(
            f"[ResourceManager] Initialized: "
            f"max_memory={config.max_total_memory_mb}MB, "
            f"max_cpu={config.max_total_cpu_cores} cores, "
            f"max_instances={config.max_total_instances}"
        )

    async def allocate(
        self,
        config: AgentInstanceConfig,
    ) -> ProjectResourceAllocation:
        """为项目分配资源.

        Args:
            config: 实例配置

        Returns:
            资源分配记录

        Raises:
            QuotaExceededError: 配额超限
        """
        async with self._lock:
            allocation_key = config.instance_key

            # 检查是否已有分配
            if allocation_key in self._allocations:
                allocation = self._allocations[allocation_key]
                # 检查是否可以分配新实例
                if not allocation.can_allocate_instance():
                    raise QuotaExceededError(
                        f"Max instances exceeded for project {config.project_id}: "
                        f"{allocation.active_instances}/{allocation.quota.max_instances}"
                    )
                return allocation

            # 检查全局限制
            quota = config.quota
            if self._total_instances >= self.config.max_total_instances:
                raise QuotaExceededError(
                    f"Max total instances exceeded: "
                    f"{self._total_instances}/{self.config.max_total_instances}"
                )

            if (
                self._total_memory_used_mb + quota.memory_request_mb
                > self.config.max_total_memory_mb
            ):
                raise QuotaExceededError(
                    f"Max total memory exceeded: "
                    f"{self._total_memory_used_mb + quota.memory_request_mb}/"
                    f"{self.config.max_total_memory_mb}MB"
                )

            if (
                self._total_cpu_used_cores + quota.cpu_request_cores
                > self.config.max_total_cpu_cores
            ):
                raise QuotaExceededError(
                    f"Max total CPU exceeded: "
                    f"{self._total_cpu_used_cores + quota.cpu_request_cores}/"
                    f"{self.config.max_total_cpu_cores} cores"
                )

            # 创建分配记录
            allocation = ProjectResourceAllocation(
                project_id=config.project_id,
                tenant_id=config.tenant_id,
                tier=config.tier,
                quota=quota,
            )
            self._allocations[allocation_key] = allocation

            logger.info(
                f"[ResourceManager] Allocated: project={config.project_id}, "
                f"tier={config.tier.value}, "
                f"memory={quota.memory_limit_mb}MB, "
                f"cpu={quota.cpu_limit_cores} cores"
            )

            return allocation

    async def release(
        self,
        tenant_id: str,
        project_id: str,
    ) -> bool:
        """释放项目的资源分配.

        Args:
            tenant_id: 租户ID
            project_id: 项目ID

        Returns:
            是否成功释放
        """
        async with self._lock:
            allocation_key = f"{tenant_id}:{project_id}"

            if allocation_key not in self._allocations:
                return False

            allocation = self._allocations[allocation_key]

            # 确保没有活跃实例
            if allocation.active_instances > 0:
                logger.warning(
                    f"[ResourceManager] Cannot release: "
                    f"project={project_id} has {allocation.active_instances} active instances"
                )
                return False

            # 更新全局追踪
            self._total_memory_used_mb -= allocation.memory_used_mb
            self._total_cpu_used_cores -= allocation.cpu_used_cores

            # 删除分配
            del self._allocations[allocation_key]

            logger.info(f"[ResourceManager] Released: project={project_id}")
            return True

    async def acquire_instance(
        self,
        tenant_id: str,
        project_id: str,
        memory_mb: float = 0.0,
        cpu_cores: float = 0.0,
    ) -> bool:
        """获取实例资源.

        在创建新实例时调用。

        Args:
            tenant_id: 租户ID
            project_id: 项目ID
            memory_mb: 内存使用量
            cpu_cores: CPU使用量

        Returns:
            是否成功获取
        """
        async with self._lock:
            allocation_key = f"{tenant_id}:{project_id}"
            allocation = self._allocations.get(allocation_key)

            if not allocation:
                logger.warning(f"[ResourceManager] No allocation found: project={project_id}")
                return False

            if not allocation.can_allocate_instance():
                logger.warning(f"[ResourceManager] Instance limit exceeded: project={project_id}")
                return False

            # 更新分配
            allocation.active_instances += 1
            allocation.memory_used_mb += memory_mb
            allocation.cpu_used_cores += cpu_cores
            allocation.updated_at = datetime.utcnow()

            # 更新全局追踪
            self._total_instances += 1
            self._total_memory_used_mb += memory_mb
            self._total_cpu_used_cores += cpu_cores

            logger.debug(
                f"[ResourceManager] Instance acquired: project={project_id}, "
                f"instances={allocation.active_instances}"
            )
            return True

    async def release_instance(
        self,
        tenant_id: str,
        project_id: str,
        memory_mb: float = 0.0,
        cpu_cores: float = 0.0,
    ) -> bool:
        """释放实例资源.

        在销毁实例时调用。

        Args:
            tenant_id: 租户ID
            project_id: 项目ID
            memory_mb: 内存使用量
            cpu_cores: CPU使用量

        Returns:
            是否成功释放
        """
        async with self._lock:
            allocation_key = f"{tenant_id}:{project_id}"
            allocation = self._allocations.get(allocation_key)

            if not allocation:
                return False

            # 更新分配
            allocation.active_instances = max(0, allocation.active_instances - 1)
            allocation.memory_used_mb = max(0, allocation.memory_used_mb - memory_mb)
            allocation.cpu_used_cores = max(0, allocation.cpu_used_cores - cpu_cores)
            allocation.updated_at = datetime.utcnow()

            # 更新全局追踪
            self._total_instances = max(0, self._total_instances - 1)
            self._total_memory_used_mb = max(0, self._total_memory_used_mb - memory_mb)
            self._total_cpu_used_cores = max(0, self._total_cpu_used_cores - cpu_cores)

            logger.debug(
                f"[ResourceManager] Instance released: project={project_id}, "
                f"instances={allocation.active_instances}"
            )
            return True

    async def acquire_request(
        self,
        tenant_id: str,
        project_id: str,
    ) -> bool:
        """获取请求资源.

        在处理新请求时调用。

        Args:
            tenant_id: 租户ID
            project_id: 项目ID

        Returns:
            是否成功获取
        """
        async with self._lock:
            allocation_key = f"{tenant_id}:{project_id}"
            allocation = self._allocations.get(allocation_key)

            if not allocation:
                return False

            if not allocation.can_accept_request():
                return False

            allocation.active_requests += 1
            allocation.updated_at = datetime.utcnow()
            return True

    async def release_request(
        self,
        tenant_id: str,
        project_id: str,
    ) -> bool:
        """释放请求资源.

        在请求完成时调用。

        Args:
            tenant_id: 租户ID
            project_id: 项目ID

        Returns:
            是否成功释放
        """
        async with self._lock:
            allocation_key = f"{tenant_id}:{project_id}"
            allocation = self._allocations.get(allocation_key)

            if not allocation:
                return False

            allocation.active_requests = max(0, allocation.active_requests - 1)
            allocation.updated_at = datetime.utcnow()
            return True

    async def get_usage(
        self,
        tenant_id: str,
        project_id: str,
    ) -> Optional[ResourceUsage]:
        """获取项目资源使用情况.

        Args:
            tenant_id: 租户ID
            project_id: 项目ID

        Returns:
            资源使用情况，不存在则返回None
        """
        allocation_key = f"{tenant_id}:{project_id}"
        allocation = self._allocations.get(allocation_key)

        if not allocation:
            return None

        return ResourceUsage(
            memory_used_mb=allocation.memory_used_mb,
            memory_limit_mb=float(allocation.quota.memory_limit_mb),
            cpu_used_cores=allocation.cpu_used_cores,
            cpu_limit_cores=allocation.quota.cpu_limit_cores,
            active_instances=allocation.active_instances,
            max_instances=allocation.quota.max_instances,
            active_requests=allocation.active_requests,
            max_concurrent_requests=(
                allocation.quota.max_instances * allocation.quota.max_concurrent_requests
            ),
        )

    async def get_global_usage(self) -> ResourceUsage:
        """获取全局资源使用情况.

        Returns:
            全局资源使用情况
        """
        return ResourceUsage(
            memory_used_mb=self._total_memory_used_mb,
            memory_limit_mb=float(self.config.max_total_memory_mb),
            cpu_used_cores=self._total_cpu_used_cores,
            cpu_limit_cores=self.config.max_total_cpu_cores,
            active_instances=self._total_instances,
            max_instances=self.config.max_total_instances,
            active_requests=sum(a.active_requests for a in self._allocations.values()),
            max_concurrent_requests=sum(
                a.quota.max_instances * a.quota.max_concurrent_requests
                for a in self._allocations.values()
            ),
        )

    def get_allocation(
        self,
        tenant_id: str,
        project_id: str,
    ) -> Optional[ProjectResourceAllocation]:
        """获取项目资源分配.

        Args:
            tenant_id: 租户ID
            project_id: 项目ID

        Returns:
            资源分配记录，不存在则返回None
        """
        allocation_key = f"{tenant_id}:{project_id}"
        return self._allocations.get(allocation_key)

    def list_allocations(self) -> Dict[str, ProjectResourceAllocation]:
        """列出所有资源分配.

        Returns:
            所有资源分配的字典
        """
        return self._allocations.copy()

    async def update_quota(
        self,
        tenant_id: str,
        project_id: str,
        quota: ResourceQuota,
    ) -> bool:
        """更新项目配额.

        Args:
            tenant_id: 租户ID
            project_id: 项目ID
            quota: 新配额

        Returns:
            是否成功更新
        """
        async with self._lock:
            allocation_key = f"{tenant_id}:{project_id}"
            allocation = self._allocations.get(allocation_key)

            if not allocation:
                return False

            # 验证新配额
            errors = quota.validate()
            if errors:
                logger.error(
                    f"[ResourceManager] Invalid quota: project={project_id}, errors={errors}"
                )
                return False

            # 检查当前使用是否超过新配额
            if allocation.active_instances > quota.max_instances:
                logger.warning(
                    f"[ResourceManager] Cannot reduce quota: "
                    f"project={project_id} has {allocation.active_instances} instances, "
                    f"new max={quota.max_instances}"
                )
                return False

            allocation.quota = quota
            allocation.updated_at = datetime.utcnow()

            logger.info(
                f"[ResourceManager] Quota updated: project={project_id}, "
                f"memory={quota.memory_limit_mb}MB, "
                f"cpu={quota.cpu_limit_cores} cores"
            )
            return True

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典."""
        return {
            "global_usage": {
                "memory_used_mb": self._total_memory_used_mb,
                "memory_limit_mb": self.config.max_total_memory_mb,
                "cpu_used_cores": self._total_cpu_used_cores,
                "cpu_limit_cores": self.config.max_total_cpu_cores,
                "total_instances": self._total_instances,
                "max_instances": self.config.max_total_instances,
            },
            "allocation_count": len(self._allocations),
            "allocations": {
                key: {
                    "project_id": alloc.project_id,
                    "tenant_id": alloc.tenant_id,
                    "tier": alloc.tier.value,
                    "active_instances": alloc.active_instances,
                    "active_requests": alloc.active_requests,
                    "memory_used_mb": alloc.memory_used_mb,
                    "cpu_used_cores": alloc.cpu_used_cores,
                }
                for key, alloc in self._allocations.items()
            },
        }
