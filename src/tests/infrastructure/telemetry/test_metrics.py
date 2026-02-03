"""Tests for OpenTelemetry metrics utilities."""


from src.infrastructure.telemetry import config, metrics


class TestCreateCounter:
    """Tests for create_counter function."""

    def test_creates_counter(self):
        """Test that counter is created."""
        # Reset state
        config._reset_providers()

        counter = metrics.create_counter("test.counter", "Test counter description")

        assert counter is not None

        # Cleanup
        config._reset_providers()

    def test_returns_none_when_no_meter(self):
        """Test that None is returned when meter is None."""
        # This test verifies that create_counter handles None meter gracefully
        # Since global meter provider might be set by other tests, we just
        # verify the function doesn't crash
        # Reset state
        config.shutdown_telemetry()

        # Configure with disabled telemetry
        result = config.configure_meter_provider(
            settings_override={"enable_telemetry": False}, force_reset=True
        )

        assert result is None

        # Even with disabled telemetry, create_counter should not crash
        # It will return None because get_meter returns None
        counter = metrics.create_counter("test.counter", "Test counter")

        # Counter should be None when telemetry is disabled
        assert counter is None

        # Cleanup
        config.shutdown_telemetry()


class TestCreateHistogram:
    """Tests for create_histogram function."""

    def test_creates_histogram(self):
        """Test that histogram is created."""
        # Reset state
        config._reset_providers()

        histogram = metrics.create_histogram("test.duration", "Duration metric")

        assert histogram is not None

        # Cleanup
        config._reset_providers()


class TestCreateGauge:
    """Tests for create_gauge function."""

    def test_creates_observable_gauge(self):
        """Test that observable gauge is created."""
        # Reset state
        config._reset_providers()

        def callback(options):
            from opentelemetry.metrics import Observation
            return Observation(42, {})

        gauge = metrics.create_gauge("test.gauge", "Gauge metric", [callback])

        assert gauge is not None

        # Cleanup
        config.shutdown_telemetry()


class TestIncrementCounter:
    """Tests for increment_counter function."""

    def test_increments_counter(self):
        """Test that counter increment doesn't crash."""
        # Reset state
        config._reset_providers()

        # Should not raise
        metrics.increment_counter("test.counter", "Test counter")

        # Cleanup
        config._reset_providers()

    def test_increments_counter_with_attributes(self):
        """Test that counter increment with attributes doesn't crash."""
        # Reset state
        config._reset_providers()

        # Should not raise
        metrics.increment_counter(
            "test.counter", "Test counter", attributes={"status": "success"}
        )

        # Cleanup
        config._reset_providers()


class TestRecordHistogramValue:
    """Tests for record_histogram_value function."""

    def test_records_value(self):
        """Test that recording value doesn't crash."""
        # Reset state
        config._reset_providers()

        # Should not raise
        metrics.record_histogram_value("test.duration", "Duration metric", 123.45)

        # Cleanup
        config._reset_providers()

    def test_records_value_with_attributes(self):
        """Test that recording value with attributes doesn't crash."""
        # Reset state
        config._reset_providers()

        # Should not raise
        metrics.record_histogram_value(
            "test.duration", "Duration metric", 123.45, attributes={"endpoint": "/api/test"}
        )

        # Cleanup
        config._reset_providers()


class TestSetGauge:
    """Tests for set_gauge function."""

    def test_sets_gauge_value(self):
        """Test that setting gauge value doesn't crash."""
        # Reset state
        config._reset_providers()

        # Should not raise
        metrics.set_gauge("test.gauge", "Gauge metric", 42)

        # Cleanup
        config.shutdown_telemetry()


class TestGetMeter:
    """Tests for get_meter function."""

    def test_returns_meter(self):
        """Test that meter is returned."""
        # Reset state
        config._reset_providers()

        meter = metrics.get_meter()

        assert meter is not None

        # Cleanup
        config._reset_providers()
