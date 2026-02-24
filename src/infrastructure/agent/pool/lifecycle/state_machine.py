"""
Agent实例生命周期状态机.

管理 Agent 实例的状态转换，确保状态变更的合法性和一致性。
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from ..types import AgentInstanceStatus, LifecycleEvent


@dataclass
class StateTransition:
    """状态转换定义."""

    from_status: AgentInstanceStatus
    to_status: AgentInstanceStatus
    trigger: str  # 触发事件名称
    guard: Callable[[], bool] | None = None  # 守卫条件
    action: Callable[[], None] | None = None  # 转换动作


# 定义所有合法的状态转换
VALID_TRANSITIONS: list[StateTransition] = [
    # 初始化阶段
    StateTransition(AgentInstanceStatus.CREATED, AgentInstanceStatus.INITIALIZING, "initialize"),
    StateTransition(
        AgentInstanceStatus.INITIALIZING, AgentInstanceStatus.READY, "initialization_complete"
    ),
    StateTransition(
        AgentInstanceStatus.INITIALIZING,
        AgentInstanceStatus.INITIALIZATION_FAILED,
        "initialization_failed",
    ),
    StateTransition(
        AgentInstanceStatus.INITIALIZATION_FAILED, AgentInstanceStatus.INITIALIZING, "retry"
    ),
    # 运行阶段
    StateTransition(AgentInstanceStatus.READY, AgentInstanceStatus.EXECUTING, "execute"),
    StateTransition(AgentInstanceStatus.EXECUTING, AgentInstanceStatus.READY, "complete"),
    StateTransition(AgentInstanceStatus.READY, AgentInstanceStatus.PAUSED, "pause"),
    StateTransition(AgentInstanceStatus.PAUSED, AgentInstanceStatus.READY, "resume"),
    StateTransition(AgentInstanceStatus.EXECUTING, AgentInstanceStatus.PAUSED, "pause"),
    # 异常阶段
    StateTransition(
        AgentInstanceStatus.READY, AgentInstanceStatus.UNHEALTHY, "health_check_failed"
    ),
    StateTransition(
        AgentInstanceStatus.EXECUTING, AgentInstanceStatus.UNHEALTHY, "health_check_failed"
    ),
    StateTransition(
        AgentInstanceStatus.PAUSED, AgentInstanceStatus.UNHEALTHY, "health_check_failed"
    ),
    StateTransition(AgentInstanceStatus.UNHEALTHY, AgentInstanceStatus.READY, "recover"),
    StateTransition(AgentInstanceStatus.UNHEALTHY, AgentInstanceStatus.DEGRADED, "degrade"),
    StateTransition(AgentInstanceStatus.DEGRADED, AgentInstanceStatus.READY, "recover"),
    StateTransition(
        AgentInstanceStatus.DEGRADED, AgentInstanceStatus.UNHEALTHY, "health_check_failed"
    ),
    # 终止阶段
    StateTransition(AgentInstanceStatus.READY, AgentInstanceStatus.TERMINATING, "terminate"),
    StateTransition(AgentInstanceStatus.PAUSED, AgentInstanceStatus.TERMINATING, "terminate"),
    StateTransition(AgentInstanceStatus.UNHEALTHY, AgentInstanceStatus.TERMINATING, "terminate"),
    StateTransition(AgentInstanceStatus.DEGRADED, AgentInstanceStatus.TERMINATING, "terminate"),
    StateTransition(
        AgentInstanceStatus.INITIALIZATION_FAILED, AgentInstanceStatus.TERMINATING, "terminate"
    ),
    StateTransition(AgentInstanceStatus.TERMINATING, AgentInstanceStatus.TERMINATED, "terminated"),
    # 强制终止 (从任何状态)
    StateTransition(
        AgentInstanceStatus.EXECUTING, AgentInstanceStatus.TERMINATING, "force_terminate"
    ),
    StateTransition(AgentInstanceStatus.CREATED, AgentInstanceStatus.TERMINATED, "force_terminate"),
    StateTransition(
        AgentInstanceStatus.INITIALIZING, AgentInstanceStatus.TERMINATED, "force_terminate"
    ),
]


class InvalidStateTransitionError(Exception):
    """非法状态转换错误."""

    def __init__(
        self, from_status: AgentInstanceStatus, to_status: AgentInstanceStatus, trigger: str
    ) -> None:
        self.from_status = from_status
        self.to_status = to_status
        self.trigger = trigger
        super().__init__(
            f"Invalid state transition: {from_status.value} -> {to_status.value} "
            f"(trigger: {trigger})"
        )


class LifecycleStateMachine:
    """生命周期状态机.

    管理 Agent 实例的状态转换，确保:
    - 只允许合法的状态转换
    - 记录所有状态变更事件
    - 支持状态转换守卫和动作
    """

    def __init__(
        self,
        instance_id: str,
        initial_status: AgentInstanceStatus = AgentInstanceStatus.CREATED,
    ) -> None:
        """初始化状态机.

        Args:
            instance_id: 实例ID
            initial_status: 初始状态
        """
        self.instance_id = instance_id
        self._status = initial_status
        self._history: list[LifecycleEvent] = []
        self._transition_map = self._build_transition_map()
        self._listeners: list[Callable[[LifecycleEvent], None]] = []

        # 记录初始状态
        self._record_event("created", None, initial_status)

    def _build_transition_map(self) -> dict[AgentInstanceStatus, dict[str, StateTransition]]:
        """构建状态转换映射."""
        transition_map: dict[AgentInstanceStatus, dict[str, StateTransition]] = {}
        for transition in VALID_TRANSITIONS:
            if transition.from_status not in transition_map:
                transition_map[transition.from_status] = {}
            transition_map[transition.from_status][transition.trigger] = transition
        return transition_map

    @property
    def status(self) -> AgentInstanceStatus:
        """当前状态."""
        return self._status

    @property
    def history(self) -> list[LifecycleEvent]:
        """状态变更历史."""
        return self._history.copy()

    def can_transition(self, trigger: str) -> bool:
        """检查是否可以执行指定的状态转换.

        Args:
            trigger: 触发事件名称

        Returns:
            是否可以转换
        """
        transitions = self._transition_map.get(self._status, {})
        transition = transitions.get(trigger)
        if not transition:
            return False
        return not (transition.guard and not transition.guard())

    def get_allowed_triggers(self) -> set[str]:
        """获取当前状态允许的所有触发事件.

        Returns:
            允许的触发事件集合
        """
        transitions = self._transition_map.get(self._status, {})
        return set(transitions.keys())

    def transition(
        self,
        trigger: str,
        details: dict | None = None,
        error_message: str | None = None,
    ) -> AgentInstanceStatus:
        """执行状态转换.

        Args:
            trigger: 触发事件名称
            details: 附加信息
            error_message: 错误消息 (如果适用)

        Returns:
            转换后的状态

        Raises:
            InvalidStateTransitionError: 非法状态转换
        """
        transitions = self._transition_map.get(self._status, {})
        transition = transitions.get(trigger)

        if not transition:
            raise InvalidStateTransitionError(self._status, AgentInstanceStatus.TERMINATED, trigger)

        # 检查守卫条件
        if transition.guard and not transition.guard():
            raise InvalidStateTransitionError(self._status, transition.to_status, trigger)

        # 记录旧状态
        old_status = self._status

        # 执行转换动作
        if transition.action:
            transition.action()

        # 更新状态
        self._status = transition.to_status

        # 记录事件
        self._record_event(trigger, old_status, self._status, details, error_message)

        return self._status

    def _record_event(
        self,
        event_type: str,
        from_status: AgentInstanceStatus | None,
        to_status: AgentInstanceStatus,
        details: dict | None = None,
        error_message: str | None = None,
    ) -> None:
        """记录生命周期事件."""
        event = LifecycleEvent(
            instance_id=self.instance_id,
            event_type=event_type,
            from_status=from_status,
            to_status=to_status,
            timestamp=datetime.now(UTC),
            details=details or {},
            error_message=error_message,
        )
        self._history.append(event)

        # 通知监听器
        for listener in self._listeners:
            try:
                listener(event)
            except Exception:
                pass  # 忽略监听器错误

    def add_listener(self, listener: Callable[[LifecycleEvent], None]) -> None:
        """添加状态变更监听器.

        Args:
            listener: 监听器函数
        """
        self._listeners.append(listener)

    def remove_listener(self, listener: Callable[[LifecycleEvent], None]) -> None:
        """移除状态变更监听器.

        Args:
            listener: 监听器函数
        """
        if listener in self._listeners:
            self._listeners.remove(listener)

    def is_active(self) -> bool:
        """是否处于活跃状态 (可接收请求)."""
        return self._status in {
            AgentInstanceStatus.READY,
            AgentInstanceStatus.EXECUTING,
            AgentInstanceStatus.DEGRADED,
        }

    def is_terminal(self) -> bool:
        """是否处于终止状态."""
        return self._status in {
            AgentInstanceStatus.TERMINATED,
            AgentInstanceStatus.INITIALIZATION_FAILED,
        }

    def is_healthy(self) -> bool:
        """是否健康."""
        return self._status not in {
            AgentInstanceStatus.UNHEALTHY,
            AgentInstanceStatus.DEGRADED,
            AgentInstanceStatus.INITIALIZATION_FAILED,
        }

    def get_uptime_seconds(self) -> float:
        """获取运行时间 (秒)."""
        if not self._history:
            return 0.0
        first_event = self._history[0]
        return (datetime.now(UTC) - first_event.timestamp).total_seconds()

    def get_last_event(self) -> LifecycleEvent | None:
        """获取最后一个事件."""
        return self._history[-1] if self._history else None

    def to_dict(self) -> dict:
        """转换为字典."""
        return {
            "instance_id": self.instance_id,
            "status": self._status.value,
            "is_active": self.is_active(),
            "is_terminal": self.is_terminal(),
            "is_healthy": self.is_healthy(),
            "uptime_seconds": self.get_uptime_seconds(),
            "allowed_triggers": list(self.get_allowed_triggers()),
            "history_count": len(self._history),
        }
