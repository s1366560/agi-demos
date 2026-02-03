"""Telemetry initialization for startup."""

import logging
import os

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
    if not settings.enable_telemetry:
        logger.info("OpenTelemetry disabled")
        return False

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
    except Exception as e:
        logger.warning(f"Failed to initialize OpenTelemetry: {e}")
        return False

    # Initialize Langfuse LLM Observability (if enabled)
    if settings.langfuse_enabled:
        try:
            import litellm

            # Set environment variables for LiteLLM Langfuse callback
            if settings.langfuse_public_key:
                os.environ["LANGFUSE_PUBLIC_KEY"] = settings.langfuse_public_key
            if settings.langfuse_secret_key:
                os.environ["LANGFUSE_SECRET_KEY"] = settings.langfuse_secret_key
            os.environ["LANGFUSE_HOST"] = settings.langfuse_host

            # Enable Langfuse callback for all LiteLLM calls
            litellm.success_callback = ["langfuse"]
            litellm.failure_callback = ["langfuse"]

            logger.info(
                f"Langfuse LLM observability enabled (host: {settings.langfuse_host}, "
                f"sample_rate: {settings.langfuse_sample_rate})"
            )
        except Exception as e:
            logger.warning(
                f"Failed to initialize Langfuse callback: {e}. Tracing will be disabled."
            )
    else:
        logger.info("Langfuse LLM observability disabled")

    return True


def shutdown_telemetry_services() -> None:
    """Shutdown OpenTelemetry services."""
    if settings.enable_telemetry:
        try:
            shutdown_telemetry()
            logger.info("OpenTelemetry shutdown complete")
        except Exception as e:
            logger.warning(f"Error shutting down OpenTelemetry: {e}")
