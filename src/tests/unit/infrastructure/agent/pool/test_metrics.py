"""
Metrics Collector Tests.

测试指标收集器的功能。
"""

import pytest

from src.infrastructure.agent.pool.metrics import PoolMetricsCollector, get_metrics_collector
from src.infrastructure.agent.pool.types import (
    CircuitState,
    HealthStatus,
    PoolStats,
    ProjectTier,
)


class TestPoolMetricsCollector:
    """PoolMetricsCollector 单元测试."""

    def setup_method(self):
        """测试前置."""
        self.collector = PoolMetricsCollector(namespace="test_pool")

    # ========================================================================
    # Counter Tests
    # ========================================================================

    def test_counter_increment(self):
        """测试计数器递增."""
        self.collector.requests_total.inc({"tenant_id": "t1", "project_id": "p1", "status": "success"})
        self.collector.requests_total.inc({"tenant_id": "t1", "project_id": "p1", "status": "success"})

        value = self.collector.requests_total.get(
            {"tenant_id": "t1", "project_id": "p1", "status": "success"}
        )
        assert value == 2.0

    def test_counter_with_different_labels(self):
        """测试不同标签的计数器."""
        self.collector.requests_total.inc({"tenant_id": "t1", "project_id": "p1", "status": "success"})
        self.collector.requests_total.inc({"tenant_id": "t1", "project_id": "p1", "status": "error"})

        success = self.collector.requests_total.get(
            {"tenant_id": "t1", "project_id": "p1", "status": "success"}
        )
        error = self.collector.requests_total.get(
            {"tenant_id": "t1", "project_id": "p1", "status": "error"}
        )

        assert success == 1.0
        assert error == 1.0

    # ========================================================================
    # Gauge Tests
    # ========================================================================

    def test_gauge_set(self):
        """测试仪表盘设置值."""
        self.collector.instances_total.set(10)
        assert self.collector.instances_total.get() == 10

    def test_gauge_inc_dec(self):
        """测试仪表盘递增递减."""
        self.collector.requests_active.set(5, {"tenant_id": "t1", "project_id": "p1"})
        self.collector.requests_active.inc({"tenant_id": "t1", "project_id": "p1"})
        self.collector.requests_active.dec({"tenant_id": "t1", "project_id": "p1"}, 2)

        value = self.collector.requests_active.get({"tenant_id": "t1", "project_id": "p1"})
        assert value == 4.0  # 5 + 1 - 2 = 4

    def test_gauge_by_tier(self):
        """测试按分级的仪表盘."""
        self.collector.instances_by_tier.set(5, {"tier": "hot"})
        self.collector.instances_by_tier.set(10, {"tier": "warm"})
        self.collector.instances_by_tier.set(3, {"tier": "cold"})

        assert self.collector.instances_by_tier.get({"tier": "hot"}) == 5
        assert self.collector.instances_by_tier.get({"tier": "warm"}) == 10
        assert self.collector.instances_by_tier.get({"tier": "cold"}) == 3

    # ========================================================================
    # Histogram Tests
    # ========================================================================

    def test_histogram_observe(self):
        """测试直方图观测."""
        labels = {"tenant_id": "t1", "project_id": "p1"}
        self.collector.request_duration_seconds.observe(0.5, labels)
        self.collector.request_duration_seconds.observe(1.0, labels)
        self.collector.request_duration_seconds.observe(2.0, labels)

        collected = self.collector.request_duration_seconds.collect()
        assert len(collected) == 1
        assert collected[0]["count"] == 3
        assert collected[0]["sum"] == 3.5  # 0.5 + 1.0 + 2.0
        assert collected[0]["avg"] == pytest.approx(1.166666, rel=0.01)

    # ========================================================================
    # Recording Methods Tests
    # ========================================================================

    def test_record_request_lifecycle(self):
        """测试请求生命周期记录."""
        # 开始请求
        on_complete = self.collector.record_request_start("t1", "p1")

        # 检查活跃请求增加
        active = self.collector.requests_active.get({"tenant_id": "t1", "project_id": "p1"})
        assert active == 1.0

        # 完成请求
        on_complete(success=True)

        # 检查活跃请求减少
        active = self.collector.requests_active.get({"tenant_id": "t1", "project_id": "p1"})
        assert active == 0.0

        # 检查总请求增加
        total = self.collector.requests_total.get(
            {"tenant_id": "t1", "project_id": "p1", "status": "success"}
        )
        assert total == 1.0

    def test_record_instance_created(self):
        """测试记录实例创建."""
        self.collector.record_instance_created(ProjectTier.HOT)
        self.collector.record_instance_created(ProjectTier.HOT)
        self.collector.record_instance_created(ProjectTier.WARM)

        hot = self.collector.instance_created_total.get({"tier": "hot"})
        warm = self.collector.instance_created_total.get({"tier": "warm"})

        assert hot == 2.0
        assert warm == 1.0

    def test_record_instance_terminated(self):
        """测试记录实例终止."""
        self.collector.record_instance_terminated(ProjectTier.COLD, "timeout")

        terminated = self.collector.instance_terminated_total.get(
            {"tier": "cold", "reason": "timeout"}
        )
        assert terminated == 1.0

    def test_record_health_check(self):
        """测试记录健康检查."""
        self.collector.record_health_check(HealthStatus.HEALTHY)
        self.collector.record_health_check(HealthStatus.HEALTHY)
        self.collector.record_health_check(HealthStatus.UNHEALTHY)

        healthy = self.collector.health_checks_total.get({"status": "healthy"})
        unhealthy = self.collector.health_checks_total.get({"status": "unhealthy"})

        assert healthy == 2.0
        assert unhealthy == 1.0

    def test_record_circuit_breaker(self):
        """测试记录熔断器状态."""
        self.collector.record_circuit_breaker_state("agent-1", CircuitState.CLOSED)
        state = self.collector.circuit_breaker_state.get({"name": "agent-1"})
        assert state == 0  # closed = 0

        self.collector.record_circuit_breaker_state("agent-1", CircuitState.OPEN)
        state = self.collector.circuit_breaker_state.get({"name": "agent-1"})
        assert state == 2  # open = 2

        self.collector.record_circuit_breaker_trip("agent-1")
        trips = self.collector.circuit_breaker_trips_total.get({"name": "agent-1"})
        assert trips == 1.0

    def test_record_prewarm(self):
        """测试记录预热池."""
        self.collector.record_prewarm_hit("l1")
        self.collector.record_prewarm_hit("l1")
        self.collector.record_prewarm_hit("l2")
        self.collector.record_prewarm_miss()

        l1_hits = self.collector.prewarm_hit_total.get({"level": "l1"})
        l2_hits = self.collector.prewarm_hit_total.get({"level": "l2"})
        misses = self.collector.prewarm_miss_total.get()

        assert l1_hits == 2.0
        assert l2_hits == 1.0
        assert misses == 1.0

    # ========================================================================
    # Update from Stats Tests
    # ========================================================================

    def test_update_from_pool_stats(self):
        """测试从池统计更新指标."""
        stats = PoolStats(
            total_instances=20,
            hot_instances=5,
            warm_instances=10,
            cold_instances=5,
            ready_instances=15,
            executing_instances=3,
            unhealthy_instances=2,
            prewarm_l1_count=3,
            prewarm_l2_count=5,
            prewarm_l3_count=10,
        )

        self.collector.update_from_pool_stats(stats)

        assert self.collector.instances_total.get() == 20
        assert self.collector.instances_by_tier.get({"tier": "hot"}) == 5
        assert self.collector.instances_by_tier.get({"tier": "warm"}) == 10
        assert self.collector.instances_by_tier.get({"tier": "cold"}) == 5
        assert self.collector.instances_by_status.get({"status": "ready"}) == 15
        assert self.collector.unhealthy_instances.get() == 2
        assert self.collector.prewarm_pool_size.get({"level": "l1"}) == 3

    # ========================================================================
    # Export Tests
    # ========================================================================

    def test_collect_all(self):
        """测试收集所有指标."""
        self.collector.instances_total.set(10)
        self.collector.requests_total.inc({"tenant_id": "t1", "project_id": "p1", "status": "success"})

        metrics = self.collector.collect_all()
        assert len(metrics) >= 2  # At least the two we set

    def test_to_dict(self):
        """测试转换为字典."""
        self.collector.instances_total.set(10)
        self.collector.instances_by_tier.set(3, {"tier": "hot"})
        self.collector.unhealthy_instances.set(1)

        data = self.collector.to_dict()

        assert data["instances"]["total"] == 10
        assert data["instances"]["by_tier"]["hot"] == 3
        assert data["health"]["unhealthy_count"] == 1

    def test_to_prometheus_format(self):
        """测试 Prometheus 格式导出."""
        self.collector.instances_total.set(10)

        prometheus = self.collector.to_prometheus_format()

        assert "test_pool_instances_total" in prometheus
        assert "10" in prometheus
        assert "# HELP" in prometheus
        assert "# TYPE" in prometheus


class TestGetMetricsCollector:
    """测试全局指标收集器."""

    def test_get_metrics_collector_singleton(self):
        """测试单例模式."""
        collector1 = get_metrics_collector()
        collector2 = get_metrics_collector()

        assert collector1 is collector2

    def test_get_metrics_collector_default_namespace(self):
        """测试默认命名空间."""
        collector = get_metrics_collector()
        # Default namespace is "agent_pool" when called without args
        # but may be "memstack_agent_pool" if called with default from PoolMetricsCollector
        assert "agent_pool" in collector.namespace
