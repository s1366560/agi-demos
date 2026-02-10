"""
熔断器实现.

提供 Circuit Breaker 模式，防止级联故障。
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, TypeVar

from ..types import CircuitState

logger = logging.getLogger(__name__)

T = TypeVar("T")


class CircuitOpenError(Exception):
    """熔断器打开错误."""

    def __init__(self, circuit_name: str, message: str = "Circuit is open"):
        self.circuit_name = circuit_name
        super().__init__(f"{circuit_name}: {message}")


@dataclass
class CircuitBreakerConfig:
    """熔断器配置."""

    # 失败阈值 - 触发熔断的连续失败次数
    failure_threshold: int = 5

    # 恢复超时 - 熔断后多久尝试恢复 (秒)
    recovery_timeout_seconds: int = 60

    # 半开状态允许的测试请求数
    half_open_requests: int = 3

    # 成功阈值 - 半开状态需要多少成功请求才能关闭熔断器
    success_threshold: int = 2

    # 统计窗口 (秒) - 失败统计的时间窗口
    window_seconds: int = 60

    # 排除的异常类型 (这些异常不计入失败)
    excluded_exceptions: List[type] = field(default_factory=list)


@dataclass
class CircuitBreakerStats:
    """熔断器统计."""

    total_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    rejected_calls: int = 0  # 被熔断拒绝的调用

    # 时间窗口内的统计
    window_failures: int = 0
    window_successes: int = 0

    # 状态变更历史
    state_changes: List[Dict[str, Any]] = field(default_factory=list)

    def failure_rate(self) -> float:
        """计算失败率."""
        if self.total_calls == 0:
            return 0.0
        return self.failed_calls / self.total_calls


class CircuitBreaker:
    """熔断器.

    实现 Circuit Breaker 模式:
    - CLOSED: 正常状态，请求正常通过
    - OPEN: 熔断状态，请求被拒绝
    - HALF_OPEN: 半开状态，允许部分请求通过以测试恢复

    状态转换:
    - CLOSED -> OPEN: 连续失败次数达到阈值
    - OPEN -> HALF_OPEN: 恢复超时后自动转换
    - HALF_OPEN -> CLOSED: 测试请求成功
    - HALF_OPEN -> OPEN: 测试请求失败
    """

    def __init__(
        self,
        name: str,
        config: Optional[CircuitBreakerConfig] = None,
        on_state_change: Optional[Callable[[CircuitState, CircuitState], None]] = None,
    ):
        """初始化熔断器.

        Args:
            name: 熔断器名称
            config: 熔断器配置
            on_state_change: 状态变更回调
        """
        self.name = name
        self.config = config or CircuitBreakerConfig()
        self._on_state_change = on_state_change

        # 状态
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._half_open_calls = 0

        # 时间戳
        self._last_failure_time: Optional[float] = None
        self._last_state_change_time = time.time()
        self._opened_at: Optional[float] = None

        # 统计
        self._stats = CircuitBreakerStats()

        # 锁
        self._lock = asyncio.Lock()

        # 失败时间窗口追踪
        self._failure_timestamps: List[float] = []

        logger.info(
            f"[CircuitBreaker] Initialized: name={name}, "
            f"failure_threshold={self.config.failure_threshold}, "
            f"recovery_timeout={self.config.recovery_timeout_seconds}s"
        )

    @property
    def state(self) -> CircuitState:
        """当前状态."""
        return self._state

    @property
    def is_closed(self) -> bool:
        """是否关闭 (正常)."""
        return self._state == CircuitState.CLOSED

    @property
    def is_open(self) -> bool:
        """是否打开 (熔断)."""
        return self._state == CircuitState.OPEN

    @property
    def is_half_open(self) -> bool:
        """是否半开."""
        return self._state == CircuitState.HALF_OPEN

    @property
    def stats(self) -> CircuitBreakerStats:
        """统计信息."""
        return self._stats

    async def call(
        self,
        func: Callable[..., T],
        *args: Any,
        **kwargs: Any,
    ) -> T:
        """执行受保护的调用.

        Args:
            func: 要执行的函数
            *args: 位置参数
            **kwargs: 关键字参数

        Returns:
            函数返回值

        Raises:
            CircuitOpenError: 熔断器打开
        """
        async with self._lock:
            # 检查是否应该尝试恢复
            if self._state == CircuitState.OPEN:
                if self._should_try_reset():
                    self._transition_to(CircuitState.HALF_OPEN)
                else:
                    self._stats.rejected_calls += 1
                    raise CircuitOpenError(self.name)

            # 半开状态检查
            if self._state == CircuitState.HALF_OPEN:
                if self._half_open_calls >= self.config.half_open_requests:
                    self._stats.rejected_calls += 1
                    raise CircuitOpenError(self.name, "Half-open request limit reached")
                self._half_open_calls += 1

        # 执行调用
        self._stats.total_calls += 1
        try:
            # 支持同步和异步函数
            if asyncio.iscoroutinefunction(func):
                result = await func(*args, **kwargs)
            else:
                result = func(*args, **kwargs)

            await self._on_success()
            return result

        except Exception as e:
            # 检查是否是排除的异常
            if any(isinstance(e, exc_type) for exc_type in self.config.excluded_exceptions):
                await self._on_success()  # 排除的异常视为成功
                raise

            await self._on_failure()
            raise

    async def _on_success(self) -> None:
        """处理成功调用."""
        async with self._lock:
            self._stats.successful_calls += 1
            self._success_count += 1

            if self._state == CircuitState.HALF_OPEN:
                if self._success_count >= self.config.success_threshold:
                    self._transition_to(CircuitState.CLOSED)
            elif self._state == CircuitState.CLOSED:
                # 重置失败计数
                self._failure_count = 0

    async def _on_failure(self) -> None:
        """处理失败调用."""
        async with self._lock:
            self._stats.failed_calls += 1
            self._failure_count += 1
            self._last_failure_time = time.time()
            self._failure_timestamps.append(time.time())

            # 清理过期的失败记录
            self._cleanup_old_failures()

            if self._state == CircuitState.HALF_OPEN:
                # 半开状态下失败，重新打开熔断器
                self._transition_to(CircuitState.OPEN)
            elif self._state == CircuitState.CLOSED:
                # 检查是否达到失败阈值
                if self._count_recent_failures() >= self.config.failure_threshold:
                    self._transition_to(CircuitState.OPEN)

    def _should_try_reset(self) -> bool:
        """检查是否应该尝试恢复."""
        if self._opened_at is None:
            return True
        elapsed = time.time() - self._opened_at
        return elapsed >= self.config.recovery_timeout_seconds

    def _count_recent_failures(self) -> int:
        """计算时间窗口内的失败次数."""
        cutoff = time.time() - self.config.window_seconds
        return sum(1 for ts in self._failure_timestamps if ts > cutoff)

    def _cleanup_old_failures(self) -> None:
        """清理过期的失败记录."""
        cutoff = time.time() - self.config.window_seconds
        self._failure_timestamps = [ts for ts in self._failure_timestamps if ts > cutoff]

    def _transition_to(self, new_state: CircuitState) -> None:
        """转换到新状态."""
        old_state = self._state
        self._state = new_state
        self._last_state_change_time = time.time()

        # 重置计数器
        if new_state == CircuitState.CLOSED:
            self._failure_count = 0
            self._success_count = 0
            self._half_open_calls = 0
            self._opened_at = None
        elif new_state == CircuitState.OPEN:
            self._opened_at = time.time()
            self._success_count = 0
        elif new_state == CircuitState.HALF_OPEN:
            self._half_open_calls = 0
            self._success_count = 0

        # 记录状态变更
        self._stats.state_changes.append(
            {
                "from": old_state.value,
                "to": new_state.value,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )

        # 保留最近的状态变更
        if len(self._stats.state_changes) > 100:
            self._stats.state_changes = self._stats.state_changes[-100:]

        logger.info(
            f"[CircuitBreaker] State changed: name={self.name}, "
            f"{old_state.value} -> {new_state.value}"
        )

        # 触发回调
        if self._on_state_change:
            try:
                self._on_state_change(old_state, new_state)
            except Exception as e:
                logger.warning(f"[CircuitBreaker] Callback error: {e}")

    async def reset(self) -> None:
        """手动重置熔断器."""
        async with self._lock:
            self._transition_to(CircuitState.CLOSED)
            self._failure_timestamps.clear()
            logger.info(f"[CircuitBreaker] Manually reset: name={self.name}")

    async def trip(self) -> None:
        """手动触发熔断."""
        async with self._lock:
            if self._state != CircuitState.OPEN:
                self._transition_to(CircuitState.OPEN)
                logger.info(f"[CircuitBreaker] Manually tripped: name={self.name}")

    def get_time_until_reset(self) -> Optional[float]:
        """获取距离尝试恢复的时间 (秒)."""
        if self._state != CircuitState.OPEN or self._opened_at is None:
            return None
        elapsed = time.time() - self._opened_at
        remaining = self.config.recovery_timeout_seconds - elapsed
        return max(0, remaining)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典."""
        return {
            "name": self.name,
            "state": self._state.value,
            "failure_count": self._failure_count,
            "success_count": self._success_count,
            "half_open_calls": self._half_open_calls,
            "time_until_reset": self.get_time_until_reset(),
            "config": {
                "failure_threshold": self.config.failure_threshold,
                "recovery_timeout_seconds": self.config.recovery_timeout_seconds,
                "half_open_requests": self.config.half_open_requests,
            },
            "stats": {
                "total_calls": self._stats.total_calls,
                "successful_calls": self._stats.successful_calls,
                "failed_calls": self._stats.failed_calls,
                "rejected_calls": self._stats.rejected_calls,
                "failure_rate": self._stats.failure_rate(),
            },
        }


