"""Tests for incremental tool discovery with version/hash tracking.

This test file follows TDD methodology:
1. Write failing test first (RED)
2. Implement minimal code to pass (GREEN)
3. Refactor while keeping tests passing (REFACTOR)

The tests verify that tool discovery can be done incrementally by
checking version hashes, avoiding full rediscovery when not needed.
"""

from unittest.mock import AsyncMock

import pytest


class TestMCPToolRegistry:
    """Test MCPToolRegistry for incremental discovery."""

    def test_registry_exists(self):
        """
        RED Test: Verify that MCPToolRegistry class exists.
        """
        from src.infrastructure.mcp.tool_registry import MCPToolRegistry

        assert MCPToolRegistry is not None

    def test_compute_tools_hash(self):
        """
        Test that tools hash is computed correctly.
        """
        from src.infrastructure.mcp.tool_registry import MCPToolRegistry

        registry = MCPToolRegistry()

        tools = [
            {"name": "tool1", "description": "First tool"},
            {"name": "tool2", "description": "Second tool"},
        ]

        hash1 = registry.compute_tools_hash(tools)
        hash2 = registry.compute_tools_hash(tools)

        # Same tools should produce same hash
        assert hash1 == hash2
        assert len(hash1) == 64  # SHA256 hex digest length

    def test_hash_changes_when_tools_change(self):
        """
        Test that hash changes when tools list changes.
        """
        from src.infrastructure.mcp.tool_registry import MCPToolRegistry

        registry = MCPToolRegistry()

        tools_v1 = [{"name": "tool1", "description": "First tool"}]
        tools_v2 = [
            {"name": "tool1", "description": "First tool"},
            {"name": "tool2", "description": "Second tool"},
        ]

        hash1 = registry.compute_tools_hash(tools_v1)
        hash2 = registry.compute_tools_hash(tools_v2)

        # Different tools should produce different hash
        assert hash1 != hash2

    def test_stored_hash_persists(self):
        """
        Test that stored hash persists across calls.
        """
        from src.infrastructure.mcp.tool_registry import MCPToolRegistry

        registry = MCPToolRegistry()

        tools = [{"name": "tool1"}]
        hash_value = registry.compute_tools_hash(tools)

        # Store hash for server
        registry.store_server_hash("sandbox-1", "my-server", hash_value)

        # Retrieve stored hash
        stored = registry.get_server_hash("sandbox-1", "my-server")

        assert stored == hash_value

    def test_check_updates_returns_false_when_unchanged(self):
        """
        Test that check_updates returns False when tools haven't changed.
        """
        from src.infrastructure.mcp.tool_registry import MCPToolRegistry

        registry = MCPToolRegistry()

        tools = [{"name": "tool1"}]
        hash_value = registry.compute_tools_hash(tools)

        # Store hash
        registry.store_server_hash("sandbox-1", "my-server", hash_value)

        # Check with same tools
        has_updates = registry.check_updates("sandbox-1", "my-server", tools)

        assert has_updates is False

    def test_check_updates_returns_true_when_changed(self):
        """
        Test that check_updates returns True when tools have changed.
        """
        from src.infrastructure.mcp.tool_registry import MCPToolRegistry

        registry = MCPToolRegistry()

        old_tools = [{"name": "tool1"}]
        new_tools = [{"name": "tool1"}, {"name": "tool2"}]

        old_hash = registry.compute_tools_hash(old_tools)
        registry.store_server_hash("sandbox-1", "my-server", old_hash)

        # Check with new tools
        has_updates = registry.check_updates("sandbox-1", "my-server", new_tools)

        assert has_updates is True


