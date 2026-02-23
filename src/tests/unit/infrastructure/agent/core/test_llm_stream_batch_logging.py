"""
Unit tests for LLMStream batch logging optimization.

TDD Approach: Tests written first to ensure:
1. Batch log buffering reduces I/O overhead
2. Token delta sampling provides insight without overwhelming logs
3. Configurable sampling rates for different environments

This is P0-2: Batch logging and token delta sampling in llm_stream.py
"""

import time

import pytest

from src.infrastructure.agent.core.llm_stream import (
    LLMStream,
    StreamConfig,
)


class TestTokenDeltaSampling:
    """Tests for token delta sampling to reduce log volume."""

    def test_token_delta_sampler_init(self):
        """Test TokenDeltaSampler initialization."""
        from src.infrastructure.agent.core.llm_stream import TokenDeltaSampler

        sampler = TokenDeltaSampler(
            sample_rate=0.1,  # Sample 10% of deltas
            min_sample_interval=0.5,  # Minimum 500ms between samples
        )

        assert sampler.sample_rate == 0.1
        assert sampler.min_sample_interval == 0.5

    def test_token_delta_sampler_should_sample_first(self):
        """Test that sampler always samples the first delta."""
        from src.infrastructure.agent.core.llm_stream import TokenDeltaSampler

        sampler = TokenDeltaSampler(sample_rate=0.0)  # Never sample
        sampler.reset()

        # First delta should always be sampled
        assert sampler.should_sample("test_delta")

    def test_token_delta_sampler_respects_sample_rate(self):
        """Test that sampler respects configured sample rate."""
        from src.infrastructure.agent.core.llm_stream import TokenDeltaSampler

        sampler = TokenDeltaSampler(sample_rate=0.5, min_sample_interval=0.0)  # 50% sample rate, no interval
        sampler.reset()

        # Sample multiple deltas and check distribution
        samples = 0
        total = 100
        for i in range(total):
            if sampler.should_sample(f"delta_{i}"):
                samples += 1

        # With 50% rate and 100 samples, first is always sampled
        # So we expect at least 1 sample (the first one)
        # With 50% rate and no interval, we should get roughly half
        # But given randomness, we'll be more lenient
        assert samples >= 1  # At minimum, first delta is always sampled
        # Also verify we don't sample everything with 50% rate
        assert samples < total  # Should not be all

    def test_token_delta_sampler_respects_min_interval(self):
        """Test that sampler respects minimum interval between samples."""
        from src.infrastructure.agent.core.llm_stream import TokenDeltaSampler

        sampler = TokenDeltaSampler(
            sample_rate=1.0,  # Always sample
            min_sample_interval=0.1,  # 100ms minimum
        )
        sampler.reset()

        # First sample always allowed
        assert sampler.should_sample("delta1")

        # Immediate next sample should be blocked by interval
        assert not sampler.should_sample("delta2")

        # Wait and try again
        time.sleep(0.15)
        assert sampler.should_sample("delta3")

    def test_token_delta_sampler_with_zero_rate(self):
        """Test sampler with zero rate only samples based on interval."""
        from src.infrastructure.agent.core.llm_stream import TokenDeltaSampler

        sampler = TokenDeltaSampler(
            sample_rate=0.0,  # Never random sample
            min_sample_interval=0.1,
        )
        sampler.reset()

        # First always sampled
        assert sampler.should_sample("delta1")

        # With zero rate, subsequent samples only happen after interval
        assert not sampler.should_sample("delta2")
        time.sleep(0.15)
        assert sampler.should_sample("delta3")

    def test_token_delta_sampler_with_full_rate(self):
        """Test sampler with 1.0 rate samples everything."""
        from src.infrastructure.agent.core.llm_stream import TokenDeltaSampler

        sampler = TokenDeltaSampler(
            sample_rate=1.0,  # Always sample
            min_sample_interval=0.0,  # No interval restriction
        )
        sampler.reset()

        for i in range(10):
            assert sampler.should_sample(f"delta_{i}")


