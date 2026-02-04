"""Tests for Dead Letter Queue and Retry Service.

Tests the DLQ port, message handling, and retry service.
"""

import asyncio
import pytest
from datetime import datetime, timezone
from typing import List
from unittest.mock import AsyncMock, MagicMock

from src.domain.events.envelope import EventEnvelope
from src.domain.events.types import AgentEventType
from src.domain.ports.services.dead_letter_queue_port import (
    DeadLetterMessage,
    DLQMessageStatus,
    DLQStats,
)
from src.domain.ports.services.unified_event_bus_port import EventWithMetadata
from src.application.services.event_retry_service import (
    EventRetryService,
    RetryConfig,
    RetryMetrics,
    RetryResult,
)


class TestDeadLetterMessage:
    """Tests for DeadLetterMessage."""

    def test_create_message(self):
        """Test basic message creation."""
        message = DeadLetterMessage(
            event_id="evt_123",
            event_type="thought",
            event_data='{"content": "test"}',
            routing_key="agent.conv-123.msg-456",
            error="Processing failed",
            error_type="ValueError",
        )

        assert message.event_id == "evt_123"
        assert message.event_type == "thought"
        assert message.status == DLQMessageStatus.PENDING
        assert message.retry_count == 0
        assert message.id.startswith("dlq_")

    def test_can_retry(self):
        """Test can_retry property."""
        message = DeadLetterMessage(
            event_id="evt_123",
            event_type="thought",
            event_data="{}",
            routing_key="agent.conv-123.msg-456",
            error="error",
            error_type="Error",
            retry_count=2,
            max_retries=3,
        )

        assert message.can_retry is True

        # Exhausted retries
        message.retry_count = 3
        # Note: DeadLetterMessage is not frozen, so we can mutate for testing
        assert DeadLetterMessage(
            event_id="evt_123",
            event_type="thought",
            event_data="{}",
            routing_key="agent.conv-123.msg-456",
            error="error",
            error_type="Error",
            retry_count=3,
            max_retries=3,
        ).can_retry is False

    def test_to_dict_and_back(self):
        """Test serialization round-trip."""
        original = DeadLetterMessage(
            event_id="evt_123",
            event_type="thought",
            event_data='{"content": "test"}',
            routing_key="agent.conv-123.msg-456",
            error="Processing failed",
            error_type="ValueError",
            metadata={"consumer": "worker-1"},
        )

        data = original.to_dict()
        restored = DeadLetterMessage.from_dict(data)

        assert restored.event_id == original.event_id
        assert restored.event_type == original.event_type
        assert restored.routing_key == original.routing_key
        assert restored.error == original.error
        assert restored.metadata == original.metadata


class TestDLQStats:
    """Tests for DLQStats."""

    def test_create_stats(self):
        """Test stats creation."""
        stats = DLQStats(
            total_messages=100,
            pending_count=50,
            discarded_count=30,
            resolved_count=20,
        )

        assert stats.total_messages == 100
        assert stats.pending_count == 50

    def test_to_dict(self):
        """Test stats to dict."""
        stats = DLQStats(
            total_messages=100,
            pending_count=50,
            error_type_counts={"ValueError": 30, "TypeError": 20},
        )

        data = stats.to_dict()

        assert data["total_messages"] == 100
        assert data["error_type_counts"]["ValueError"] == 30


class TestRetryConfig:
    """Tests for RetryConfig."""

    def test_default_config(self):
        """Test default retry configuration."""
        config = RetryConfig()

        assert config.max_retries == 3
        assert len(config.retry_delays) == 4
        assert config.jitter_factor == 0.1

    def test_custom_config(self):
        """Test custom retry configuration."""
        config = RetryConfig(
            max_retries=5,
            retry_delays=[0.5, 1.0, 2.0],
            fatal_exceptions=[SystemExit],
        )

        assert config.max_retries == 5
        assert len(config.fatal_exceptions) == 1


class TestRetryMetrics:
    """Tests for RetryMetrics."""

    def test_success_rate(self):
        """Test success rate calculation."""
        metrics = RetryMetrics(successes=80, failures=20)

        assert metrics.total_processed == 100
        assert metrics.success_rate == 80.0

    def test_success_rate_zero_processed(self):
        """Test success rate with no events processed."""
        metrics = RetryMetrics()

        assert metrics.total_processed == 0
        assert metrics.success_rate == 100.0  # Default to 100% when no events

    def test_retry_success_rate(self):
        """Test retry success rate calculation."""
        metrics = RetryMetrics(retries_attempted=10, retries_succeeded=7)

        assert metrics.retry_success_rate == 70.0

    def test_reset(self):
        """Test metrics reset."""
        metrics = RetryMetrics(successes=100, failures=50)
        metrics.reset()

        assert metrics.successes == 0
        assert metrics.failures == 0