class TestIncrementalDiscovery:
    """Test incremental discovery integration."""

    @pytest.mark.asyncio
    async def test_discover_only_changed_servers(self):
        """
        Test that discovery only runs for changed servers.
        """
        from src.infrastructure.mcp.tool_registry import MCPToolRegistry

        registry = MCPToolRegistry()

        # Mock sandbox adapter
        mock_adapter = AsyncMock()

        # Track which servers were discovered
        discovered_servers = []

        async def track_discovery(**kwargs):
            server_name = kwargs.get("arguments", {}).get("name", "")
            discovered_servers.append(server_name)
            return {"content": [{"type": "text", "text": f'[{{"name": "{server_name}_tool1"}}]'}]}

        mock_adapter.call_tool = track_discovery

        # First discovery - both servers
        tools_server1 = [{"name": "server1_tool1"}]
        tools_server2 = [{"name": "server2_tool1"}]

        registry.store_server_hash("sb-1", "server1", registry.compute_tools_hash(tools_server1))
        registry.store_server_hash("sb-1", "server2", registry.compute_tools_hash(tools_server2))

        # Simulate server1 changed, server2 unchanged
        new_tools_server1 = [{"name": "server1_tool1"}, {"name": "server1_tool2"}]

        # Check which need update
        needs_update_1 = registry.check_updates("sb-1", "server1", new_tools_server1)
        needs_update_2 = registry.check_updates("sb-1", "server2", tools_server2)

        assert needs_update_1 is True  # Changed
        assert needs_update_2 is False  # Unchanged

    @pytest.mark.asyncio
    async def test_full_discovery_on_first_run(self):
        """
        Test that full discovery happens on first run (no stored hash).
        """
        from src.infrastructure.mcp.tool_registry import MCPToolRegistry

        registry = MCPToolRegistry()

        tools = [{"name": "tool1"}]

        # First check - no stored hash
        has_updates = registry.check_updates("sb-1", "new-server", tools)

        # Should return True (needs discovery)
        assert has_updates is True

    @pytest.mark.asyncio
    async def test_invalidate_server_hash(self):
        """
        Test that server hash can be invalidated.
        """
        from src.infrastructure.mcp.tool_registry import MCPToolRegistry

        registry = MCPToolRegistry()

        tools = [{"name": "tool1"}]
        hash_value = registry.compute_tools_hash(tools)

        registry.store_server_hash("sb-1", "my-server", hash_value)

        # Verify stored
        assert registry.get_server_hash("sb-1", "my-server") == hash_value

        # Invalidate
        registry.invalidate_server_hash("sb-1", "my-server")

        # Should return None
        assert registry.get_server_hash("sb-1", "my-server") is None

    @pytest.mark.asyncio
    async def test_invalidate_all_for_sandbox(self):
        """
        Test that all server hashes for a sandbox can be invalidated.
        """
        from src.infrastructure.mcp.tool_registry import MCPToolRegistry

        registry = MCPToolRegistry()

        tools = [{"name": "tool1"}]
        hash_value = registry.compute_tools_hash(tools)

        registry.store_server_hash("sb-1", "server1", hash_value)
        registry.store_server_hash("sb-1", "server2", hash_value)
        registry.store_server_hash("sb-2", "server1", hash_value)

        # Invalidate all for sb-1
        registry.invalidate_sandbox("sb-1")

        # sb-1 servers should be cleared
        assert registry.get_server_hash("sb-1", "server1") is None
        assert registry.get_server_hash("sb-1", "server2") is None

        # sb-2 should still have hash
        assert registry.get_server_hash("sb-2", "server1") == hash_value


class TestRegistryStats:
    """Test registry statistics."""

    def test_get_registry_stats(self):
        """
        Test that get_stats returns registry statistics.
        """
        from src.infrastructure.mcp.tool_registry import MCPToolRegistry

        registry = MCPToolRegistry()

        stats = registry.get_stats()

        assert "total_servers" in stats
        assert "total_hashes" in stats
        assert "cache_hits" in stats
        assert "cache_misses" in stats

    def test_stats_track_operations(self):
        """
        Test that stats track cache operations.
        """
        from src.infrastructure.mcp.tool_registry import MCPToolRegistry

        registry = MCPToolRegistry()

        tools = [{"name": "tool1"}]
        hash_value = registry.compute_tools_hash(tools)

        # Store hash
        registry.store_server_hash("sb-1", "server1", hash_value)

        # Check updates (cache hit)
        registry.check_updates("sb-1", "server1", tools)

        # Check new server (cache miss)
        registry.check_updates("sb-1", "server2", tools)

        stats = registry.get_stats()

        assert stats["cache_hits"] >= 1
        assert stats["cache_misses"] >= 1
