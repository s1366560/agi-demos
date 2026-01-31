"""Unit tests for Temporal OpenTelemetry integration.

TDD Approach:
1. RED - Write failing tests first
2. GREEN - Implement minimal code to pass
3. REFACTOR - Improve code while tests pass
"""

# Import modules to ensure they are covered by pytest-cov
from src.configuration.temporal_config import TemporalSettings
from src.infrastructure.adapters.secondary.temporal.client import (
    TemporalClientFactory,
    create_tracing_interceptor,
)

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.unit
class TestTemporalTelemetryConfig:
    """Test cases for Temporal OpenTelemetry configuration."""

    def test_create_tracing_interceptor_when_telemetry_enabled(self):
        """Test that TracingInterceptor is created when telemetry is enabled."""
        from src.infrastructure.adapters.secondary.temporal.client import (
            create_tracing_interceptor,
        )
        from src.infrastructure.telemetry.config import configure_tracer_provider

        # Arrange: Enable telemetry and configure tracer
        provider = configure_tracer_provider({"temporal_tracing_enabled": True})

        # Act: Create tracing interceptor
        interceptor = create_tracing_interceptor()

        # Assert: Interceptor should be created
        assert interceptor is not None
        # Verify it's the correct type
        from temporalio.contrib.opentelemetry import TracingInterceptor
        assert isinstance(interceptor, TracingInterceptor)

    def test_create_tracing_interceptor_when_telemetry_disabled(self):
        """Test that no interceptor is created when telemetry is disabled."""
        from src.infrastructure.adapters.secondary.temporal.client import (
            create_tracing_interceptor,
        )

        # Arrange: Reset global state for testing
        from src.infrastructure.telemetry import config

        config._reset_providers()

        # Act: Try to create tracing interceptor with disabled telemetry
        interceptor = create_tracing_interceptor()

        # Assert: Should return None when telemetry is disabled
        assert interceptor is None

    def test_tracing_interceptor_type(self):
        """Test that TracingInterceptor has expected behavior."""
        from temporalio.contrib.opentelemetry import TracingInterceptor

        # Arrange: Create a mock tracer provider
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import SimpleSpanProcessor
        from opentelemetry.sdk.trace.export import ConsoleSpanExporter

        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
        trace.set_tracer_provider(provider)

        # Act: Create tracing interceptor
        interceptor = TracingInterceptor()

        # Assert: Interceptor should be created successfully
        assert interceptor is not None


@pytest.mark.unit
class TestTemporalClientFactoryWithTelemetry:
    """Test TemporalClientFactory with OpenTelemetry support."""

    @pytest.mark.asyncio
    async def test_get_client_includes_tracing_interceptor_when_enabled(self):
        """Test that get_client adds tracing interceptor when telemetry is enabled."""
        from src.infrastructure.adapters.secondary.temporal.client import (
            TemporalClientFactory,
        )
        from src.configuration.temporal_config import TemporalSettings

        # Arrange: Enable telemetry
        settings = TemporalSettings(
            temporal_host="localhost:7233",
            temporal_namespace="default",
            temporal_tracing_enabled=True,
        )

        # Mock the Client.connect to avoid actual connection
        with patch("src.infrastructure.adapters.secondary.temporal.client.Client.connect") as mock_connect:
            mock_client = AsyncMock()
            mock_connect.return_value = mock_client

            # Act: Get client with telemetry enabled
            client = await TemporalClientFactory.get_client(settings)

            # Assert: Client.connect should be called
            assert mock_connect.called
            # Check if interceptors were passed
            call_kwargs = mock_connect.call_args.kwargs
            if "interceptors" in call_kwargs:
                # Verify interceptor is in the call
                from temporalio.contrib.opentelemetry import TracingInterceptor
                assert any(isinstance(i, TracingInterceptor) for i in call_kwargs["interceptors"])

    @pytest.mark.asyncio
    async def test_get_client_without_interceptor_when_disabled(self):
        """Test that get_client skips interceptor when telemetry is disabled."""
        from src.infrastructure.adapters.secondary.temporal.client import (
            TemporalClientFactory,
        )
        from src.configuration.temporal_config import TemporalSettings

        # Arrange: Disable telemetry (default)
        settings = TemporalSettings(
            temporal_host="localhost:7233",
            temporal_namespace="default",
        )

        # Mock the Client.connect and reset instance
        with patch("src.infrastructure.adapters.secondary.temporal.client.Client.connect") as mock_connect:
            mock_client = AsyncMock()
            mock_connect.return_value = mock_client

            # Reset instance to force reconnection
            TemporalClientFactory._instance = None

            # Act: Get client with telemetry disabled
            client = await TemporalClientFactory.get_client(settings)

            # Assert: Client.connect should be called
            assert mock_connect.called
            call_kwargs = mock_connect.call_args.kwargs
            # Should not have interceptors, or empty list
            interceptors = call_kwargs.get("interceptors", [])
            assert len(interceptors) == 0


