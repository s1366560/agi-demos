"""
后端基类定义.

定义不同分级后端的通用接口。
"""

from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, AsyncIterator, Dict, List, Optional

from ..config import AgentInstanceConfig
from ..instance import AgentInstance, ChatRequest
from ..types import HealthCheckResult


class BackendType(str, Enum):
    """后端类型."""

    CONTAINER = "container"  # 容器级隔离 (HOT tier)
    SHARED_POOL = "shared_pool"  # 共享Worker池 (WARM tier)
    ON_DEMAND = "on_demand"  # 按需创建 (COLD tier)


class Backend(ABC):
    """后端基类.

    定义不同分级后端的通用接口，包括:
    - 实例创建/销毁
    - 请求执行
    - 健康检查
    - 资源管理
    """

    @property
    @abstractmethod
    def backend_type(self) -> BackendType:
        """后端类型."""
        pass

    @abstractmethod
    async def start(self) -> None:
        """启动后端."""
        pass

    @abstractmethod
    async def stop(self) -> None:
        """停止后端."""
        pass

    @abstractmethod
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
        pass

    @abstractmethod
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
        pass

    @abstractmethod
    async def get_instance(
        self,
        instance_id: str,
    ) -> Optional[AgentInstance]:
        """获取实例.

        Args:
            instance_id: 实例ID

        Returns:
            实例或None
        """
        pass

    @abstractmethod
    async def list_instances(self) -> List[AgentInstance]:
        """列出所有实例.

        Returns:
            实例列表
        """
        pass

    @abstractmethod
    async def execute(
        self,
        instance_id: str,
        request: ChatRequest,
    ) -> AsyncIterator[Dict[str, Any]]:
        """在实例上执行请求.

        Args:
            instance_id: 实例ID
            request: 聊天请求

        Yields:
            Agent事件
        """
        pass

    @abstractmethod
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
        pass

    @abstractmethod
    def get_stats(self) -> Dict[str, Any]:
        """获取后端统计信息.

        Returns:
            统计信息
        """
        pass
