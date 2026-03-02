"""Performance/stress tests for the Agent Pool system.

Tests cover:
a) Pool manager instance creation throughput
b) Circuit breaker state transitions under load
c) Failure recovery strategy selection speed
d) State recovery checkpoint serialization time
e) Auto-scaler response time

Run with: pytest src/tests/performance/test_pool_performance.py -v -m performance
"""

from __future__ import annotations

import logging
import statistics
import time
from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock

import pytest

from src.infrastructure.agent.pool.circuit_breaker.breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
)
from src.infrastructure.agent.pool.config import (
    AgentInstanceConfig,
    PoolConfig,
    ResourceQuota,
)
from src.infrastructure.agent.pool.ha.auto_scaling import (
    AutoScalingService,
    ScalingDirection,
    ScalingMetrics,
    ScalingPolicy,
    ScalingReason,
)
from src.infrastructure.agent.pool.ha.failure_recovery import (
    FailureEvent,
    FailurePattern,
    FailureRecoveryService,
    FailureType,
    RecoveryAction,
)
from src.infrastructure.agent.pool.ha.state_recovery import (
    CheckpointType,
    StateCheckpoint,
    StateRecoveryService,
)
from src.infrastructure.agent.pool.manager import AgentPoolManager
from src.infrastructure.agent.pool.types import CircuitState, ProjectTier

logger = logging.getLogger(__name__)


def _print_report(
    name: str,
    iterations: int,
    times: list[float],
) -> None:
    """Print a formatted benchmark report."""
    avg = statistics.mean(times)
    med = statistics.median(times)
    p95 = sorted(times)[int(len(times) * 0.95)]
    p99 = sorted(times)[int(len(times) * 0.99)]
    mn = min(times)
    mx = max(times)
    total_s = sum(times) / 1000
    throughput = iterations / total_s if total_s > 0 else 0

    print(f"\n{'=' * 60}")
    print(f"Benchmark: {name}")
    print(f"{'=' * 60}")
    print(f"  Iterations: {iterations}")
    print(f"  Min:        {mn:.4f}ms")
    print(f"  Max:        {mx:.4f}ms")
    print(f"  Avg:        {avg:.4f}ms")
    print(f"  Median:     {med:.4f}ms")
    print(f"  P95:        {p95:.4f}ms")
    print(f"  P99:        {p99:.4f}ms")
    print(f"  Throughput: {throughput:.2f} ops/s")


# =============================================================================
# a) Pool Manager Instance Creation Throughput
# =============================================================================


@pytest.mark.performance
class TestPoolManagerCreateInstanceThroughput:
    """Benchmark AgentPoolManager._create_instance with mocked deps."""

    async def test_create_instance_throughput(self) -> None:
        """Measure time to create N mock instances via AgentPoolManager."""
        # Arrange
        config = PoolConfig()

        resource_manager = Mock()
        resource_manager.allocate = AsyncMock()
        resource_manager.acquire_instance = AsyncMock()
        resource_manager.release_instance = AsyncMock()

        health_monitor = Mock()
        health_monitor.start_monitoring = AsyncMock()
        health_monitor.stop_monitoring = AsyncMock()
        health_monitor.stop_all_monitoring = AsyncMock()

        manager = AgentPoolManager(
            config=config,
            resource_manager=resource_manager,
            health_monitor=health_monitor,
        )

        iterations = 100
        times: list[float] = []

        for i in range(iterations):
            # Create a unique mock instance each time
            mock_instance = Mock()
            mock_instance.id = f"inst-{i}"
            mock_instance.is_active = True
            mock_instance.initialize = AsyncMock(return_value=True)
            mock_instance.config = AgentInstanceConfig(
                project_id=f"project-{i}",
                tenant_id="tenant-1",
                agent_mode="default",
                tier=ProjectTier.WARM,
                quota=ResourceQuota(),
            )
            mock_instance.metrics = Mock(total_requests=0)
            mock_instance.active_requests = 0
            mock_instance.status = Mock(value="ready")

            # Patch AgentInstance constructor to return our mock
            import src.infrastructure.agent.pool.manager as mgr_module

            original_agent_instance = mgr_module.AgentInstance

            def make_mock_instance(config: AgentInstanceConfig) -> Mock:
                mock_instance.config = config
                return mock_instance

            mgr_module.AgentInstance = make_mock_instance

            try:
                start = time.perf_counter()
                _instance = await manager._create_instance(
                    tenant_id="tenant-1",
                    project_id=f"project-{i}",
                    agent_mode="default",
                )
                end = time.perf_counter()
                times.append((end - start) * 1000)
            finally:
                mgr_module.AgentInstance = original_agent_instance

        _print_report("PoolManager._create_instance", iterations, times)

        avg = statistics.mean(times)
        p99 = sorted(times)[int(len(times) * 0.99)]

        # Instance creation with mocked deps should be < 10ms avg
        assert avg < 10.0, f"Avg create_instance too slow: {avg:.4f}ms"
        assert p99 < 50.0, f"P99 create_instance too slow: {p99:.4f}ms"

    async def test_classify_project_throughput(self) -> None:
        """Measure project classification speed."""
        config = PoolConfig()
        resource_manager = Mock()
        health_monitor = Mock()
        health_monitor.stop_all_monitoring = AsyncMock()

        manager = AgentPoolManager(
            config=config,
            resource_manager=resource_manager,
            health_monitor=health_monitor,
        )

        iterations = 1000
        times: list[float] = []

        for i in range(iterations):
            start = time.perf_counter()
            _tier = await manager.classify_project(
                tenant_id="tenant-1",
                project_id=f"project-{i}",
            )
            end = time.perf_counter()
            times.append((end - start) * 1000)

        _print_report("PoolManager.classify_project", iterations, times)

        avg = statistics.mean(times)
        assert avg < 1.0, f"Avg classify_project too slow: {avg:.4f}ms"


