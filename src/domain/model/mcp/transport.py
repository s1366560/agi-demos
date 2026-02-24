"""
MCP Transport Domain Models.

Defines transport protocol types and configuration value objects.
Consolidates definitions from:
- src/infrastructure/mcp/config.py (McpLocalConfig, McpRemoteConfig, McpWebSocketConfig)
- src/infrastructure/agent/mcp/client.py (transport configs)
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any


class TransportType(str, Enum):
    """MCP transport protocol types."""

    LOCAL = "local"  # stdio/subprocess
    STDIO = "stdio"  # alias for local
    HTTP = "http"  # HTTP request/response
    SSE = "sse"  # Server-Sent Events (Streamable HTTP)
    WEBSOCKET = "websocket"  # WebSocket bidirectional

    @classmethod
    def normalize(cls, value: str) -> "TransportType":
        """Normalize transport type string to enum."""
        normalized = value.lower().strip()
        if normalized == "stdio":
            return cls.LOCAL
        return cls(normalized)


@dataclass(frozen=True)
class TransportConfig:
    """
    MCP transport configuration value object.

    Contains all settings needed to establish a connection
    using any supported transport protocol.
    """

    transport_type: TransportType

    # Local (stdio) transport config
    command: list[str] | None = None
    environment: dict[str, str] | None = None

    # Remote transport config (HTTP/SSE/WebSocket)
    url: str | None = None
    headers: dict[str, str] | None = None

    # Common config
    timeout: int = 30000  # milliseconds
    enabled: bool = True

    # WebSocket specific config
    heartbeat_interval: int = 30  # seconds
    reconnect_attempts: int = 3

    def __post_init__(self):
        """Validate configuration based on transport type."""
        if self.transport_type in (TransportType.LOCAL, TransportType.STDIO):
            if not self.command:
                raise ValueError("Command is required for local/stdio transport")
        elif self.transport_type in (
            TransportType.HTTP,
            TransportType.SSE,
            TransportType.WEBSOCKET,
        ):
            if not self.url:
                raise ValueError(f"URL is required for {self.transport_type.value} transport")

    @property
    def timeout_seconds(self) -> float:
        """Get timeout in seconds."""
        return self.timeout / 1000.0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "type": self.transport_type.value,
            "command": self.command,
            "environment": self.environment,
            "url": self.url,
            "headers": self.headers,
            "timeout": self.timeout,
            "enabled": self.enabled,
            "heartbeat_interval": self.heartbeat_interval,
            "reconnect_attempts": self.reconnect_attempts,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TransportConfig":
        """Create from dictionary."""
        transport_type = TransportType.normalize(data.get("type", "local"))
        return cls(
            transport_type=transport_type,
            command=data.get("command"),
            environment=data.get("environment"),
            url=data.get("url"),
            headers=data.get("headers"),
            timeout=data.get("timeout", 30000),
            enabled=data.get("enabled", True),
            heartbeat_interval=data.get("heartbeat_interval", 30),
            reconnect_attempts=data.get("reconnect_attempts", 3),
        )

    @classmethod
    def local(
        cls,
        command: list[str],
        environment: dict[str, str] | None = None,
        timeout: int = 30000,
    ) -> "TransportConfig":
        """Create local (stdio) transport config."""
        return cls(
            transport_type=TransportType.LOCAL,
            command=command,
            environment=environment,
            timeout=timeout,
        )

    @classmethod
    def http(
        cls,
        url: str,
        headers: dict[str, str] | None = None,
        timeout: int = 30000,
    ) -> "TransportConfig":
        """Create HTTP transport config."""
        return cls(
            transport_type=TransportType.HTTP,
            url=url,
            headers=headers,
            timeout=timeout,
        )

    @classmethod
    def sse(
        cls,
        url: str,
        headers: dict[str, str] | None = None,
        timeout: int = 30000,
    ) -> "TransportConfig":
        """Create SSE transport config."""
        return cls(
            transport_type=TransportType.SSE,
            url=url,
            headers=headers,
            timeout=timeout,
        )

    @classmethod
    def websocket(
        cls,
        url: str,
        headers: dict[str, str] | None = None,
        timeout: int = 30000,
        heartbeat_interval: int = 30,
        reconnect_attempts: int = 3,
    ) -> "TransportConfig":
        """Create WebSocket transport config."""
        return cls(
            transport_type=TransportType.WEBSOCKET,
            url=url,
            headers=headers,
            timeout=timeout,
            heartbeat_interval=heartbeat_interval,
            reconnect_attempts=reconnect_attempts,
        )
