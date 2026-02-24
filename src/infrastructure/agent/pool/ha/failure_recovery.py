"""
Failure Recovery and Auto-Healing.

Provides automatic failure detection and recovery:
- Instance failure detection
- Automatic restart with state recovery
- Circuit breaker integration
- Failure pattern detection
- Alert generation

Recovery strategies:
- RESTART: Simple restart (stateless)
- RECOVER: Restart with state recovery
- MIGRATE: Move to different backend
- ESCALATE: Human intervention required
"""

import asyncio
import contextlib
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class FailureType(str, Enum):
    """Types of failures."""

    HEALTH_CHECK_FAILED = "health_check_failed"
    INITIALIZATION_FAILED = "initialization_failed"
    EXECUTION_ERROR = "execution_error"
    RESOURCE_EXHAUSTED = "resource_exhausted"
    TIMEOUT = "timeout"
    CONNECTION_LOST = "connection_lost"
    CONTAINER_CRASHED = "container_crashed"
    UNKNOWN = "unknown"


class RecoveryStrategy(str, Enum):
    """Recovery strategies."""

    RESTART = "restart"  # Simple restart
    RECOVER = "recover"  # Restart with state recovery
    MIGRATE = "migrate"  # Move to different backend/tier
    ESCALATE = "escalate"  # Human intervention


