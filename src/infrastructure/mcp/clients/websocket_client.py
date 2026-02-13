"""MCP WebSocket Client for WebSocket transport.

This module provides a WebSocket-based MCP client for remote MCP servers
that communicate via WebSocket protocol with JSON-RPC messages.

This client is used by MCP Activities in the Temporal Worker to manage
WebSocket MCP server connections independently from the API service.

Features:
- Bidirectional communication (server can push messages)
- Persistent connection (no repeated handshakes)
- Cross-network support (can connect to remote servers)
- Automatic heartbeat/ping-pong for connection health
"""

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import aiohttp

from src.infrastructure.mcp.clients.subprocess_client import (
    MCPToolResult,
    MCPToolSchema,
)

logger = logging.getLogger(__name__)

# Default timeout in seconds
DEFAULT_TIMEOUT = 600


@dataclass
class MCPWebSocketClientConfig:
    """Configuration for MCP WebSocket Client."""

    url: str
    headers: Dict[str, str] = field(default_factory=dict)
    timeout: float = DEFAULT_TIMEOUT
    heartbeat_interval: Optional[float] = None
    reconnect_attempts: int = 3


class MCPWebSocketClient:
    """
    WebSocket-based MCP client for remote MCP servers.

    Uses WebSocket for bidirectional JSON-RPC communication.
    Designed to run within Temporal Worker activities.

    Features:
    - Bidirectional communication (server can push messages)
    - Persistent connection (no repeated handshakes)
    - Cross-network support (can connect to remote sandbox servers)
    - Automatic heartbeat/ping-pong for connection health

    Usage:
        client = MCPWebSocketClient(
            url="ws://sandbox:8765",
            headers={"Authorization": "Bearer xxx"},
        )
        await client.connect()
        tools = await client.list_tools()
        result = await client.call_tool("read_file", {"path": "/etc/hosts"})
        await client.disconnect()

    Or use as async context manager:
        async with MCPWebSocketClient(url="ws://sandbox:8765") as client:
            tools = await client.list_tools()
            result = await client.call_tool("read_file", {"path": "/etc/hosts"})
    """

    def __init__(
        self,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        timeout: float = DEFAULT_TIMEOUT,
        heartbeat_interval: Optional[float] = None,
        reconnect_attempts: int = 3,
    ):
        """
        Initialize the WebSocket client.

        Args:
            url: WebSocket URL of the MCP server (ws:// or wss://)
            headers: HTTP headers for connection upgrade
            timeout: Default timeout for operations in seconds
            heartbeat_interval: Ping interval in seconds for connection health.
                None disables heartbeat (recommended for long-running tool calls).
                aiohttp uses heartbeat/2 as PONG timeout, so heartbeat=30 means
                connections are killed after 15s without PONG.
            reconnect_attempts: Max reconnection attempts on connection loss
        """
        if not url:
            raise ValueError("WebSocket URL is required")

        self.url = url
        self.headers = headers or {}
        self.timeout = timeout
        self.heartbeat_interval = heartbeat_interval
        self.reconnect_attempts = reconnect_attempts

        self._session: Optional[aiohttp.ClientSession] = None
        self._ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self._request_id = 0
        self._lock = asyncio.Lock()
        self._pending_requests: Dict[int, asyncio.Future] = {}
        self._receive_task: Optional[asyncio.Task] = None
        self._cleanup_lock = asyncio.Lock()  # Lock to prevent double cleanup
        self._is_cleaning_up = False

        self.server_info: Optional[Dict[str, Any]] = None
        self._tools: List[MCPToolSchema] = []
        self._connected = False

    async def __aenter__(self) -> "MCPWebSocketClient":
        """Async context manager entry - connect to server."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit - disconnect from server."""
        await self.disconnect()

    def __del__(self):
        """Destructor - ensure cleanup warning if not properly closed."""
        if self._connected or self._ws is not None or self._session is not None:
            logger.warning(
                f"MCPWebSocketClient for {self.url} was not properly closed. "
                "Use 'await client.disconnect()' or async context manager."
            )

    @property
    def is_connected(self) -> bool:
        """Check if the client is connected."""
        return self._connected and self._ws is not None and not self._ws.closed

    async def connect(self, timeout: Optional[float] = None) -> bool:
        """
        Connect to the remote MCP server via WebSocket.

        Args:
            timeout: Connection timeout in seconds (uses default if None)

        Returns:
            True if connection successful, False otherwise
        """
        timeout = timeout or self.timeout

        if self.is_connected:
            logger.debug("WebSocket already connected")
            return True

        logger.info(f"Connecting to MCP server via WebSocket: {self.url}")

        try:
            # Create aiohttp session
            self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout))

            # Connect WebSocket with increased max_msg_size for large file transfers
            # Default is 4MB, we increase to 100MB to support large attachments
            self._ws = await self._session.ws_connect(
                self.url,
                headers=self.headers,
                heartbeat=self.heartbeat_interval,
                max_msg_size=100 * 1024 * 1024,  # 100MB
            )

            # Start background task to receive messages
            self._receive_task = asyncio.create_task(self._receive_loop())

            # Send initialize request
            init_result = await self._send_request(
                "initialize",
                {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {
                        "roots": {"listChanged": True},
                        "sampling": {},
                        "extensions": {
                            "io.modelcontextprotocol/ui": {
                                "mimeTypes": ["text/html;profile=mcp-app"],
                            },
                        },
                    },
                    "clientInfo": {"name": "memstack-mcp-worker", "version": "1.0.0"},
                },
                timeout=timeout,
            )

            if init_result:
                self.server_info = init_result.get("serverInfo", {})

                # Send initialized notification
                await self._send_notification("notifications/initialized", {})

                # Pre-fetch tools list
                tools = await self.list_tools(timeout=timeout)
                self._tools = tools

                self._connected = True
                logger.info(
                    f"MCP WebSocket connected: {self.server_info} with {len(self._tools)} tools"
                )
                return True

            logger.error("MCP initialize request failed")
            await self.disconnect()
            return False

        except asyncio.TimeoutError:
            logger.error(f"MCP WebSocket connection timeout after {timeout}s")
            await self.disconnect()
            return False
        except aiohttp.WSServerHandshakeError as e:
            logger.error(f"WebSocket handshake failed: {e}")
            await self.disconnect()
            return False
        except Exception as e:
            logger.exception(f"Error connecting to MCP WebSocket: {e}")
            await self.disconnect()
            return False

    async def disconnect(self) -> None:
        """Close the WebSocket connection with proper cleanup protection."""
        # Prevent double cleanup
        async with self._cleanup_lock:
            if self._is_cleaning_up:
                logger.debug("Disconnect already in progress, skipping")
                return
            self._is_cleaning_up = True

        try:
            logger.info("Disconnecting MCP WebSocket client")
            self._connected = False

            # Cancel receive task
            if self._receive_task and not self._receive_task.done():
                self._receive_task.cancel()
                try:
                    await asyncio.wait_for(self._receive_task, timeout=5.0)
                except (asyncio.CancelledError, asyncio.TimeoutError):
                    pass
                except Exception as e:
                    logger.warning(f"Error waiting for receive task: {e}")
                self._receive_task = None

            # Close WebSocket with timeout
            if self._ws and not self._ws.closed:
                try:
                    await asyncio.wait_for(self._ws.close(), timeout=5.0)
                except asyncio.TimeoutError:
                    logger.warning("WebSocket close timed out")
                except Exception as e:
                    logger.warning(f"Error closing WebSocket: {e}")
            self._ws = None

            # Close session with timeout
            if self._session and not self._session.closed:
                try:
                    await asyncio.wait_for(self._session.close(), timeout=5.0)
                except asyncio.TimeoutError:
                    logger.warning("Session close timed out")
                except Exception as e:
                    logger.warning(f"Error closing session: {e}")
            self._session = None

            # Fail pending requests
            for request_id, future in list(self._pending_requests.items()):
                if not future.done():
                    future.set_exception(RuntimeError("WebSocket connection closed"))
            self._pending_requests.clear()

            self._tools = []
            self.server_info = None
        finally:
            async with self._cleanup_lock:
                self._is_cleaning_up = False

    async def _receive_loop(self) -> None:
        """Background task to receive and dispatch WebSocket messages."""
        try:
            async for msg in self._ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    try:
                        data = json.loads(msg.data)
                        await self._handle_message(data)
                    except json.JSONDecodeError as e:
                        logger.error(f"Invalid JSON from WebSocket: {e}")

                elif msg.type == aiohttp.WSMsgType.ERROR:
                    logger.error(f"WebSocket error: {self._ws.exception()}")
                    break

                elif msg.type == aiohttp.WSMsgType.CLOSED:
                    logger.info("WebSocket connection closed by server")
                    break

                elif msg.type == aiohttp.WSMsgType.CLOSE:
                    logger.info(f"WebSocket close frame received: {msg.data}")
                    break

        except asyncio.CancelledError:
            logger.debug("WebSocket receive loop cancelled")
        except Exception as e:
            logger.error(f"Error in WebSocket receive loop: {e}", exc_info=True)
        finally:
            self._connected = False
            # Fail all pending requests
            for request_id, future in list(self._pending_requests.items()):
                if not future.done():
                    future.set_exception(RuntimeError("WebSocket connection closed"))
            self._pending_requests.clear()

    async def _handle_message(self, data: dict) -> None:
        """Handle incoming JSON-RPC message."""
        request_id = data.get("id")

        if request_id is not None and request_id in self._pending_requests:
            future = self._pending_requests.pop(request_id)

            if "error" in data:
                error = data["error"]
                error_msg = (
                    error.get("message", str(error)) if isinstance(error, dict) else str(error)
                )
                future.set_exception(RuntimeError(f"MCP server error: {error_msg}"))
            else:
                future.set_result(data.get("result", {}))

        elif "method" in data and "id" not in data:
            # This is a notification from server (no response expected)
            method = data.get("method")
            logger.debug(f"Received server notification: {method}")
            # Handle server-initiated notifications if needed

        else:
            logger.warning(f"Received unexpected message: {data}")

    async def list_tools(self, timeout: Optional[float] = None) -> List[MCPToolSchema]:
        """
        List available tools.

        Args:
            timeout: Operation timeout in seconds

        Returns:
            List of tool schemas
        """
        timeout = timeout or self.timeout
        result = await self._send_request("tools/list", {}, timeout=timeout)

        if result:
            tools_data = result.get("tools", [])
            return [
                MCPToolSchema(
                    name=tool.get("name", ""),
                    description=tool.get("description"),
                    inputSchema=tool.get("inputSchema", {}),
                    meta=tool.get("_meta"),
                )
                for tool in tools_data
            ]
        return []
    async def call_tool(
        self,
        name: str,
        arguments: Dict[str, Any],
        timeout: Optional[float] = None,
    ) -> MCPToolResult:
        """
        Call a tool on the MCP server.

        Args:
            name: Tool name
            arguments: Tool arguments
            timeout: Operation timeout in seconds

        Returns:
            Tool execution result

        Raises:
            ConnectionError: If the WebSocket connection is lost (enables retry).
        """
        timeout = timeout or self.timeout
        logger.info(f"Calling MCP tool: {name}")
        logger.debug(f"Tool arguments: {arguments}")

        try:
            result = await self._send_request(
                "tools/call",
                {"name": name, "arguments": arguments},
                timeout=timeout,
            )

            if result:
                return MCPToolResult(
                    content=result.get("content", []),
                    isError=result.get("isError", False),
                    artifact=result.get("artifact"),
                )

        except ConnectionError:
            # Re-raise connection errors so callers can retry
            raise
        except Exception as e:
            logger.error(f"Tool call error: {e}")
            return MCPToolResult(
                content=[{"type": "text", "text": f"Error: {str(e)}"}],
                isError=True,
            )

        # _send_request returned None - this means timeout
        logger.error(
            f"Tool '{name}' call failed: request timed out"
        )
        return MCPToolResult(
            content=[
                {
                    "type": "text",
                    "text": f"Error: Tool '{name}' request timed out after {timeout}s",
                }
            ],
            isError=True,
        )

    def get_cached_tools(self) -> List[MCPToolSchema]:
        """Get cached tools list (from connection time)."""
        return self._tools

    async def read_resource(
        self,
        uri: str,
        timeout: Optional[float] = None,
    ) -> Optional[Dict[str, Any]]:
        """Read a resource from the MCP server via resources/read.

        Args:
            uri: Resource URI (e.g., ui://server/app.html)
            timeout: Operation timeout in seconds

        Returns:
            Resource response dict with 'contents' list, or None on error.
        """
        timeout = timeout or self.timeout
        try:
            result = await self._send_request(
                "resources/read", {"uri": uri}, timeout=timeout,
            )
            return result
        except Exception as e:
            logger.error("resources/read error for %s: %s", uri, e)
            return None

    async def list_resources(
        self,
        timeout: Optional[float] = None,
    ) -> Optional[Dict[str, Any]]:
        """List resources from the MCP server via resources/list.

        Returns:
            Response dict with 'resources' list, or None on error.
        """
        timeout = timeout or self.timeout
        try:
            result = await self._send_request(
                "resources/list", {}, timeout=timeout,
            )
            return result
        except Exception as e:
            logger.error("resources/list error: %s", e)
            return None

    async def _send_request(
        self,
        method: str,
        params: Dict[str, Any],
        timeout: float = DEFAULT_TIMEOUT,
    ) -> Optional[Dict[str, Any]]:
        """Send a JSON-RPC request and wait for response.

        Raises:
            ConnectionError: If the WebSocket connection is closed or lost.
        """
        if not self._ws or self._ws.closed:
            raise ConnectionError(f"WebSocket not connected to {self.url}")

        async with self._lock:
            self._request_id += 1
            request_id = self._request_id
            request = {
                "jsonrpc": "2.0",
                "method": method,
                "params": params,
                "id": request_id,
            }

            # Create future for response
            future: asyncio.Future = asyncio.get_event_loop().create_future()
            self._pending_requests[request_id] = future

        try:
            logger.debug(f"Sending WebSocket request: {method} (id={request_id})")
            await self._ws.send_json(request)

            # Wait for response with timeout
            result = await asyncio.wait_for(future, timeout=timeout)
            return result

        except asyncio.TimeoutError:
            async with self._lock:
                self._pending_requests.pop(request_id, None)
            logger.error(f"MCP request '{method}' timed out after {timeout}s")
            return None
        except (ConnectionError, ConnectionResetError, RuntimeError) as e:
            async with self._lock:
                self._pending_requests.pop(request_id, None)
            error_str = str(e)
            if "closed" in error_str.lower() or "connection" in error_str.lower():
                logger.error(f"MCP WebSocket connection lost: {e}")
                self._connected = False
                raise ConnectionError(f"WebSocket connection lost: {e}") from e
            logger.error(f"MCP request error: {e}")
            raise
        except Exception as e:
            async with self._lock:
                self._pending_requests.pop(request_id, None)
            logger.error(f"MCP request error: {e}")
            return None

    async def _send_notification(self, method: str, params: Dict[str, Any]) -> None:
        """Send a JSON-RPC notification (no response expected)."""
        if not self._ws or self._ws.closed:
            return

        notification = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        }

        try:
            logger.debug(f"Sending notification: {method}")
            await self._ws.send_json(notification)
        except Exception as e:
            logger.error(f"Notification error: {e}")