# =============================================================================
# b) Circuit Breaker State Transitions Under Load
# =============================================================================


@pytest.mark.performance
class TestCircuitBreakerStateTransitionsPerformance:
    """Benchmark circuit breaker state transitions."""

    def test_transition_to_latency(self) -> None:
        """Measure _transition_to() latency for each state transition."""
        cb = CircuitBreaker(
            name="perf-test",
            config=CircuitBreakerConfig(failure_threshold=5),
        )

        iterations = 10000
        times: list[float] = []

        for _ in range(iterations):
            # CLOSED -> OPEN
            start = time.perf_counter()
            cb._transition_to(CircuitState.OPEN)
            end = time.perf_counter()
            times.append((end - start) * 1000)

            # OPEN -> HALF_OPEN
            start = time.perf_counter()
            cb._transition_to(CircuitState.HALF_OPEN)
            end = time.perf_counter()
            times.append((end - start) * 1000)

            # HALF_OPEN -> CLOSED
            start = time.perf_counter()
            cb._transition_to(CircuitState.CLOSED)
            end = time.perf_counter()
            times.append((end - start) * 1000)

        _print_report(
            "CircuitBreaker._transition_to (3 transitions per iter)",
            iterations * 3,
            times,
        )

        avg = statistics.mean(times)
        p99 = sorted(times)[int(len(times) * 0.99)]

        # Single transition should be < 0.1ms (sync, in-memory)
        assert avg < 0.1, f"Avg transition too slow: {avg:.4f}ms"
        assert p99 < 1.0, f"P99 transition too slow: {p99:.4f}ms"

    def test_full_cycle_under_load(self) -> None:
        """Benchmark full CLOSED->OPEN->HALF_OPEN->CLOSED cycle."""
        iterations = 5000
        times: list[float] = []

        for _ in range(iterations):
            cb = CircuitBreaker(
                name="cycle-test",
                config=CircuitBreakerConfig(failure_threshold=5),
            )
            start = time.perf_counter()
            cb._transition_to(CircuitState.OPEN)
            cb._transition_to(CircuitState.HALF_OPEN)
            cb._transition_to(CircuitState.CLOSED)
            end = time.perf_counter()
            times.append((end - start) * 1000)

        _print_report("CircuitBreaker full cycle (3 transitions)", iterations, times)

        avg = statistics.mean(times)
        assert avg < 0.5, f"Avg full cycle too slow: {avg:.4f}ms"

    def test_cleanup_old_failures_performance(self) -> None:
        """Benchmark _cleanup_old_failures with many failure timestamps."""
        cb = CircuitBreaker(
            name="cleanup-test",
            config=CircuitBreakerConfig(window_seconds=60),
        )

        # Pre-populate with 10000 failure timestamps
        now = time.time()
        cb._failure_timestamps = [now - i * 0.01 for i in range(10000)]

        iterations = 1000
        times: list[float] = []

        for _ in range(iterations):
            # Re-populate so cleanup has work to do
            cb._failure_timestamps = [now - i * 0.01 for i in range(10000)]

            start = time.perf_counter()
            cb._cleanup_old_failures()
            end = time.perf_counter()
            times.append((end - start) * 1000)

        _print_report("CircuitBreaker._cleanup_old_failures (10k entries)", iterations, times)

        avg = statistics.mean(times)
        assert avg < 5.0, f"Avg cleanup too slow: {avg:.4f}ms"

    def test_count_recent_failures_performance(self) -> None:
        """Benchmark _count_recent_failures with many timestamps."""
        cb = CircuitBreaker(
            name="count-test",
            config=CircuitBreakerConfig(window_seconds=60),
        )

        now = time.time()
        cb._failure_timestamps = [now - i * 0.005 for i in range(10000)]

        iterations = 1000
        times: list[float] = []

        for _ in range(iterations):
            start = time.perf_counter()
            _count = cb._count_recent_failures()
            end = time.perf_counter()
            times.append((end - start) * 1000)

        _print_report("CircuitBreaker._count_recent_failures (10k entries)", iterations, times)

        avg = statistics.mean(times)
        assert avg < 5.0, f"Avg count too slow: {avg:.4f}ms"


