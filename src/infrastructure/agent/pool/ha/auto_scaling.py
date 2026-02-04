"""
Dynamic Auto-Scaling Service.

Provides automatic scaling based on load metrics:
- CPU/Memory utilization
- Request queue depth
- Response latency
- Instance health

Scaling policies:
- Scale up when load exceeds threshold
- Scale down when resources underutilized
- Cooldown periods to prevent thrashing
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class ScalingDirection(str, Enum):
    """Scaling direction."""

    UP = "up"
    DOWN = "down"
    NONE = "none"


class ScalingReason(str, Enum):
    """Reason for scaling decision."""

    HIGH_CPU = "high_cpu"
    HIGH_MEMORY = "high_memory"
    HIGH_QUEUE_DEPTH = "high_queue_depth"
    HIGH_LATENCY = "high_latency"
    LOW_UTILIZATION = "low_utilization"
    HEALTH_ISSUES = "health_issues"
    SCHEDULED = "scheduled"
    MANUAL = "manual"


@dataclass
class ScalingPolicy:
    """Scaling policy configuration."""

    # Thresholds
    cpu_scale_up_threshold: float = 0.8  # 80%
    cpu_scale_down_threshold: float = 0.3  # 30%
    memory_scale_up_threshold: float = 0.85  # 85%
    memory_scale_down_threshold: float = 0.4  # 40%
    queue_depth_scale_up_threshold: int = 100
    queue_depth_scale_down_threshold: int = 10
    latency_scale_up_threshold_ms: float = 5000  # 5s
    latency_scale_down_threshold_ms: float = 500  # 500ms

    # Scaling behavior
    scale_up_increment: int = 1
    scale_down_increment: int = 1
    min_instances: int = 0
    max_instances: int = 10

    # Cooldown periods
    scale_up_cooldown_seconds: int = 60
    scale_down_cooldown_seconds: int = 300

    # Evaluation
    evaluation_periods: int = 3  # Number of periods to evaluate before scaling
    evaluation_interval_seconds: int = 30


@dataclass
class ScalingMetrics:
    """Metrics used for scaling decisions."""

    cpu_utilization: float = 0.0  # 0-1
    memory_utilization: float = 0.0  # 0-1
    queue_depth: int = 0
    average_latency_ms: float = 0.0
    active_requests: int = 0
    healthy_instances: int = 0
    total_instances: int = 0
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class ScalingEvent:
    """Scaling event record."""

    event_id: str
    instance_key: str
    direction: ScalingDirection
    reason: ScalingReason
    previous_count: int
    target_count: int
    metrics: ScalingMetrics
    timestamp: datetime = field(default_factory=datetime.utcnow)
    success: bool = False
    error_message: Optional[str] = None


@dataclass
class ScalingDecision:
    """Scaling decision."""

    direction: ScalingDirection
    reason: ScalingReason
    target_count: int
    metrics: ScalingMetrics
    confidence: float = 1.0  # 0-1, how confident in the decision


class AutoScalingService:
    """
    Dynamic auto-scaling service.

    Monitors metrics and automatically scales instances.
    """

    def __init__(
        self,
        pool_manager: Optional[Any] = None,
        default_policy: Optional[ScalingPolicy] = None,
    ):
        self._pool_manager = pool_manager
        self._default_policy = default_policy or ScalingPolicy()

        # Per-instance policies
        self._policies: Dict[str, ScalingPolicy] = {}

        # Metrics history for evaluation
        self._metrics_history: Dict[str, List[ScalingMetrics]] = {}

        # Scaling state
        self._last_scale_up: Dict[str, datetime] = {}
        self._last_scale_down: Dict[str, datetime] = {}
        self._current_counts: Dict[str, int] = {}

        # Events
        self._scaling_events: List[ScalingEvent] = []
        self._max_events = 1000

        # Callbacks
        self._on_scale_callbacks: List[Callable] = []

        # Control
        self._is_running = False
        self._monitor_task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        """Start auto-scaling service."""
        self._is_running = True
        self._monitor_task = asyncio.create_task(self._monitoring_loop())
        logger.info("Auto-Scaling Service started")

    async def stop(self) -> None:
        """Stop auto-scaling service."""
        self._is_running = False
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
        logger.info("Auto-Scaling Service stopped")

    def set_policy(
        self,
        instance_key: str,
        policy: ScalingPolicy,
    ) -> None:
        """Set scaling policy for an instance."""
        self._policies[instance_key] = policy
        logger.info(f"Scaling policy set for {instance_key}")

    def get_policy(self, instance_key: str) -> ScalingPolicy:
        """Get scaling policy for an instance."""
        return self._policies.get(instance_key, self._default_policy)

    async def report_metrics(
        self,
        instance_key: str,
        metrics: ScalingMetrics,
    ) -> Optional[ScalingDecision]:
        """
        Report metrics and get scaling decision.

        Args:
            instance_key: Instance to evaluate
            metrics: Current metrics

        Returns:
            Scaling decision if action needed
        """
        async with self._lock:
            # Store metrics
            if instance_key not in self._metrics_history:
                self._metrics_history[instance_key] = []
            self._metrics_history[instance_key].append(metrics)

            # Keep only recent history
            policy = self.get_policy(instance_key)
            max_history = policy.evaluation_periods * 2
            self._metrics_history[instance_key] = self._metrics_history[instance_key][
                -max_history:
            ]

            # Evaluate scaling
            decision = self._evaluate_scaling(instance_key, metrics)

            return decision

    async def scale(
        self,
        instance_key: str,
        direction: ScalingDirection,
        reason: ScalingReason = ScalingReason.MANUAL,
        target_count: Optional[int] = None,
    ) -> ScalingEvent:
        """
        Manually trigger scaling.

        Args:
            instance_key: Instance to scale
            direction: Scale up or down
            reason: Reason for scaling
            target_count: Optional specific target count

        Returns:
            Scaling event
        """
        policy = self.get_policy(instance_key)
        current = self._current_counts.get(instance_key, 1)

        if target_count is None:
            if direction == ScalingDirection.UP:
                target_count = min(
                    current + policy.scale_up_increment,
                    policy.max_instances,
                )
            elif direction == ScalingDirection.DOWN:
                target_count = max(
                    current - policy.scale_down_increment,
                    policy.min_instances,
                )
            else:
                target_count = current

        metrics = (
            self._metrics_history.get(instance_key, [ScalingMetrics()])[-1]
            if instance_key in self._metrics_history
            else ScalingMetrics()
        )

        event = ScalingEvent(
            event_id=f"scale:{instance_key}:{int(time.time() * 1000)}",
            instance_key=instance_key,
            direction=direction,
            reason=reason,
            previous_count=current,
            target_count=target_count,
            metrics=metrics,
        )

        try:
            await self._execute_scaling(instance_key, event)
            event.success = True
        except Exception as e:
            event.success = False
            event.error_message = str(e)
            logger.error(f"Scaling failed: {e}")

        self._record_event(event)
        return event

    async def get_scaling_history(
        self,
        instance_key: Optional[str] = None,
        limit: int = 100,
    ) -> List[ScalingEvent]:
        """Get scaling event history."""
        events = self._scaling_events
        if instance_key:
            events = [e for e in events if e.instance_key == instance_key]
        return list(reversed(events[-limit:]))

    async def get_scaling_stats(self) -> Dict[str, Any]:
        """Get scaling statistics."""
        scale_up_count = sum(
            1 for e in self._scaling_events if e.direction == ScalingDirection.UP
        )
        scale_down_count = sum(
            1 for e in self._scaling_events if e.direction == ScalingDirection.DOWN
        )
        success_count = sum(1 for e in self._scaling_events if e.success)

        by_reason: Dict[str, int] = {}
        for e in self._scaling_events:
            by_reason[e.reason.value] = by_reason.get(e.reason.value, 0) + 1

        return {
            "total_events": len(self._scaling_events),
            "scale_up_count": scale_up_count,
            "scale_down_count": scale_down_count,
            "success_count": success_count,
            "failure_count": len(self._scaling_events) - success_count,
            "by_reason": by_reason,
            "active_policies": len(self._policies),
        }

    def on_scale(self, callback: Callable) -> None:
        """Register scaling callback."""
        self._on_scale_callbacks.append(callback)

    # =========================================================================
    # Private Methods
    # =========================================================================

    async def _monitoring_loop(self) -> None:
        """Main monitoring loop."""
        while self._is_running:
            try:
                await asyncio.sleep(self._default_policy.evaluation_interval_seconds)

                # Evaluate all tracked instances
                for instance_key in list(self._metrics_history.keys()):
                    if not self._metrics_history.get(instance_key):
                        continue

                    metrics = self._metrics_history[instance_key][-1]
                    decision = self._evaluate_scaling(instance_key, metrics)

                    if decision and decision.direction != ScalingDirection.NONE:
                        await self.scale(
                            instance_key,
                            decision.direction,
                            decision.reason,
                            decision.target_count,
                        )

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Monitoring loop error: {e}")

    def _evaluate_scaling(
        self,
        instance_key: str,
        metrics: ScalingMetrics,
    ) -> Optional[ScalingDecision]:
        """Evaluate if scaling is needed."""
        policy = self.get_policy(instance_key)
        history = self._metrics_history.get(instance_key, [])

        if len(history) < policy.evaluation_periods:
            return None  # Not enough data

        # Check cooldowns
        now = datetime.utcnow()

        # Check scale up conditions
        scale_up_decision = self._check_scale_up(instance_key, policy, history, now)
        if scale_up_decision:
            return scale_up_decision

        # Check scale down conditions
        scale_down_decision = self._check_scale_down(instance_key, policy, history, now)
        if scale_down_decision:
            return scale_down_decision

        return None

    def _check_scale_up(
        self,
        instance_key: str,
        policy: ScalingPolicy,
        history: List[ScalingMetrics],
        now: datetime,
    ) -> Optional[ScalingDecision]:
        """Check if scale up is needed."""
        # Check cooldown
        last_up = self._last_scale_up.get(instance_key)
        if last_up:
            cooldown_end = last_up + timedelta(seconds=policy.scale_up_cooldown_seconds)
            if now < cooldown_end:
                return None

        current = self._current_counts.get(instance_key, 1)
        if current >= policy.max_instances:
            return None

        recent = history[-policy.evaluation_periods:]
        metrics = recent[-1]

        # Check CPU
        avg_cpu = sum(m.cpu_utilization for m in recent) / len(recent)
        if avg_cpu >= policy.cpu_scale_up_threshold:
            return ScalingDecision(
                direction=ScalingDirection.UP,
                reason=ScalingReason.HIGH_CPU,
                target_count=min(
                    current + policy.scale_up_increment,
                    policy.max_instances,
                ),
                metrics=metrics,
                confidence=min(avg_cpu / policy.cpu_scale_up_threshold, 1.0),
            )

        # Check memory
        avg_memory = sum(m.memory_utilization for m in recent) / len(recent)
        if avg_memory >= policy.memory_scale_up_threshold:
            return ScalingDecision(
                direction=ScalingDirection.UP,
                reason=ScalingReason.HIGH_MEMORY,
                target_count=min(
                    current + policy.scale_up_increment,
                    policy.max_instances,
                ),
                metrics=metrics,
                confidence=min(avg_memory / policy.memory_scale_up_threshold, 1.0),
            )

        # Check queue depth
        avg_queue = sum(m.queue_depth for m in recent) / len(recent)
        if avg_queue >= policy.queue_depth_scale_up_threshold:
            return ScalingDecision(
                direction=ScalingDirection.UP,
                reason=ScalingReason.HIGH_QUEUE_DEPTH,
                target_count=min(
                    current + policy.scale_up_increment,
                    policy.max_instances,
                ),
                metrics=metrics,
                confidence=min(avg_queue / policy.queue_depth_scale_up_threshold, 1.0),
            )

        # Check latency
        avg_latency = sum(m.average_latency_ms for m in recent) / len(recent)
        if avg_latency >= policy.latency_scale_up_threshold_ms:
            return ScalingDecision(
                direction=ScalingDirection.UP,
                reason=ScalingReason.HIGH_LATENCY,
                target_count=min(
                    current + policy.scale_up_increment,
                    policy.max_instances,
                ),
                metrics=metrics,
                confidence=min(
                    avg_latency / policy.latency_scale_up_threshold_ms, 1.0
                ),
            )

        return None

    def _check_scale_down(
        self,
        instance_key: str,
        policy: ScalingPolicy,
        history: List[ScalingMetrics],
        now: datetime,
    ) -> Optional[ScalingDecision]:
        """Check if scale down is needed."""
        # Check cooldown
        last_down = self._last_scale_down.get(instance_key)
        if last_down:
            cooldown_end = last_down + timedelta(
                seconds=policy.scale_down_cooldown_seconds
            )
            if now < cooldown_end:
                return None

        current = self._current_counts.get(instance_key, 1)
        if current <= policy.min_instances:
            return None

        recent = history[-policy.evaluation_periods:]
        metrics = recent[-1]

        # All metrics must be below threshold
        avg_cpu = sum(m.cpu_utilization for m in recent) / len(recent)
        avg_memory = sum(m.memory_utilization for m in recent) / len(recent)
        avg_queue = sum(m.queue_depth for m in recent) / len(recent)
        avg_latency = sum(m.average_latency_ms for m in recent) / len(recent)

        if (
            avg_cpu <= policy.cpu_scale_down_threshold
            and avg_memory <= policy.memory_scale_down_threshold
            and avg_queue <= policy.queue_depth_scale_down_threshold
            and avg_latency <= policy.latency_scale_down_threshold_ms
        ):
            return ScalingDecision(
                direction=ScalingDirection.DOWN,
                reason=ScalingReason.LOW_UTILIZATION,
                target_count=max(
                    current - policy.scale_down_increment,
                    policy.min_instances,
                ),
                metrics=metrics,
                confidence=1.0 - max(
                    avg_cpu / policy.cpu_scale_up_threshold,
                    avg_memory / policy.memory_scale_up_threshold,
                ),
            )

        return None

    async def _execute_scaling(
        self,
        instance_key: str,
        event: ScalingEvent,
    ) -> None:
        """Execute the scaling action."""
        logger.info(
            f"Executing scaling: {instance_key}, "
            f"direction={event.direction.value}, "
            f"target={event.target_count}"
        )

        # Update state
        if event.direction == ScalingDirection.UP:
            self._last_scale_up[instance_key] = datetime.utcnow()
        elif event.direction == ScalingDirection.DOWN:
            self._last_scale_down[instance_key] = datetime.utcnow()

        self._current_counts[instance_key] = event.target_count

        # Execute via pool manager if available
        # Note: Current architecture doesn't support replica count,
        # but this is prepared for future container-based scaling
        if self._pool_manager:
            # For now, just log - actual scaling will be implemented
            # when container backend supports replicas
            logger.info(
                f"Scaling {instance_key} to {event.target_count} instances "
                f"(reason: {event.reason.value})"
            )

        # Notify callbacks
        for callback in self._on_scale_callbacks:
            try:
                await callback(instance_key, event)
            except Exception as e:
                logger.error(f"Scale callback error: {e}")

    def _record_event(self, event: ScalingEvent) -> None:
        """Record scaling event."""
        self._scaling_events.append(event)
        # Trim history
        if len(self._scaling_events) > self._max_events:
            self._scaling_events = self._scaling_events[-self._max_events:]
