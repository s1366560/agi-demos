"""
Pool Metrics Collector.

提供 Prometheus 兼容的指标收集，用于监控 Agent Pool 的运行状态。

指标类别:
- 实例指标: 实例数量、状态分布、分级分布
- 资源指标: 内存使用、CPU使用、配额利用率
- 请求指标: 请求数、延迟、错误率
- 健康指标: 健康检查结果、恢复次数
- 熔断器指标: 熔断状态、触发次数
"""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ..types import (
    CircuitState,
    HealthStatus,
    PoolStats,
    ProjectTier,
)

logger = logging.getLogger(__name__)


# ============================================================================
# Metric Types
# ============================================================================


@dataclass
class Counter:
    """计数器指标."""

    name: str
    help: str
    labels: list[str] = field(default_factory=list)
    _values: dict[tuple[Any, ...], float] = field(default_factory=dict)

    def inc(self, labels: dict[str, str] | None = None, value: float = 1.0) -> None:
        """增加计数."""
        key = self._make_key(labels)
        self._values[key] = self._values.get(key, 0.0) + value

    def get(self, labels: dict[str, str] | None = None) -> float:
        """获取当前值."""
        key = self._make_key(labels)
        return self._values.get(key, 0.0)

    def _make_key(self, labels: dict[str, str] | None) -> tuple[Any, ...]:
        """生成标签键."""
        if not labels:
            return ()
        return tuple(sorted(labels.items()))

    def collect(self) -> list[dict[str, Any]]:
        """收集所有指标值."""
        results = []
        for key, value in self._values.items():
            label_dict = dict(key) if key else {}
            results.append(
                {
                    "name": self.name,
                    "type": "counter",
                    "value": value,
                    "labels": label_dict,
                }
            )
        return results


@dataclass
class Gauge:
    """仪表盘指标."""

    name: str
    help: str
    labels: list[str] = field(default_factory=list)
    _values: dict[tuple[Any, ...], float] = field(default_factory=dict)

    def set(self, value: float, labels: dict[str, str] | None = None) -> None:
        """设置值."""
        key = self._make_key(labels)
        self._values[key] = value

    def inc(self, labels: dict[str, str] | None = None, value: float = 1.0) -> None:
        """增加值."""
        key = self._make_key(labels)
        self._values[key] = self._values.get(key, 0.0) + value

    def dec(self, labels: dict[str, str] | None = None, value: float = 1.0) -> None:
        """减少值."""
        key = self._make_key(labels)
        self._values[key] = self._values.get(key, 0.0) - value

    def get(self, labels: dict[str, str] | None = None) -> float:
        """获取当前值."""
        key = self._make_key(labels)
        return self._values.get(key, 0.0)

    def _make_key(self, labels: dict[str, str] | None) -> tuple[Any, ...]:
        """生成标签键."""
        if not labels:
            return ()
        return tuple(sorted(labels.items()))

    def collect(self) -> list[dict[str, Any]]:
        """收集所有指标值."""
        results = []
        for key, value in self._values.items():
            label_dict = dict(key) if key else {}
            results.append(
                {
                    "name": self.name,
                    "type": "gauge",
                    "value": value,
                    "labels": label_dict,
                }
            )
        return results


@dataclass
class Histogram:
    """直方图指标."""

    name: str
    help: str
    labels: list[str] = field(default_factory=list)
    buckets: list[float] = field(
        default_factory=lambda: [0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0]
    )
    _values: dict[tuple[Any, ...], list[float]] = field(default_factory=dict)

    def observe(self, value: float, labels: dict[str, str] | None = None) -> None:
        """记录观测值."""
        key = self._make_key(labels)
        if key not in self._values:
            self._values[key] = []
        self._values[key].append(value)

    def _make_key(self, labels: dict[str, str] | None) -> tuple[Any, ...]:
        """生成标签键."""
        if not labels:
            return ()
        return tuple(sorted(labels.items()))

    def collect(self) -> list[dict[str, Any]]:
        """收集所有指标值."""
        results = []
        for key, values in self._values.items():
            label_dict = dict(key) if key else {}
            if values:
                results.append(
                    {
                        "name": self.name,
                        "type": "histogram",
                        "count": len(values),
                        "sum": sum(values),
                        "avg": sum(values) / len(values),
                        "min": min(values),
                        "max": max(values),
                        "labels": label_dict,
                    }
                )
        return results


# ============================================================================
# Pool Metrics Collector
# ============================================================================