# =============================================================================
# c) Failure Recovery Strategy Selection Speed
# =============================================================================


@pytest.mark.performance
class TestFailureRecoveryStrategySelectionSpeed:
    """Benchmark failure recovery strategy lookup and pattern detection."""

    def test_recovery_action_lookup_speed(self) -> None:
        """Measure _recovery_actions dict lookup speed."""
        svc = FailureRecoveryService()

        failure_types = list(FailureType)
        iterations = 10000
        times: list[float] = []

        for i in range(iterations):
            ft = failure_types[i % len(failure_types)]
            start = time.perf_counter()
            action = svc._recovery_actions.get(ft)
            end = time.perf_counter()
            times.append((end - start) * 1000)

            # Verify correctness on first pass
            if i < len(failure_types):
                assert action is not None
                assert isinstance(action, RecoveryAction)

        _print_report("FailureRecovery._recovery_actions.get()", iterations, times)

        avg = statistics.mean(times)
        assert avg < 0.01, f"Avg lookup too slow: {avg:.6f}ms"

    def test_detect_pattern_speed_with_history(self) -> None:
        """Measure _detect_pattern speed with populated failure history."""
        svc = FailureRecoveryService()

        # Populate failure history with many events
        instance_key = "tenant1:project1:default"
        now = datetime.now(UTC)
        svc._failure_history[instance_key] = [
            FailureEvent(
                event_id=f"evt-{i}",
                instance_key=instance_key,
                failure_type=list(FailureType)[i % len(list(FailureType))],
                timestamp=now,
            )
            for i in range(100)
        ]

        iterations = 5000
        times: list[float] = []

        pattern = None
        for _ in range(iterations):
            start = time.perf_counter()
            pattern = svc._detect_pattern(instance_key)
            end = time.perf_counter()
            times.append((end - start) * 1000)

        _print_report("FailureRecovery._detect_pattern (100 events)", iterations, times)

        avg = statistics.mean(times)
        # Pattern detection is sync, should be fast
        assert avg < 1.0, f"Avg pattern detection too slow: {avg:.4f}ms"
        assert pattern is not None
        assert isinstance(pattern, FailurePattern)
        assert pattern.is_recurring is True

    def test_detect_pattern_no_history(self) -> None:
        """Measure _detect_pattern speed with no history (early return)."""
        svc = FailureRecoveryService()

        iterations = 10000
        times: list[float] = []

        pattern = None
        for _ in range(iterations):
            start = time.perf_counter()
            pattern = svc._detect_pattern("nonexistent:key")
            end = time.perf_counter()
            times.append((end - start) * 1000)

        _print_report("FailureRecovery._detect_pattern (empty)", iterations, times)

        avg = statistics.mean(times)
        assert avg < 0.01, f"Avg empty pattern detection too slow: {avg:.6f}ms"
        assert pattern is None

    def test_cleanup_old_failures_speed(self) -> None:
        """Measure _cleanup_old_failures speed."""
        svc = FailureRecoveryService(pattern_detection_window_minutes=60)

        instance_key = "tenant1:project1:default"
        now = datetime.now(UTC)
        # Mix old and recent failures
        svc._failure_history[instance_key] = [
            FailureEvent(
                event_id=f"evt-{i}",
                instance_key=instance_key,
                failure_type=FailureType.TIMEOUT,
                timestamp=now,
            )
            for i in range(500)
        ]

        iterations = 2000
        times: list[float] = []

        for _ in range(iterations):
            # Re-populate to ensure cleanup has work
            svc._failure_history[instance_key] = [
                FailureEvent(
                    event_id=f"evt-{i}",
                    instance_key=instance_key,
                    failure_type=FailureType.TIMEOUT,
                    timestamp=now,
                )
                for i in range(500)
            ]

            start = time.perf_counter()
            svc._cleanup_old_failures(instance_key)
            end = time.perf_counter()
            times.append((end - start) * 1000)

        _print_report("FailureRecovery._cleanup_old_failures (500 events)", iterations, times)

        avg = statistics.mean(times)
        assert avg < 2.0, f"Avg cleanup too slow: {avg:.4f}ms"


