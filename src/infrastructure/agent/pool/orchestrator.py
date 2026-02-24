"""
Pool Orchestrator - Unified management of all pool services.

Coordinates:
- AgentPoolManager: Instance lifecycle management
- HealthMonitor: Health checking
- FailureRecoveryService: Automatic failure recovery
- AutoScalingService: Dynamic scaling
- StateRecoveryService: State persistence
- PoolMetricsCollector: Metrics collection
- AlertService: Critical event notifications

Usage:
    orchestrator = PoolOrchestrator(config)
    await orchestrator.start()

    # Get instance
    instance = await orchestrator.get_instance(tenant_id, project_id)

    # Graceful shutdown
    await orchestrator.stop()
"""

import asyncio
import contextlib
import logging
from dataclasses import dataclass, field
from typing import Any

from src.domain.ports.services.alert_service_port import (
    Alert,
    AlertServicePort,
    AlertSeverity,
    NullAlertService,
)

from .config import PoolConfig
from .ha import (
    AutoScalingService,
    FailureRecoveryService,
    FailureType,
    ScalingMetrics,
    ScalingPolicy,
    StateRecoveryService,
)
from .health import HealthMonitor, HealthMonitorConfig
from .instance import AgentInstance
from .manager import AgentPoolManager
from .metrics import PoolMetricsCollector, get_metrics_collector
from .types import HealthStatus, ProjectTier

logger = logging.getLogger(__name__)


@dataclass
class OrchestratorConfig:
    """Configuration for Pool Orchestrator."""

    # Pool configuration
    pool_config: PoolConfig = field(default_factory=PoolConfig)

    # Feature flags
    enable_health_monitor: bool = True
    enable_failure_recovery: bool = True
    enable_auto_scaling: bool = False  # Disabled by default
    enable_state_recovery: bool = True
    enable_metrics: bool = True

    # Health monitor settings
    health_check_interval_seconds: int = 30
    health_check_timeout_seconds: int = 10

    # State recovery settings
    redis_url: str | None = None
    checkpoint_interval_seconds: int = 60
    checkpoint_ttl_seconds: int = 86400  # 24 hours

    # Failure recovery settings
    max_failures_per_hour: int = 10
    pattern_detection_window_minutes: int = 60

    # Auto scaling settings
    scaling_policy: ScalingPolicy | None = None
    scaling_evaluation_interval_seconds: int = 30