class PoolMetricsCollector:
    """池化管理指标收集器.

    收集并暴露 Agent Pool 的各类指标，支持 Prometheus 格式导出。
    """

    def __init__(self, namespace: str = "memstack_agent_pool") -> None:
        """初始化指标收集器.

        Args:
            namespace: 指标命名空间前缀
        """
        self.namespace = namespace

        # 实例指标
        self.instances_total = Gauge(
            name=f"{namespace}_instances_total",
            help="Total number of agent instances",
        )
        self.instances_by_tier = Gauge(
            name=f"{namespace}_instances_by_tier",
            help="Number of instances by tier",
            labels=["tier"],
        )
        self.instances_by_status = Gauge(
            name=f"{namespace}_instances_by_status",
            help="Number of instances by status",
            labels=["status"],
        )

        # 请求指标
        self.requests_total = Counter(
            name=f"{namespace}_requests_total",
            help="Total number of requests",
            labels=["tenant_id", "project_id", "status"],
        )
        self.requests_active = Gauge(
            name=f"{namespace}_requests_active",
            help="Number of active requests",
            labels=["tenant_id", "project_id"],
        )
        self.request_duration_seconds = Histogram(
            name=f"{namespace}_request_duration_seconds",
            help="Request duration in seconds",
            labels=["tenant_id", "project_id"],
            buckets=[0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0],
        )

        # 资源指标
        self.memory_used_bytes = Gauge(
            name=f"{namespace}_memory_used_bytes",
            help="Memory used in bytes",
            labels=["tenant_id", "project_id"],
        )
        self.memory_limit_bytes = Gauge(
            name=f"{namespace}_memory_limit_bytes",
            help="Memory limit in bytes",
            labels=["tenant_id", "project_id"],
        )
        self.cpu_used_cores = Gauge(
            name=f"{namespace}_cpu_used_cores",
            help="CPU cores used",
            labels=["tenant_id", "project_id"],
        )

        # 健康指标
        self.health_checks_total = Counter(
            name=f"{namespace}_health_checks_total",
            help="Total number of health checks",
            labels=["status"],
        )
        self.unhealthy_instances = Gauge(
            name=f"{namespace}_unhealthy_instances",
            help="Number of unhealthy instances",
        )
        self.recoveries_total = Counter(
            name=f"{namespace}_recoveries_total",
            help="Total number of recovery attempts",
            labels=["result"],
        )

        # 熔断器指标
        self.circuit_breaker_state = Gauge(
            name=f"{namespace}_circuit_breaker_state",
            help="Circuit breaker state (0=closed, 1=half_open, 2=open)",
            labels=["name"],
        )
        self.circuit_breaker_trips_total = Counter(
            name=f"{namespace}_circuit_breaker_trips_total",
            help="Total number of circuit breaker trips",
            labels=["name"],
        )

        # 生命周期指标
        self.instance_created_total = Counter(
            name=f"{namespace}_instance_created_total",
            help="Total number of instances created",
            labels=["tier"],
        )
        self.instance_terminated_total = Counter(
            name=f"{namespace}_instance_terminated_total",
            help="Total number of instances terminated",
            labels=["tier", "reason"],
        )
        self.instance_initialization_duration_seconds = Histogram(
            name=f"{namespace}_instance_initialization_duration_seconds",
            help="Instance initialization duration in seconds",
            labels=["tier"],
            buckets=[0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
        )

        # 预热池指标
        self.prewarm_pool_size = Gauge(
            name=f"{namespace}_prewarm_pool_size",
            help="Number of prewarmed instances",
            labels=["level"],
        )
        self.prewarm_hit_total = Counter(
            name=f"{namespace}_prewarm_hit_total",
            help="Total number of prewarm cache hits",
            labels=["level"],
        )
        self.prewarm_miss_total = Counter(
            name=f"{namespace}_prewarm_miss_total",
            help="Total number of prewarm cache misses",
        )

        logger.info(f"[PoolMetricsCollector] Initialized: namespace={namespace}")

    # ========================================================================
    # Recording Methods
    # ========================================================================

    def record_request_start(
        self,
        tenant_id: str,
        project_id: str,
    ) -> Callable[[], None]:
        """记录请求开始，返回用于记录结束的回调函数.

        Args:
            tenant_id: 租户ID
            project_id: 项目ID

        Returns:
            结束回调函数
        """
        labels = {"tenant_id": tenant_id, "project_id": project_id}
        start_time = time.time()
        self.requests_active.inc(labels)

        def on_complete(success: bool = True) -> None:
            duration = time.time() - start_time
            self.requests_active.dec(labels)
            self.request_duration_seconds.observe(duration, labels)
            status_labels = {**labels, "status": "success" if success else "error"}
            self.requests_total.inc(status_labels)

        return on_complete

    def record_instance_created(self, tier: ProjectTier) -> None:
        """记录实例创建."""
        self.instance_created_total.inc({"tier": tier.value})

    def record_instance_terminated(
        self,
        tier: ProjectTier,
        reason: str = "normal",
    ) -> None:
        """记录实例终止."""
        self.instance_terminated_total.inc({"tier": tier.value, "reason": reason})

    def record_instance_initialization(
        self,
        tier: ProjectTier,
        duration_seconds: float,
    ) -> None:
        """记录实例初始化时间."""
        self.instance_initialization_duration_seconds.observe(
            duration_seconds, {"tier": tier.value}
        )

    def record_health_check(self, status: HealthStatus) -> None:
        """记录健康检查结果."""
        self.health_checks_total.inc({"status": status.value})

    def record_recovery_attempt(self, success: bool) -> None:
        """记录恢复尝试."""
        self.recoveries_total.inc({"result": "success" if success else "failed"})

    def record_circuit_breaker_state(
        self,
        name: str,
        state: CircuitState,
    ) -> None:
        """记录熔断器状态."""
        state_value = {"closed": 0, "half_open": 1, "open": 2}.get(state.value, -1)
        self.circuit_breaker_state.set(state_value, {"name": name})

    def record_circuit_breaker_trip(self, name: str) -> None:
        """记录熔断器触发."""
        self.circuit_breaker_trips_total.inc({"name": name})

    def record_prewarm_hit(self, level: str) -> None:
        """记录预热命中."""
        self.prewarm_hit_total.inc({"level": level})

    def record_prewarm_miss(self) -> None:
        """记录预热未命中."""
        self.prewarm_miss_total.inc()

    # ========================================================================
    # Update Methods (from pool stats)
    # ========================================================================

    def update_from_pool_stats(self, stats: PoolStats) -> None:
        """从池统计更新指标.

        Args:
            stats: 池统计信息
        """
        # 实例总数
        self.instances_total.set(stats.total_instances)

        # 按分级
        self.instances_by_tier.set(stats.hot_instances, {"tier": "hot"})
        self.instances_by_tier.set(stats.warm_instances, {"tier": "warm"})
        self.instances_by_tier.set(stats.cold_instances, {"tier": "cold"})

        # 按状态
        self.instances_by_status.set(stats.ready_instances, {"status": "ready"})
        self.instances_by_status.set(stats.executing_instances, {"status": "executing"})
        self.instances_by_status.set(stats.unhealthy_instances, {"status": "unhealthy"})

        # 不健康实例数
        self.unhealthy_instances.set(stats.unhealthy_instances)

        # 预热池
        self.prewarm_pool_size.set(stats.prewarm_l1_count, {"level": "l1"})
        self.prewarm_pool_size.set(stats.prewarm_l2_count, {"level": "l2"})
        self.prewarm_pool_size.set(stats.prewarm_l3_count, {"level": "l3"})

    # ========================================================================
    # Export Methods
    # ========================================================================

    def collect_all(self) -> list[dict[str, Any]]:
        """收集所有指标.

        Returns:
            指标列表
        """
        metrics = []

        # 收集所有指标类型
        for attr_name in dir(self):
            attr = getattr(self, attr_name)
            if isinstance(attr, (Counter, Gauge, Histogram)):
                metrics.extend(attr.collect())

        return metrics

    def to_prometheus_format(self) -> str:
        """导出为 Prometheus 文本格式.

        Returns:
            Prometheus 格式的指标文本
        """
        lines = []

        for attr_name in dir(self):
            attr = getattr(self, attr_name)
            if isinstance(attr, (Counter, Gauge)):
                lines.append(f"# HELP {attr.name} {attr.help}")
                lines.append(f"# TYPE {attr.name} {type(attr).__name__.lower()}")
                for metric in attr.collect():
                    labels_str = ""
                    if metric["labels"]:
                        label_pairs = [f'{k}="{v}"' for k, v in metric["labels"].items()]
                        labels_str = "{" + ",".join(label_pairs) + "}"
                    lines.append(f"{metric['name']}{labels_str} {metric['value']}")
            elif isinstance(attr, Histogram):
                lines.append(f"# HELP {attr.name} {attr.help}")
                lines.append(f"# TYPE {attr.name} histogram")
                for metric in attr.collect():
                    labels_str = ""
                    if metric["labels"]:
                        label_pairs = [f'{k}="{v}"' for k, v in metric["labels"].items()]
                        labels_str = "{" + ",".join(label_pairs) + "}"
                    base_name = metric["name"]
                    lines.append(f"{base_name}_count{labels_str} {metric['count']}")
                    lines.append(f"{base_name}_sum{labels_str} {metric['sum']}")

        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        """转换为字典格式.

        Returns:
            指标字典
        """
        return {
            "instances": {
                "total": self.instances_total.get(),
                "by_tier": {
                    "hot": self.instances_by_tier.get({"tier": "hot"}),
                    "warm": self.instances_by_tier.get({"tier": "warm"}),
                    "cold": self.instances_by_tier.get({"tier": "cold"}),
                },
                "by_status": {
                    "ready": self.instances_by_status.get({"status": "ready"}),
                    "executing": self.instances_by_status.get({"status": "executing"}),
                    "unhealthy": self.instances_by_status.get({"status": "unhealthy"}),
                },
            },
            "health": {
                "unhealthy_count": self.unhealthy_instances.get(),
            },
            "prewarm": {
                "l1": self.prewarm_pool_size.get({"level": "l1"}),
                "l2": self.prewarm_pool_size.get({"level": "l2"}),
                "l3": self.prewarm_pool_size.get({"level": "l3"}),
            },
        }


# ============================================================================
# Global Singleton
# ============================================================================

_global_collector: PoolMetricsCollector | None = None


def get_metrics_collector(namespace: str = "agent_pool") -> PoolMetricsCollector:
    """获取全局指标收集器单例.

    Args:
        namespace: 指标命名空间 (仅首次创建时使用)

    Returns:
        指标收集器实例
    """
    global _global_collector

    if _global_collector is None:
        _global_collector = PoolMetricsCollector(namespace=namespace)

    return _global_collector
