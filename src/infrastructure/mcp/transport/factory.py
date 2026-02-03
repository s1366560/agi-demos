"""
Transport factory for MCP.

Creates appropriate transport instances based on configuration.
"""

import logging
from typing import Dict, Type

from src.domain.model.mcp.transport import TransportConfig, TransportType
from src.infrastructure.mcp.transport.base import BaseTransport, MCPTransportError

logger = logging.getLogger(__name__)


class TransportFactory:
    """
    Factory for creating MCP transport instances.

    Supports creating transports for different protocols based on
    TransportConfig or transport type string.
    """

    _transports: Dict[TransportType, Type[BaseTransport]] = {}

    @classmethod
    def register(cls, transport_type: TransportType, transport_class: Type[BaseTransport]) -> None:
        """
        Register a transport implementation.

        Args:
            transport_type: Transport type enum value.
            transport_class: Transport class implementing BaseTransport.
        """
        cls._transports[transport_type] = transport_class
        logger.debug(f"Registered transport: {transport_type.value} -> {transport_class.__name__}")

    @classmethod
    def create(cls, config: TransportConfig) -> BaseTransport:
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

        transport_class = cls._transports.get(transport_type)

        if not transport_class:
            # Lazy import and register
            cls._lazy_register()
            transport_class = cls._transports.get(transport_type)

        if not transport_class:
            raise MCPTransportError(f"Unsupported transport type: {transport_type.value}")

        return transport_class(config)

    @classmethod
    def create_from_type(
        cls,
        transport_type: str,
        config_dict: Dict,
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
            heartbeat_interval=config_dict.get("heartbeat_interval"),
            reconnect_attempts=config_dict.get("reconnect_attempts"),
        )

        return cls.create(config)

    @classmethod
    def supports(cls, transport_type: str) -> bool:
        """
        Check if a transport type is supported.

        Args:
            transport_type: Transport type string.

        Returns:
            True if supported.
        """
        try:
            normalized = TransportType.normalize(transport_type)
            cls._lazy_register()
            return normalized in cls._transports
        except ValueError:
            return False

    @classmethod
    def _lazy_register(cls) -> None:
        """Lazily register built-in transports."""
        if cls._transports:
            return

        # Import and register built-in transports
        from src.infrastructure.mcp.transport.http import HTTPTransport
        from src.infrastructure.mcp.transport.stdio import StdioTransport
        from src.infrastructure.mcp.transport.websocket import WebSocketTransport

        cls.register(TransportType.LOCAL, StdioTransport)
        cls.register(TransportType.STDIO, StdioTransport)
        cls.register(TransportType.HTTP, HTTPTransport)
        cls.register(TransportType.WEBSOCKET, WebSocketTransport)

        # SSE uses the existing implementation from agent/mcp/client.py
        # Will be added when extracted

    @classmethod
    def get_supported_types(cls) -> list[str]:
        """Get list of supported transport type strings."""
        cls._lazy_register()
        return [t.value for t in cls._transports.keys()]