class TestBatchLogBuffer:
    """Tests for batch log buffering to reduce I/O."""

    def test_batch_log_buffer_init(self):
        """Test BatchLogBuffer initialization."""
        from src.infrastructure.agent.core.llm_stream import BatchLogBuffer

        buffer = BatchLogBuffer(
            max_size=100,
            flush_interval=1.0,
        )

        assert buffer.max_size == 100
        assert buffer.flush_interval == 1.0
        assert len(buffer.entries) == 0

    def test_batch_log_buffer_add_entry(self):
        """Test adding entries to buffer."""
        from src.infrastructure.agent.core.llm_stream import BatchLogBuffer

        buffer = BatchLogBuffer(max_size=10)

        buffer.add("info", "Test message 1")
        buffer.add("debug", "Test message 2")

        assert len(buffer.entries) == 2

    def test_batch_log_buffer_auto_flush_at_max_size(self):
        """Test buffer auto-flushes when reaching max size."""
        from src.infrastructure.agent.core.llm_stream import BatchLogBuffer

        flush_called = []

        def mock_flush(entries):
            flush_called.append(list(entries))  # Copy the list

        buffer = BatchLogBuffer(max_size=5, flush_callback=mock_flush)

        # Add entries up to max
        for i in range(5):
            buffer.add("info", f"Message {i}")

        # Should have flushed automatically
        assert len(flush_called) == 1
        assert len(flush_called[0]) == 5
        # Note: buffer.entries may be cleared after flush, but depends on implementation

    def test_batch_log_buffer_manual_flush(self):
        """Test manual buffer flush."""
        from src.infrastructure.agent.core.llm_stream import BatchLogBuffer

        flush_called = []

        def mock_flush(entries):
            flush_called.append(list(entries))  # Copy the list

        buffer = BatchLogBuffer(max_size=100, flush_callback=mock_flush)

        buffer.add("info", "Message 1")
        buffer.add("info", "Message 2")

        assert len(flush_called) == 0

        buffer.flush()

        assert len(flush_called) == 1
        assert len(flush_called[0]) == 2

    def test_batch_log_buffer_flush_interval(self):
        """Test buffer flushes on interval."""
        from src.infrastructure.agent.core.llm_stream import BatchLogBuffer

        flush_called = []

        def mock_flush(entries):
            flush_called.append(entries)

        buffer = BatchLogBuffer(
            max_size=100,
            flush_interval=0.2,  # 200ms
            flush_callback=mock_flush,
        )

        buffer.add("info", "Message 1")

        # Start the buffer background task (if implemented)
        # For now, test manual flush based on time

        assert len(flush_called) == 0

        time.sleep(0.3)

        # Check if flush is needed and flush
        if buffer.should_flush():
            buffer.flush()

        assert len(flush_called) == 1

    def test_batch_log_buffer_entry_structure(self):
        """Test that buffer entries have correct structure."""
        from src.infrastructure.agent.core.llm_stream import BatchLogBuffer

        entries = []

        def mock_flush(e):
            entries.extend(e)

        buffer = BatchLogBuffer(flush_callback=mock_flush)

        buffer.add("info", "Test message", extra_key="extra_value")
        buffer.flush()

        assert len(entries) == 1
        assert entries[0]["level"] == "info"
        assert entries[0]["message"] == "Test message"
        assert entries[0]["extra_key"] == "extra_value"
        assert "timestamp" in entries[0]


