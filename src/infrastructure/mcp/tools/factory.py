"""
MCP Tool Factory.

Provides factory for creating appropriate tool adapters based on
transport type and configuration.
"""

import logging
from typing import Any, ClassVar

from src.domain.model.mcp.transport import TransportType
from src.infrastructure.mcp.tools.base import (
    BaseMCPToolAdapter,
    LocalToolAdapter,
    WebSocketToolAdapter,
)

logger = logging.getLogger(__name__)


class MCPToolFactory:
    """
    Factory for creating MCP tool adapters.

    Creates appropriate adapter instances based on transport type
    and server configuration.
    """

    _adapters: ClassVar[dict[str, BaseMCPToolAdapter]] = {}

    @classmethod
    def create_adapter(
        cls,
        server_name: str,
        transport_type: TransportType,
        **config: Any,
    ) -> BaseMCPToolAdapter:
        """
        Create a tool adapter for the given transport type.

        Args:
            server_name: Name of the MCP server
            transport_type: Transport type (local, websocket, http)
            **config: Transport-specific configuration

        Returns:
            BaseMCPToolAdapter instance

        Raises:
            ValueError: If transport type is not supported
        """
        # Normalize transport type
        if isinstance(transport_type, str):
            transport = TransportType.normalize(transport_type)
        elif isinstance(transport_type, TransportType):
            # Handle stdio -> local normalization
            transport = TransportType.normalize(transport_type.value)
        else:
            transport = transport_type

        if transport in (TransportType.LOCAL, TransportType.STDIO):
            return cls._create_local_adapter(server_name, **config)

        elif transport == TransportType.WEBSOCKET:
            return cls._create_websocket_adapter(server_name, **config)

        elif transport == TransportType.HTTP:
            # HTTP adapters use WebSocket for bidirectional MCP communication
            # Fall back to WebSocket if websocket_url provided
            if "websocket_url" in config:
                return cls._create_websocket_adapter(server_name, **config)
            raise ValueError("HTTP transport requires websocket_url for MCP communication")

        else:
            raise ValueError(f"Unsupported transport type: {transport}")

    @classmethod
    def _create_local_adapter(cls, server_name: str, **config: Any) -> LocalToolAdapter:
        """Create local (stdio) adapter."""
        command = config.get("command")
        if not command:
            raise ValueError("Local adapter requires 'command' configuration")

        return LocalToolAdapter(
            server_name=server_name,
            command=command,
            args=config.get("args", []),
            env=config.get("env", {}),
        )

    @classmethod
    def _create_websocket_adapter(cls, server_name: str, **config: Any) -> WebSocketToolAdapter:
        """Create WebSocket adapter."""
        websocket_url = config.get("websocket_url")
        if not websocket_url:
            raise ValueError("WebSocket adapter requires 'websocket_url' configuration")

        return WebSocketToolAdapter(
            server_name=server_name,
            websocket_url=websocket_url,
        )

    @classmethod
    def get_or_create(
        cls,
        server_name: str,
        transport_type: TransportType,
        **config: Any,
    ) -> BaseMCPToolAdapter:
        """
        Get existing adapter or create new one.

        Maintains a cache of adapters by server name.

        Args:
            server_name: Name of the MCP server
            transport_type: Transport type
            **config: Configuration

        Returns:
            BaseMCPToolAdapter instance
        """
        if server_name in cls._adapters:
            return cls._adapters[server_name]

        adapter = cls.create_adapter(server_name, transport_type, **config)
        cls._adapters[server_name] = adapter
        return adapter

    @classmethod
    def remove_adapter(cls, server_name: str) -> BaseMCPToolAdapter | None:
        """
        Remove adapter from cache.

        Args:
            server_name: Name of the server

        Returns:
            Removed adapter or None
        """
        return cls._adapters.pop(server_name, None)

    @classmethod
    def clear_all(cls) -> None:
        """Clear all cached adapters."""
        cls._adapters.clear()

    @classmethod
    def list_adapters(cls) -> list[str]:
        """List all cached adapter server names."""
        return list(cls._adapters.keys())
