"""OpenTelemetry configuration and initialization.

This module handles the setup and configuration of OpenTelemetry
for distributed tracing and metrics collection.
"""

import contextlib
import logging
from typing import Any

from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
    OTLPSpanExporter as GRPCTraceExporter,
)
from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
    OTLPSpanExporter as HTTPTraceExporter,
)
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import ConsoleMetricExporter, PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SimpleSpanProcessor,
)
from opentelemetry.sdk.trace.sampling import TraceIdRatioBased

from src.configuration.config import get_settings

logger = logging.getLogger(__name__)

# Global providers (cached after initialization)
_TRACER_PROVIDER: TracerProvider | None = None
_METER_PROVIDER: MeterProvider | None = None
# Flag to control telemetry globally (for testing)
_TELEMETRY_ENABLED: bool | None = None


def _reset_providers() -> None:
    """Reset global providers (for testing)."""
    global _TRACER_PROVIDER, _METER_PROVIDER, _TELEMETRY_ENABLED
    _TRACER_PROVIDER = None
    _METER_PROVIDER = None
    _TELEMETRY_ENABLED = None

    # Also clear global meter provider
    with contextlib.suppress(Exception):
        metrics.set_meter_provider(None)


def _create_resource(settings_override: dict[str, Any] | None = None) -> Resource:
    """Create OpenTelemetry Resource with service attributes."""
    settings = settings_override or get_settings().__dict__

    attributes = {
        "service.name": settings.get("service_name", "memstack"),
        "deployment.environment": settings.get("environment", "development"),
        "service.namespace": "memstack",
    }

    # Add version from pyproject.toml if available
    try:
        from importlib.metadata import version

        attributes["service.version"] = version("memstack")
    except Exception:
        attributes["service.version"] = "0.3.0"

    return Resource.create(attributes)


def _create_trace_exporter(settings_override: dict[str, Any] | None = None) -> Any:
    """Create appropriate trace exporter based on configuration."""
    settings = settings_override or get_settings().__dict__

    endpoint = settings.get("otel_exporter_otlp_endpoint")

    if endpoint:
        # Use OTLP exporter
        # Detect if endpoint uses http (not grpc) protocol
        if endpoint.startswith("http://") or endpoint.startswith("https://"):
            # HTTP exporter - ensure path includes /v1/traces
            if not endpoint.endswith("/v1/traces"):
                endpoint = f"{endpoint.rstrip('/')}/v1/traces"
            return HTTPTraceExporter(endpoint=endpoint)
        else:
            # gRPC exporter (default)
            return GRPCTraceExporter(endpoint=endpoint, insecure=True)
    else:
        # Fall back to console exporter for development
        logger.info("No OTLP endpoint configured, using console exporter")
        return ConsoleSpanExporter()


def _get_sampler(settings_override: dict[str, Any] | None = None) -> TraceIdRatioBased:
    """Create sampler based on environment."""
    settings = settings_override or get_settings().__dict__
    environment = settings.get("environment", "development")

    # Sample 100% in development, 10% in production
    if environment == "development":
        # Always sample in dev
        return TraceIdRatioBased(1.0)
    else:
        # 10% sampling in production
        return TraceIdRatioBased(0.1)


def configure_tracer_provider(
    settings_override: dict[str, Any] | None = None, force_reset: bool = False
) -> TracerProvider | None:
    """Configure and return the tracer provider.

    Args:
        settings_override: Optional settings dict for testing
        force_reset: Force reconfiguration even if already configured

    Returns:
        TracerProvider if telemetry is enabled, None otherwise
    """
    global _TRACER_PROVIDER, _TELEMETRY_ENABLED

    settings_dict = settings_override or get_settings().__dict__
    enable_telemetry = settings_dict.get("enable_telemetry", True)

    # Check module-level flag first
    if _TELEMETRY_ENABLED is False:
        return None

    if not enable_telemetry:
        logger.info("Telemetry is disabled")
        _TELEMETRY_ENABLED = False
        return None

    if _TRACER_PROVIDER is not None and not force_reset:
        return _TRACER_PROVIDER

    try:
        resource = _create_resource(settings_override)
        exporter = _create_trace_exporter(settings_override)
        sampler = _get_sampler(settings_override)

        provider = TracerProvider(resource=resource, sampler=sampler)

        # Use BatchSpanProcessor for better performance
        if isinstance(exporter, ConsoleSpanExporter):
            provider.add_span_processor(SimpleSpanProcessor(exporter))
        else:
            provider.add_span_processor(BatchSpanProcessor(exporter))

        # Set global tracer provider
        trace.set_tracer_provider(provider)
        _TRACER_PROVIDER = provider

        logger.info(
            f"Tracer provider configured: service={settings_dict.get('service_name', 'memstack')}, "
            f"environment={settings_dict.get('environment', 'development')}"
        )

        return provider

    except Exception as e:
        logger.error(f"Failed to configure tracer provider: {e}")
        return None


