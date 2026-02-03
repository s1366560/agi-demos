"""
Agent Pool 类型定义.

包含所有池化管理相关的枚举、数据类和类型别名。
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional


class ProjectTier(str, Enum):
    """项目分级.

    根据项目的访问频率、付费等级、SLA要求等自动或手动分级。
    不同分级对应不同的资源隔离策略。
    """

    HOT = "hot"  # 高频访问，独立容器/进程
    WARM = "warm"  # 中频访问，共享Worker池
    COLD = "cold"  # 低频访问，按需创建


class AgentInstanceStatus(str, Enum):
    """Agent实例状态.

    定义实例生命周期中的所有状态。
    状态转换由 LifecycleStateMachine 管理。
    """

    # 初始化阶段
    CREATED = "created"  # 配置已验证，资源已预留
    INITIALIZING = "initializing"  # 正在初始化
    INITIALIZATION_FAILED = "initialization_failed"  # 初始化失败

    # 运行阶段
    READY = "ready"  # 可接收请求
    EXECUTING = "executing"  # 正在处理请求
    PAUSED = "paused"  # 暂停接收新请求

    # 异常阶段
    UNHEALTHY = "unhealthy"  # 健康检查失败
    DEGRADED = "degraded"  # 降级运行 (部分功能不可用)

    # 终止阶段
    TERMINATING = "terminating"  # 正在终止
    TERMINATED = "terminated"  # 已终止


class HealthStatus(str, Enum):
    """健康状态."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


class CircuitState(str, Enum):
    """熔断器状态."""

    CLOSED = "closed"  # 正常
    HALF_OPEN = "half_open"  # 半开 (尝试恢复)
    OPEN = "open"  # 熔断


class RecoveryAction(str, Enum):
    """恢复动作."""

    RESTART = "restart"  # 重启实例
    MIGRATE = "migrate"  # 迁移到其他 Worker
    DEGRADE = "degrade"  # 降级运行
    ALERT = "alert"  # 仅告警
    TERMINATE = "terminate"  # 终止实例


@dataclass
class HealthCheckResult:
    """健康检查结果."""

    status: HealthStatus
    latency_ms: float = 0.0
    error_rate: float = 0.0
    memory_usage_pct: float = 0.0
    cpu_usage_pct: float = 0.0
    active_requests: int = 0
    last_check_at: Optional[datetime] = None
    details: Dict[str, Any] = field(default_factory=dict)
    error_message: Optional[str] = None

    def is_healthy(self) -> bool:
        """是否健康."""
        return self.status == HealthStatus.HEALTHY


@dataclass
class InstanceMetrics:
    """实例指标."""

    # 请求统计
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0

    # 延迟统计 (ms)
    avg_latency_ms: float = 0.0
    p50_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0
    p99_latency_ms: float = 0.0
    max_latency_ms: float = 0.0

    # 资源使用
    memory_used_mb: float = 0.0
    cpu_used_pct: float = 0.0

    # 工具统计
    tool_execution_count: Dict[str, int] = field(default_factory=dict)

    # 时间戳
    created_at: Optional[datetime] = None
    last_request_at: Optional[datetime] = None
    last_error_at: Optional[datetime] = None

    def error_rate(self) -> float:
        """计算错误率."""
        if self.total_requests == 0:
            return 0.0
        return self.failed_requests / self.total_requests


@dataclass
class ResourceUsage:
    """资源使用情况."""

    memory_used_mb: float = 0.0
    memory_limit_mb: float = 0.0
    cpu_used_cores: float = 0.0
    cpu_limit_cores: float = 0.0
    active_instances: int = 0
    max_instances: int = 0
    active_requests: int = 0
    max_concurrent_requests: int = 0

    def memory_usage_pct(self) -> float:
        """内存使用百分比."""
        if self.memory_limit_mb == 0:
            return 0.0
        return (self.memory_used_mb / self.memory_limit_mb) * 100

    def cpu_usage_pct(self) -> float:
        """CPU使用百分比."""
        if self.cpu_limit_cores == 0:
            return 0.0
        return (self.cpu_used_cores / self.cpu_limit_cores) * 100


@dataclass
class TierMigration:
    """分级迁移信息."""

    project_id: str
    tenant_id: str
    from_tier: ProjectTier
    to_tier: ProjectTier
    reason: str
    scheduled_at: Optional[datetime] = None
    executed_at: Optional[datetime] = None
    status: str = "pending"  # pending, executing, completed, failed


@dataclass
class ProjectMetrics:
    """项目指标 (用于分级决策)."""

    project_id: str
    tenant_id: str

    # 访问统计
    daily_requests: int = 0
    weekly_requests: int = 0
    monthly_requests: int = 0

    # 并发统计
    avg_concurrent: float = 0.0
    max_concurrent: int = 0

    # 延迟统计
    avg_latency_ms: float = 0.0
    p99_latency_ms: float = 0.0

    # 业务属性
    subscription_tier: str = "free"  # free, basic, professional, enterprise
    sla_requirement: float = 0.99  # 99%

    # 时间戳
    last_request_at: Optional[datetime] = None
    tier_updated_at: Optional[datetime] = None


@dataclass
class LifecycleEvent:
    """生命周期事件."""

    instance_id: str
    event_type: str  # created, initialized, started, paused, resumed, stopped, error, recovered
    from_status: Optional[AgentInstanceStatus] = None
    to_status: Optional[AgentInstanceStatus] = None
    timestamp: datetime = field(default_factory=datetime.utcnow)
    details: Dict[str, Any] = field(default_factory=dict)
    error_message: Optional[str] = None


@dataclass
class PoolStats:
    """池统计信息."""

    # 实例统计
    total_instances: int = 0
    hot_instances: int = 0
    warm_instances: int = 0
    cold_instances: int = 0

    # 状态统计
    ready_instances: int = 0
    executing_instances: int = 0
    unhealthy_instances: int = 0

    # 资源统计
    total_memory_mb: float = 0.0
    used_memory_mb: float = 0.0
    total_cpu_cores: float = 0.0
    used_cpu_cores: float = 0.0

    # 预热池统计
    prewarm_l1_count: int = 0
    prewarm_l2_count: int = 0
    prewarm_l3_count: int = 0

    # 请求统计
    total_requests: int = 0
    active_requests: int = 0
    queued_requests: int = 0
