"""OpenTelemetry configuration and initialization.

This module handles the setup and configuration of OpenTelemetry
for distributed tracing and metrics collection.
"""

import contextlib
import logging
import os
from base64 import b64encode
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
)
from opentelemetry.sdk.trace.sampling import TraceIdRatioBased

from src.configuration.config import get_settings

logger = logging.getLogger(__name__)

# Global providers (cached after initialization)
_TRACER_PROVIDER: TracerProvider | None = None
_METER_PROVIDER: MeterProvider | None = None
# Flag to control telemetry globally (for testing)
_TELEMETRY_ENABLED: bool | None = None
_LANGFUSE_SPAN_EXPORTER_CONFIGURED: bool = False


def _reset_providers() -> None:
    """Reset global providers (for testing)."""
    global _TRACER_PROVIDER, _METER_PROVIDER, _TELEMETRY_ENABLED
    global _LANGFUSE_SPAN_EXPORTER_CONFIGURED
    _TRACER_PROVIDER = None
    _METER_PROVIDER = None
    _TELEMETRY_ENABLED = None
    _LANGFUSE_SPAN_EXPORTER_CONFIGURED = False

    # Also clear global meter provider
    with contextlib.suppress(Exception):
        metrics.set_meter_provider(None)  # type: ignore[arg-type]


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


def _create_trace_exporter(settings_override: dict[str, Any] | None = None) -> Any | None:
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
    logger.info("No OTLP endpoint configured; trace export disabled")
    return None


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


def configure_langfuse_span_exporter(
    settings_override: dict[str, Any] | None = None,
    provider: TracerProvider | None = None,
    force_reset: bool = False,
) -> bool:
    """Attach a Langfuse OTLP exporter to the app tracer provider.

    LiteLLM's ``langfuse_otel`` callback reuses an existing global OpenTelemetry
    provider when one is already configured. In that mode LiteLLM emits spans to
    the app provider, so the app provider itself must export those spans to
    Langfuse.
    """
    global _LANGFUSE_SPAN_EXPORTER_CONFIGURED

    settings = settings_override or get_settings().__dict__
    if not settings.get("langfuse_enabled", False):
        return False

    if _LANGFUSE_SPAN_EXPORTER_CONFIGURED and not force_reset:
        return True

    public_key = settings.get("langfuse_public_key")
    secret_key = settings.get("langfuse_secret_key")
    host = settings.get("langfuse_host")

    if not public_key or not secret_key or not host:
        logger.warning("Langfuse exporter skipped: missing host or API keys")
        return False

    tracer_provider = provider or _TRACER_PROVIDER
    if tracer_provider is None:
        current_provider = trace.get_tracer_provider()
        if isinstance(current_provider, TracerProvider):
            tracer_provider = current_provider

    if tracer_provider is None:
        logger.warning("Langfuse exporter skipped: no SDK tracer provider configured")
        return False

    endpoint = f"{str(host).rstrip('/')}/api/public/otel/v1/traces"
    auth_token = b64encode(f"{public_key}:{secret_key}".encode()).decode("ascii")
    exporter = HTTPTraceExporter(
        endpoint=endpoint,
        headers={"Authorization": f"Basic {auth_token}"},
    )
    tracer_provider.add_span_processor(BatchSpanProcessor(exporter))
    _LANGFUSE_SPAN_EXPORTER_CONFIGURED = True

    logger.info("Langfuse OTLP span exporter configured (host: %s)", host)
    return True


def configure_langfuse_llm_observability(
    settings_override: dict[str, Any] | None = None,
) -> bool:
    """Configure LiteLLM's Langfuse OTel callback for the current process."""
    settings = settings_override or get_settings().__dict__
    if not settings.get("langfuse_enabled", False):
        logger.info("Langfuse LLM observability disabled")
        return False

    public_key = settings.get("langfuse_public_key")
    secret_key = settings.get("langfuse_secret_key")
    host = settings.get("langfuse_host")
    if not public_key or not secret_key or not host:
        logger.warning("Langfuse LLM observability skipped: missing host or API keys")
        return False

    try:
        import litellm

        os.environ["LANGFUSE_PUBLIC_KEY"] = str(public_key)
        os.environ["LANGFUSE_SECRET_KEY"] = str(secret_key)
        os.environ["LANGFUSE_HOST"] = str(host)
        os.environ["LANGFUSE_OTEL_HOST"] = str(host)

        if settings.get("enable_telemetry", True):
            configure_tracer_provider(settings_override=settings_override)
        else:
            configure_langfuse_span_exporter(settings_override=settings_override)

        existing_callbacks = list(getattr(litellm, "callbacks", []) or [])
        litellm.callbacks = [callback for callback in existing_callbacks if callback != "langfuse"]
        if "langfuse_otel" not in litellm.callbacks:
            litellm.callbacks.append("langfuse_otel")

        logger.info(
            "Langfuse LLM observability enabled (host: %s, sample_rate: %s)",
            host,
            settings.get("langfuse_sample_rate", 1.0),
        )
        return True
    except Exception as e:
        logger.warning(
            "Failed to initialize Langfuse callback: %s. Tracing will be disabled.",
            e,
        )
        return False


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
        configure_langfuse_span_exporter(
            settings_override=settings_override,
            provider=_TRACER_PROVIDER,
        )
        return _TRACER_PROVIDER

    try:
        resource = _create_resource(settings_override)
        exporter = _create_trace_exporter(settings_override)
        sampler = _get_sampler(settings_override)

        provider = TracerProvider(resource=resource, sampler=sampler)

        if exporter is not None:
            provider.add_span_processor(BatchSpanProcessor(exporter))

        configure_langfuse_span_exporter(
            settings_override=settings_override,
            provider=provider,
            force_reset=force_reset,
        )

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
                metrics.set_meter_provider(None)  # type: ignore[arg-type]
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
    global _LANGFUSE_SPAN_EXPORTER_CONFIGURED

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
    _LANGFUSE_SPAN_EXPORTER_CONFIGURED = False


# Export globals for module-level access in tests
TRACER_PROVIDER = property(lambda self: _TRACER_PROVIDER)
METER_PROVIDER = property(lambda self: _METER_PROVIDER)


def _get_tracer_provider_global() -> TracerProvider | None:
    """Get the global tracer provider (for testing)."""
    return _TRACER_PROVIDER


def _get_meter_provider_global() -> MeterProvider | None:
    """Get the global meter provider (for testing)."""
    return _METER_PROVIDER