def configure_meter_provider(
    settings_override: dict[str, Any] | None = None, force_reset: bool = False
) -> MeterProvider | None:
    """Configure and return the meter provider.

    Args:
        settings_override: Optional settings dict for testing
        force_reset: Force reconfiguration even if already configured

    Returns:
        MeterProvider if telemetry is enabled, None otherwise
    """
    global _METER_PROVIDER, _TELEMETRY_ENABLED

    settings_dict = settings_override or get_settings().__dict__
    enable_telemetry = settings_dict.get("enable_telemetry", True)

    # Check module-level flag first
    if _TELEMETRY_ENABLED is False:
        return None

    if not enable_telemetry:
        # Clear global meter provider when telemetry is disabled
        if force_reset:
            with contextlib.suppress(Exception):
                metrics.set_meter_provider(None)
        _TELEMETRY_ENABLED = False
        return None

    if _METER_PROVIDER is not None and not force_reset:
        return _METER_PROVIDER

    try:
        resource = _create_resource(settings_override)

        # Use console exporter for metrics (can be replaced with OTLP)
        metric_exporter = ConsoleMetricExporter()

        reader = PeriodicExportingMetricReader(metric_exporter, export_interval_millis=60000)

        provider = MeterProvider(resource=resource, metric_readers=[reader])

        # Set global meter provider
        metrics.set_meter_provider(provider)
        _METER_PROVIDER = provider

        logger.info("Meter provider configured")

        return provider

    except Exception as e:
        logger.error(f"Failed to configure meter provider: {e}")
        return None


def configure_telemetry(settings_override: dict[str, Any] | None = None) -> None:
    """Configure OpenTelemetry tracing and metrics.

    This function should be called during application startup.

    Args:
        settings_override: Optional settings dict for testing
    """
    configure_tracer_provider(settings_override)
    configure_meter_provider(settings_override)


def get_tracer(instrumentation_name: str = "memstack") -> trace.Tracer | None:
    """Get a tracer for the given instrumentation name.

    Args:
        instrumentation_name: Name of the instrumented module

    Returns:
        Tracer instance or None if telemetry is disabled
    """
    provider = configure_tracer_provider()
    if provider is None:
        return None

    return provider.get_tracer(instrumentation_name)


def get_meter(instrumentation_name: str = "memstack-telemetry") -> metrics.Meter | None:
    """Get a meter for the given instrumentation name.

    Args:
        instrumentation_name: Name of the instrumented module

    Returns:
        Meter instance or None if telemetry is disabled
    """
    provider = configure_meter_provider()
    if provider is None:
        return None

    return provider.get_meter(instrumentation_name)


def shutdown_telemetry() -> None:
    """Shutdown OpenTelemetry providers.

    This function should be called during application shutdown.
    """
    global _TRACER_PROVIDER, _METER_PROVIDER, _TELEMETRY_ENABLED

    if _TRACER_PROVIDER is not None:
        try:
            _TRACER_PROVIDER.shutdown()
            logger.info("Tracer provider shutdown complete")
        except Exception as e:
            logger.error(f"Error shutting down tracer provider: {e}")
        finally:
            _TRACER_PROVIDER = None

    if _METER_PROVIDER is not None:
        try:
            _METER_PROVIDER.shutdown()
            logger.info("Meter provider shutdown complete")
        except Exception as e:
            logger.error(f"Error shutting down meter provider: {e}")
        finally:
            _METER_PROVIDER = None

    # Reset the enabled flag
    _TELEMETRY_ENABLED = None


# Export globals for module-level access in tests
TRACER_PROVIDER = property(lambda self: _TRACER_PROVIDER)
METER_PROVIDER = property(lambda self: _METER_PROVIDER)


def _get_tracer_provider_global() -> TracerProvider | None:
    """Get the global tracer provider (for testing)."""
    return _TRACER_PROVIDER


def _get_meter_provider_global() -> MeterProvider | None:
    """Get the global meter provider (for testing)."""
    return _METER_PROVIDER
