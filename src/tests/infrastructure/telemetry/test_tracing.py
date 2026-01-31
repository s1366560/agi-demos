"""Tests for OpenTelemetry tracing utilities."""

import pytest

from src.infrastructure.telemetry import config, tracing


class TestGetCurrentSpan:
    """Tests for get_current_span function."""

    def test_returns_span(self):
        """Test that a span is returned."""
        # Reset state
        config._reset_providers()

        span = tracing.get_current_span()

        assert span is not None
        # Should return NonRecordingSpan when no active span
        from opentelemetry.trace import NonRecordingSpan
        assert isinstance(span, NonRecordingSpan)

        # Cleanup
        config._reset_providers()


class TestGetTraceId:
    """Tests for get_trace_id function."""

    def test_returns_none_when_no_span(self):
        """Test that None is returned when there is no current span."""
        # Reset state
        config._reset_providers()

        result = tracing.get_trace_id()

        # No active span, should return None
        assert result is None

        # Cleanup
        config._reset_providers()


class TestWithTracer:
    """Tests for with_tracer decorator."""

    def test_decorates_sync_function(self):
        """Test that sync function is decorated correctly."""
        # Reset state
        config._reset_providers()

        @tracing.with_tracer("test-component")
        def test_function(arg1, arg2):
            return arg1 + arg2

        result = test_function(1, 2)

        assert result == 3

        # Cleanup
        config._reset_providers()

    def test_function_works_without_telemetry(self):
        """Test that function works when telemetry is disabled."""
        # Reset state and disable telemetry
        config._reset_providers()

        @tracing.with_tracer("test-component")
        def test_function(arg1, arg2):
            return arg1 + arg2

        result = test_function(1, 2)

        assert result == 3

        # Cleanup
        config._reset_providers()

    def test_handles_exception_in_sync_function(self):
        """Test that exception is propagated correctly."""
        # Reset state
        config._reset_providers()

        @tracing.with_tracer("test-component")
        def test_function():
            raise ValueError("Test error")

        with pytest.raises(ValueError, match="Test error"):
            test_function()

        # Cleanup
        config._reset_providers()


class TestAsyncWithTracer:
    """Tests for async_with_tracer decorator."""

    @pytest.mark.asyncio
    async def test_decorates_async_function(self):
        """Test that async function is decorated correctly."""
        # Reset state
        config._reset_providers()

        @tracing.async_with_tracer("test-component")
        async def test_function(arg1, arg2):
            return arg1 + arg2

        result = await test_function(1, 2)

        assert result == 3

        # Cleanup
        config._reset_providers()

    @pytest.mark.asyncio
    async def test_handles_exception_in_async_function(self):
        """Test that exception is propagated correctly in async function."""
        # Reset state
        config._reset_providers()

        @tracing.async_with_tracer("test-component")
        async def test_function():
            raise ValueError("Test error")

        with pytest.raises(ValueError, match="Test error"):
            await test_function()

        # Cleanup
        config._reset_providers()


class TestAddSpanAttributes:
    """Tests for add_span_attributes function."""

    def test_does_not_crash(self):
        """Test that adding attributes doesn't crash."""
        # Reset state
        config._reset_providers()

        # Should not raise even without active span
        tracing.add_span_attributes({"key1": "value1", "key2": 42})

        # Cleanup
        config._reset_providers()


class TestAddSpanEvent:
    """Tests for add_span_event function."""

    def test_does_not_crash(self):
        """Test that adding event doesn't crash."""
        # Reset state
        config._reset_providers()

        # Should not raise even without active span
        tracing.add_span_event("test-event", {"attr1": "value1"})

        # Cleanup
        config._reset_providers()


class TestSetSpanError:
    """Tests for set_span_error function."""

    def test_does_not_crash(self):
        """Test that setting error doesn't crash."""
        # Reset state
        config._reset_providers()

        # Should not raise even without active span
        tracing.set_span_error(ValueError("Test error"))

        # Cleanup
        config._reset_providers()