# =============================================================================
# d) State Recovery Checkpoint Serialization
# =============================================================================


@pytest.mark.performance
class TestStateRecoveryCheckpointSerialization:
    """Benchmark StateCheckpoint serialization and in-memory recovery."""

    def test_checkpoint_to_dict_speed(self) -> None:
        """Measure StateCheckpoint.to_dict() serialization speed."""
        checkpoint = StateCheckpoint(
            checkpoint_id="cp-test-001",
            instance_key="tenant1:project1:default",
            checkpoint_type=CheckpointType.FULL,
            state_data={
                "lifecycle": "ready",
                "conversations": [{"id": f"conv-{i}", "messages": i * 10} for i in range(20)],
                "tools": {"active": ["terminal", "web_search"], "pending": []},
                "resources": {"memory_mb": 256, "cpu_cores": 0.5},
            },
            metadata={"source": "benchmark", "version": "1.0"},
        )

        iterations = 10000
        times: list[float] = []

        for _ in range(iterations):
            start = time.perf_counter()
            _data = checkpoint.to_dict()
            end = time.perf_counter()
            times.append((end - start) * 1000)

        _print_report("StateCheckpoint.to_dict()", iterations, times)

        avg = statistics.mean(times)
        assert avg < 0.1, f"Avg to_dict too slow: {avg:.4f}ms"

    def test_checkpoint_from_dict_speed(self) -> None:
        """Measure StateCheckpoint.from_dict() deserialization speed."""
        checkpoint = StateCheckpoint(
            checkpoint_id="cp-test-001",
            instance_key="tenant1:project1:default",
            checkpoint_type=CheckpointType.FULL,
            state_data={
                "lifecycle": "ready",
                "conversations": [{"id": f"conv-{i}", "messages": i * 10} for i in range(20)],
                "tools": {"active": ["terminal", "web_search"], "pending": []},
            },
            metadata={"source": "benchmark"},
        )
        data = checkpoint.to_dict()

        iterations = 10000
        times: list[float] = []

        for _ in range(iterations):
            start = time.perf_counter()
            _cp = StateCheckpoint.from_dict(data)
            end = time.perf_counter()
            times.append((end - start) * 1000)

        _print_report("StateCheckpoint.from_dict()", iterations, times)

        avg = statistics.mean(times)
        assert avg < 0.1, f"Avg from_dict too slow: {avg:.4f}ms"

    def test_roundtrip_serialization(self) -> None:
        """Measure full to_dict -> from_dict roundtrip."""
        checkpoint = StateCheckpoint(
            checkpoint_id="cp-roundtrip",
            instance_key="tenant1:project1:default",
            checkpoint_type=CheckpointType.FULL,
            state_data={
                "key": "value",
                "nested": {"a": 1, "b": [1, 2, 3]},
                "large_list": list(range(100)),
            },
            metadata={"source": "roundtrip-test"},
        )

        iterations = 5000
        times: list[float] = []

        for _ in range(iterations):
            start = time.perf_counter()
            data = checkpoint.to_dict()
            _restored = StateCheckpoint.from_dict(data)
            end = time.perf_counter()
            times.append((end - start) * 1000)

        _print_report("StateCheckpoint roundtrip (to_dict + from_dict)", iterations, times)

        avg = statistics.mean(times)
        assert avg < 0.5, f"Avg roundtrip too slow: {avg:.4f}ms"

    async def test_create_checkpoint_in_memory_speed(self) -> None:
        """Measure create_checkpoint speed using in-memory storage."""
        svc = StateRecoveryService()  # No redis_url -> in-memory fallback
        await svc.start()

        iterations = 1000
        times: list[float] = []

        for i in range(iterations):
            start = time.perf_counter()
            _cp = await svc.create_checkpoint(
                instance_key="tenant1:project1:default",
                checkpoint_type=CheckpointType.FULL,
                state_data={"iteration": i, "status": "active"},
                metadata={"source": "benchmark"},
            )
            end = time.perf_counter()
            times.append((end - start) * 1000)

        await svc.stop()

        _print_report("StateRecoveryService.create_checkpoint (in-memory)", iterations, times)

        avg = statistics.mean(times)
        p99 = sorted(times)[int(len(times) * 0.99)]

        assert avg < 1.0, f"Avg create_checkpoint too slow: {avg:.4f}ms"
        assert p99 < 5.0, f"P99 create_checkpoint too slow: {p99:.4f}ms"

    async def test_recover_instance_in_memory_speed(self) -> None:
        """Measure recover_instance speed using in-memory storage."""
        svc = StateRecoveryService()
        await svc.start()

        # Pre-populate with checkpoints
        for i in range(10):
            await svc.create_checkpoint(
                instance_key="tenant1:project1:default",
                checkpoint_type=CheckpointType.FULL,
                state_data={"iteration": i, "status": "active"},
                metadata={"source": "setup"},
            )

        iterations = 1000
        times: list[float] = []
        result = None

        for _ in range(iterations):
            start = time.perf_counter()
            result = await svc.recover_instance("tenant1:project1:default")
            end = time.perf_counter()
            times.append((end - start) * 1000)

        await svc.stop()

        _print_report("StateRecoveryService.recover_instance (in-memory)", iterations, times)

        avg = statistics.mean(times)
        p99 = sorted(times)[int(len(times) * 0.99)]

        assert result is not None
        assert result.success is True
        assert result.recovered_state is not None
        assert avg < 2.0, f"Avg recover_instance too slow: {avg:.4f}ms"
        assert p99 < 10.0, f"P99 recover_instance too slow: {p99:.4f}ms"


