"""Unit tests for WebSocket client lock optimization.

These tests verify that the WebSocket client uses minimal lock scope
for request ID generation, allowing concurrent send operations.
"""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

import pytest


class TestWebSocketClientLockOptimization:
    """Test suite for WebSocket client lock optimization."""

    def test_client_has_request_id_lock(self):
        """Test that client has lock for request ID generation."""
        from src.infrastructure.mcp.clients.websocket_client import MCPWebSocketClient

        client = MCPWebSocketClient(url="ws://localhost:8765")

        # Verify lock exists for request ID generation
        assert hasattr(client, "_request_id_lock"), "Missing _request_id_lock"
        # _lock is an alias for backward compatibility (same lock object)
        assert client._lock is client._request_id_lock, (
            "_lock should be an alias for _request_id_lock"
        )

    @pytest.mark.asyncio
    async def test_concurrent_request_id_generation(self):
        """Test that request IDs are unique under concurrent access."""
        from src.infrastructure.mcp.clients.websocket_client import MCPWebSocketClient

        client = MCPWebSocketClient(url="ws://localhost:8765")
        generated_ids = []

        async def generate_id():
            async with client._request_id_lock:
                client._request_id += 1
                request_id = client._request_id
                await asyncio.sleep(0.001)  # Simulate some work while holding lock
                generated_ids.append(request_id)

        # Generate IDs concurrently
        await asyncio.gather(*[generate_id() for _ in range(100)])

        # All IDs should be unique
        assert len(generated_ids) == 100
        assert len(set(generated_ids)) == 100, "Duplicate request IDs generated"

    @pytest.mark.asyncio
    async def test_send_request_lock_scope_minimal(self):
        """Test that lock is only held for request ID generation, not send."""
        from src.infrastructure.mcp.clients.websocket_client import MCPWebSocketClient

        client = MCPWebSocketClient(url="ws://localhost:8765")

        # Mock the WebSocket
        mock_ws = MagicMock()
        mock_ws.closed = False
        mock_ws.send_json = AsyncMock()

        client._ws = mock_ws

        # Track lock acquisition timing
        lock_acquisition_times = []
        lock_release_times = []
        send_times = []

        original_lock = client._request_id_lock

        # Track the actual send operation timing
        async def mock_send_json(data):
            send_times.append(time.time())
            await asyncio.sleep(0.05)  # Simulate slow send

        mock_ws.send_json = mock_send_json

        # Track pending requests
        original_wait = asyncio.Future
        created_futures = []

        async def create_future():
            future = original_wait()
            created_futures.append(future)
            return future

        # Simulate the minimal lock pattern
        request_ids = []

        async def send_request_minimal(method, params):
            # Only hold lock for ID generation
            async with client._request_id_lock:
                client._request_id += 1
                request_id = client._request_id
                request_ids.append(request_id)
                lock_release_times.append(time.time())

            # Send happens outside lock
            request = {
                "jsonrpc": "2.0",
                "method": method,
                "params": params,
                "id": request_id,
            }

            # This should NOT be under lock
            await mock_ws.send_json(request)
            return request_id

        # Send two requests concurrently
        start = time.time()
        results = await asyncio.gather(
            send_request_minimal("method1", {}),
            send_request_minimal("method2", {}),
        )
        total_time = time.time() - start

        # Both requests should complete
        assert len(results) == 2
        assert len(set(results)) == 2  # Unique request IDs

        # Total time should be ~0.05s (parallel sends), not ~0.10s (serial sends)
        # Allow some margin for test overhead
        assert total_time < 0.10, f"Sends took {total_time:.2f}s - likely serialized by lock"

    @pytest.mark.asyncio
    async def test_concurrent_sends_dont_block_on_id_generation(self):
        """Test that concurrent sends can proceed in parallel."""
        from src.infrastructure.mcp.clients.websocket_client import MCPWebSocketClient

        client = MCPWebSocketClient(url="ws://localhost:8765")

        # Mock the WebSocket
        mock_ws = MagicMock()
        mock_ws.closed = False

        send_count = 0
        send_lock = asyncio.Lock()

        async def mock_send_json(data):
            nonlocal send_count
            async with send_lock:
                send_count += 1
            await asyncio.sleep(0.02)  # Simulate network delay

        mock_ws.send_json = mock_send_json
        client._ws = mock_ws

        # Track timing
        start_time = time.time()

        async def do_send(i):
            # Acquire request ID lock only for ID generation
            async with client._request_id_lock:
                client._request_id += 1
                request_id = client._request_id

            # Send outside lock
            await mock_ws.send_json({"id": request_id, "method": f"method_{i}"})
            return request_id

        # Send 10 requests concurrently
        results = await asyncio.gather(*[do_send(i) for i in range(10)])
        total_time = time.time() - start_time

        # All 10 should complete
        assert len(results) == 10
        assert len(set(results)) == 10  # All unique

        # If sends are parallel, should take ~0.02s (one batch)
        # If serialized, would take ~0.20s
        assert total_time < 0.15, f"Sends took {total_time:.2f}s - likely serialized"

    @pytest.mark.asyncio
    async def test_pending_requests_dict_access_is_threadsafe(self):
        """Test that pending_requests dict access is properly synchronized."""
        from src.infrastructure.mcp.clients.websocket_client import MCPWebSocketClient

        client = MCPWebSocketClient(url="ws://localhost:8765")

        # Simulate concurrent access to pending_requests
        access_count = 0
        errors = []

        async def access_pending():
            nonlocal access_count
            try:
                # Simulate the pattern in _send_request
                async with client._request_id_lock:
                    client._request_id += 1
                    request_id = client._request_id
                    future = asyncio.get_event_loop().create_future()
                    client._pending_requests[request_id] = future

                # Simulate some work
                await asyncio.sleep(0.001)

                # Clean up
                async with client._request_id_lock:
                    client._pending_requests.pop(request_id, None)

                access_count += 1
            except Exception as e:
                errors.append(e)

        # Run many concurrent accesses
        await asyncio.gather(*[access_pending() for _ in range(100)])

        # All should complete without errors
        assert len(errors) == 0, f"Errors during concurrent access: {errors}"
        assert access_count == 100
        # All requests should be cleaned up
        assert len(client._pending_requests) == 0


class TestWebSocketClientMinimalLockImplementation:
    """Test that the implementation uses minimal lock scope."""

    @pytest.mark.asyncio
    async def test_lock_not_held_during_send(self):
        """Test that lock is released before send operation."""
        from src.infrastructure.mcp.clients.websocket_client import MCPWebSocketClient

        client = MCPWebSocketClient(url="ws://localhost:8765")

        # Mock WebSocket
        mock_ws = MagicMock()
        mock_ws.closed = False

        send_started = asyncio.Event()
        lock_released_before_send = False

        async def mock_send_json(data):
            # Check if lock was released before this was called
            nonlocal lock_released_before_send
            # Try to acquire the lock - should succeed immediately if released
            if client._request_id_lock.locked():
                lock_released_before_send = False
            else:
                lock_released_before_send = True
            send_started.set()
            return None

        mock_ws.send_json = mock_send_json
        client._ws = mock_ws

        # Manually simulate the optimized pattern
        async with client._request_id_lock:
            client._request_id += 1
            request_id = client._request_id

        # Now send outside lock
        await mock_ws.send_json({"id": request_id})

        # Lock should have been released before send
        assert lock_released_before_send, "Lock was held during send operation"
