"""Unit tests for MCP connection pool.

These tests verify the connection pool implementation for high-concurrency
WebSocket connections.
"""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestMCPConnectionPoolBasics:
    """Test basic connection pool functionality."""

    def test_pool_initialization(self):
        """Test that pool initializes with correct settings."""
        from src.infrastructure.mcp.clients.mcp_connection_pool import MCPConnectionPool

        pool = MCPConnectionPool(url="ws://localhost:8765", pool_size=5)

        assert pool._url == "ws://localhost:8765"
        assert pool._pool_size == 5
        assert pool._created_count == 0
        assert pool.available_count == 0

    def test_pool_default_size(self):
        """Test that pool has default size of 3."""
        from src.infrastructure.mcp.clients.mcp_connection_pool import MCPConnectionPool

        pool = MCPConnectionPool(url="ws://localhost:8765")

        assert pool._pool_size == 3

    @pytest.mark.asyncio
    async def test_get_connection_creates_new(self):
        """Test that get_connection creates a new connection when pool is empty."""
        from src.infrastructure.mcp.clients.mcp_connection_pool import MCPConnectionPool

        pool = MCPConnectionPool(url="ws://localhost:8765", pool_size=3)

        # Mock MCPWebSocketClient
        with patch(
            "src.infrastructure.mcp.clients.mcp_connection_pool.MCPWebSocketClient"
        ) as mock_client_class:
            mock_client = MagicMock()
            mock_client.connect = AsyncMock(return_value=True)
            mock_client_class.return_value = mock_client

            conn = await pool.get_connection()

            assert conn is not None
            assert pool._created_count == 1
            mock_client.connect.assert_called_once()

    @pytest.mark.asyncio
    async def test_return_connection(self):
        """Test that return_connection puts connection back in pool."""
        from src.infrastructure.mcp.clients.mcp_connection_pool import MCPConnectionPool

        pool = MCPConnectionPool(url="ws://localhost:8765", pool_size=3)

        mock_client = MagicMock()
        mock_client.is_connected = True

        await pool.return_connection(mock_client)

        assert pool.available_count == 1

    @pytest.mark.asyncio
    async def test_get_connection_reuses_from_pool(self):
        """Test that get_connection reuses available connection from pool."""
        from src.infrastructure.mcp.clients.mcp_connection_pool import MCPConnectionPool

        pool = MCPConnectionPool(url="ws://localhost:8765", pool_size=3)

        mock_client = MagicMock()
        mock_client.is_connected = True

        # Return a connection to the pool
        await pool.return_connection(mock_client)

        # Get connection should reuse the returned one
        conn = await pool.get_connection()

        assert conn is mock_client
        assert pool.available_count == 0


class TestConnectionPoolSizeLimits:
    """Test pool size limit behavior."""

    @pytest.mark.asyncio
    async def test_pool_respects_max_size(self):
        """Test that pool doesn't create more than pool_size connections."""
        from src.infrastructure.mcp.clients.mcp_connection_pool import MCPConnectionPool

        pool = MCPConnectionPool(url="ws://localhost:8765", pool_size=2)

        with patch(
            "src.infrastructure.mcp.clients.mcp_connection_pool.MCPWebSocketClient"
        ) as mock_client_class:
            mock_client = MagicMock()
            mock_client.connect = AsyncMock(return_value=True)
            mock_client.is_connected = True
            mock_client_class.return_value = mock_client

            # Get first connection
            conn1 = await pool.get_connection()
            assert pool._created_count == 1

            # Get second connection
            conn2 = await pool.get_connection()
            assert pool._created_count == 2

            # Both should be created
            assert conn1 is not None
            assert conn2 is not None

    @pytest.mark.asyncio
    async def test_pool_waits_when_exhausted(self):
        """Test that get_connection waits when pool is exhausted."""
        from src.infrastructure.mcp.clients.mcp_connection_pool import MCPConnectionPool

        pool = MCPConnectionPool(url="ws://localhost:8765", pool_size=2)

        with patch(
            "src.infrastructure.mcp.clients.mcp_connection_pool.MCPWebSocketClient"
        ) as mock_client_class:
            mock_client = MagicMock()
            mock_client.connect = AsyncMock(return_value=True)
            mock_client.is_connected = True
            mock_client_class.return_value = mock_client

            # Exhaust the pool
            conn1 = await pool.get_connection()
            conn2 = await pool.get_connection()

            # Third request should wait
            got_connection = False

            async def get_and_return():
                nonlocal got_connection
                conn = await pool.get_connection()
                got_connection = True
                await pool.return_connection(conn)

            # Start the waiting task
            task = asyncio.create_task(get_and_return())

            # Wait a bit, then return a connection
            await asyncio.sleep(0.1)
            await pool.return_connection(conn1)

            # Wait for task to complete
            await asyncio.wait_for(task, timeout=1.0)

            assert got_connection