class CircuitBreakerRegistry:
    """熔断器注册表.

    管理多个熔断器实例。
    """

    def __init__(self, default_config: Optional[CircuitBreakerConfig] = None):
        """初始化注册表.

        Args:
            default_config: 默认配置
        """
        self.default_config = default_config or CircuitBreakerConfig()
        self._breakers: Dict[str, CircuitBreaker] = {}
        self._lock = asyncio.Lock()

    async def get_or_create(
        self,
        name: str,
        config: Optional[CircuitBreakerConfig] = None,
    ) -> CircuitBreaker:
        """获取或创建熔断器.

        Args:
            name: 熔断器名称
            config: 熔断器配置

        Returns:
            熔断器实例
        """
        async with self._lock:
            if name not in self._breakers:
                self._breakers[name] = CircuitBreaker(
                    name=name,
                    config=config or self.default_config,
                )
            return self._breakers[name]

    def get(self, name: str) -> Optional[CircuitBreaker]:
        """获取熔断器.

        Args:
            name: 熔断器名称

        Returns:
            熔断器实例或None
        """
        return self._breakers.get(name)

    async def remove(self, name: str) -> bool:
        """移除熔断器.

        Args:
            name: 熔断器名称

        Returns:
            是否成功移除
        """
        async with self._lock:
            return self._breakers.pop(name, None) is not None

    def list_all(self) -> List[Dict[str, Any]]:
        """列出所有熔断器.

        Returns:
            熔断器信息列表
        """
        return [breaker.to_dict() for breaker in self._breakers.values()]

    async def reset_all(self) -> None:
        """重置所有熔断器."""
        for breaker in self._breakers.values():
            await breaker.reset()