class RecoveryStatus(str, Enum):
    """Recovery operation status."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class FailureEvent:
    """Failure event record."""

    event_id: str
    instance_key: str
    failure_type: FailureType
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    error_message: str | None = None
    error_details: dict[str, Any] = field(default_factory=dict)
    recovery_attempted: bool = False
    recovery_strategy: RecoveryStrategy | None = None
    recovery_status: RecoveryStatus | None = None


@dataclass
class RecoveryAction:
    """Recovery action configuration."""

    failure_type: FailureType
    strategy: RecoveryStrategy
    max_retries: int = 3
    retry_delay_seconds: int = 5
    backoff_multiplier: float = 2.0
    max_delay_seconds: int = 300
    conditions: dict[str, Any] = field(default_factory=dict)


@dataclass
class FailurePattern:
    """Detected failure pattern."""

    pattern_id: str
    instance_key: str
    failure_types: list[FailureType]
    occurrence_count: int
    first_occurrence: datetime
    last_occurrence: datetime
    is_recurring: bool = False


class FailureRecoveryService:
    """
    Automatic failure recovery service.

    Detects failures and applies recovery strategies automatically.
    """

    def __init__(
        self,
        state_recovery_service: Any | None = None,
        pool_manager: Any | None = None,
        max_failures_per_hour: int = 10,
        pattern_detection_window_minutes: int = 60,
    ) -> None:
        self._state_recovery = state_recovery_service
        self._pool_manager = pool_manager
        self._max_failures_per_hour = max_failures_per_hour
        self._pattern_window = timedelta(minutes=pattern_detection_window_minutes)

        # Failure history
        self._failure_history: dict[str, list[FailureEvent]] = {}

        # Recovery actions configuration
        self._recovery_actions: dict[FailureType, RecoveryAction] = {
            FailureType.HEALTH_CHECK_FAILED: RecoveryAction(
                failure_type=FailureType.HEALTH_CHECK_FAILED,
                strategy=RecoveryStrategy.RESTART,
                max_retries=3,
                retry_delay_seconds=10,
            ),
            FailureType.INITIALIZATION_FAILED: RecoveryAction(
                failure_type=FailureType.INITIALIZATION_FAILED,
                strategy=RecoveryStrategy.RESTART,
                max_retries=2,
                retry_delay_seconds=30,
            ),
            FailureType.EXECUTION_ERROR: RecoveryAction(
                failure_type=FailureType.EXECUTION_ERROR,
                strategy=RecoveryStrategy.RECOVER,
                max_retries=2,
                retry_delay_seconds=5,
            ),
            FailureType.RESOURCE_EXHAUSTED: RecoveryAction(
                failure_type=FailureType.RESOURCE_EXHAUSTED,
                strategy=RecoveryStrategy.MIGRATE,
                max_retries=1,
                retry_delay_seconds=60,
            ),
            FailureType.TIMEOUT: RecoveryAction(
                failure_type=FailureType.TIMEOUT,
                strategy=RecoveryStrategy.RESTART,
                max_retries=2,
                retry_delay_seconds=10,
            ),
            FailureType.CONNECTION_LOST: RecoveryAction(
                failure_type=FailureType.CONNECTION_LOST,
                strategy=RecoveryStrategy.RESTART,
                max_retries=5,
                retry_delay_seconds=5,
            ),
            FailureType.CONTAINER_CRASHED: RecoveryAction(
                failure_type=FailureType.CONTAINER_CRASHED,
                strategy=RecoveryStrategy.RECOVER,
                max_retries=3,
                retry_delay_seconds=30,
            ),
            FailureType.UNKNOWN: RecoveryAction(
                failure_type=FailureType.UNKNOWN,
                strategy=RecoveryStrategy.ESCALATE,
                max_retries=1,
                retry_delay_seconds=60,
            ),
        }

        # Callbacks
        self._on_failure_callbacks: list[Callable[..., Any]] = []
        self._on_recovery_callbacks: list[Callable[..., Any]] = []
        self._on_escalation_callbacks: list[Callable[..., Any]] = []

        # Recovery state
        self._active_recoveries: dict[str, asyncio.Task[Any]] = {}
        self._recovery_attempts: dict[str, int] = {}

        self._is_running = False
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        """Start the failure recovery service."""
        self._is_running = True
        logger.info("Failure Recovery Service started")

    async def stop(self) -> None:
        """Stop the failure recovery service."""
        self._is_running = False

        # Cancel active recoveries
        for task in self._active_recoveries.values():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

        self._active_recoveries.clear()
        logger.info("Failure Recovery Service stopped")

    async def report_failure(
        self,
        instance_key: str,
        failure_type: FailureType,
        error_message: str | None = None,
        error_details: dict[str, Any] | None = None,
        auto_recover: bool = True,
    ) -> FailureEvent:
        """
        Report a failure and optionally trigger recovery.

        Args:
            instance_key: Failed instance
            failure_type: Type of failure
            error_message: Error message
            error_details: Additional details
            auto_recover: Whether to automatically attempt recovery

        Returns:
            Failure event
        """
        event = FailureEvent(
            event_id=f"{instance_key}:{failure_type.value}:{int(time.time() * 1000)}",
            instance_key=instance_key,
            failure_type=failure_type,
            error_message=error_message,
            error_details=error_details or {},
        )

        async with self._lock:
            # Record failure
            if instance_key not in self._failure_history:
                self._failure_history[instance_key] = []
            self._failure_history[instance_key].append(event)

            # Cleanup old failures
            self._cleanup_old_failures(instance_key)

            # Notify callbacks
            await self._notify_failure(event)

            # Check for patterns
            pattern = self._detect_pattern(instance_key)
            if pattern and pattern.is_recurring:
                logger.warning(
                    f"Recurring failure pattern detected: {instance_key}, "
                    f"count={pattern.occurrence_count}"
                )
                if pattern.occurrence_count >= self._max_failures_per_hour:
                    # Too many failures, escalate
                    await self._escalate(instance_key, event, "Too many failures")
                    return event

            # Attempt recovery
            if auto_recover:
                _recover_task = asyncio.create_task(self._attempt_recovery(event))
                self._background_tasks.add(_recover_task)  # type: ignore[attr-defined]
                _recover_task.add_done_callback(self._background_tasks.discard)  # type: ignore[attr-defined]

        return event

    async def get_failure_history(
        self,
        instance_key: str | None = None,
        limit: int = 100,
    ) -> list[FailureEvent]:
        """Get failure history."""
        if instance_key:
            return list(reversed(self._failure_history.get(instance_key, [])[-limit:]))

        # All failures, sorted by time
        all_failures = []
        for failures in self._failure_history.values():
            all_failures.extend(failures)
        return sorted(all_failures, key=lambda f: f.timestamp, reverse=True)[:limit]

    async def get_failure_stats(self) -> dict[str, Any]:
        """Get failure statistics."""
        total = 0
        by_type: dict[str, int] = {}
        by_instance: dict[str, int] = {}
        recovered = 0
        failed_recovery = 0

        for instance_key, failures in self._failure_history.items():
            total += len(failures)
            by_instance[instance_key] = len(failures)

            for f in failures:
                by_type[f.failure_type.value] = by_type.get(f.failure_type.value, 0) + 1
                if f.recovery_status == RecoveryStatus.SUCCESS:
                    recovered += 1
                elif f.recovery_status == RecoveryStatus.FAILED:
                    failed_recovery += 1

        return {
            "total_failures": total,
            "by_type": by_type,
            "by_instance": by_instance,
            "recovered": recovered,
            "failed_recovery": failed_recovery,
            "active_recoveries": len(self._active_recoveries),
        }

    def on_failure(self, callback: Callable[..., Any]) -> None:
        """Register failure callback."""
        self._on_failure_callbacks.append(callback)

    def on_recovery(self, callback: Callable[..., Any]) -> None:
        """Register recovery callback."""
        self._on_recovery_callbacks.append(callback)

    def on_escalation(self, callback: Callable[..., Any]) -> None:
        """Register escalation callback."""
        self._on_escalation_callbacks.append(callback)

    # =========================================================================
    # Private Methods
    # =========================================================================

    async def _attempt_recovery(self, event: FailureEvent) -> None:
        """Attempt to recover from failure."""
        instance_key = event.instance_key

        # Check if recovery already in progress
        if instance_key in self._active_recoveries:
            logger.debug(f"Recovery already in progress: {instance_key}")
            return

        # Get recovery action
        action = self._recovery_actions.get(
            event.failure_type,
            self._recovery_actions[FailureType.UNKNOWN],
        )

        # Check retry count
        attempts = self._recovery_attempts.get(instance_key, 0)
        if attempts >= action.max_retries:
            logger.warning(
                f"Max retries exceeded for {instance_key}: {attempts}/{action.max_retries}"
            )
            await self._escalate(instance_key, event, "Max retries exceeded")
            return

        # Start recovery
        event.recovery_attempted = True
        event.recovery_strategy = action.strategy
        event.recovery_status = RecoveryStatus.IN_PROGRESS

        task = asyncio.create_task(self._execute_recovery(instance_key, event, action))
        self._active_recoveries[instance_key] = task

    async def _execute_recovery(
        self,
        instance_key: str,
        event: FailureEvent,
        action: RecoveryAction,
    ) -> None:
        """Execute recovery action."""
        try:
            # Calculate delay with backoff
            attempts = self._recovery_attempts.get(instance_key, 0)
            delay = min(
                action.retry_delay_seconds * (action.backoff_multiplier**attempts),
                action.max_delay_seconds,
            )

            logger.info(
                f"Executing recovery for {instance_key}: "
                f"strategy={action.strategy.value}, attempt={attempts + 1}, delay={delay}s"
            )

            await asyncio.sleep(delay)

            # Execute based on strategy
            if action.strategy == RecoveryStrategy.RESTART:
                await self._recovery_restart(instance_key)
            elif action.strategy == RecoveryStrategy.RECOVER:
                await self._recovery_with_state(instance_key)
            elif action.strategy == RecoveryStrategy.MIGRATE:
                await self._recovery_migrate(instance_key)
            elif action.strategy == RecoveryStrategy.ESCALATE:
                await self._escalate(instance_key, event, "Manual intervention required")
                return

            # Recovery successful
            event.recovery_status = RecoveryStatus.SUCCESS
            self._recovery_attempts[instance_key] = 0  # Reset counter
            await self._notify_recovery(instance_key, event)
            logger.info(f"Recovery successful: {instance_key}")

        except Exception as e:
            logger.error(f"Recovery failed for {instance_key}: {e}")
            event.recovery_status = RecoveryStatus.FAILED
            self._recovery_attempts[instance_key] = attempts + 1

            # Retry if possible
            if self._recovery_attempts[instance_key] < action.max_retries:
                _retry_task = asyncio.create_task(self._attempt_recovery(event))
                self._background_tasks.add(_retry_task)  # type: ignore[attr-defined]
                _retry_task.add_done_callback(self._background_tasks.discard)  # type: ignore[attr-defined]
            else:
                await self._escalate(instance_key, event, str(e))

        finally:
            self._active_recoveries.pop(instance_key, None)

    async def _recovery_restart(self, instance_key: str) -> None:
        """Simple restart recovery."""
        if self._pool_manager:
            # Terminate and recreate
            await self._pool_manager.terminate_instance(instance_key, graceful=False)
            # Instance will be recreated on next request
            logger.info(f"Instance terminated for restart: {instance_key}")

    async def _recovery_with_state(self, instance_key: str) -> None:
        """Restart with state recovery."""
        # Recover state first
        if self._state_recovery:
            result = await self._state_recovery.recover_instance(instance_key)
            if not result.success:
                logger.warning(f"State recovery failed: {result.error_message}")

        # Then restart
        await self._recovery_restart(instance_key)

    async def _recovery_migrate(self, instance_key: str) -> None:
        """Migrate to different backend."""
        if self._pool_manager:
            # Get current tier
            parts = instance_key.split(":")
            if len(parts) >= 2:
                tenant_id, project_id = parts[0], parts[1]
                # Downgrade tier (e.g., HOT -> WARM, WARM -> COLD)
                from ..types import ProjectTier

                await self._pool_manager.set_project_tier(
                    tenant_id=tenant_id,
                    project_id=project_id,
                    tier=ProjectTier.COLD,
                )
                logger.info(f"Migrated to COLD tier: {instance_key}")

        # Then restart
        await self._recovery_restart(instance_key)

    async def _escalate(
        self,
        instance_key: str,
        event: FailureEvent,
        reason: str,
    ) -> None:
        """Escalate to human intervention."""
        logger.error(
            f"ESCALATION REQUIRED: {instance_key}, reason={reason}, "
            f"failure_type={event.failure_type.value}"
        )
        event.recovery_status = RecoveryStatus.FAILED

        # Notify escalation callbacks
        for callback in self._on_escalation_callbacks:
            try:
                await callback(instance_key, event, reason)
            except Exception as e:
                logger.error(f"Escalation callback error: {e}")

    async def _notify_failure(self, event: FailureEvent) -> None:
        """Notify failure callbacks."""
        for callback in self._on_failure_callbacks:
            try:
                await callback(event)
            except Exception as e:
                logger.error(f"Failure callback error: {e}")

    async def _notify_recovery(
        self,
        instance_key: str,
        event: FailureEvent,
    ) -> None:
        """Notify recovery callbacks."""
        for callback in self._on_recovery_callbacks:
            try:
                await callback(instance_key, event)
            except Exception as e:
                logger.error(f"Recovery callback error: {e}")

    def _cleanup_old_failures(self, instance_key: str) -> None:
        """Cleanup failures older than pattern window."""
        if instance_key not in self._failure_history:
            return

        cutoff = datetime.now(UTC) - self._pattern_window
        self._failure_history[instance_key] = [
            f for f in self._failure_history[instance_key] if f.timestamp > cutoff
        ]

    def _detect_pattern(self, instance_key: str) -> FailurePattern | None:
        """Detect failure patterns."""
        failures = self._failure_history.get(instance_key, [])
        if len(failures) < 3:
            return None

        # Count by type
        types = [f.failure_type for f in failures]
        is_recurring = len(failures) >= 3

        return FailurePattern(
            pattern_id=f"pattern:{instance_key}:{int(time.time())}",
            instance_key=instance_key,
            failure_types=list(set(types)),
            occurrence_count=len(failures),
            first_occurrence=failures[0].timestamp,
            last_occurrence=failures[-1].timestamp,
            is_recurring=is_recurring,
        )
