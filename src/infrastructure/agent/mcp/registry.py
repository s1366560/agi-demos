"""
MCP Server Registry for managing discovered MCP servers.

The registry maintains a cache of server connections and tool metadata,
providing efficient tool lookup and server health monitoring.
"""

import asyncio
import contextlib
import logging
from datetime import UTC, datetime
from typing import Any

from src.infrastructure.agent.mcp.client import MCPClient

logger = logging.getLogger(__name__)

# Valid MCP logging levels as per MCP specification
VALID_LOGGING_LEVELS = frozenset(
    ["debug", "info", "notice", "warning", "error", "critical", "alert", "emergency"]
)


class MCPServerRegistry:
    """
    Registry for managing MCP server connections and tool discovery.

    Features:
    - Server connection pooling
    - Tool metadata caching
    - Periodic health checks using lightweight ping
    - Automatic reconnection on failure
    - Roots management for directory access
    - Logging level control
    """

    def __init__(
        self,
        cache_ttl_seconds: int = 300,
        health_check_interval_seconds: int = 60,
        max_reconnect_attempts: int = 3,
    ) -> None:
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

        # Roots: list of root directories accessible by servers
        self._roots: list[dict[str, str]] = []

        # Elicitation handler: async callback for elicitation requests
        self._elicitation_handler: callable | None = None

        # Background tasks
        self._health_check_task: asyncio.Task | None = None
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
            with contextlib.suppress(asyncio.CancelledError):
                await self._health_check_task

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
            self._health_status[server_id] = (True, datetime.now(UTC))
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
            age = datetime.now(UTC) - last_sync
            if age.total_seconds() < self.cache_ttl_seconds:
                logger.debug(f"Using cached tools for server {server_id}")
                return tools

        # Fetch from server
        client = self._clients.get(server_id)
        if not client:
            raise ValueError(f"Server not registered: {server_id}")

        try:
            tools = await client.list_tools()
            self._tool_cache[server_id] = (tools, datetime.now(UTC))
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
        Check health of a registered server using lightweight ping.

        Uses the ping() method instead of list_tools() for more efficient
        health checking.

        Args:
            server_id: Unique server identifier

        Returns:
            True if server is healthy, False otherwise
        """
        client = self._clients.get(server_id)
        if not client:
            return False

        try:
            # Use ping() for lightweight health check
            is_healthy = await client.ping()
            self._health_status[server_id] = (is_healthy, datetime.now(UTC))
            return is_healthy
        except Exception as e:
            logger.error(f"Health check failed for server {server_id}: {e}")
            self._health_status[server_id] = (False, datetime.now(UTC))
            return False

    def get_health_status(self, server_id: str) -> tuple[bool, datetime] | None:
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

                # Verify connection with health check using ping
                if await client.ping():
                    logger.info(f"Successfully reconnected to server {server_id}")
                    self._health_status[server_id] = (True, datetime.now(UTC))
                    return
            except Exception as e:
                logger.error(f"Reconnect attempt {attempt + 1} failed for {server_id}: {e}")
                await asyncio.sleep(2**attempt)  # Exponential backoff

        logger.error(
            f"Failed to reconnect to server {server_id} after {self.max_reconnect_attempts} attempts"
        )
        self._health_status[server_id] = (False, datetime.now(UTC))

    # =========================================================================
    # Logging Level Control (Priority 1)
    # =========================================================================

    async def set_server_logging_level(self, server_id: str, level: str) -> bool:
        """
        Set the logging level for a registered MCP server.

        Args:
            server_id: Unique server identifier
            level: Logging level (debug, info, notice, warning, error, critical, alert, emergency)

        Returns:
            True if successful, False otherwise
        """
        # Validate logging level
        if level not in VALID_LOGGING_LEVELS:
            logger.warning(f"Invalid logging level: {level}")
            return False

        client = self._clients.get(server_id)
        if not client:
            logger.warning(f"Server not registered: {server_id}")
            return False

        try:
            result = await client.set_logging_level(level)
            if result:
                logger.info(f"Set logging level to {level} for server {server_id}")
            return result
        except Exception as e:
            logger.error(f"Failed to set logging level for server {server_id}: {e}")
            return False

    # =========================================================================
    # Roots Management (Priority 1)
    # =========================================================================

    async def add_root(self, uri: str, name: str | None = None) -> None:
        """
        Add a root directory that servers can access.

        Args:
            uri: URI of the root directory (e.g., file:///workspace)
            name: Optional human-readable name for the root
        """
        # Check if root already exists
        for root in self._roots:
            if root["uri"] == uri:
                return  # Already exists

        root_entry = {"uri": uri}
        if name:
            root_entry["name"] = name

        self._roots.append(root_entry)
        logger.info(f"Added root: {uri}")

    async def remove_root(self, uri: str) -> None:
        """
        Remove a root directory.

        Args:
            uri: URI of the root directory to remove
        """
        self._roots = [r for r in self._roots if r["uri"] != uri]
        logger.info(f"Removed root: {uri}")

    def get_roots(self) -> list[dict[str, str]]:
        """
        Get list of configured roots.

        Returns:
            List of root entries with uri and optional name
        """
        return list(self._roots)

    async def notify_roots_list_changed(self) -> None:
        """
        Notify all registered servers that the roots list has changed.

        This sends a roots/list_changed notification to all servers.
        """
        for server_id, client in self._clients.items():
            try:
                if hasattr(client, "send_roots_list_changed"):
                    await client.send_roots_list_changed()
                    logger.debug(f"Notified server {server_id} of roots change")
            except Exception as e:
                logger.error(f"Failed to notify server {server_id} of roots change: {e}")

    # =========================================================================
    # Elicitation Support (Priority 3 - MCP -> HITL integration)
    # =========================================================================

    def set_elicitation_handler(self, handler: callable) -> None:
        """
        Set the elicitation request handler.

        The handler is called when an MCP server requests information
        from the user via the elicitation mechanism.

        Args:
            handler: Async function with signature:
                async def handler(
                    server_id: str,
                    message: str,
                    schema: Dict[str, Any]
                ) -> Dict[str, Any]

                Returns the user's response data matching the schema.
        """
        self._elicitation_handler = handler
        logger.info("Elicitation handler registered")

    async def handle_elicitation_request(
        self,
        server_id: str,
        message: str,
        requested_schema: dict,
        timeout_seconds: float = 300.0,
    ) -> dict | None:
        """
        Handle an elicitation request from an MCP server.

        This method is called by the MCP client when the server
        requests information from the user. It forwards the request
        to the registered elicitation handler (typically the HITL system).

        Args:
            server_id: ID of the server making the request
            message: Human-readable message from the server
            requested_schema: JSON Schema describing the requested data
            timeout_seconds: Timeout for the request (default: 5 minutes)

        Returns:
            User's response data matching the schema, or None if no handler
        """
        if not self._elicitation_handler:
            logger.warning(
                f"No elicitation handler registered, cannot fulfill request from {server_id}"
            )
            return None

        try:
            logger.info(f"Forwarding elicitation request from server {server_id}")

            # Call the handler with timeout
            result = await asyncio.wait_for(
                self._elicitation_handler(server_id, message, requested_schema),
                timeout=timeout_seconds,
            )

            logger.info(f"Elicitation request from {server_id} fulfilled")
            return result

        except TimeoutError:
            logger.error(f"Elicitation request from {server_id} timed out")
            return None
        except Exception as e:
            logger.error(f"Error handling elicitation request from {server_id}: {e}")
            return None

    # =========================================================================
    # Prompts API Support (Priority 3)
    # =========================================================================

    async def get_server_prompts(self, server_id: str) -> list[dict]:
        """
        Get list of prompts available from a registered MCP server.

        Args:
            server_id: Unique server identifier

        Returns:
            List of prompt definitions with name, description, and arguments

        Raises:
            ValueError: If server is not registered
        """
        client = self._clients.get(server_id)
        if not client:
            raise ValueError(f"Server not registered: {server_id}")

        try:
            # Check if client supports prompts
            if not hasattr(client, "list_prompts"):
                logger.debug(f"Server {server_id} does not support prompts")
                return []

            prompts = await client.list_prompts()
            logger.debug(f"Retrieved {len(prompts)} prompts from server {server_id}")
            return prompts
        except Exception as e:
            logger.error(f"Failed to get prompts from server {server_id}: {e}")
            raise

    async def get_server_prompt(
        self,
        server_id: str,
        prompt_name: str,
        arguments: dict | None = None,
    ) -> dict:
        """
        Get a specific prompt from a registered MCP server.

        Args:
            server_id: Unique server identifier
            prompt_name: Name of the prompt to retrieve
            arguments: Optional arguments to fill in the prompt template

        Returns:
            Prompt definition with messages

        Raises:
            ValueError: If server is not registered
        """
        client = self._clients.get(server_id)
        if not client:
            raise ValueError(f"Server not registered: {server_id}")

        try:
            prompt = await client.get_prompt(prompt_name, arguments)
            logger.debug(f"Retrieved prompt {prompt_name} from server {server_id}")
            return prompt
        except Exception as e:
            logger.error(f"Failed to get prompt {prompt_name} from server {server_id}: {e}")
            raise

    async def get_all_prompts(self) -> dict[str, list[dict]]:
        """
        Get prompts from all registered servers.

        Returns:
            Dictionary mapping server_id to list of prompts
        """
        result = {}
        for server_id in self._clients.keys():
            try:
                prompts = await self.get_server_prompts(server_id)
                result[server_id] = prompts
            except Exception as e:
                logger.error(f"Failed to get prompts from server {server_id}: {e}")
                result[server_id] = []
        return result