class TestConnectionPoolDisconnect:
    """Test handling of disconnected connections."""

    @pytest.mark.asyncio
    async def test_return_disconnected_connection_not_pooled(self):
        """Test that disconnected connections are not returned to pool."""
        from src.infrastructure.mcp.clients.mcp_connection_pool import MCPConnectionPool

        pool = MCPConnectionPool(url="ws://localhost:8765", pool_size=3)

        mock_client = MagicMock()
        mock_client.is_connected = False
        mock_client.disconnect = AsyncMock()

        await pool.return_connection(mock_client)

        # Disconnected connection should not be in pool
        assert pool.available_count == 0
        mock_client.disconnect.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_connection_skips_disconnected(self):
        """Test that get_connection skips disconnected connections in pool."""
        from src.infrastructure.mcp.clients.mcp_connection_pool import MCPConnectionPool

        pool = MCPConnectionPool(url="ws://localhost:8765", pool_size=3)

        # Add a disconnected connection to the pool directly
        mock_disconnected = MagicMock()
        mock_disconnected.is_connected = False
        mock_disconnected.disconnect = AsyncMock()
        await pool._connections.put(mock_disconnected)

        with patch(
            "src.infrastructure.mcp.clients.mcp_connection_pool.MCPWebSocketClient"
        ) as mock_client_class:
            mock_new_client = MagicMock()
            mock_new_client.connect = AsyncMock(return_value=True)
            mock_new_client.is_connected = True
            mock_client_class.return_value = mock_new_client

            # Get connection should create new one since pooled one is disconnected
            conn = await pool.get_connection()

            # Should have created a new connection
            mock_client_class.assert_called_once()
            assert conn is mock_new_client
            # Disconnected client should be cleaned up
            mock_disconnected.disconnect.assert_called()


class TestConnectionPoolConcurrency:
    """Test concurrent access to the pool."""

    @pytest.mark.asyncio
    async def test_concurrent_get_connection(self):
        """Test concurrent get_connection calls."""
        from src.infrastructure.mcp.clients.mcp_connection_pool import MCPConnectionPool

        pool = MCPConnectionPool(url="ws://localhost:8765", pool_size=5)

        with patch(
            "src.infrastructure.mcp.clients.mcp_connection_pool.MCPWebSocketClient"
        ) as mock_client_class:
            # Create unique mock for each call
            call_count = 0

            def create_mock(*args, **kwargs):
                nonlocal call_count
                call_count += 1
                mock = MagicMock()
                mock.connect = AsyncMock(return_value=True)
                mock.is_connected = True
                mock.id = call_count  # Unique identifier
                return mock

            mock_client_class.side_effect = create_mock

            # Concurrent get_connection calls
            results = await asyncio.gather(
                pool.get_connection(),
                pool.get_connection(),
                pool.get_connection(),
            )

            assert len(results) == 3
            # All should be unique connections
            ids = [c.id for c in results]
            assert len(set(ids)) == 3

    @pytest.mark.asyncio
    async def test_concurrent_get_and_return(self):
        """Test concurrent get and return operations."""
        from src.infrastructure.mcp.clients.mcp_connection_pool import MCPConnectionPool

        pool = MCPConnectionPool(url="ws://localhost:8765", pool_size=3)

        with patch(
            "src.infrastructure.mcp.clients.mcp_connection_pool.MCPWebSocketClient"
        ) as mock_client_class:
            mock_client = MagicMock()
            mock_client.connect = AsyncMock(return_value=True)
            mock_client.is_connected = True
            mock_client_class.return_value = mock_client

            async def get_use_return():
                conn = await pool.get_connection()
                await asyncio.sleep(0.01)  # Simulate use
                await pool.return_connection(conn)

            # Run many concurrent operations
            await asyncio.gather(*[get_use_return() for _ in range(10)])

            # Should not exceed max connections created
            assert pool._created_count <= pool._pool_size