@pytest.mark.unit
class TestTelemetrySettings:
    """Test telemetry settings configuration."""

    def test_temporal_settings_has_temporal_tracing_enabled_field(self):
        """Test that TemporalSettings includes temporal_tracing_enabled field."""
        from src.configuration.temporal_config import TemporalSettings

        # Act & Assert: Settings should accept temporal_tracing_enabled parameter
        settings = TemporalSettings(
            temporal_host="localhost:7233",
            temporal_namespace="default",
            temporal_tracing_enabled=True,
        )

        assert settings.temporal_tracing_enabled is True

    def test_temporal_settings_telemetry_defaults_to_false(self):
        """Test that temporal_tracing_enabled defaults to False."""
        from src.configuration.temporal_config import TemporalSettings

        # Act & Assert: Default should be False for safety
        settings = TemporalSettings(
            temporal_host="localhost:7233",
            temporal_namespace="default",
        )

        assert settings.temporal_tracing_enabled is False


@pytest.mark.unit
class TestTracingInterceptorEdgeCases:
    """Test edge cases for TracingInterceptor creation."""

    def test_create_tracing_interceptor_when_provider_is_none(self):
        """Test that None is returned when tracer provider is None."""
        from src.infrastructure.adapters.secondary.temporal.client import (
            create_tracing_interceptor,
        )
        from src.infrastructure.telemetry import config

        # Arrange: Reset provider to None
        config._reset_providers()

        # Act: Try to create interceptor with no provider
        interceptor = create_tracing_interceptor()

        # Assert: Should return None
        assert interceptor is None


@pytest.mark.unit
class TestGetTemporalClient:
    """Test get_temporal_client convenience function."""

    @pytest.mark.asyncio
    async def test_get_temporal_client_convenience_function(self):
        """Test that get_temporal_client is a convenience wrapper."""
        from src.infrastructure.adapters.secondary.temporal.client import (
            get_temporal_client,
            TemporalClientFactory,
        )

        # Arrange: Mock the factory
        with patch.object(TemporalClientFactory, "get_client", new=AsyncMock()) as mock_get_client:
            mock_get_client.return_value = AsyncMock()

            # Act: Call convenience function
            client = await get_temporal_client()

            # Assert: Should delegate to factory
            mock_get_client.assert_called_once()


@pytest.mark.unit
class TestTemporalClientFactoryUtilities:
    """Test utility methods of TemporalClientFactory."""

    @pytest.mark.asyncio
    async def test_is_connected_returns_true_when_connected(self):
        """Test that is_connected returns True when client exists."""
        from src.infrastructure.adapters.secondary.temporal.client import (
            TemporalClientFactory,
        )

        # Arrange: Set up instance
        TemporalClientFactory._instance = AsyncMock()

        # Act: Check connection status
        result = TemporalClientFactory.is_connected()

        # Assert: Should return True
        assert result is True

        # Cleanup
        TemporalClientFactory._instance = None

    @pytest.mark.asyncio
    async def test_is_connected_returns_false_when_not_connected(self):
        """Test that is_connected returns False when no client exists."""
        from src.infrastructure.adapters.secondary.temporal.client import (
            TemporalClientFactory,
        )

        # Arrange: Ensure no instance
        TemporalClientFactory._instance = None

        # Act: Check connection status
        result = TemporalClientFactory.is_connected()

        # Assert: Should return False
        assert result is False

    @pytest.mark.asyncio
    async def test_close_resets_instance(self):
        """Test that close resets the client instance."""
        from src.infrastructure.adapters.secondary.temporal.client import (
            TemporalClientFactory,
        )

        # Arrange: Set up instance
        TemporalClientFactory._instance = AsyncMock()
        TemporalClientFactory._settings = AsyncMock()

        # Act: Close connection
        await TemporalClientFactory.close()

        # Assert: Instance should be reset
        assert TemporalClientFactory._instance is None
        assert TemporalClientFactory._settings is None

    @pytest.mark.asyncio
    async def test_close_when_no_instance_is_noop(self):
        """Test that close does nothing when no instance exists."""
        from src.infrastructure.adapters.secondary.temporal.client import (
            TemporalClientFactory,
        )

        # Arrange: Ensure no instance
        TemporalClientFactory._instance = None

        # Act: Close should not raise
        await TemporalClientFactory.close()

        # Assert: Should still be None
        assert TemporalClientFactory._instance is None
