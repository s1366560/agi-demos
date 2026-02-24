"""MCP Connection Pool for high-concurrency scenarios.

This module provides a pool of WebSocket connections that can be reused
across multiple concurrent operations, improving performance and reducing
connection overhead.
"""

import asyncio
import logging
from contextlib import asynccontextmanager

from src.infrastructure.mcp.clients.websocket_client import MCPWebSocketClient

logger = logging.getLogger(__name__)


class MCPConnectionPool:
    """Pool of WebSocket connections for high-concurrency scenarios.

    This pool manages a set of MCPWebSocketClient connections that can be
    reused across multiple operations. The pool enforces a maximum size
    and handles connection lifecycle (creation, reuse, cleanup).

    Attributes:
        _url: WebSocket URL for connections.
        _pool_size: Maximum number of connections in the pool.
        _connections: Queue of available connections.
        _created_count: Total number of connections created (for stats).
    """

    def __init__(
        self,
        url: str,
        pool_size: int = 3,
        timeout: float = 30.0,
        connect_timeout: float = 10.0,
    ) -> None:
        """Initialize the connection pool.

        Args:
            url: WebSocket URL to connect to.
            pool_size: Maximum number of connections in the pool.
            timeout: Default timeout for operations.
            connect_timeout: Timeout for initial connection.
        """
        self._url = url
        self._pool_size = pool_size
        self._timeout = timeout
        self._connect_timeout = connect_timeout
        self._connections: asyncio.Queue[MCPWebSocketClient] = asyncio.Queue()
        self._lock = asyncio.Lock()
        self._created_count = 0
        self._semaphore = asyncio.Semaphore(pool_size)

    @property
    def available_count(self) -> int:
        """Number of available connections in the pool."""
        return self._connections.qsize()

    @property
    def pool_size(self) -> int:
        """Maximum pool size."""
        return self._pool_size

    async def get_connection(self) -> MCPWebSocketClient:
        """Get a connection from the pool or create a new one.

        If a connection is available in the pool and is still connected,
        it will be reused. Otherwise, a new connection is created.

        The semaphore ensures we don't exceed pool_size concurrent connections.

        Returns:
            A connected MCPWebSocketClient instance.

        Raises:
            ConnectionError: If unable to establish a connection.
        """
        # Wait for a slot in the pool
        await self._semaphore.acquire()

        # Try to get an existing connection
        while not self._connections.empty():
            client = self._connections.get_nowait()

            if client.is_connected:
                logger.debug("Reusing existing connection from pool")
                return client
            else:
                # Connection is dead, clean it up
                logger.debug("Discarding disconnected connection from pool")
                try:
                    await client.disconnect()
                except Exception as e:
                    logger.warning(f"Error disconnecting stale connection: {e}")
                # Decrement created count since we're removing this connection
                async with self._lock:
                    self._created_count -= 1

        # Create a new connection
        async with self._lock:
            self._created_count += 1
            created_num = self._created_count

        logger.debug(f"Creating new connection #{created_num}")
        client = MCPWebSocketClient(
            url=self._url,
            timeout=self._timeout,
        )

        try:
            connected = await client.connect(timeout=self._connect_timeout)
            if not connected:
                raise ConnectionError(f"Failed to connect to {self._url}")
            return client
        except Exception as e:
            # If connection fails, release the semaphore and decrement count
            self._semaphore.release()
            async with self._lock:
                self._created_count -= 1
            raise ConnectionError(f"Failed to create connection: {e}") from e

    async def return_connection(self, client: MCPWebSocketClient) -> None:
        """Return a connection to the pool for reuse.

        If the connection is still active, it's returned to the pool.
        Otherwise, it's disconnected and the semaphore is released.

        Args:
            client: The MCPWebSocketClient to return.
        """
        if not client.is_connected:
            logger.debug("Connection disconnected, not returning to pool")
            try:
                await client.disconnect()
            except Exception as e:
                logger.warning(f"Error disconnecting client: {e}")
            async with self._lock:
                self._created_count -= 1
            self._semaphore.release()
            return

        # Return to pool
        try:
            self._connections.put_nowait(client)
            logger.debug("Connection returned to pool")
        except asyncio.QueueFull:
            # Pool is full, just disconnect
            logger.debug("Pool full, disconnecting connection")
            await client.disconnect()
            async with self._lock:
                self._created_count -= 1

        # Release the semaphore slot
        self._semaphore.release()

    async def close_all(self) -> None:
        """Close all connections in the pool.

        This should be called when the pool is no longer needed to
        properly release resources.
        """
        logger.info(f"Closing all connections in pool ({self.available_count} available)")

        while not self._connections.empty():
            client = self._connections.get_nowait()
            try:
                await client.disconnect()
            except Exception as e:
                logger.warning(f"Error disconnecting client during close_all: {e}")

        async with self._lock:
            self._created_count = 0

        logger.info("All pool connections closed")

    @asynccontextmanager
    async def connection(self):
        """Context manager for getting and returning a connection.

        Usage:
            async with pool.connection() as conn:
                result = await conn.call_tool(...)

        Yields:
            An MCPWebSocketClient connection.

        Raises:
            ConnectionError: If unable to get a connection.
        """
        conn = None
        try:
            conn = await self.get_connection()
            yield conn
        finally:
            if conn is not None:
                await self.return_connection(conn)

    def __repr__(self) -> str:
        """String representation of the pool."""
        return (
            f"MCPConnectionPool(url={self._url!r}, "
            f"pool_size={self._pool_size}, "
            f"available={self.available_count}, "
            f"created={self._created_count})"
        )
