"""Temporal Client Factory for MemStack.

This module provides a singleton Temporal client factory with connection
pooling and TLS support for production deployments.
"""

import logging
from typing import Optional, List

from temporalio.client import Client, TLSConfig

from src.configuration.temporal_config import TemporalSettings, get_temporal_settings

logger = logging.getLogger(__name__)


def create_tracing_interceptor():
    """Create an OpenTelemetry TracingInterceptor for Temporal client.

    Returns:
        TracingInterceptor instance if telemetry is enabled, None otherwise
    """
    try:
        from temporalio.contrib.opentelemetry import TracingInterceptor
        from src.infrastructure.telemetry.config import _TRACER_PROVIDER

        if _TRACER_PROVIDER is None:
            return None

        return TracingInterceptor()
    except ImportError:
        # temporalio[opentelemetry] not installed
        logger.warning(
            "temporalio[opentelemetry] not installed. "
            "Install with: pip install temporalio[opentelemetry]"
        )
        return None
    except Exception as e:
        logger.warning(f"Failed to create TracingInterceptor: {e}")
        return None


class TemporalClientFactory:
    """Factory for creating and managing Temporal client connections.

    Uses singleton pattern to maintain a single connection across the application.
    """

    _instance: Optional[Client] = None
    _settings: Optional[TemporalSettings] = None

    @classmethod
    async def get_client(cls, settings: Optional[TemporalSettings] = None) -> Client:
        """Get or create a Temporal client instance.

        Args:
            settings: Optional Temporal settings. If not provided, uses cached settings.

        Returns:
            Connected Temporal client
        """
        if cls._instance is not None:
            return cls._instance

        if settings is None:
            settings = get_temporal_settings()

        cls._settings = settings

        # Build TLS config if enabled
        tls_config = None
        if settings.temporal_tls_enabled:
            tls_config = cls._build_tls_config(settings)

        # Build interceptors list
        interceptors: List = []
        if settings.temporal_tracing_enabled:
            tracing_interceptor = create_tracing_interceptor()
            if tracing_interceptor is not None:
                interceptors.append(tracing_interceptor)
                logger.info("OpenTelemetry tracing enabled for Temporal client")

        logger.info(
            f"Connecting to Temporal server at {settings.temporal_host}, "
            f"namespace: {settings.temporal_namespace}"
        )

        try:
            connect_kwargs = {
                "target_host": settings.temporal_host,
                "namespace": settings.temporal_namespace,
                "tls": tls_config,
            }
            if interceptors:
                connect_kwargs["interceptors"] = interceptors

            cls._instance = await Client.connect(**connect_kwargs)
            logger.info("Successfully connected to Temporal server")
            return cls._instance
        except Exception as e:
            logger.error(f"Failed to connect to Temporal server: {e}")
            raise

    @classmethod
    def _build_tls_config(cls, settings: TemporalSettings) -> TLSConfig:
        """Build TLS configuration for secure connections.

        Args:
            settings: Temporal settings with TLS configuration

        Returns:
            TLSConfig for client connection
        """
        client_cert = None
        client_key = None
        server_root_ca_cert = None

        if settings.temporal_tls_cert_path:
            with open(settings.temporal_tls_cert_path, "rb") as f:
                client_cert = f.read()

        if settings.temporal_tls_key_path:
            with open(settings.temporal_tls_key_path, "rb") as f:
                client_key = f.read()

        if settings.temporal_tls_ca_path:
            with open(settings.temporal_tls_ca_path, "rb") as f:
                server_root_ca_cert = f.read()

        return TLSConfig(
            client_cert=client_cert,
            client_private_key=client_key,
            server_root_ca_cert=server_root_ca_cert,
        )

    @classmethod
    async def close(cls) -> None:
        """Close the Temporal client connection."""
        if cls._instance is not None:
            # Temporal Python SDK client doesn't have explicit close method
            # but we reset the instance for reconnection on next use
            cls._instance = None
            cls._settings = None
            logger.info("Temporal client connection closed")

    @classmethod
    def is_connected(cls) -> bool:
        """Check if client is connected."""
        return cls._instance is not None


async def get_temporal_client(settings: Optional[TemporalSettings] = None) -> Client:
    """Convenience function to get the Temporal client.

    Args:
        settings: Optional Temporal settings

    Returns:
        Connected Temporal client
    """
    return await TemporalClientFactory.get_client(settings)
