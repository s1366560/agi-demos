"""Tests for Resource HTML caching in MCP App tools.

This test file follows TDD methodology:
1. Write failing test first (RED)
2. Implement minimal code to pass (GREEN)
3. Refactor while keeping tests passing (REFACTOR)

The tests verify that resource HTML is cached to reduce UI latency
when MCP App tools return UI content.
"""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def make_tool_info(
    name: str = "ui_tool",
    description: str = "Test UI tool",
    resource_uri: str = "app://ui-tool",
) -> dict:
    """Helper to create tool_info dict for SandboxMCPServerToolAdapter."""
    tool_info = {
        "name": name,
        "description": description,
        "input_schema": {"type": "object"},
    }
    if resource_uri:
        tool_info["_meta"] = {"ui": {"resourceUri": resource_uri}}
    return tool_info


class TestResourceHTMLCaching:
    """Test Resource HTML caching functionality."""

    @pytest.mark.asyncio
    async def test_fetch_resource_html_caches_result(self):
        """
        RED Test: Verify that fetch_resource_html caches the result.
        """
        from src.infrastructure.mcp.sandbox_tool_adapter import SandboxMCPServerToolAdapter

        # Mock sandbox adapter
        mock_adapter = AsyncMock()
        mock_adapter.read_resource = AsyncMock(return_value="<html>Cached</html>")

        # Create adapter with UI metadata
        tool = SandboxMCPServerToolAdapter(
            sandbox_adapter=mock_adapter,
            sandbox_id="sandbox-1",
            server_name="test-server",
            tool_info=make_tool_info(),
        )

        # First fetch
        html1 = await tool.fetch_resource_html()

        # Second fetch (should use cache)
        html2 = await tool.fetch_resource_html()

        # Assert: Both should return same content
        assert html1 == "<html>Cached</html>"
        assert html2 == html1

        # Assert: read_resource should only be called once (cache hit on second)
        assert mock_adapter.read_resource.call_count == 1

    @pytest.mark.asyncio
    async def test_cache_respects_ttl(self):
        """
        Test that cached HTML expires after TTL.
        """
        from src.infrastructure.mcp.sandbox_tool_adapter import SandboxMCPServerToolAdapter

        mock_adapter = AsyncMock()

        # First call returns old content, second returns new
        call_count = [0]

        async def mock_read_resource(*args, **kwargs):
            call_count[0] += 1
            return f"<html>Version {call_count[0]}</html>"

        mock_adapter.read_resource = mock_read_resource

        tool = SandboxMCPServerToolAdapter(
            sandbox_adapter=mock_adapter,
            sandbox_id="sandbox-1",
            server_name="test-server",
            tool_info=make_tool_info(),
            cache_ttl_seconds=0.1,  # 100ms TTL for testing
        )

        # First fetch
        html1 = await tool.fetch_resource_html()
        assert "Version 1" in html1

        # Immediate second fetch (cache hit)
        html2 = await tool.fetch_resource_html()
        assert "Version 1" in html2  # Still cached

        # Wait for TTL to expire
        import asyncio

        await asyncio.sleep(0.15)

        # Third fetch (cache miss, should fetch new)
        html3 = await tool.fetch_resource_html()
        assert "Version 2" in html3  # Fresh content

    @pytest.mark.asyncio
    async def test_cache_can_be_invalidated(self):
        """
        Test that cache can be manually invalidated.
        """
        from src.infrastructure.mcp.sandbox_tool_adapter import SandboxMCPServerToolAdapter

        mock_adapter = AsyncMock()
        call_count = [0]

        async def mock_read_resource(*args, **kwargs):
            call_count[0] += 1
            return f"<html>Content {call_count[0]}</html>"

        mock_adapter.read_resource = mock_read_resource

        tool = SandboxMCPServerToolAdapter(
            sandbox_adapter=mock_adapter,
            sandbox_id="sandbox-1",
            server_name="test-server",
            tool_info=make_tool_info(),
        )

        # First fetch
        html1 = await tool.fetch_resource_html()
        assert call_count[0] == 1

        # Invalidate cache
        tool.invalidate_resource_cache()

        # Second fetch (should refetch after invalidation)
        html2 = await tool.fetch_resource_html()
        assert call_count[0] == 2  # Should have made another call

    @pytest.mark.asyncio
    async def test_no_caching_when_ttl_is_zero(self):
        """
        Test that caching is disabled when TTL is 0.
        """
        from src.infrastructure.mcp.sandbox_tool_adapter import SandboxMCPServerToolAdapter

        mock_adapter = AsyncMock()
        mock_adapter.read_resource = AsyncMock(return_value="<html>Fresh</html>")

        tool = SandboxMCPServerToolAdapter(
            sandbox_adapter=mock_adapter,
            sandbox_id="sandbox-1",
            server_name="test-server",
            tool_info=make_tool_info(),
            cache_ttl_seconds=0,  # Disable caching
        )

        # Multiple fetches
        await tool.fetch_resource_html()
        await tool.fetch_resource_html()
        await tool.fetch_resource_html()

        # Assert: Each fetch should call read_resource (no caching)
        assert mock_adapter.read_resource.call_count == 3

    @pytest.mark.asyncio
    async def test_cache_handles_fetch_errors_gracefully(self):
        """
        Test that cache handles fetch errors without caching failures.
        """
        from src.infrastructure.mcp.sandbox_tool_adapter import SandboxMCPServerToolAdapter

        mock_adapter = AsyncMock()
        call_count = [0]

        async def mock_read_resource(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise Exception("Network error")
            return "<html>Success</html>"

        mock_adapter.read_resource = mock_read_resource

        tool = SandboxMCPServerToolAdapter(
            sandbox_adapter=mock_adapter,
            sandbox_id="sandbox-1",
            server_name="test-server",
            tool_info=make_tool_info(),
        )

        # First fetch (error)
        html1 = await tool.fetch_resource_html()
        assert "Error" in html1 or html1 == ""  # Should return error placeholder

        # Second fetch (should retry, not use cached error)
        html2 = await tool.fetch_resource_html()
        assert "Success" in html2

    @pytest.mark.asyncio
    async def test_prefetch_html_runs_in_background(self):
        """
        Test that prefetch_html runs without blocking.
        """
        from src.infrastructure.mcp.sandbox_tool_adapter import SandboxMCPServerToolAdapter

        mock_adapter = AsyncMock()
        mock_adapter.read_resource = AsyncMock(return_value="<html>Prefetched</html>")

        tool = SandboxMCPServerToolAdapter(
            sandbox_adapter=mock_adapter,
            sandbox_id="sandbox-1",
            server_name="test-server",
            tool_info=make_tool_info(),
        )

        # Prefetch should not block
        import asyncio

        start_time = asyncio.get_event_loop().time()

        # Prefetch runs in background
        tool.prefetch_resource_html()

        elapsed = asyncio.get_event_loop().time() - start_time

        # Should return immediately (not wait for fetch)
        assert elapsed < 0.1  # Should be nearly instant


class TestResourceCacheStats:
    """Test cache statistics."""

    @pytest.mark.asyncio
    async def test_get_cache_stats(self):
        """
        Test that get_cache_stats returns cache statistics.
        """
        from src.infrastructure.mcp.sandbox_tool_adapter import SandboxMCPServerToolAdapter

        mock_adapter = AsyncMock()
        mock_adapter.read_resource = AsyncMock(return_value="<html>Test</html>")

        tool = SandboxMCPServerToolAdapter(
            sandbox_adapter=mock_adapter,
            sandbox_id="sandbox-1",
            server_name="test-server",
            tool_info=make_tool_info(),
        )

        # Get initial stats
        stats = tool.get_cache_stats()

        assert "hits" in stats
        assert "misses" in stats
        assert "last_fetch_at" in stats

        # Fetch once
        await tool.fetch_resource_html()

        # Fetch again (cache hit)
        await tool.fetch_resource_html()

        updated_stats = tool.get_cache_stats()
        assert updated_stats["hits"] >= 1
        assert updated_stats["misses"] >= 1
