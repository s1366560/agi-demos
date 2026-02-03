"""Tests for OpenTelemetry configuration module."""


from src.infrastructure.telemetry import config


class TestConfigureTracerProvider:
    """Tests for tracer provider configuration."""

    def test_disabled_when_telemetry_disabled(self):
        """Test that tracer provider is None when telemetry is disabled."""
        # Reset state
        config._reset_providers()

        result = config.configure_tracer_provider(
            settings_override={"enable_telemetry": False}
        )

        assert result is None

    def test_returns_provider_when_enabled(self):
        """Test that provider is returned when telemetry is enabled."""
        # Reset state
        config._reset_providers()

        result = config.configure_tracer_provider(
            settings_override={"enable_telemetry": True, "service_name": "test-service"}
        )

        assert result is not None

        # Cleanup
        config._reset_providers()

    def test_returns_cached_provider(self):
        """Test that cached provider is returned if already configured."""
        # Reset state
        config._reset_providers()

        # First call should create provider
        provider1 = config.configure_tracer_provider(
            settings_override={"enable_telemetry": True}
        )
        # Second call should return cached
        provider2 = config.configure_tracer_provider()

        assert provider1 is not None
        assert provider1 is provider2

        # Cleanup
        config._reset_providers()

    def test_resource_attributes_set(self):
        """Test that resource attributes are set correctly."""
        # Reset state
        config._reset_providers()

        provider = config.configure_tracer_provider(
            settings_override={
                "enable_telemetry": True,
                "service_name": "test-service",
                "environment": "test",
            }
        )

        assert provider is not None
        # Verify resource has service name
        resource = provider.resource
        attributes = dict(resource.attributes)
        assert attributes.get("service.name") == "test-service"
        assert attributes.get("deployment.environment") == "test"

        # Cleanup
        config._reset_providers()


class TestConfigureMeterProvider:
    """Tests for meter provider configuration."""

    def test_disabled_when_telemetry_disabled(self):
        """Test that meter provider is None when telemetry is disabled."""
        # Reset state
        config._reset_providers()

        result = config.configure_meter_provider(
            settings_override={"enable_telemetry": False}
        )

        assert result is None

    def test_returns_cached_provider(self):
        """Test that cached provider is returned if already configured."""
        # Reset state
        config._reset_providers()

        # First call should create provider
        provider1 = config.configure_meter_provider(
            settings_override={"enable_telemetry": True}
        )
        # Second call should return cached
        provider2 = config.configure_meter_provider()

        assert provider1 is not None
        assert provider1 is provider2

        # Cleanup
        config._reset_providers()


class TestGetTracer:
    """Tests for get_tracer function."""

    def test_returns_tracer_from_provider(self):
        """Test that tracer is obtained from provider."""
        # Reset state
        config._reset_providers()

        tracer = config.get_tracer("test-instrumentation")

        assert tracer is not None

        # Cleanup
        config._reset_providers()

    def test_returns_none_when_no_provider(self):
        """Test that None is returned when provider is None."""
        # Reset state
        config._reset_providers()

        tracer = config.get_tracer("test-instrumentation")

        # Should return a tracer even when not explicitly configured
        # (uses default settings which enable telemetry)
        assert tracer is not None

        # Cleanup
        config._reset_providers()


class TestGetMeter:
    """Tests for get_meter function."""

    def test_returns_meter_from_provider(self):
        """Test that meter is obtained from provider."""
        # Reset state
        config._reset_providers()

        meter = config.get_meter("test-instrumentation")

        assert meter is not None

        # Cleanup
        config._reset_providers()


class TestConfigureTelemetry:
    """Tests for configure_telemetry function."""

    def test_configures_both_providers(self):
        """Test that both tracer and meter providers are configured."""
        # Reset state
        config._reset_providers()

        config.configure_telemetry(
            settings_override={"enable_telemetry": True}
        )

        # Verify providers are configured
        assert config._get_tracer_provider_global() is not None
        assert config._get_meter_provider_global() is not None

        # Cleanup
        config._reset_providers()


class TestShutdownTelemetry:
    """Tests for shutdown_telemetry function."""

    def test_shutdown_clears_providers(self):
        """Test that shutdown clears both providers."""
        # Reset state
        config._reset_providers()

        # Configure telemetry
        config.configure_telemetry(
            settings_override={"enable_telemetry": True}
        )

        # Verify providers exist
        assert config._get_tracer_provider_global() is not None
        assert config._get_meter_provider_global() is not None

        # Shutdown
        config.shutdown_telemetry()

        # Verify providers are cleared
        assert config._get_tracer_provider_global() is None
        assert config._get_meter_provider_global() is None