class TestEventRetryService:
    """Tests for EventRetryService."""

    @pytest.fixture
    def sample_event(self):
        """Create a sample event for testing."""
        envelope = EventEnvelope.wrap(
            event_type=AgentEventType.THOUGHT,
            payload={"content": "test thought"},
        )
        return EventWithMetadata(
            envelope=envelope,
            routing_key="agent.conv-123.msg-456",
            sequence_id="1234567890-0",
        )

    @pytest.fixture
    def mock_dlq(self):
        """Create a mock DLQ."""
        dlq = AsyncMock()
        dlq.send_to_dlq.return_value = "dlq_test123"
        return dlq

    @pytest.mark.asyncio
    async def test_process_success(self, sample_event):
        """Test successful processing."""
        service = EventRetryService()

        async def handler(event):
            pass  # Success

        result = await service.process_with_retry(sample_event, handler)

        assert result.success is True
        assert result.attempts == 1
        assert result.final_error is None
        assert service.metrics.successes == 1

    @pytest.mark.asyncio
    async def test_process_failure_exhausted_retries(self, sample_event, mock_dlq):
        """Test processing failure after exhausting retries."""
        config = RetryConfig(max_retries=2, retry_delays=[0.01, 0.02])
        service = EventRetryService(dlq=mock_dlq, default_config=config)

        async def failing_handler(event):
            raise ValueError("Always fails")

        result = await service.process_with_retry(sample_event, failing_handler)

        assert result.success is False
        assert result.attempts == 3  # 1 initial + 2 retries
        assert result.error_type == "ValueError"
        assert result.dlq_message_id == "dlq_test123"
        assert service.metrics.failures == 1

        # Verify DLQ was called
        mock_dlq.send_to_dlq.assert_called_once()

    @pytest.mark.asyncio
    async def test_process_retry_then_success(self, sample_event):
        """Test processing that fails then succeeds on retry."""
        config = RetryConfig(max_retries=3, retry_delays=[0.01, 0.02, 0.03])
        service = EventRetryService(default_config=config)

        call_count = 0

        async def flaky_handler(event):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("Temporary failure")
            # Success on third attempt

        result = await service.process_with_retry(sample_event, flaky_handler)

        assert result.success is True
        assert result.attempts == 3
        assert service.metrics.successes == 1
        assert service.metrics.retries_succeeded == 1

    @pytest.mark.asyncio
    async def test_process_fatal_exception(self, sample_event, mock_dlq):
        """Test processing with fatal exception (no retry)."""
        config = RetryConfig(
            max_retries=3,
            retry_delays=[0.01],
            fatal_exceptions=[SystemExit],
        )
        service = EventRetryService(dlq=mock_dlq, default_config=config)

        async def fatal_handler(event):
            raise SystemExit("Fatal error")

        result = await service.process_with_retry(sample_event, fatal_handler)

        assert result.success is False
        assert result.attempts == 1  # No retries for fatal exceptions

    @pytest.mark.asyncio
    async def test_process_batch(self, sample_event):
        """Test batch processing."""
        service = EventRetryService()
        events = [sample_event, sample_event, sample_event]
        call_count = 0

        async def handler(event):
            nonlocal call_count
            call_count += 1

        results = await service.process_batch_with_retry(events, handler)

        assert len(results) == 3
        assert all(r.success for r in results)
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_process_batch_stop_on_failure(self, sample_event, mock_dlq):
        """Test batch processing stops on failure."""
        config = RetryConfig(max_retries=0, retry_delays=[])
        service = EventRetryService(dlq=mock_dlq, default_config=config)
        events = [sample_event, sample_event, sample_event]

        async def failing_handler(event):
            raise ValueError("Fail")

        results = await service.process_batch_with_retry(
            events, failing_handler, stop_on_failure=True
        )

        # Should stop after first failure
        assert len(results) == 1
        assert results[0].success is False


class TestRetryResult:
    """Tests for RetryResult."""

    def test_success_result(self):
        """Test successful result."""
        result = RetryResult(success=True, attempts=1, processing_time_ms=100.5)

        assert result.success is True
        assert result.attempts == 1
        assert result.final_error is None

    def test_failure_result(self):
        """Test failure result."""
        result = RetryResult(
            success=False,
            attempts=4,
            final_error="Connection timeout",
            error_type="ConnectionError",
            dlq_message_id="dlq_abc123",
        )

        assert result.success is False
        assert result.final_error == "Connection timeout"
        assert result.dlq_message_id == "dlq_abc123"