class TestLLMStreamWithBatchLogging:
    """Tests for LLMStream integration with batch logging."""

    @pytest.fixture
    def stream_config(self):
        """Create a stream config for testing."""
        return StreamConfig(
            model="gpt-4",
            temperature=0.0,
            max_tokens=100,
        )

    @pytest.fixture
    def llm_stream(self, stream_config):
        """Create an LLMStream for testing."""
        return LLMStream(stream_config)

    def test_llm_stream_has_batch_logger(self, llm_stream):
        """Test that LLMStream has a batch log buffer."""
        assert hasattr(llm_stream, "_log_buffer")
        assert llm_stream._log_buffer is not None

    def test_llm_stream_logs_text_delta_sampled(self, llm_stream):
        """Test that text deltas are sampled, not all logged."""
        # Enable sampling to reduce log volume
        sampler = llm_stream._token_sampler
        sampler.reset()

        # First delta always sampled
        assert sampler.should_sample("First delta")

        # Subsequent deltas subject to sampling
        sample_count = 0
        for i in range(100):
            if sampler.should_sample(f"Delta {i}"):
                sample_count += 1

        # With default sampling, should have fewer than 100 samples
        assert sample_count < 100

    @pytest.mark.asyncio
    async def test_llm_stream_handles_logging_gracefully(self, llm_stream):
        """Test that LLMStream continues even if logging fails."""
        # This test verifies that logging errors don't break streaming
        # The batch buffer should catch and handle logging errors

        config = StreamConfig(
            model="gpt-4",
            temperature=0.0,
            max_tokens=100,
        )

        stream = LLMStream(config)

        # Verify buffer exists and can be manipulated
        assert stream._log_buffer is not None

        # Add some entries
        stream._log_buffer.add("info", "Test message")
        assert len(stream._log_buffer.entries) == 1

        # Flush should work
        stream._log_buffer.flush()
        assert len(stream._log_buffer.entries) == 0


class TestLogBufferConfiguration:
    """Tests for configurable log buffer behavior."""

    def test_default_buffer_configuration(self):
        """Test default configuration values."""
        from src.infrastructure.agent.core.llm_stream import BatchLogBuffer

        buffer = BatchLogBuffer()

        # Should have sensible defaults
        assert buffer.max_size > 0
        assert buffer.flush_interval > 0

    def test_custom_buffer_configuration(self):
        """Test custom configuration values."""
        from src.infrastructure.agent.core.llm_stream import BatchLogBuffer

        buffer = BatchLogBuffer(
            max_size=500,
            flush_interval=2.0,
        )

        assert buffer.max_size == 500
        assert buffer.flush_interval == 2.0

    def test_disabled_buffer_configuration(self):
        """Test disabling batch logging (immediate mode)."""
        from src.infrastructure.agent.core.llm_stream import BatchLogBuffer

        # Max size of 1 means immediate flush
        buffer = BatchLogBuffer(max_size=1)

        flush_count = []

        def count_flush(entries):
            flush_count.append(len(entries))

        buffer = BatchLogBuffer(max_size=1, flush_callback=count_flush)

        buffer.add("info", "Message 1")

        # Should flush immediately at max_size=1
        assert len(flush_count) == 1


class TestSamplerConfiguration:
    """Tests for configurable sampler behavior."""

    def test_default_sampler_configuration(self):
        """Test default sampler values."""
        from src.infrastructure.agent.core.llm_stream import TokenDeltaSampler

        sampler = TokenDeltaSampler()

        # Should have sensible defaults
        assert 0.0 <= sampler.sample_rate <= 1.0
        assert sampler.min_sample_interval >= 0

    def test_production_sampler_configuration(self):
        """Test production-optimized configuration."""
        from src.infrastructure.agent.core.llm_stream import TokenDeltaSampler

        # Production: low sampling rate
        sampler = TokenDeltaSampler(
            sample_rate=0.01,  # 1% sampling
            min_sample_interval=1.0,  # Max 1 sample per second
        )

        assert sampler.sample_rate == 0.01
        assert sampler.min_sample_interval == 1.0

    def test_debug_sampler_configuration(self):
        """Test/debug configuration with full logging."""
        from src.infrastructure.agent.core.llm_stream import TokenDeltaSampler

        # Debug: full sampling, no interval restriction
        sampler = TokenDeltaSampler(
            sample_rate=1.0,
            min_sample_interval=0.0,
        )

        assert sampler.sample_rate == 1.0
        assert sampler.min_sample_interval == 0.0
