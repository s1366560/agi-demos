"""
MCPTransportPort - Abstract interface for MCP transport operations.

This port defines the contract for low-level MCP message transport,
supporting multiple protocols (stdio, HTTP, SSE, WebSocket).
"""

from abc import abstractmethod
from typing import Any, AsyncIterator, Callable, Dict, Optional, Protocol, runtime_checkable

from src.domain.model.mcp.transport import TransportConfig


@runtime_checkable
class MCPTransportPort(Protocol):
    """
    Abstract interface for MCP transport layer.

    This port defines the contract for sending and receiving
    MCP protocol messages over different transport mechanisms.
    """

    @abstractmethod
    async def start(self, config: TransportConfig) -> None:
        """
        Start the transport connection.

        Args:
            config: Transport configuration with connection details.

        Raises:
            MCPTransportError: If transport fails to start.
        """
        ...

    @abstractmethod
    async def stop(self) -> None:
        """
        Stop the transport connection.

        Should be idempotent - safe to call multiple times.
        """
        ...

    @abstractmethod
    async def send(
        self,
        message: Dict[str, Any],
        timeout: Optional[float] = None,
    ) -> None:
        """
        Send a message over the transport.

        Args:
            message: JSON-RPC message to send.
            timeout: Optional send timeout in seconds.

        Raises:
            MCPTransportError: If send fails.
            MCPTransportClosedError: If transport is closed.
        """
        ...

    @abstractmethod
    async def receive(
        self,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Receive a message from the transport.

        Args:
            timeout: Optional receive timeout in seconds.

        Returns:
            Received JSON-RPC message.

        Raises:
            MCPTransportError: If receive fails.
            MCPTransportClosedError: If transport is closed.
            asyncio.TimeoutError: If timeout expires.
        """
        ...

    @abstractmethod
    async def receive_stream(self) -> AsyncIterator[Dict[str, Any]]:
        """
        Receive messages as an async iterator.

        Yields:
            Received JSON-RPC messages.

        Raises:
            MCPTransportError: If receive fails.
            MCPTransportClosedError: If transport is closed.
        """
        ...

    @property
    @abstractmethod
    def is_open(self) -> bool:
        """Check if transport is currently open."""
        ...


@runtime_checkable
class MCPTransportFactoryPort(Protocol):
    """
    Factory interface for creating transport instances.

    Allows different transport implementations to be created
    based on configuration.
    """

    @abstractmethod
    def create(self, config: TransportConfig) -> MCPTransportPort:
        """
        Create a transport instance for the given configuration.

        Args:
            config: Transport configuration specifying type and details.

        Returns:
            MCPTransportPort implementation for the transport type.

        Raises:
            ValueError: If transport type is not supported.
        """
        ...

    @abstractmethod
    def supports(self, transport_type: str) -> bool:
        """
        Check if this factory supports a transport type.

        Args:
            transport_type: Transport type name (e.g., "stdio", "websocket").

        Returns:
            True if this factory can create the transport.
        """
        ...


# Type alias for message handlers
MessageHandler = Callable[[Dict[str, Any]], Any]


@runtime_checkable
class MCPBidirectionalTransportPort(Protocol):
    """
    Extended transport interface for bidirectional communication.

    Some transports (like WebSocket) support full-duplex communication
    with message callbacks.
    """

    @abstractmethod
    async def start(self, config: TransportConfig) -> None:
        """Start the transport connection."""
        ...

    @abstractmethod
    async def stop(self) -> None:
        """Stop the transport connection."""
        ...

    @abstractmethod
    async def send(
        self,
        message: Dict[str, Any],
        timeout: Optional[float] = None,
    ) -> None:
        """Send a message over the transport."""
        ...

    @abstractmethod
    def on_message(self, handler: MessageHandler) -> None:
        """
        Register a message handler.

        Args:
            handler: Async callable that receives messages.
        """
        ...

    @abstractmethod
    def on_error(self, handler: MessageHandler) -> None:
        """
        Register an error handler.

        Args:
            handler: Async callable that receives errors.
        """
        ...

    @abstractmethod
    def on_close(self, handler: MessageHandler) -> None:
        """
        Register a close handler.

        Args:
            handler: Async callable called when transport closes.
        """
        ...

    @property
    @abstractmethod
    def is_open(self) -> bool:
        """Check if transport is currently open."""
        ...

    @abstractmethod
    async def wait_closed(self) -> None:
        """Wait for the transport to close."""
        ...
