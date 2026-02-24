"""
健康监控器.

监控 Agent 实例的健康状态，提供自动恢复策略。
"""

import asyncio
import contextlib
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from ..instance import AgentInstance
from ..types import (
    AgentInstanceStatus,
    HealthCheckResult,
    HealthStatus,
    RecoveryAction,
)

logger = logging.getLogger(__name__)


@dataclass
class HealthMonitorConfig:
    """健康监控配置."""

    # 检查间隔
    check_interval_seconds: int = 30
    check_timeout_seconds: int = 10

    # 阈值
    unhealthy_threshold: int = 3  # 连续N次失败判定为不健康
    healthy_threshold: int = 2  # 连续N次成功判定为健康
    degraded_error_rate_threshold: float = 0.1  # 10%以上错误率判定为降级
    unhealthy_error_rate_threshold: float = 0.5  # 50%以上错误率判定为不健康

    # 延迟阈值
    latency_warning_ms: float = 1000.0  # 延迟超过1秒警告
    latency_critical_ms: float = 5000.0  # 延迟超过5秒严重

    # 内存阈值
    memory_warning_pct: float = 80.0  # 内存使用超过80%警告
    memory_critical_pct: float = 95.0  # 内存使用超过95%严重

    # 恢复配置
    max_recovery_attempts: int = 3  # 最大恢复尝试次数
    recovery_cooldown_seconds: int = 60  # 恢复冷却时间


@dataclass
class InstanceHealthState:
    """实例健康状态追踪."""

    instance_id: str
    consecutive_failures: int = 0
    consecutive_successes: int = 0
    recovery_attempts: int = 0
    last_recovery_at: datetime | None = None
    last_check_result: HealthCheckResult | None = None
    history: list[HealthCheckResult] = field(default_factory=list)

    def record_check(self, result: HealthCheckResult) -> None:
        """记录健康检查结果."""
        self.last_check_result = result
        self.history.append(result)
        if len(self.history) > 100:
            self.history = self.history[-100:]

        if result.is_healthy():
            self.consecutive_successes += 1
            self.consecutive_failures = 0
        else:
            self.consecutive_failures += 1
            self.consecutive_successes = 0

    def can_attempt_recovery(self, config: HealthMonitorConfig) -> bool:
        """是否可以尝试恢复."""
        if self.recovery_attempts >= config.max_recovery_attempts:
            return False

        if self.last_recovery_at:
            elapsed = (datetime.now(UTC) - self.last_recovery_at).total_seconds()
            if elapsed < config.recovery_cooldown_seconds:
                return False

        return True

    def record_recovery_attempt(self) -> None:
        """记录恢复尝试."""
        self.recovery_attempts += 1
        self.last_recovery_at = datetime.now(UTC)

    def reset_recovery_state(self) -> None:
        """重置恢复状态 (成功恢复后)."""
        self.recovery_attempts = 0
        self.last_recovery_at = None


