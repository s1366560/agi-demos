"""
Base transport implementation for MCP.

Provides common functionality and abstract interface for transport implementations.
"""

import logging
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from types import TracebackType
from typing import Any

from src.domain.model.mcp.transport import TransportConfig

logger = logging.getLogger(__name__)


class BaseTransport(ABC):
    """
    Abstract base class for MCP transport implementations.

    Provides common functionality like request ID management,
    logging, and the core interface that all transports must implement.
    """

    def __init__(self, config: TransportConfig | None = None) -> None:
        """
        Initialize base transport.

        Args:
            config: Optional transport configuration.
        """
        self._config = config
        self._request_id = 0
        self._is_open = False

    @property
    def is_open(self) -> bool:
        """Check if transport is currently open."""
        return self._is_open

    @property
    def config(self) -> TransportConfig | None:
        """Get transport configuration."""
        return self._config

    def _next_request_id(self) -> int:
        """Generate next request ID."""
        self._request_id += 1
        return self._request_id

    @abstractmethod
    async def start(self, config: TransportConfig) -> None:
        """
        Start the transport connection.

        Args:
            config: Transport configuration.

        Raises:
            MCPTransportError: If transport fails to start.
        """
        ...

    @abstractmethod
    async def stop(self) -> None:
        """
        Stop the transport connection.

        Should be idempotent.
        """
        ...

    @abstractmethod
    async def send(
        self,
        message: dict[str, Any],
        timeout: float | None = None,
    ) -> None:
        """
        Send a message over the transport.

        Args:
            message: JSON-RPC message to send.
            timeout: Optional send timeout in seconds.

        Raises:
            MCPTransportError: If send fails.
        """
        ...

    @abstractmethod
    async def receive(
        self,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """
        Receive a message from the transport.

        Args:
            timeout: Optional receive timeout in seconds.

        Returns:
            Received JSON-RPC message.

        Raises:
            MCPTransportError: If receive fails.
            asyncio.TimeoutError: If timeout expires.
        """
        ...

    async def receive_stream(self) -> AsyncIterator[dict[str, Any]]:
        """
        Receive messages as an async iterator.

        Default implementation using receive().
        Subclasses may override for more efficient streaming.

        Yields:
            Received JSON-RPC messages.
        """
        while self._is_open:
            try:
                message = await self.receive()
                yield message
            except Exception:
                break

    async def __aenter__(self) -> "BaseTransport":
        """Async context manager entry."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Async context manager exit."""
        await self.stop()


class MCPTransportError(Exception):
    """Base exception for transport errors."""

    pass


class MCPTransportClosedError(MCPTransportError):
    """Exception raised when transport is closed."""

    pass


class MCPTransportTimeoutError(MCPTransportError):
    """Exception raised on transport timeout."""

    pass