class PoolOrchestrator:
    """
    Unified orchestrator for all pool services.

    Manages the lifecycle of pool components and coordinates
    between them for seamless operation.
    """

    def __init__(self, config: OrchestratorConfig | None = None) -> None:
        self.config = config or OrchestratorConfig()

        # Core services
        self._pool_manager: AgentPoolManager | None = None
        self._health_monitor: HealthMonitor | None = None
        self._failure_recovery: FailureRecoveryService | None = None
        self._auto_scaling: AutoScalingService | None = None
        self._state_recovery: StateRecoveryService | None = None
        self._metrics_collector: PoolMetricsCollector | None = None
        self._alert_service: AlertServicePort = NullAlertService()

        # State
        self._is_running = False
        self._background_tasks: list[asyncio.Task[Any]] = []
        self._lock = asyncio.Lock()

    @property
    def is_running(self) -> bool:
        """Check if orchestrator is running."""
        return self._is_running

    @property
    def pool_manager(self) -> AgentPoolManager | None:
        """Get pool manager instance."""
        return self._pool_manager

    async def start(self) -> None:
        """Start all pool services."""
        if self._is_running:
            logger.warning("Orchestrator already running")
            return

        logger.info("Starting Pool Orchestrator...")

        try:
            # 1. Initialize metrics collector first
            if self.config.enable_metrics:
                self._metrics_collector = get_metrics_collector("agent_pool")
                logger.info("Metrics collector initialized")

            # 2. Initialize state recovery (needed for recovery on startup)
            if self.config.enable_state_recovery:
                self._state_recovery = StateRecoveryService(
                    redis_url=self.config.redis_url,
                    checkpoint_ttl_seconds=self.config.checkpoint_ttl_seconds,
                )
                await self._state_recovery.start()
                logger.info("State recovery service started")

            # 3. Initialize pool manager
            self._pool_manager = AgentPoolManager(config=self.config.pool_config)
            await self._pool_manager.start()
            logger.info("Pool manager started")

            # 4. Recover instances from checkpoints
            if self._state_recovery:
                await self._recover_instances()

            # 5. Initialize health monitor
            if self.config.enable_health_monitor:
                self._health_monitor = HealthMonitor(
                    config=HealthMonitorConfig(
                        check_interval_seconds=self.config.health_check_interval_seconds,
                        check_timeout_seconds=self.config.health_check_timeout_seconds,
                    )
                )
                # Note: HealthMonitor doesn't support callbacks yet
                # Health changes will be monitored through get_health_state
                logger.info("Health monitor initialized")

            # 6. Initialize failure recovery
            if self.config.enable_failure_recovery:
                self._failure_recovery = FailureRecoveryService(
                    state_recovery_service=self._state_recovery,
                    pool_manager=self._pool_manager,
                    max_failures_per_hour=self.config.max_failures_per_hour,
                    pattern_detection_window_minutes=self.config.pattern_detection_window_minutes,
                )
                self._failure_recovery.on_failure(self._on_failure)
                self._failure_recovery.on_recovery(self._on_recovery)
                self._failure_recovery.on_escalation(self._on_escalation)
                await self._failure_recovery.start()
                logger.info("Failure recovery service started")

            # 7. Initialize auto scaling
            if self.config.enable_auto_scaling:
                self._auto_scaling = AutoScalingService(
                    pool_manager=self._pool_manager,
                    default_policy=self.config.scaling_policy or ScalingPolicy(),
                )
                self._auto_scaling.on_scale(self._on_scale)
                await self._auto_scaling.start()
                logger.info("Auto scaling service started")

            # 8. Start background tasks
            if self.config.enable_state_recovery:
                task = asyncio.create_task(self._checkpoint_loop())
                self._background_tasks.append(task)

            if self.config.enable_auto_scaling:
                task = asyncio.create_task(self._scaling_metrics_loop())
                self._background_tasks.append(task)

            self._is_running = True
            logger.info("Pool Orchestrator started successfully")

        except Exception as e:
            logger.error(f"Failed to start orchestrator: {e}")
            await self.stop()
            raise

    async def stop(self) -> None:
        """Stop all pool services gracefully."""
        if not self._is_running:
            return

        logger.info("Stopping Pool Orchestrator...")
        self._is_running = False

        # Cancel background tasks
        for task in self._background_tasks:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._background_tasks.clear()

        # Stop services in reverse order
        if self._auto_scaling:
            await self._auto_scaling.stop()
            logger.info("Auto scaling service stopped")

        if self._failure_recovery:
            await self._failure_recovery.stop()
            logger.info("Failure recovery service stopped")

        if self._health_monitor:
            await self._health_monitor.stop_all_monitoring()
            logger.info("Health monitor stopped")

        # Checkpoint all instances before shutdown
        if self._state_recovery and self._pool_manager:
            await self._checkpoint_all_instances()

        if self._pool_manager:
            await self._pool_manager.stop()
            logger.info("Pool manager stopped")

        if self._state_recovery:
            await self._state_recovery.stop()
            logger.info("State recovery service stopped")

        logger.info("Pool Orchestrator stopped")

    async def get_instance(
        self,
        tenant_id: str,
        project_id: str,
        agent_mode: str = "default",
    ) -> AgentInstance:
        """
        Get or create an agent instance.

        Args:
            tenant_id: Tenant identifier
            project_id: Project identifier
            agent_mode: Agent mode

        Returns:
            AgentInstance ready for use
        """
        if not self._pool_manager:
            raise RuntimeError("Orchestrator not started")

        instance = await self._pool_manager.get_or_create_instance(
            tenant_id=tenant_id,
            project_id=project_id,
            agent_mode=agent_mode,
        )

        # Register with health monitor
        if self._health_monitor:
            await self._health_monitor.register_instance(instance)  # type: ignore[attr-defined]

        return instance

    async def terminate_instance(
        self,
        instance_key: str,
        graceful: bool = True,
    ) -> bool:
        """Terminate an instance."""
        if not self._pool_manager:
            return False

        # Checkpoint before termination
        if self._state_recovery and graceful:
            from .ha import CheckpointType

            await self._state_recovery.create_checkpoint(
                instance_key=instance_key,
                checkpoint_type=CheckpointType.FULL,
                state_data={"reason": "termination"},
            )

        # Unregister from health monitor
        if self._health_monitor:
            await self._health_monitor.unregister_instance(instance_key)  # type: ignore[attr-defined]

        parts = instance_key.split(":")
        tenant_id_part = parts[0] if len(parts) > 0 else ""
        project_id_part = parts[1] if len(parts) > 1 else ""
        agent_mode_part = parts[2] if len(parts) > 2 else "default"
        return await self._pool_manager.terminate_instance(
            tenant_id=tenant_id_part,
            project_id=project_id_part,
            agent_mode=agent_mode_part,
            graceful=graceful,
        )

    def set_alert_service(self, alert_service: AlertServicePort) -> None:
        """Set the alert service for notifications.

        Args:
            alert_service: Alert service implementation (Slack, Email, etc.)
        """
        self._alert_service = alert_service
        logger.info("Alert service configured for pool orchestrator")

    async def set_project_tier(
        self,
        tenant_id: str,
        project_id: str,
        tier: ProjectTier,
    ) -> None:
        """Set project tier."""
        if self._pool_manager:
            await self._pool_manager.set_project_tier(tenant_id, project_id, tier)

    async def pause_instance(self, instance_key: str) -> bool:
        """Pause an instance."""
        if not self._pool_manager:
            return False

        instance = self._pool_manager._instances.get(instance_key)
        if instance:
            await instance.pause()
            return True
        return False

    async def resume_instance(self, instance_key: str) -> bool:
        """Resume a paused instance."""
        if not self._pool_manager:
            return False

        instance = self._pool_manager._instances.get(instance_key)
        if instance:
            await instance.resume()
            return True
        return False

    async def get_status(self) -> dict[str, Any]:
        """Get orchestrator status."""
        status = {
            "running": self._is_running,
            "services": {
                "pool_manager": self._pool_manager is not None,
                "health_monitor": self._health_monitor is not None,
                "failure_recovery": self._failure_recovery is not None,
                "auto_scaling": self._auto_scaling is not None,
                "state_recovery": self._state_recovery is not None,
                "metrics_collector": self._metrics_collector is not None,
            },
            "config": {
                "enable_health_monitor": self.config.enable_health_monitor,
                "enable_failure_recovery": self.config.enable_failure_recovery,
                "enable_auto_scaling": self.config.enable_auto_scaling,
                "enable_state_recovery": self.config.enable_state_recovery,
                "enable_metrics": self.config.enable_metrics,
            },
        }

        # Add pool stats
        if self._pool_manager:
            stats = self._pool_manager.get_stats()
            status["pool_stats"] = (
                stats.to_dict()
                if hasattr(stats, "to_dict")
                else {
                    "total_instances": stats.total_instances,
                    "active_requests": stats.active_requests,
                }
            )

        # Add failure stats
        if self._failure_recovery:
            status["failure_stats"] = await self._failure_recovery.get_failure_stats()

        # Add scaling stats
        if self._auto_scaling:
            status["scaling_stats"] = await self._auto_scaling.get_scaling_stats()

        # Add checkpoint stats
        if self._state_recovery:
            status["checkpoint_stats"] = await self._state_recovery.get_checkpoint_stats()

        return status

    # =========================================================================
    # Callback Handlers
    # =========================================================================

    async def _on_health_change(
        self,
        instance_key: str,
        old_status: HealthStatus,
        new_status: HealthStatus,
    ) -> None:
        """Handle health status change."""
        logger.info(f"Health change: {instance_key} {old_status.value} -> {new_status.value}")

        # Record metrics using the collector's built-in methods
        if self._metrics_collector:
            self._metrics_collector.record_health_check(new_status)

        # Report unhealthy as failure
        if new_status == HealthStatus.UNHEALTHY and self._failure_recovery:
            await self._failure_recovery.report_failure(
                instance_key=instance_key,
                failure_type=FailureType.HEALTH_CHECK_FAILED,
                error_message=f"Health status changed to {new_status.value}",
            )

    async def _on_failure(self, event: Any) -> None:
        """Handle failure event."""
        logger.warning(f"Failure detected: {event.instance_key} - {event.failure_type}")
        # Metrics tracked via record_recovery_attempt

    async def _on_recovery(self, instance_key: str, event: Any) -> None:
        """Handle recovery success."""
        logger.info(f"Recovery successful: {instance_key}")

        if self._metrics_collector:
            self._metrics_collector.record_recovery_attempt(success=True)

    async def _on_escalation(
        self,
        instance_key: str,
        event: Any,
        reason: str,
    ) -> None:
        """Handle escalation (human intervention needed)."""
        logger.error(f"ESCALATION: {instance_key} - {reason}")

        if self._metrics_collector:
            self._metrics_collector.record_recovery_attempt(success=False)

        # Send alert notification
        try:
            alert = Alert(
                title=f"Agent Pool Escalation: {instance_key}",
                message=f"Human intervention required. Reason: {reason}",
                severity=AlertSeverity.CRITICAL,
                source="agent_pool_orchestrator",
                metadata={
                    "instance_key": instance_key,
                    "event_type": type(event).__name__ if event else "unknown",
                    "reason": reason,
                },
            )
            await self._alert_service.send_alert(alert)
        except Exception as e:
            logger.error(f"Failed to send escalation alert: {e}")

    async def _on_scale(self, instance_key: str, event: Any) -> None:
        """Handle scaling event."""
        logger.info(
            f"Scaling: {instance_key} {event.direction.value} "
            f"from {event.previous_count} to {event.target_count}"
        )

        if self._metrics_collector:
            self._metrics_collector.counter_increment(  # type: ignore[attr-defined]
                "scaling_events_total",
                labels={"direction": event.direction.value},
            )

    # =========================================================================
    # Background Tasks
    # =========================================================================

    async def _checkpoint_loop(self) -> None:
        """Periodically checkpoint instance state."""
        while self._is_running:
            try:
                await asyncio.sleep(self.config.checkpoint_interval_seconds)
                await self._checkpoint_all_instances()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Checkpoint loop error: {e}")

    async def _checkpoint_all_instances(self) -> None:
        """Checkpoint all active instances."""
        if not self._pool_manager or not self._state_recovery:
            return

        from .ha import CheckpointType

        for instance_key, instance in self._pool_manager._instances.items():
            try:
                await self._state_recovery.create_checkpoint(
                    instance_key=instance_key,
                    checkpoint_type=CheckpointType.LIFECYCLE,
                    state_data={
                        "status": instance.status.value,
                        "request_count": instance._metrics.request_count,  # type: ignore[attr-defined]
                        "tier": instance.config.tier.value if instance.config.tier else "unknown",
                    },
                )
            except Exception as e:
                logger.error(f"Failed to checkpoint {instance_key}: {e}")

    async def _scaling_metrics_loop(self) -> None:
        """Periodically report metrics for auto-scaling decisions."""
        while self._is_running:
            try:
                await asyncio.sleep(self.config.scaling_evaluation_interval_seconds)
                await self._report_scaling_metrics()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Scaling metrics loop error: {e}")

    async def _report_scaling_metrics(self) -> None:
        """Report metrics to auto-scaling service."""
        if not self._pool_manager or not self._auto_scaling:
            return

        for instance_key, instance in self._pool_manager._instances.items():
            try:
                metrics = ScalingMetrics(
                    cpu_utilization=instance._metrics.cpu_percent / 100.0,  # type: ignore[attr-defined]
                    memory_utilization=instance._metrics.memory_used_mb / 2048.0,  # Assume 2GB max
                    queue_depth=instance._pending_requests,  # type: ignore[attr-defined]
                    average_latency_ms=instance._metrics.average_latency_ms,  # type: ignore[attr-defined]
                    active_requests=instance._active_requests,
                    healthy_instances=1 if instance.status.value == "ready" else 0,
                    total_instances=1,
                )
                await self._auto_scaling.report_metrics(instance_key, metrics)
            except Exception as e:
                logger.error(f"Failed to report metrics for {instance_key}: {e}")

    async def _recover_instances(self) -> None:
        """Recover instances from checkpoints on startup."""
        if not self._state_recovery:
            return

        logger.info("Recovering instances from checkpoints...")
        results = await self._state_recovery.recover_all_instances()

        recovered = sum(1 for r in results if r.success)
        failed = len(results) - recovered

        logger.info(f"Recovery complete: {recovered} recovered, {failed} failed")

        # Note: Custom metric for recovered instances not in default collector
        # Could add to collector if needed


