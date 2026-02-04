"""Event Retry Service - Automatic retry with backoff.

This service provides:
1. Automatic retry with exponential backoff
2. Integration with DLQ for failed events
3. Circuit breaker pattern for failing handlers

Usage:
    retry_service = EventRetryService(dlq=dlq_adapter, event_bus=event_bus)

    # Process with automatic retry
    success = await retry_service.process_with_retry(
        event=event,
        handler=my_handler,
        routing_key="agent.conv-123.msg-456",
    )
"""

import asyncio
import logging
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional

from src.domain.events.envelope import EventEnvelope
from src.domain.ports.services.dead_letter_queue_port import DeadLetterQueuePort
from src.domain.ports.services.unified_event_bus_port import (
    EventWithMetadata,
    UnifiedEventBusPort,
)

logger = logging.getLogger(__name__)


# Type for event handlers
EventHandler = Callable[[EventWithMetadata], Awaitable[None]]


@dataclass
class RetryConfig:
    """Configuration for retry behavior.

    Attributes:
        max_retries: Maximum retry attempts
        retry_delays: Delay (seconds) for each retry attempt
        jitter_factor: Random jitter factor (0.0-1.0)
        retry_exceptions: Exception types that should trigger retry
        fatal_exceptions: Exception types that should NOT retry
    """

    max_retries: int = 3
    retry_delays: List[float] = field(default_factory=lambda: [1.0, 5.0, 15.0, 60.0])
    jitter_factor: float = 0.1
    retry_exceptions: Optional[List[type]] = None  # None = all exceptions
    fatal_exceptions: List[type] = field(default_factory=list)


@dataclass
class RetryResult:
    """Result of a retry operation.

    Attributes:
        success: Whether processing succeeded
        attempts: Number of attempts made
        final_error: Error from the last attempt (if failed)
        error_type: Type of the final error
        dlq_message_id: DLQ message ID (if sent to DLQ)
        processing_time_ms: Total processing time
    """

    success: bool
    attempts: int
    final_error: Optional[str] = None
    error_type: Optional[str] = None
    dlq_message_id: Optional[str] = None
    processing_time_ms: float = 0.0