# =============================================================================
# e) Auto-Scaler Decision Latency
# =============================================================================


@pytest.mark.performance
class TestAutoScalerDecisionLatency:
    """Benchmark auto-scaler decision computation."""

    def test_evaluate_scaling_with_scale_up(self) -> None:
        """Measure _evaluate_scaling computation time for scale-up scenarios."""
        policy = ScalingPolicy(evaluation_periods=3)
        svc = AutoScalingService(default_policy=policy)

        instance_key = "tenant1:project1:default"
        svc._current_counts[instance_key] = 3

        # Populate history with high CPU metrics (triggers scale-up)
        high_cpu_metrics = [
            ScalingMetrics(cpu_utilization=0.9, memory_utilization=0.5) for _ in range(5)
        ]
        svc._metrics_history[instance_key] = high_cpu_metrics

        iterations = 10000
        times: list[float] = []
        decision = None

        for _ in range(iterations):
            start = time.perf_counter()
            decision = svc._evaluate_scaling(
                instance_key,
                ScalingMetrics(cpu_utilization=0.9, memory_utilization=0.5),
            )
            end = time.perf_counter()
            times.append((end - start) * 1000)

        _print_report("AutoScaling._evaluate_scaling (scale-up)", iterations, times)

        avg = statistics.mean(times)
        p99 = sorted(times)[int(len(times) * 0.99)]

        assert decision is not None
        assert decision.direction == ScalingDirection.UP
        assert decision.reason == ScalingReason.HIGH_CPU
        assert avg < 0.1, f"Avg evaluate_scaling too slow: {avg:.4f}ms"
        assert p99 < 1.0, f"P99 evaluate_scaling too slow: {p99:.4f}ms"

    def test_evaluate_scaling_with_scale_down(self) -> None:
        """Measure _evaluate_scaling computation time for scale-down scenarios."""
        policy = ScalingPolicy(evaluation_periods=3)
        svc = AutoScalingService(default_policy=policy)

        instance_key = "tenant1:project1:default"
        svc._current_counts[instance_key] = 5

        # Populate history with low utilization metrics (triggers scale-down)
        low_metrics = [
            ScalingMetrics(
                cpu_utilization=0.1,
                memory_utilization=0.2,
                queue_depth=2,
                average_latency_ms=100,
            )
            for _ in range(5)
        ]
        svc._metrics_history[instance_key] = low_metrics

        iterations = 10000
        times: list[float] = []
        decision = None

        for _ in range(iterations):
            start = time.perf_counter()
            decision = svc._evaluate_scaling(
                instance_key,
                ScalingMetrics(
                    cpu_utilization=0.1,
                    memory_utilization=0.2,
                    queue_depth=2,
                    average_latency_ms=100,
                ),
            )
            end = time.perf_counter()
            times.append((end - start) * 1000)

        _print_report("AutoScaling._evaluate_scaling (scale-down)", iterations, times)

        avg = statistics.mean(times)

        assert decision is not None
        assert decision.direction == ScalingDirection.DOWN
        assert decision.reason == ScalingReason.LOW_UTILIZATION
        assert avg < 0.1, f"Avg evaluate_scaling too slow: {avg:.4f}ms"

    def test_evaluate_scaling_no_action(self) -> None:
        """Measure _evaluate_scaling when no scaling needed."""
        policy = ScalingPolicy(evaluation_periods=3)
        svc = AutoScalingService(default_policy=policy)

        instance_key = "tenant1:project1:default"
        svc._current_counts[instance_key] = 3

        # Normal metrics: not too high, not too low
        normal_metrics = [
            ScalingMetrics(
                cpu_utilization=0.5,
                memory_utilization=0.5,
                queue_depth=50,
                average_latency_ms=1000,
            )
            for _ in range(5)
        ]
        svc._metrics_history[instance_key] = normal_metrics

        iterations = 10000
        times: list[float] = []
        decision = None

        for _ in range(iterations):
            start = time.perf_counter()
            decision = svc._evaluate_scaling(
                instance_key,
                ScalingMetrics(
                    cpu_utilization=0.5,
                    memory_utilization=0.5,
                    queue_depth=50,
                    average_latency_ms=1000,
                ),
            )
            end = time.perf_counter()
            times.append((end - start) * 1000)

        _print_report("AutoScaling._evaluate_scaling (no action)", iterations, times)

        avg = statistics.mean(times)

        assert decision is None
        assert avg < 0.1, f"Avg evaluate_scaling too slow: {avg:.4f}ms"

    def test_evaluate_scaling_insufficient_data(self) -> None:
        """Measure _evaluate_scaling early return with insufficient data."""
        policy = ScalingPolicy(evaluation_periods=3)
        svc = AutoScalingService(default_policy=policy)

        instance_key = "tenant1:project1:default"
        # Only 1 data point, needs 3
        svc._metrics_history[instance_key] = [
            ScalingMetrics(cpu_utilization=0.9),
        ]

        iterations = 10000
        times: list[float] = []
        decision = None

        for _ in range(iterations):
            start = time.perf_counter()
            decision = svc._evaluate_scaling(
                instance_key,
                ScalingMetrics(cpu_utilization=0.9),
            )
            end = time.perf_counter()
            times.append((end - start) * 1000)

        _print_report("AutoScaling._evaluate_scaling (insufficient data)", iterations, times)

        avg = statistics.mean(times)

        assert decision is None
        assert avg < 0.01, f"Avg early-return too slow: {avg:.6f}ms"

    def test_check_scale_up_all_metrics(self) -> None:
        """Benchmark _check_scale_up across all metric types."""
        policy = ScalingPolicy(evaluation_periods=3)
        svc = AutoScalingService(default_policy=policy)

        instance_key = "tenant1:project1:default"
        svc._current_counts[instance_key] = 2
        now = datetime.now(UTC)

        scenarios = [
            ("high_cpu", ScalingMetrics(cpu_utilization=0.95)),
            ("high_memory", ScalingMetrics(memory_utilization=0.95)),
            ("high_queue", ScalingMetrics(queue_depth=200)),
            ("high_latency", ScalingMetrics(average_latency_ms=8000)),
        ]

        for scenario_name, metric in scenarios:
            svc._metrics_history[instance_key] = [metric] * 5
            svc._last_scale_up.pop(instance_key, None)

            times: list[float] = []
            iterations = 5000

            for _ in range(iterations):
                start = time.perf_counter()
                _decision = svc._check_scale_up(
                    instance_key,
                    policy,
                    svc._metrics_history[instance_key],
                    now,
                )
                end = time.perf_counter()
                times.append((end - start) * 1000)

            avg = statistics.mean(times)
            print(f"\n  _check_scale_up ({scenario_name}): avg={avg:.4f}ms")
            assert avg < 0.1, f"_check_scale_up ({scenario_name}) too slow: {avg:.4f}ms"