class TestConnectionPoolClose:
    """Test pool cleanup."""

    @pytest.mark.asyncio
    async def test_close_all_connections(self):
        """Test that close_all closes all connections."""
        from src.infrastructure.mcp.clients.mcp_connection_pool import MCPConnectionPool

        pool = MCPConnectionPool(url="ws://localhost:8765", pool_size=3)

        # Add some mock connections to the pool
        mock_clients = []
        for _ in range(3):
            mock_client = MagicMock()
            mock_client.is_connected = True
            mock_client.disconnect = AsyncMock()
            mock_clients.append(mock_client)
            await pool._connections.put(mock_client)

        assert pool.available_count == 3

        await pool.close_all()

        # All should be disconnected
        for mock_client in mock_clients:
            mock_client.disconnect.assert_called_once()

        # Pool should be empty
        assert pool.available_count == 0

    @pytest.mark.asyncio
    async def test_close_all_handles_disconnected(self):
        """Test that close_all handles already disconnected connections."""
        from src.infrastructure.mcp.clients.mcp_connection_pool import MCPConnectionPool

        pool = MCPConnectionPool(url="ws://localhost:8765", pool_size=3)

        # Add a mix of connected and disconnected
        mock_connected = MagicMock()
        mock_connected.is_connected = True
        mock_connected.disconnect = AsyncMock()

        mock_disconnected = MagicMock()
        mock_disconnected.is_connected = False
        mock_disconnected.disconnect = AsyncMock()

        await pool._connections.put(mock_connected)
        await pool._connections.put(mock_disconnected)

        await pool.close_all()

        # Both should have disconnect called (even if already disconnected)
        mock_connected.disconnect.assert_called_once()
        # Disconnected ones should also be cleaned up
        assert pool.available_count == 0


class TestConnectionPoolContext:
    """Test pool usage as context manager."""

    @pytest.mark.asyncio
    async def test_pool_context_manager(self):
        """Test using pool with async context manager pattern."""
        from src.infrastructure.mcp.clients.mcp_connection_pool import MCPConnectionPool

        pool = MCPConnectionPool(url="ws://localhost:8765", pool_size=3)

        with patch(
            "src.infrastructure.mcp.clients.mcp_connection_pool.MCPWebSocketClient"
        ) as mock_client_class:
            mock_client = MagicMock()
            mock_client.connect = AsyncMock(return_value=True)
            mock_client.is_connected = True
            mock_client_class.return_value = mock_client

            # Use the pool's connection context
            async with pool.connection() as conn:
                assert conn is not None
                assert pool.available_count == 0  # Connection is in use

            # After context, connection should be returned
            assert pool.available_count == 1

    @pytest.mark.asyncio
    async def test_pool_context_returns_on_exception(self):
        """Test that connection is returned even if exception occurs."""
        from src.infrastructure.mcp.clients.mcp_connection_pool import MCPConnectionPool

        pool = MCPConnectionPool(url="ws://localhost:8765", pool_size=3)

        with patch(
            "src.infrastructure.mcp.clients.mcp_connection_pool.MCPWebSocketClient"
        ) as mock_client_class:
            mock_client = MagicMock()
            mock_client.connect = AsyncMock(return_value=True)
            mock_client.is_connected = True
            mock_client_class.return_value = mock_client

            try:
                async with pool.connection() as conn:
                    raise ValueError("Test error")
            except ValueError:
                pass

            # Connection should still be returned
            assert pool.available_count == 1


class TestConnectionPoolStats:
    """Test pool statistics."""

    def test_available_count(self):
        """Test available_count property."""
        from src.infrastructure.mcp.clients.mcp_connection_pool import MCPConnectionPool

        pool = MCPConnectionPool(url="ws://localhost:8765", pool_size=3)

        assert pool.available_count == 0

        # Add mock connections
        for _ in range(2):
            mock_client = MagicMock()
            pool._connections.put_nowait(mock_client)

        assert pool.available_count == 2

    @pytest.mark.asyncio
    async def test_created_count_tracking(self):
        """Test that created_count tracks total connections created."""
        from src.infrastructure.mcp.clients.mcp_connection_pool import MCPConnectionPool

        pool = MCPConnectionPool(url="ws://localhost:8765", pool_size=5)

        with patch(
            "src.infrastructure.mcp.clients.mcp_connection_pool.MCPWebSocketClient"
        ) as mock_client_class:
            mock_client = MagicMock()
            mock_client.connect = AsyncMock(return_value=True)
            mock_client.is_connected = True
            mock_client_class.return_value = mock_client

            # Create some connections
            conn1 = await pool.get_connection()
            conn2 = await pool.get_connection()

            assert pool._created_count == 2

            # Return and reuse
            await pool.return_connection(conn1)
            conn3 = await pool.get_connection()

            # Should still be 2 (reused conn1)
            assert pool._created_count == 2