class HealthMonitor:
    """健康监控器.

    监控 Agent 实例的健康状态:
    - 定期执行健康检查
    - 追踪连续失败/成功次数
    - 决定恢复策略
    - 触发告警
    """

    def __init__(
        self,
        config: HealthMonitorConfig | None = None,
        on_unhealthy: Callable[[AgentInstance, HealthCheckResult], None] | None = None,
        on_recovered: Callable[[AgentInstance], None] | None = None,
    ) -> None:
        """初始化健康监控器.

        Args:
            config: 监控配置
            on_unhealthy: 不健康回调
            on_recovered: 恢复回调
        """
        self.config = config or HealthMonitorConfig()
        self._on_unhealthy = on_unhealthy
        self._on_recovered = on_recovered

        # 实例健康状态追踪
        self._health_states: dict[str, InstanceHealthState] = {}
        self._lock = asyncio.Lock()

        # 监控任务
        self._monitoring_tasks: dict[str, asyncio.Task[None]] = {}
        self._monitored_instances: dict[str, AgentInstance] = {}

        logger.info(
            f"[HealthMonitor] Initialized: "
            f"check_interval={self.config.check_interval_seconds}s, "
            f"unhealthy_threshold={self.config.unhealthy_threshold}"
        )

    async def check_instance(
        self,
        instance: AgentInstance,
    ) -> HealthCheckResult:
        """执行单次健康检查.

        Args:
            instance: Agent实例

        Returns:
            健康检查结果
        """
        try:
            # 执行实例的健康检查
            result = await asyncio.wait_for(
                instance.health_check(),
                timeout=self.config.check_timeout_seconds,
            )

            # 更新健康状态
            async with self._lock:
                if instance.id not in self._health_states:
                    self._health_states[instance.id] = InstanceHealthState(instance_id=instance.id)
                state = self._health_states[instance.id]
                state.record_check(result)

                # 检查是否需要标记为不健康
                if state.consecutive_failures >= self.config.unhealthy_threshold:
                    if instance.status not in {
                        AgentInstanceStatus.UNHEALTHY,
                        AgentInstanceStatus.TERMINATING,
                        AgentInstanceStatus.TERMINATED,
                    }:
                        instance.mark_unhealthy(result.error_message)
                        if self._on_unhealthy:
                            self._on_unhealthy(instance, result)

                # 检查是否已恢复
                elif state.consecutive_successes >= self.config.healthy_threshold:
                    if instance.status == AgentInstanceStatus.UNHEALTHY:
                        instance.mark_recovered()
                        state.reset_recovery_state()
                        if self._on_recovered:
                            self._on_recovered(instance)

            return result

        except TimeoutError:
            result = HealthCheckResult(
                status=HealthStatus.UNHEALTHY,
                error_message="Health check timeout",
                last_check_at=datetime.now(UTC),
            )

            async with self._lock:
                if instance.id not in self._health_states:
                    self._health_states[instance.id] = InstanceHealthState(instance_id=instance.id)
                self._health_states[instance.id].record_check(result)

            return result

        except Exception as e:
            logger.error(f"[HealthMonitor] Check failed: instance={instance.id}, error={e}")
            result = HealthCheckResult(
                status=HealthStatus.UNKNOWN,
                error_message=str(e),
                last_check_at=datetime.now(UTC),
            )

            async with self._lock:
                if instance.id not in self._health_states:
                    self._health_states[instance.id] = InstanceHealthState(instance_id=instance.id)
                self._health_states[instance.id].record_check(result)

            return result

    async def start_monitoring(
        self,
        instance: AgentInstance,
        interval_seconds: int | None = None,
    ) -> None:
        """启动对实例的持续监控.

        Args:
            instance: Agent实例
            interval_seconds: 检查间隔 (可选)
        """
        if instance.id in self._monitoring_tasks:
            logger.warning(f"[HealthMonitor] Already monitoring: instance={instance.id}")
            return

        interval = interval_seconds or self.config.check_interval_seconds
        self._monitored_instances[instance.id] = instance

        async def _monitor_loop() -> None:
            while True:
                try:
                    # 检查实例是否仍在监控列表中
                    if instance.id not in self._monitored_instances:
                        break

                    # 检查实例是否已终止
                    if instance.status in {
                        AgentInstanceStatus.TERMINATED,
                        AgentInstanceStatus.TERMINATING,
                    }:
                        break

                    # 执行健康检查
                    await self.check_instance(instance)

                    # 等待下一次检查
                    await asyncio.sleep(interval)

                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error(
                        f"[HealthMonitor] Monitor loop error: instance={instance.id}, error={e}"
                    )
                    await asyncio.sleep(interval)

        task = asyncio.create_task(_monitor_loop())
        self._monitoring_tasks[instance.id] = task

        logger.info(
            f"[HealthMonitor] Started monitoring: instance={instance.id}, interval={interval}s"
        )

    async def stop_monitoring(self, instance_id: str) -> None:
        """停止对实例的监控.

        Args:
            instance_id: 实例ID
        """
        if instance_id in self._monitoring_tasks:
            task = self._monitoring_tasks.pop(instance_id)
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

        self._monitored_instances.pop(instance_id, None)
        logger.info(f"[HealthMonitor] Stopped monitoring: instance={instance_id}")

    async def stop_all_monitoring(self) -> None:
        """停止所有监控."""
        instance_ids = list(self._monitoring_tasks.keys())
        for instance_id in instance_ids:
            await self.stop_monitoring(instance_id)

    def determine_recovery_action(
        self,
        instance: AgentInstance,
        result: HealthCheckResult,
    ) -> RecoveryAction:
        """决定恢复策略.

        Args:
            instance: Agent实例
            result: 健康检查结果

        Returns:
            恢复动作
        """
        state = self._health_states.get(instance.id)
        if not state:
            return RecoveryAction.ALERT

        # 检查是否可以尝试恢复
        if not state.can_attempt_recovery(self.config):
            # 超过最大恢复次数，终止实例
            return RecoveryAction.TERMINATE

        # 根据错误类型决定策略
        error_msg = (result.error_message or "").lower()

        # 连接错误 - 尝试重启
        if any(kw in error_msg for kw in ["connection", "timeout", "network"]):
            return RecoveryAction.RESTART

        # 内存问题 - 尝试迁移
        if result.memory_usage_pct > self.config.memory_critical_pct:
            return RecoveryAction.MIGRATE

        # 高错误率但非致命 - 降级
        if (
            self.config.degraded_error_rate_threshold
            <= result.error_rate
            < self.config.unhealthy_error_rate_threshold
        ):
            return RecoveryAction.DEGRADE

        # 默认尝试重启
        return RecoveryAction.RESTART

    async def handle_unhealthy(
        self,
        instance: AgentInstance,
        result: HealthCheckResult,
    ) -> RecoveryAction:
        """处理不健康实例.

        Args:
            instance: Agent实例
            result: 健康检查结果

        Returns:
            执行的恢复动作
        """
        action = self.determine_recovery_action(instance, result)

        state = self._health_states.get(instance.id)
        if state:
            state.record_recovery_attempt()

        logger.info(
            f"[HealthMonitor] Handling unhealthy: instance={instance.id}, action={action.value}"
        )

        return action

    def get_health_state(self, instance_id: str) -> InstanceHealthState | None:
        """获取实例健康状态.

        Args:
            instance_id: 实例ID

        Returns:
            健康状态，不存在则返回None
        """
        return self._health_states.get(instance_id)

    def get_all_health_states(self) -> dict[str, InstanceHealthState]:
        """获取所有实例的健康状态.

        Returns:
            健康状态字典
        """
        return self._health_states.copy()

    def get_monitored_instances(self) -> set[str]:
        """获取正在监控的实例ID集合.

        Returns:
            实例ID集合
        """
        return set(self._monitoring_tasks.keys())

    def to_dict(self) -> dict[str, Any]:
        """转换为字典."""
        return {
            "config": {
                "check_interval_seconds": self.config.check_interval_seconds,
                "unhealthy_threshold": self.config.unhealthy_threshold,
                "healthy_threshold": self.config.healthy_threshold,
            },
            "monitored_count": len(self._monitoring_tasks),
            "health_states": {
                instance_id: {
                    "consecutive_failures": state.consecutive_failures,
                    "consecutive_successes": state.consecutive_successes,
                    "recovery_attempts": state.recovery_attempts,
                    "last_check_status": (
                        state.last_check_result.status.value if state.last_check_result else None
                    ),
                }
                for instance_id, state in self._health_states.items()
            },
        }
