"""
MCP Server Registry for managing discovered MCP servers.

The registry maintains a cache of server connections and tool metadata,
providing efficient tool lookup and server health monitoring.
"""

import asyncio
import logging
from datetime import datetime
from typing import Any, Optional

from src.infrastructure.agent.mcp.client import MCPClient

logger = logging.getLogger(__name__)


class MCPServerRegistry:
    """
    Registry for managing MCP server connections and tool discovery.

    Features:
    - Server connection pooling
    - Tool metadata caching
    - Periodic health checks
    - Automatic reconnection on failure
    """

    def __init__(
        self,
        cache_ttl_seconds: int = 300,
        health_check_interval_seconds: int = 60,
        max_reconnect_attempts: int = 3,
    ):
        """
        Initialize MCP server registry.

        Args:
            cache_ttl_seconds: Time-to-live for cached tool metadata
            health_check_interval_seconds: Interval between health checks
            max_reconnect_attempts: Maximum reconnection attempts
        """
        self.cache_ttl_seconds = cache_ttl_seconds
        self.health_check_interval_seconds = health_check_interval_seconds
        self.max_reconnect_attempts = max_reconnect_attempts

        # Server connections: server_id -> MCPClient
        self._clients: dict[str, MCPClient] = {}

        # Tool cache: server_id -> (tools, last_sync_at)
        self._tool_cache: dict[str, tuple[list[dict], datetime]] = {}

        # Health status: server_id -> (is_healthy, last_check_at)
        self._health_status: dict[str, tuple[bool, datetime]] = {}

        # Background tasks
        self._health_check_task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self) -> None:
        """Start the registry and background health checks."""
        if self._running:
            return

        self._running = True
        self._health_check_task = asyncio.create_task(self._run_health_checks())
        logger.info("MCP server registry started")

    async def stop(self) -> None:
        """Stop the registry and disconnect all servers."""
        if not self._running:
            return

        self._running = False

        # Cancel health check task
        if self._health_check_task:
            self._health_check_task.cancel()
            try:
                await self._health_check_task
            except asyncio.CancelledError:
                pass

        # Disconnect all clients
        for server_id, client in self._clients.items():
            try:
                await client.disconnect()
                logger.info(f"Disconnected MCP server: {server_id}")
            except Exception as e:
                logger.error(f"Error disconnecting server {server_id}: {e}")

        self._clients.clear()
        self._tool_cache.clear()
        self._health_status.clear()
        logger.info("MCP server registry stopped")

    async def register_server(
        self, server_id: str, server_type: str, transport_config: dict
    ) -> None:
        """
        Register and connect to an MCP server.

        Args:
            server_id: Unique server identifier
            server_type: Transport protocol type
            transport_config: Configuration for the transport
        """
        if server_id in self._clients:
            logger.warning(f"Server {server_id} already registered, reconnecting")
            await self.unregister_server(server_id)

        client = MCPClient(server_type, transport_config)

        try:
            await client.connect()
            self._clients[server_id] = client
            self._health_status[server_id] = (True, datetime.utcnow())
            logger.info(f"Registered MCP server: {server_id}")

            # Initial tool discovery
            await self.sync_tools(server_id)
        except Exception as e:
            logger.error(f"Failed to register server {server_id}: {e}")
            raise

    async def unregister_server(self, server_id: str) -> None:
        """
        Unregister and disconnect from an MCP server.

        Args:
            server_id: Unique server identifier
        """
        client = self._clients.pop(server_id, None)
        if client:
            try:
                await client.disconnect()
                logger.info(f"Unregistered MCP server: {server_id}")
            except Exception as e:
                logger.error(f"Error unregistering server {server_id}: {e}")

        self._tool_cache.pop(server_id, None)
        self._health_status.pop(server_id, None)

    async def sync_tools(self, server_id: str, force: bool = False) -> list[dict]:
        """
        Sync tool metadata from an MCP server.

        Args:
            server_id: Unique server identifier
            force: Force sync even if cache is valid

        Returns:
            List of tool definitions
        """
        # Check cache
        if not force and server_id in self._tool_cache:
            tools, last_sync = self._tool_cache[server_id]
            age = datetime.utcnow() - last_sync
            if age.total_seconds() < self.cache_ttl_seconds:
                logger.debug(f"Using cached tools for server {server_id}")
                return tools

        # Fetch from server
        client = self._clients.get(server_id)
        if not client:
            raise ValueError(f"Server not registered: {server_id}")

        try:
            tools = await client.list_tools()
            self._tool_cache[server_id] = (tools, datetime.utcnow())
            logger.info(f"Synced {len(tools)} tools from server {server_id}")
            return tools
        except Exception as e:
            logger.error(f"Failed to sync tools from server {server_id}: {e}")
            raise

    async def get_tools(self, server_id: str) -> list[dict]:
        """
        Get cached tool metadata for a server.

        Args:
            server_id: Unique server identifier

        Returns:
            List of tool definitions
        """
        if server_id not in self._tool_cache:
            return await self.sync_tools(server_id)

        tools, _ = self._tool_cache[server_id]
        return tools

    async def get_all_tools(self) -> dict[str, list[dict]]:
        """
        Get tool metadata from all registered servers.

        Returns:
            Dictionary mapping server_id to list of tools
        """
        result = {}
        for server_id in self._clients.keys():
            try:
                result[server_id] = await self.get_tools(server_id)
            except Exception as e:
                logger.error(f"Failed to get tools from server {server_id}: {e}")
                result[server_id] = []
        return result

    async def call_tool(self, server_id: str, tool_name: str, arguments: dict) -> Any:
        """
        Call a tool on a registered MCP server.

        Args:
            server_id: Unique server identifier
            tool_name: Name of the tool to call
            arguments: Tool arguments

        Returns:
            Tool execution result
        """
        client = self._clients.get(server_id)
        if not client:
            raise ValueError(f"Server not registered: {server_id}")

        try:
            result = await client.call_tool(tool_name, arguments)
            logger.info(f"Successfully called tool {tool_name} on server {server_id}")
            return result
        except Exception as e:
            logger.error(f"Failed to call tool {tool_name} on server {server_id}: {e}")
            raise

    async def health_check(self, server_id: str) -> bool:
        """
        Check health of a registered server.

        Args:
            server_id: Unique server identifier

        Returns:
            True if server is healthy, False otherwise
        """
        client = self._clients.get(server_id)
        if not client:
            return False

        try:
            is_healthy = await client.health_check()
            self._health_status[server_id] = (is_healthy, datetime.utcnow())
            return is_healthy
        except Exception as e:
            logger.error(f"Health check failed for server {server_id}: {e}")
            self._health_status[server_id] = (False, datetime.utcnow())
            return False

    def get_health_status(self, server_id: str) -> Optional[tuple[bool, datetime]]:
        """
        Get cached health status for a server.

        Args:
            server_id: Unique server identifier

        Returns:
            Tuple of (is_healthy, last_check_at) or None if not found
        """
        return self._health_status.get(server_id)

    def is_server_registered(self, server_id: str) -> bool:
        """Check if a server is registered."""
        return server_id in self._clients

    def get_registered_servers(self) -> list[str]:
        """Get list of all registered server IDs."""
        return list(self._clients.keys())

    async def _run_health_checks(self) -> None:
        """Background task for periodic health checks."""
        while self._running:
            try:
                await asyncio.sleep(self.health_check_interval_seconds)

                for server_id in list(self._clients.keys()):
                    is_healthy = await self.health_check(server_id)

                    if not is_healthy:
                        logger.warning(f"Server {server_id} is unhealthy, attempting reconnect")
                        await self._attempt_reconnect(server_id)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in health check loop: {e}")

    async def _attempt_reconnect(self, server_id: str) -> None:
        """
        Attempt to reconnect to an unhealthy server.

        Args:
            server_id: Unique server identifier
        """
        client = self._clients.get(server_id)
        if not client:
            return

        for attempt in range(self.max_reconnect_attempts):
            try:
                logger.info(f"Reconnecting to server {server_id} (attempt {attempt + 1})")
                await client.disconnect()
                await client.connect()

                # Verify connection with health check
                if await client.health_check():
                    logger.info(f"Successfully reconnected to server {server_id}")
                    self._health_status[server_id] = (True, datetime.utcnow())
                    return
            except Exception as e:
                logger.error(f"Reconnect attempt {attempt + 1} failed for {server_id}: {e}")
                await asyncio.sleep(2**attempt)  # Exponential backoff

        logger.error(
            f"Failed to reconnect to server {server_id} after {self.max_reconnect_attempts} attempts"
        )
        self._health_status[server_id] = (False, datetime.utcnow())
