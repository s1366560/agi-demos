"""
Agent实例封装.

封装单个项目的 ReActAgent，管理实例级资源和生命周期。
"""

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, AsyncIterator, Dict, List, Optional

from .config import AgentInstanceConfig
from .lifecycle import LifecycleStateMachine
from .types import (
    AgentInstanceStatus,
    HealthCheckResult,
    HealthStatus,
    InstanceMetrics,
)

if TYPE_CHECKING:
    from ..core.react_agent import ReActAgent

logger = logging.getLogger(__name__)


@dataclass
class ChatRequest:
    """聊天请求."""

    conversation_id: str
    message_id: str
    user_message: str
    user_id: str
    conversation_context: List[Dict[str, Any]] = field(default_factory=list)
    attachment_ids: Optional[List[str]] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    max_steps: Optional[int] = None


@dataclass
class ChatResult:
    """聊天结果."""

    content: str = ""
    last_event_time_us: int = 0
    last_event_counter: int = 0
    is_error: bool = False
    error_message: Optional[str] = None
    execution_time_ms: float = 0.0
    event_count: int = 0
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)


class AgentInstance:
    """Agent实例封装.

    封装单个项目的 ReActAgent，提供:
    - 生命周期状态管理
    - 并发控制 (信号量)
    - 指标收集
    - 健康检查支持
    """

    def __init__(
        self,
        config: AgentInstanceConfig,
        react_agent: Optional["ReActAgent"] = None,
        instance_id: Optional[str] = None,
    ):
        """初始化Agent实例.

        Args:
            config: 实例配置
            react_agent: ReActAgent实例 (可选，支持延迟初始化)
            instance_id: 实例ID (可选，自动生成)
        """
        self.id = instance_id or str(uuid.uuid4())
        self.config = config
        self._agent = react_agent

        # 生命周期状态机
        self._lifecycle = LifecycleStateMachine(
            instance_id=self.id,
            initial_status=AgentInstanceStatus.CREATED,
        )

        # 并发控制
        self._semaphore = asyncio.Semaphore(config.quota.max_concurrent_requests)
        self._active_requests = 0
        self._request_lock = asyncio.Lock()

        # 指标
        self._metrics = InstanceMetrics(created_at=datetime.now(timezone.utc))
        self._latencies: List[float] = []  # 最近N次请求延迟

        # 时间戳
        self._created_at = datetime.now(timezone.utc)
        self._last_activity_at = datetime.now(timezone.utc)
        self._initialized_at: Optional[datetime] = None

        # 健康检查
        self._consecutive_failures = 0
        self._last_health_check: Optional[HealthCheckResult] = None

        logger.info(
            f"[AgentInstance] Created: id={self.id}, "
            f"project={config.project_id}, tier={config.tier.value}"
        )

    @property
    def status(self) -> AgentInstanceStatus:
        """当前状态."""
        return self._lifecycle.status

    @property
    def is_active(self) -> bool:
        """是否处于活跃状态."""
        return self._lifecycle.is_active()

    @property
    def is_healthy(self) -> bool:
        """是否健康."""
        return self._lifecycle.is_healthy()

    @property
    def project_key(self) -> str:
        """项目键."""
        return self.config.instance_key

    @property
    def metrics(self) -> InstanceMetrics:
        """获取指标."""
        return self._metrics

    @property
    def active_requests(self) -> int:
        """当前活跃请求数."""
        return self._active_requests

    async def initialize(self, force_refresh: bool = False) -> bool:
        """初始化实例.

        Args:
            force_refresh: 是否强制刷新

        Returns:
            是否成功
        """
        try:
            # 转换到初始化中状态
            self._lifecycle.transition("initialize")
            logger.info(f"[AgentInstance] Initializing: id={self.id}")

            # 如果没有提供agent，需要创建
            if self._agent is None:
                self._agent = await self._create_agent()

            # 初始化完成
            self._lifecycle.transition("initialization_complete")
            self._initialized_at = datetime.now(timezone.utc)

            logger.info(f"[AgentInstance] Initialized successfully: id={self.id}")
            return True

        except Exception as e:
            logger.error(f"[AgentInstance] Initialization failed: {e}", exc_info=True)
            self._lifecycle.transition(
                "initialization_failed",
                error_message=str(e),
            )
            return False

    async def _create_agent(self) -> "ReActAgent":
        """创建ReActAgent实例.

        子类可重写此方法以自定义创建逻辑。
        """
        # 延迟导入避免循环依赖
        from ..core.react_agent import ReActAgent

        # 这里需要从配置加载工具等
        # 实际实现会从 AgentSessionPool 获取缓存的组件
        agent = ReActAgent(
            model=self.config.model or "gpt-4",
            tools={},  # 工具会通过 tool_provider 动态加载
            temperature=self.config.temperature,
            max_tokens=self.config.max_tokens,
            max_steps=self.config.max_steps,
        )
        return agent

    async def execute(
        self,
        request: ChatRequest,
    ) -> AsyncIterator[Dict[str, Any]]:
        """执行聊天请求.

        带并发控制和指标收集。

        Args:
            request: 聊天请求

        Yields:
            Agent事件
        """
        if not self.is_active:
            raise RuntimeError(f"Instance not active: status={self.status.value}")

        if self._agent is None:
            raise RuntimeError("Agent not initialized")

        start_time = time.time()

        # 获取信号量
        async with self._semaphore:
            async with self._request_lock:
                self._active_requests += 1
                if self._active_requests == 1 and self.status == AgentInstanceStatus.READY:
                    self._lifecycle.transition("execute")

            try:
                # 更新活动时间
                self._last_activity_at = datetime.now(timezone.utc)

                # 执行请求
                event_count = 0
                async for event in self._agent.stream(
                    conversation_id=request.conversation_id,
                    user_message=request.user_message,
                    conversation_context=request.conversation_context,
                ):
                    event_count += 1
                    yield event

                # 更新成功指标
                execution_time_ms = (time.time() - start_time) * 1000
                self._update_metrics(
                    success=True,
                    latency_ms=execution_time_ms,
                )
                self._consecutive_failures = 0

            except Exception as e:
                # 更新失败指标
                execution_time_ms = (time.time() - start_time) * 1000
                self._update_metrics(
                    success=False,
                    latency_ms=execution_time_ms,
                )
                self._consecutive_failures += 1
                logger.error(f"[AgentInstance] Execution error: {e}", exc_info=True)
                raise

            finally:
                async with self._request_lock:
                    self._active_requests -= 1
                    if self._active_requests == 0 and self.status == AgentInstanceStatus.EXECUTING:
                        self._lifecycle.transition("complete")

    def _update_metrics(self, success: bool, latency_ms: float) -> None:
        """更新指标."""
        self._metrics.total_requests += 1
        if success:
            self._metrics.successful_requests += 1
        else:
            self._metrics.failed_requests += 1
            self._metrics.last_error_at = datetime.now(timezone.utc)

        self._metrics.last_request_at = datetime.now(timezone.utc)

        # 更新延迟统计
        self._latencies.append(latency_ms)
        if len(self._latencies) > 100:
            self._latencies = self._latencies[-100:]

        if self._latencies:
            self._metrics.avg_latency_ms = sum(self._latencies) / len(self._latencies)
            sorted_latencies = sorted(self._latencies)
            self._metrics.p50_latency_ms = sorted_latencies[len(sorted_latencies) // 2]
            self._metrics.p95_latency_ms = sorted_latencies[int(len(sorted_latencies) * 0.95)]
            self._metrics.p99_latency_ms = sorted_latencies[int(len(sorted_latencies) * 0.99)]
            self._metrics.max_latency_ms = max(sorted_latencies)

    async def health_check(self) -> HealthCheckResult:
        """执行健康检查.

        Returns:
            健康检查结果
        """
        start_time = time.time()

        try:
            # 检查状态
            if self._lifecycle.is_terminal():
                return HealthCheckResult(
                    status=HealthStatus.UNHEALTHY,
                    error_message="Instance is terminated",
                    last_check_at=datetime.now(timezone.utc),
                )

            # 检查agent是否可用
            if self._agent is None:
                return HealthCheckResult(
                    status=HealthStatus.UNHEALTHY,
                    error_message="Agent not initialized",
                    last_check_at=datetime.now(timezone.utc),
                )

            # 检查错误率
            error_rate = self._metrics.error_rate()
            if error_rate > 0.5:  # 50%以上错误率
                status = HealthStatus.UNHEALTHY
            elif error_rate > 0.1:  # 10%以上错误率
                status = HealthStatus.DEGRADED
            else:
                status = HealthStatus.HEALTHY

            # 构建结果
            latency_ms = (time.time() - start_time) * 1000
            result = HealthCheckResult(
                status=status,
                latency_ms=latency_ms,
                error_rate=error_rate,
                active_requests=self._active_requests,
                last_check_at=datetime.now(timezone.utc),
                details={
                    "total_requests": self._metrics.total_requests,
                    "failed_requests": self._metrics.failed_requests,
                    "avg_latency_ms": self._metrics.avg_latency_ms,
                    "consecutive_failures": self._consecutive_failures,
                },
            )

            self._last_health_check = result
            return result

        except Exception as e:
            latency_ms = (time.time() - start_time) * 1000
            result = HealthCheckResult(
                status=HealthStatus.UNHEALTHY,
                latency_ms=latency_ms,
                error_message=str(e),
                last_check_at=datetime.now(timezone.utc),
            )
            self._last_health_check = result
            return result

    async def pause(self) -> None:
        """暂停接收新请求."""
        if self._lifecycle.can_transition("pause"):
            self._lifecycle.transition("pause")
            logger.info(f"[AgentInstance] Paused: id={self.id}")

    async def resume(self) -> None:
        """恢复接收请求."""
        if self._lifecycle.can_transition("resume"):
            self._lifecycle.transition("resume")
            logger.info(f"[AgentInstance] Resumed: id={self.id}")

    async def stop(self, graceful: bool = True, timeout: float = 30.0) -> None:
        """停止实例.

        Args:
            graceful: 是否优雅停止 (等待进行中的请求完成)
            timeout: 优雅停止超时时间 (秒)
        """
        logger.info(f"[AgentInstance] Stopping: id={self.id}, graceful={graceful}")

        if graceful:
            # 先暂停接收新请求
            if self._lifecycle.can_transition("pause"):
                self._lifecycle.transition("pause")

            # 等待进行中的请求完成
            start_time = time.time()
            while self._active_requests > 0:
                if time.time() - start_time > timeout:
                    logger.warning(
                        f"[AgentInstance] Graceful stop timeout, "
                        f"forcing termination: id={self.id}, "
                        f"active_requests={self._active_requests}"
                    )
                    break
                await asyncio.sleep(0.5)

        # 转换到终止中状态
        if self._lifecycle.can_transition("terminate"):
            self._lifecycle.transition("terminate")
        elif self._lifecycle.can_transition("force_terminate"):
            self._lifecycle.transition("force_terminate")

        # 清理资源
        await self._cleanup()

        # 转换到已终止状态
        if self._lifecycle.can_transition("terminated"):
            self._lifecycle.transition("terminated")

        logger.info(f"[AgentInstance] Stopped: id={self.id}")

    async def _cleanup(self) -> None:
        """清理资源."""
        # 清理agent资源
        if self._agent is not None:
            # Agent可能有需要清理的资源
            pass

        self._agent = None

    def mark_unhealthy(self, error_message: Optional[str] = None) -> None:
        """标记为不健康."""
        if self._lifecycle.can_transition("health_check_failed"):
            self._lifecycle.transition(
                "health_check_failed",
                error_message=error_message,
            )

    def mark_recovered(self) -> None:
        """标记为已恢复."""
        if self._lifecycle.can_transition("recover"):
            self._lifecycle.transition("recover")

    def get_idle_seconds(self) -> float:
        """获取空闲时间 (秒)."""
        return (datetime.now(timezone.utc) - self._last_activity_at).total_seconds()

    def is_idle_expired(self) -> bool:
        """是否空闲超时."""
        return self.get_idle_seconds() > self.config.idle_timeout_seconds

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典."""
        return {
            "id": self.id,
            "project_id": self.config.project_id,
            "tenant_id": self.config.tenant_id,
            "agent_mode": self.config.agent_mode,
            "tier": self.config.tier.value,
            "status": self.status.value,
            "is_active": self.is_active,
            "is_healthy": self.is_healthy,
            "active_requests": self._active_requests,
            "metrics": {
                "total_requests": self._metrics.total_requests,
                "successful_requests": self._metrics.successful_requests,
                "failed_requests": self._metrics.failed_requests,
                "avg_latency_ms": self._metrics.avg_latency_ms,
                "error_rate": self._metrics.error_rate(),
            },
            "created_at": self._created_at.isoformat(),
            "last_activity_at": self._last_activity_at.isoformat(),
            "idle_seconds": self.get_idle_seconds(),
            "lifecycle": self._lifecycle.to_dict(),
        }
