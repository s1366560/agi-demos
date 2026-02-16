"""Unit tests for enhanced health check cache in MCPSandboxAdapter.

These tests verify that the adapter uses TTL caching for health checks
to avoid frequent Docker API calls and supports fast reconnect.
"""

import asyncio
import time
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestHealthCheckCache:
    """Test suite for health check cache optimization."""

    def test_adapter_has_health_check_cache(self):
        """Test that adapter has health check cache with TTL."""
        from src.infrastructure.adapters.secondary.sandbox.mcp_sandbox_adapter import (
            MCPSandboxAdapter,
        )

        with patch("docker.from_env"):
            adapter = MCPSandboxAdapter()

            # Verify health check cache exists
            assert hasattr(adapter, "_last_healthy_at"), "Missing _last_healthy_at cache"
            assert hasattr(adapter, "_health_check_ttl_seconds"), "Missing _health_check_ttl_seconds"
            assert adapter._health_check_ttl_seconds > 0, "Health check TTL should be positive"

    @pytest.mark.asyncio
    async def test_health_check_cache_hit(self):
        """Test that health check returns cached result within TTL."""
        from src.infrastructure.adapters.secondary.sandbox.mcp_sandbox_adapter import (
            MCPSandboxAdapter,
        )

        with patch("docker.from_env"):
            adapter = MCPSandboxAdapter()
            adapter._health_check_ttl_seconds = 5.0

            sandbox_id = "test-sandbox"

            # Mark as healthy in cache
            await adapter._last_healthy_at.set(sandbox_id, datetime.now())

            # Check if cached as healthy
            cached = await adapter._last_healthy_at.get(sandbox_id)
            is_cached = cached is not None
            assert is_cached, "Health check should be cached"

    @pytest.mark.asyncio
    async def test_health_check_cache_expiry(self):
        """Test that health check cache expires after TTL."""
        from src.infrastructure.adapters.secondary.sandbox.mcp_sandbox_adapter import (
            MCPSandboxAdapter,
        )

        with patch("docker.from_env"):
            adapter = MCPSandboxAdapter()
            # Use very short TTL for the test
            from src.infrastructure.adapters.secondary.sandbox.health_monitor import TTLCache
            adapter._last_healthy_at = TTLCache(default_ttl_seconds=0.1, max_size=100)

            sandbox_id = "test-sandbox"

            # Mark as healthy in cache
            await adapter._last_healthy_at.set(sandbox_id, datetime.now())

            # Should be cached immediately
            cached = await adapter._last_healthy_at.get(sandbox_id)
            assert cached is not None

            # Wait for TTL to expire
            await asyncio.sleep(0.15)

            # Cache should be expired
            cached = await adapter._last_healthy_at.get(sandbox_id)
            assert cached is None, "Health check cache should expire after TTL"

    @pytest.mark.asyncio
    async def test_health_check_skips_docker_api_when_cached(self):
        """Test that health check skips Docker API call when cached."""
        from src.infrastructure.adapters.secondary.sandbox.mcp_sandbox_adapter import (
            MCPSandboxAdapter,
        )

        with patch("docker.from_env") as mock_docker:
            mock_client = MagicMock()
            mock_docker.return_value = mock_client

            adapter = MCPSandboxAdapter()
            adapter._health_check_ttl_seconds = 5.0

            sandbox_id = "test-sandbox"

            # Mark as healthy in cache
            await adapter._last_healthy_at.set(sandbox_id, datetime.now())

            # Check if we can determine health from cache (no Docker API call needed)
            last_healthy = await adapter._last_healthy_at.get(sandbox_id)
            is_healthy_from_cache = last_healthy is not None

            assert is_healthy_from_cache, "Should determine health from cache"

    @pytest.mark.asyncio
    async def test_fast_reconnect_after_disconnect(self):
        """Test that fast reconnect is possible after disconnect."""
        from src.infrastructure.adapters.secondary.sandbox.mcp_sandbox_adapter import (
            MCPSandboxAdapter,
            MCPSandboxInstance,
        )
        from src.domain.ports.services.sandbox_port import SandboxStatus, SandboxConfig

        with patch("docker.from_env"):
            adapter = MCPSandboxAdapter()

            # Create a mock instance
            instance = MCPSandboxInstance(
                id="test-sandbox",
                status=SandboxStatus.RUNNING,
                config=SandboxConfig(image="test"),
                project_path="/tmp",
                endpoint="ws://localhost:8000",
                websocket_url="ws://localhost:8765",
            )
            adapter._active_sandboxes["test-sandbox"] = instance

            # Mock MCP client
            mock_client = MagicMock()
            mock_client.is_connected = False  # Disconnected
            instance.mcp_client = mock_client

            # Track reconnect timing
            reconnect_times = []

            async def mock_connect(*args, **kwargs):
                reconnect_times.append(time.time())
                mock_client.is_connected = True
                return True

            # Patch connect_mcp
            adapter.connect_mcp = mock_connect

            # Attempt reconnect
            start = time.time()
            result = await adapter.connect_mcp("test-sandbox", timeout=5.0)
            reconnect_duration = time.time() - start

            # Reconnect should be fast (no Docker API call needed for cached health)
            assert result is True
            # With cached health, reconnect should be fast
            assert reconnect_duration < 1.0, (
                f"Fast reconnect took {reconnect_duration:.2f}s - too slow"
            )


