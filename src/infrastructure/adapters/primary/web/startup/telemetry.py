"""Telemetry initialization for startup."""

import logging

from src.configuration.config import get_settings
from src.infrastructure.telemetry import instrument_all, shutdown_telemetry

logger = logging.getLogger(__name__)
settings = get_settings()


async def initialize_telemetry() -> bool:
    """
    Initialize OpenTelemetry and Langfuse observability.

    Returns:
        True if telemetry was initialized, False if disabled.
    """
    initialized = False

    if settings.enable_telemetry:
        logger.info("Initializing OpenTelemetry...")
        try:
            from src.infrastructure.telemetry.config import configure_meter_provider

            configure_meter_provider()

            # Auto-instrument other libraries (httpx, sqlalchemy, redis)
            instrumentation_results = instrument_all(auto_instrument=True)

            logger.info(f"OpenTelemetry auto-instrumentation: {instrumentation_results}")
            logger.info(
                f"OpenTelemetry initialized (service={settings.service_name}, "
                f"environment={settings.environment})"
            )
            initialized = True
        except Exception as e:
            logger.warning(f"Failed to initialize OpenTelemetry: {e}")
    else:
        logger.info("OpenTelemetry disabled")

    # Initialize Langfuse LLM Observability (if enabled)
    try:
        from src.infrastructure.telemetry.config import configure_langfuse_llm_observability

        if configure_langfuse_llm_observability(settings_override=dict(settings.__dict__)):
            initialized = True
    except Exception as e:
        logger.warning(f"Failed to initialize Langfuse callback: {e}. Tracing will be disabled.")

    return initialized


def shutdown_telemetry_services() -> None:
    """Shutdown OpenTelemetry services."""
    if settings.enable_telemetry:
        try:
            shutdown_telemetry()
            logger.info("OpenTelemetry shutdown complete")
        except Exception as e:
            logger.warning(f"Error shutting down OpenTelemetry: {e}")