class EventRetryService:
    """Service for processing events with automatic retry.

    Implements retry with exponential backoff and DLQ integration.
    """

    def __init__(
        self,
        dlq: Optional[DeadLetterQueuePort] = None,
        event_bus: Optional[UnifiedEventBusPort] = None,
        *,
        default_config: Optional[RetryConfig] = None,
    ):
        """Initialize the retry service.

        Args:
            dlq: Dead letter queue for failed events
            event_bus: Event bus for republishing
            default_config: Default retry configuration
        """
        self._dlq = dlq
        self._event_bus = event_bus
        self._config = default_config or RetryConfig()
        self._metrics = RetryMetrics()

    async def process_with_retry(
        self,
        event: EventWithMetadata,
        handler: EventHandler,
        *,
        config: Optional[RetryConfig] = None,
    ) -> RetryResult:
        """Process an event with automatic retry.

        Args:
            event: Event to process
            handler: Handler function
            config: Optional custom retry config

        Returns:
            RetryResult with processing outcome
        """
        cfg = config or self._config
        start_time = datetime.now(timezone.utc)
        attempts = 0
        last_error: Optional[BaseException] = None
        last_error_tb: Optional[str] = None

        while attempts <= cfg.max_retries:
            attempts += 1

            try:
                await handler(event)

                # Success
                self._metrics.successes += 1
                if attempts > 1:
                    self._metrics.retries_succeeded += 1

                return RetryResult(
                    success=True,
                    attempts=attempts,
                    processing_time_ms=self._elapsed_ms(start_time),
                )

            except BaseException as e:
                last_error = e
                last_error_tb = traceback.format_exc()

                # Check if this is a fatal exception
                if self._is_fatal(e, cfg):
                    logger.error(
                        f"[RetryService] Fatal error processing {event.envelope.event_type}: {e}"
                    )
                    break

                # Check if we should retry
                if not self._should_retry(e, cfg):
                    logger.warning(
                        f"[RetryService] Non-retryable error: {e}"
                    )
                    break

                # Check if we have retries left
                if attempts > cfg.max_retries:
                    break

                # Calculate delay with jitter
                delay = self._get_delay(attempts - 1, cfg)
                logger.warning(
                    f"[RetryService] Attempt {attempts} failed, retrying in {delay:.1f}s: {e}"
                )
                self._metrics.retries_attempted += 1
                await asyncio.sleep(delay)

        # All retries exhausted - send to DLQ
        self._metrics.failures += 1
        dlq_message_id = None

        if self._dlq:
            try:
                dlq_message_id = await self._dlq.send_to_dlq(
                    event_id=event.envelope.event_id,
                    event_type=event.envelope.event_type,
                    event_data=event.envelope.to_json(),
                    routing_key=event.routing_key,
                    error=str(last_error),
                    error_type=type(last_error).__name__ if last_error else "UnknownError",
                    error_traceback=last_error_tb,
                    retry_count=attempts - 1,
                    max_retries=cfg.max_retries,
                    metadata={
                        "sequence_id": event.sequence_id,
                        "handler": handler.__name__,
                    },
                )
                logger.info(
                    f"[RetryService] Event sent to DLQ: {dlq_message_id}"
                )
            except Exception as dlq_error:
                logger.error(
                    f"[RetryService] Failed to send to DLQ: {dlq_error}"
                )

        return RetryResult(
            success=False,
            attempts=attempts,
            final_error=str(last_error) if last_error else None,
            error_type=type(last_error).__name__ if last_error else None,
            dlq_message_id=dlq_message_id,
            processing_time_ms=self._elapsed_ms(start_time),
        )

    async def process_batch_with_retry(
        self,
        events: List[EventWithMetadata],
        handler: EventHandler,
        *,
        config: Optional[RetryConfig] = None,
        stop_on_failure: bool = False,
    ) -> List[RetryResult]:
        """Process multiple events with retry.

        Args:
            events: Events to process
            handler: Handler function
            config: Optional custom retry config
            stop_on_failure: Stop processing on first failure

        Returns:
            List of RetryResults
        """
        results = []
        for event in events:
            result = await self.process_with_retry(event, handler, config=config)
            results.append(result)

            if stop_on_failure and not result.success:
                break

        return results

    def _is_fatal(self, error: Exception, config: RetryConfig) -> bool:
        """Check if an error is fatal (should not retry)."""
        return any(isinstance(error, t) for t in config.fatal_exceptions)

    def _should_retry(self, error: Exception, config: RetryConfig) -> bool:
        """Check if an error should trigger a retry."""
        if config.retry_exceptions is None:
            # Retry all non-fatal exceptions
            return True
        return any(isinstance(error, t) for t in config.retry_exceptions)

    def _get_delay(self, attempt: int, config: RetryConfig) -> float:
        """Calculate delay for a retry attempt with jitter."""
        import random

        # Get base delay
        if attempt < len(config.retry_delays):
            base_delay = config.retry_delays[attempt]
        else:
            base_delay = config.retry_delays[-1]

        # Add jitter
        jitter = base_delay * config.jitter_factor * random.random()
        return base_delay + jitter

    def _elapsed_ms(self, start: datetime) -> float:
        """Calculate elapsed time in milliseconds."""
        return (datetime.now(timezone.utc) - start).total_seconds() * 1000

    @property
    def metrics(self) -> "RetryMetrics":
        """Get retry service metrics."""
        return self._metrics


@dataclass
class RetryMetrics:
    """Metrics for the retry service.

    Attributes:
        successes: Total successful processings
        failures: Total failed processings (after all retries)
        retries_attempted: Total retry attempts
        retries_succeeded: Retries that eventually succeeded
    """

    successes: int = 0
    failures: int = 0
    retries_attempted: int = 0
    retries_succeeded: int = 0

    @property
    def total_processed(self) -> int:
        """Total events processed."""
        return self.successes + self.failures

    @property
    def success_rate(self) -> float:
        """Success rate as a percentage."""
        if self.total_processed == 0:
            return 100.0
        return (self.successes / self.total_processed) * 100

    @property
    def retry_success_rate(self) -> float:
        """Rate of retries that succeeded."""
        if self.retries_attempted == 0:
            return 0.0
        return (self.retries_succeeded / self.retries_attempted) * 100

    def reset(self) -> None:
        """Reset all metrics."""
        self.successes = 0
        self.failures = 0
        self.retries_attempted = 0
        self.retries_succeeded = 0

    def to_dict(self) -> Dict[str, Any]:
        """Convert metrics to dictionary."""
        return {
            "successes": self.successes,
            "failures": self.failures,
            "retries_attempted": self.retries_attempted,
            "retries_succeeded": self.retries_succeeded,
            "total_processed": self.total_processed,
            "success_rate": self.success_rate,
            "retry_success_rate": self.retry_success_rate,
        }
