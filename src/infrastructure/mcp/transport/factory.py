"""
Transport factory for MCP.

Creates appropriate transport instances based on configuration.
"""

import logging
from typing import Any

from src.domain.model.mcp.transport import TransportConfig, TransportType
from src.infrastructure.mcp.transport.base import BaseTransport, MCPTransportError

logger = logging.getLogger(__name__)


class TransportFactory:
    """
    Factory for creating MCP transport instances.

    Supports creating transports for different protocols based on
    TransportConfig or transport type string.
    """

    def __init__(self) -> None:
        """Initialize the transport factory with an empty registry."""
        self._transports: dict[TransportType, type[BaseTransport]] = {}

    def register(self, transport_type: TransportType, transport_class: type[BaseTransport]) -> None:
        """
        Register a transport implementation.

        Args:
            transport_type: Transport type enum value.
            transport_class: Transport class implementing BaseTransport.
        """
        self._transports[transport_type] = transport_class
        logger.debug(f"Registered transport: {transport_type.value} -> {transport_class.__name__}")

    def create(self, config: TransportConfig) -> BaseTransport:
        """
        Create a transport instance from configuration.

        Args:
            config: Transport configuration.

        Returns:
            Configured transport instance.

        Raises:
            MCPTransportError: If transport type is not supported.
        """
        transport_type = config.transport_type

        # Normalize stdio to local
        if transport_type == TransportType.STDIO:
            transport_type = TransportType.LOCAL

        transport_class = self._transports.get(transport_type)

        if not transport_class:
            # Lazy import and register
            self._lazy_register()
            transport_class = self._transports.get(transport_type)

        if not transport_class:
            raise MCPTransportError(f"Unsupported transport type: {transport_type.value}")

        return transport_class(config)

    def create_from_type(
        self,
        transport_type: str,
        config_dict: dict[str, Any],
    ) -> BaseTransport:
        """
        Create a transport from type string and config dict.

        Args:
            transport_type: Transport type string (e.g., "stdio", "websocket").
            config_dict: Configuration dictionary.

        Returns:
            Configured transport instance.
        """
        # Normalize and create TransportConfig
        normalized_type = TransportType.normalize(transport_type)

        config = TransportConfig(
            transport_type=normalized_type,
            command=config_dict.get("command"),
            url=config_dict.get("url"),
            headers=config_dict.get("headers"),
            environment=config_dict.get("env"),
            timeout=config_dict.get("timeout", 30000),
            heartbeat_interval=config_dict.get("heartbeat_interval") or 0,
            reconnect_attempts=config_dict.get("reconnect_attempts") or 3,
        )

        return self.create(config)

    def supports(self, transport_type: str) -> bool:
        """
        Check if a transport type is supported.

        Args:
            transport_type: Transport type string.

        Returns:
            True if supported.
        """
        try:
            normalized = TransportType.normalize(transport_type)
            self._lazy_register()
            return normalized in self._transports
        except ValueError:
            return False

    def _lazy_register(self) -> None:
        """Lazily register built-in transports."""
        if self._transports:
            return

        # Import and register built-in transports
        from src.infrastructure.mcp.transport.http import HTTPTransport
        from src.infrastructure.mcp.transport.sse import SSETransport
        from src.infrastructure.mcp.transport.stdio import StdioTransport
        from src.infrastructure.mcp.transport.websocket import WebSocketTransport

        self.register(TransportType.LOCAL, StdioTransport)
        self.register(TransportType.STDIO, StdioTransport)
        self.register(TransportType.HTTP, HTTPTransport)
        self.register(TransportType.SSE, SSETransport)
        self.register(TransportType.WEBSOCKET, WebSocketTransport)

    def get_supported_types(self) -> list[str]:
        """Get list of supported transport type strings."""
        self._lazy_register()
        return [t.value for t in self._transports.keys()]