# =============================================================================
# Factory Function
# =============================================================================


def create_orchestrator(
    pool_config: PoolConfig | None = None,
    redis_url: str | None = None,
    enable_ha: bool = True,
    enable_scaling: bool = False,
) -> PoolOrchestrator:
    """
    Create a configured pool orchestrator.

    Args:
        pool_config: Pool configuration
        redis_url: Redis URL for state persistence
        enable_ha: Enable high availability features
        enable_scaling: Enable auto-scaling

    Returns:
        Configured PoolOrchestrator
    """
    config = OrchestratorConfig(
        pool_config=pool_config or PoolConfig(),
        redis_url=redis_url,
        enable_health_monitor=enable_ha,
        enable_failure_recovery=enable_ha,
        enable_state_recovery=enable_ha,
        enable_auto_scaling=enable_scaling,
    )
    return PoolOrchestrator(config)


# Global orchestrator instance
_global_orchestrator: PoolOrchestrator | None = None


async def get_global_orchestrator() -> PoolOrchestrator:
    """Get global orchestrator instance."""
    global _global_orchestrator
    if _global_orchestrator is None:
        _global_orchestrator = create_orchestrator()
    return _global_orchestrator


async def shutdown_global_orchestrator() -> None:
    """Shutdown global orchestrator."""
    global _global_orchestrator
    if _global_orchestrator:
        await _global_orchestrator.stop()
        _global_orchestrator = None
