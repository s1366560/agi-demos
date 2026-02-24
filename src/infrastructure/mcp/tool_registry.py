"""MCP Tool Registry for incremental tool discovery.

Provides version/hash-based tracking of MCP server tools to enable
incremental discovery - only re-discover tools when they have changed.
"""

import hashlib
import json
import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class RegistryStats:
    """Statistics for the tool registry."""

    total_servers: int = 0
    total_hashes: int = 0
    cache_hits: int = 0
    cache_misses: int = 0


class MCPToolRegistry:
    """Registry for tracking MCP server tool versions using hash comparison.

    This registry stores the hash of each MCP server's tool list,
    enabling incremental discovery by only re-fetching tools when
    the hash changes.

    Key: (sandbox_id, server_name)
    Value: SHA256 hash of tools list
    """

    def __init__(self) -> None:
        """Initialize the tool registry."""
        self._hashes: dict[tuple[str, str], str] = {}
        self._stats = RegistryStats()

    def compute_tools_hash(self, tools: list[dict[str, Any]]) -> str:
        """Compute a SHA256 hash of the tools list.

        The hash is computed from a normalized JSON representation
        of the tools, ensuring consistent hashing regardless of
        key order or formatting.

        Args:
            tools: List of tool definitions (dicts with name, description, etc.)

        Returns:
            Hex string of SHA256 hash (64 characters)
        """
        # Normalize tools for consistent hashing
        normalized = []
        for tool in sorted(tools, key=lambda t: t.get("name", "")):
            # Only include relevant fields for hash
            normalized.append({
                "name": tool.get("name", ""),
                "description": tool.get("description", ""),
                "input_schema": tool.get("input_schema", tool.get("inputSchema", {})),
            })

        # Compute hash
        json_str = json.dumps(normalized, sort_keys=True)
        return hashlib.sha256(json_str.encode()).hexdigest()

    def store_server_hash(
        self,
        sandbox_id: str,
        server_name: str,
        hash_value: str,
    ) -> None:
        """Store the hash for a server's tools.

        Args:
            sandbox_id: Sandbox container ID
            server_name: MCP server name
            hash_value: SHA256 hash of tools list
        """
        key = (sandbox_id, server_name)
        is_new = key not in self._hashes
        self._hashes[key] = hash_value

        if is_new:
            self._stats.total_servers += 1

        logger.debug(
            "Stored hash for server %s in sandbox %s: %s...",
            server_name, sandbox_id, hash_value[:8]
        )

    def get_server_hash(
        self,
        sandbox_id: str,
        server_name: str,
    ) -> str | None:
        """Get the stored hash for a server's tools.

        Args:
            sandbox_id: Sandbox container ID
            server_name: MCP server name

        Returns:
            Stored hash or None if not found
        """
        key = (sandbox_id, server_name)
        return self._hashes.get(key)

    def check_updates(
        self,
        sandbox_id: str,
        server_name: str,
        current_tools: list[dict[str, Any]],
    ) -> bool:
        """Check if tools have been updated since last discovery.

        Args:
            sandbox_id: Sandbox container ID
            server_name: MCP server name
            current_tools: Current list of tools

        Returns:
            True if tools have changed (or no stored hash), False otherwise
        """
        current_hash = self.compute_tools_hash(current_tools)
        stored_hash = self.get_server_hash(sandbox_id, server_name)

        if stored_hash is None:
            # No stored hash - needs discovery
            self._stats.cache_misses += 1
            logger.debug(
                "No stored hash for server %s in sandbox %s - needs discovery",
                server_name, sandbox_id
            )
            return True

        if stored_hash == current_hash:
            # Hash matches - no updates
            self._stats.cache_hits += 1
            logger.debug(
                "Tools unchanged for server %s in sandbox %s (hash: %s...)",
                server_name, sandbox_id, current_hash[:8]
            )
            return False

        # Hash differs - tools updated
        self._stats.cache_misses += 1
        logger.info(
            "Tools updated for server %s in sandbox %s "
            "(old: %s..., new: %s...)",
            server_name, sandbox_id,
            stored_hash[:8], current_hash[:8]
        )
        return True

    def invalidate_server_hash(
        self,
        sandbox_id: str,
        server_name: str,
    ) -> None:
        """Invalidate the stored hash for a server.

        Args:
            sandbox_id: Sandbox container ID
            server_name: MCP server name
        """
        key = (sandbox_id, server_name)
        if key in self._hashes:
            del self._hashes[key]
            self._stats.total_servers = max(0, self._stats.total_servers - 1)
            logger.debug(
                "Invalidated hash for server %s in sandbox %s",
                server_name, sandbox_id
            )

    def invalidate_sandbox(self, sandbox_id: str) -> int:
        """Invalidate all stored hashes for a sandbox.

        Args:
            sandbox_id: Sandbox container ID

        Returns:
            Number of hashes invalidated
        """
        keys_to_remove = [
            key for key in self._hashes
            if key[0] == sandbox_id
        ]

        for key in keys_to_remove:
            del self._hashes[key]

        self._stats.total_servers -= len(keys_to_remove)
        self._stats.total_servers = max(0, self._stats.total_servers)

        if keys_to_remove:
            logger.debug(
                "Invalidated %d hash(es) for sandbox %s",
                len(keys_to_remove), sandbox_id
            )

        return len(keys_to_remove)

    def get_stats(self) -> dict[str, int]:
        """Get registry statistics.

        Returns:
            Dict with total_servers, total_hashes, cache_hits, cache_misses
        """
        return {
            "total_servers": self._stats.total_servers,
            "total_hashes": len(self._hashes),
            "cache_hits": self._stats.cache_hits,
            "cache_misses": self._stats.cache_misses,
        }

    def clear(self) -> None:
        """Clear all stored hashes and reset statistics."""
        self._hashes.clear()
        self._stats = RegistryStats()
        logger.debug("Cleared all stored hashes")


# Global registry instance
_registry: MCPToolRegistry | None = None


def get_tool_registry() -> MCPToolRegistry:
    """Get the global tool registry instance.

    Returns:
        MCPToolRegistry singleton
    """
    global _registry
    if _registry is None:
        _registry = MCPToolRegistry()
    return _registry


def reset_tool_registry() -> None:
    """Reset the global tool registry (for testing)."""
    global _registry
    _registry = None
