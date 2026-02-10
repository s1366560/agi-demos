"""
MCP Connector - MCP WebSocket connection management.

Handles establishing and managing MCP WebSocket connections to sandbox containers.
Extracted from MCPSandboxAdapter.
"""

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from src.infrastructure.adapters.secondary.sandbox.instance import MCPSandboxInstance
from src.infrastructure.mcp.clients.websocket_client import MCPWebSocketClient

logger = logging.getLogger(__name__)


class MCPConnector:
    """
    Manages MCP WebSocket connections to sandbox containers.

    Responsibilities:
    - Establishing MCP connections
    - Connection health monitoring
    - Reconnection logic
    - Tool discovery and caching
    """

    def __init__(
        self,
        connection_timeout: float = 30.0,
        tool_cache_ttl: float = 300.0,  # 5 minutes
    ):
        """
        Initialize MCP connector.

        Args:
            connection_timeout: Timeout for connection attempts
            tool_cache_ttl: TTL for tool cache in seconds
        """
        self._connection_timeout = connection_timeout
        self._tool_cache_ttl = tool_cache_ttl

    def build_websocket_url(
        self,
        host: str,
        port: int,
        sandbox_id: str,
    ) -> str:
        """Build WebSocket URL for MCP connection."""
        return f"ws://{host}:{port}/mcp/{sandbox_id}"

    async def connect(
        self,
        instance: MCPSandboxInstance,
        host: str = "localhost",
        max_retries: int = 5,
        retry_delay: float = 2.0,
    ) -> bool:
        """
        Establish MCP WebSocket connection to sandbox.

        Args:
            instance: Sandbox instance to connect to
            host: Host address for WebSocket connection
            max_retries: Maximum connection retry attempts
            retry_delay: Delay between retries in seconds

        Returns:
            True if connection successful, False otherwise
        """
        if not instance.mcp_port:
            logger.error(f"No MCP port allocated for sandbox {instance.id}")
            return False

        # Build WebSocket URL
        ws_url = self.build_websocket_url(host, instance.mcp_port, instance.id)
        instance.websocket_url = ws_url

        logger.info(f"Connecting to MCP server at {ws_url}")

        # Create MCP client
        client = MCPWebSocketClient(url=ws_url)
        instance.mcp_client = client

        # Attempt connection with retries
        for attempt in range(1, max_retries + 1):
            try:
                logger.debug(f"Connection attempt {attempt}/{max_retries}")

                connected = await asyncio.wait_for(
                    client.connect(),
                    timeout=self._connection_timeout,
                )

                if connected:
                    logger.info(f"Successfully connected to MCP server for sandbox {instance.id}")

                    # Refresh tool cache
                    await self._refresh_tools(instance)

                    return True

            except asyncio.TimeoutError:
                logger.warning(f"Connection timeout (attempt {attempt}/{max_retries})")
            except Exception as e:
                logger.warning(f"Connection failed (attempt {attempt}/{max_retries}): {e}")

            if attempt < max_retries:
                await asyncio.sleep(retry_delay)

        logger.error(f"Failed to connect to MCP server after {max_retries} attempts")
        instance.mcp_client = None
        return False

    async def disconnect(self, instance: MCPSandboxInstance) -> None:
        """
        Disconnect MCP client from sandbox.

        Args:
            instance: Sandbox instance to disconnect
        """
        if instance.mcp_client:
            try:
                await instance.mcp_client.disconnect()
                logger.info(f"Disconnected MCP client for sandbox {instance.id}")
            except Exception as e:
                logger.warning(f"Error disconnecting MCP client: {e}")
            finally:
                instance.mcp_client = None

    async def reconnect(
        self,
        instance: MCPSandboxInstance,
        host: str = "localhost",
    ) -> bool:
        """
        Reconnect MCP client after connection loss.

        Args:
            instance: Sandbox instance to reconnect
            host: Host address

        Returns:
            True if reconnection successful
        """
        await self.disconnect(instance)
        return await self.connect(instance, host)

    async def is_healthy(self, instance: MCPSandboxInstance) -> bool:
        """
        Check if MCP connection is healthy.

        Args:
            instance: Sandbox instance to check

        Returns:
            True if connection is healthy
        """
        if not instance.mcp_client:
            return False

        try:
            # Try to list tools as health check
            await asyncio.wait_for(
                instance.mcp_client.list_tools(),
                timeout=5.0,
            )
            return True
        except Exception:
            return False

    async def list_tools(
        self,
        instance: MCPSandboxInstance,
        use_cache: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        List available MCP tools for sandbox.

        Args:
            instance: Sandbox instance
            use_cache: Whether to use cached tools

        Returns:
            List of tool definitions
        """
        # Check cache validity
        if use_cache and instance.tools_cache:
            if instance.last_tool_refresh:
                age = (datetime.now() - instance.last_tool_refresh).total_seconds()
                if age < self._tool_cache_ttl:
                    return instance.tools_cache

        # Refresh from server
        await self._refresh_tools(instance)
        return instance.tools_cache

    async def call_tool(
        self,
        instance: MCPSandboxInstance,
        tool_name: str,
        arguments: Dict[str, Any],
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Call an MCP tool on the sandbox.

        Args:
            instance: Sandbox instance
            tool_name: Name of tool to call
            arguments: Tool arguments
            timeout: Optional execution timeout

        Returns:
            Tool execution result

        Raises:
            RuntimeError: If not connected or call fails
        """
        if not instance.mcp_client:
            raise RuntimeError(f"No MCP connection for sandbox {instance.id}")

        try:
            if timeout:
                result = await asyncio.wait_for(
                    instance.mcp_client.call_tool(tool_name, arguments),
                    timeout=timeout,
                )
            else:
                result = await instance.mcp_client.call_tool(tool_name, arguments)

            # Update activity timestamp
            instance.last_activity_at = datetime.now()

            return result

        except asyncio.TimeoutError:
            raise RuntimeError(f"Tool call {tool_name} timed out after {timeout}s")
        except Exception as e:
            raise RuntimeError(f"Tool call {tool_name} failed: {e}") from e

    async def _refresh_tools(self, instance: MCPSandboxInstance) -> None:
        """Refresh tool cache from MCP server."""
        if not instance.mcp_client:
            return

        try:
            tools = await asyncio.wait_for(
                instance.mcp_client.list_tools(),
                timeout=10.0,
            )
            instance.tools_cache = tools
            instance.last_tool_refresh = datetime.now()
            logger.debug(f"Refreshed {len(tools)} tools for sandbox {instance.id}")
        except Exception as e:
            logger.warning(f"Failed to refresh tools for sandbox {instance.id}: {e}")