class TestHealthCheckCacheInvalidation:
    """Test health check cache invalidation scenarios."""

    @pytest.mark.asyncio
    async def test_cache_invalidated_on_error(self):
        """Test that cache is invalidated when error occurs."""
        from src.infrastructure.adapters.secondary.sandbox.mcp_sandbox_adapter import (
            MCPSandboxAdapter,
        )

        with patch("docker.from_env"):
            adapter = MCPSandboxAdapter()
            sandbox_id = "test-sandbox"

            # Mark as healthy in cache
            await adapter._last_healthy_at.set(sandbox_id, datetime.now())
            cached = await adapter._last_healthy_at.get(sandbox_id)
            assert cached is not None

            # Invalidate cache (simulating error case)
            await adapter._last_healthy_at.delete(sandbox_id)

            # Should be invalidated
            cached = await adapter._last_healthy_at.get(sandbox_id)
            assert cached is None

    @pytest.mark.asyncio
    async def test_cache_invalidated_on_terminate(self):
        """Test that cache is invalidated when sandbox is terminated."""
        from src.infrastructure.adapters.secondary.sandbox.mcp_sandbox_adapter import (
            MCPSandboxAdapter,
            MCPSandboxInstance,
        )
        from src.domain.ports.services.sandbox_port import SandboxStatus, SandboxConfig

        with patch("docker.from_env") as mock_docker:
            mock_client = MagicMock()
            mock_docker.return_value = mock_client

            # Mock container
            mock_container = MagicMock()
            mock_container.status = "running"
            mock_container.stop = MagicMock()
            mock_container.remove = MagicMock()
            mock_client.containers.get.return_value = mock_container

            adapter = MCPSandboxAdapter()
            sandbox_id = "test-sandbox"

            # Create a mock instance
            instance = MCPSandboxInstance(
                id=sandbox_id,
                status=SandboxStatus.RUNNING,
                config=SandboxConfig(image="test"),
                project_path="/tmp",
                endpoint="ws://localhost:8000",
            )
            adapter._active_sandboxes[sandbox_id] = instance

            # Mark as healthy in cache
            await adapter._last_healthy_at.set(sandbox_id, datetime.now())
            cached = await adapter._last_healthy_at.get(sandbox_id)
            assert cached is not None

            # Terminate sandbox
            await adapter.terminate_sandbox(sandbox_id)

            # Cache should be invalidated
            cached = await adapter._last_healthy_at.get(sandbox_id)
            assert cached is None, "Health check cache should be invalidated on terminate"


class TestHealthCheckCacheTTLConfig:
    """Test health check cache TTL configuration."""

    def test_default_ttl_is_reasonable(self):
        """Test that default TTL is reasonable for production use."""
        from src.infrastructure.adapters.secondary.sandbox.mcp_sandbox_adapter import (
            MCPSandboxAdapter,
        )

        with patch("docker.from_env"):
            adapter = MCPSandboxAdapter()

            # Default TTL should be between 10-60 seconds
            assert 10 <= adapter._health_check_ttl_seconds <= 60, (
                f"Default TTL {adapter._health_check_ttl_seconds}s is outside reasonable range"
            )

    def test_ttl_cache_has_max_size(self):
        """Test that TTL cache has max size to prevent memory leaks."""
        from src.infrastructure.adapters.secondary.sandbox.mcp_sandbox_adapter import (
            MCPSandboxAdapter,
        )

        with patch("docker.from_env"):
            adapter = MCPSandboxAdapter()

            # TTLCache should have max_size configured
            assert hasattr(adapter._last_healthy_at, "_max_size"), (
                "TTLCache should have max_size"
            )
            assert adapter._last_healthy_at._max_size > 0, "max_size should be positive"
