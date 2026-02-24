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
from types import TracebackType
from typing import Any, cast

import aiohttp

from src.infrastructure.mcp.clients.subprocess_client import (
    MCPToolResult,
    MCPToolSchema,
)

logger = logging.getLogger(__name__)

# Default timeout in seconds (can be overridden per-call)
DEFAULT_TIMEOUT = 60


@dataclass
class MCPWebSocketClientConfig:
    """Configuration for MCP WebSocket Client."""

    url: str
    headers: dict[str, str] = field(default_factory=dict)
    timeout: float = DEFAULT_TIMEOUT
    heartbeat_interval: float | None = None
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
        headers: dict[str, str] | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        heartbeat_interval: float | None = None,
        reconnect_attempts: int = 3,
    ) -> None:
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

        self._session: aiohttp.ClientSession | None = None
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._request_id = 0
        # Lock for request ID generation and pending_requests access
        # This is a minimal lock - only held during ID generation, not during send
        self._request_id_lock = asyncio.Lock()
        # Legacy lock - kept for backward compatibility
        self._lock = self._request_id_lock
        self._pending_requests: dict[int, asyncio.Future[Any]] = {}
        self._receive_task: asyncio.Task[None] | None = None
        self._cleanup_lock = asyncio.Lock()  # Lock to prevent double cleanup
        self._is_cleaning_up = False

        self.server_info: dict[str, Any] | None = None
        self._tools: list[MCPToolSchema] = []
        self._connected = False

        # Notification handlers for server-initiated messages
        self.on_resource_updated: callable | None = None
        self.on_resource_list_changed: callable | None = None
        self.on_progress: callable | None = None
        self.on_cancelled: callable | None = None
        self.on_prompts_list_changed: callable | None = None

        # Request handlers for server-initiated requests (Phase 2)
        self.on_sampling_request: callable | None = None
        self.on_elicitation_request: callable | None = None
        self.on_roots_list: callable | None = None
        self.on_roots_list_changed: callable | None = None

        # Client state
        self._roots: list[dict[str, Any]] = []

    async def __aenter__(self) -> "MCPWebSocketClient":
        """Async context manager entry - connect to server."""
        await self.connect()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Async context manager exit - disconnect from server."""
        await self.disconnect()

    def __del__(self) -> None:
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

    async def connect(self, timeout: float | None = None) -> bool:
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

            logger.error("MCP initialize request returned no result (likely timed out)")
            await self.disconnect()
            return False

        except TimeoutError:
            logger.error(f"MCP WebSocket connection timeout after {timeout}s to {self.url}")
            await self.disconnect()
            return False
        except aiohttp.WSServerHandshakeError as e:
            logger.error(f"WebSocket handshake failed for {self.url}: {e}")
            await self.disconnect()
            return False
        except Exception as e:
            logger.exception(f"Error connecting to MCP WebSocket {self.url}: {e}")
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
            await self._cleanup_receive_task()
            await self._cleanup_websocket()
            await self._cleanup_session()
            self._fail_pending_requests()
            self._tools = []
            self.server_info = None
        finally:
            async with self._cleanup_lock:
                self._is_cleaning_up = False
        """Cancel and await the background receive task."""
        if not self._receive_task or self._receive_task.done():
            self._receive_task = None
            return
        self._receive_task.cancel()
        try:
            await asyncio.wait_for(self._receive_task, timeout=5.0)
        except (TimeoutError, asyncio.CancelledError):
            pass
        except Exception as e:
            logger.warning(f"Error waiting for receive task: {e}")
        self._receive_task = None
    async def _cleanup_websocket(self) -> None:
        """Close the WebSocket connection with timeout."""
        if self._ws and not self._ws.closed:
            try:
                await asyncio.wait_for(self._ws.close(), timeout=5.0)
            except TimeoutError:
                logger.warning("WebSocket close timed out")
            except Exception as e:
                logger.warning(f"Error closing WebSocket: {e}")
            self._ws = None
        """Close the aiohttp session with timeout."""
        if self._session and not self._session.closed:
            try:
                await asyncio.wait_for(self._session.close(), timeout=5.0)
            except TimeoutError:
                logger.warning("Session close timed out")
            except Exception as e:
                logger.warning(f"Error closing session: {e}")
            self._session = None
        """Fail all pending requests with a connection closed error."""
        for _request_id, future in list(self._pending_requests.items()):
            if not future.done():
                future.set_exception(RuntimeError("WebSocket connection closed"))
        self._pending_requests.clear()

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
            for _request_id, future in list(self._pending_requests.items()):
                if not future.done():
                    future.set_exception(RuntimeError("WebSocket connection closed"))
            self._pending_requests.clear()

    async def _handle_message(self, data: dict[str, Any]) -> None:
        """Handle incoming JSON-RPC message."""
        request_id = data.get("id")

        if request_id is not None and request_id in self._pending_requests:
            # Response to our request
            future = self._pending_requests.pop(request_id)

            if "error" in data:
                error = data["error"]
                error_msg = (
                    error.get("message", str(error)) if isinstance(error, dict) else str(error)
                )
                future.set_exception(RuntimeError(f"MCP server error: {error_msg}"))
            else:
                future.set_result(data.get("result", {}))

        elif "method" in data and "id" in data:
            # This is a request FROM the server (server-initiated)
            method = data.get("method")
            params = data.get("params", {})
            logger.debug(f"Received server request: {method} (id={request_id})")

            # Handle server-initiated requests
            await self._handle_server_request(request_id, method, params)

        elif "method" in data and "id" not in data:
            # This is a notification from server (no response expected)
            method = data.get("method")
            params = data.get("params", {})
            logger.debug(f"Received server notification: {method}")

            # Dispatch to registered handlers
            if method == "notifications/resources/updated" and self.on_resource_updated:
                await self.on_resource_updated(params)
            elif method == "notifications/resources/list_changed" and self.on_resource_list_changed:
                await self.on_resource_list_changed(params)
            elif method == "notifications/progress" and self.on_progress:
                await self.on_progress(params)
            elif method == "notifications/cancelled" and self.on_cancelled:
                await self.on_cancelled(params)
            elif method == "notifications/prompts/list_changed" and self.on_prompts_list_changed:
                await self.on_prompts_list_changed(params)
            elif method == "notifications/roots/list_changed" and self.on_roots_list_changed:
                await self.on_roots_list_changed(params)

        else:
            logger.warning(f"Received unexpected message: {data}")

    async def list_tools(self, timeout: float | None = None) -> list[MCPToolSchema]:
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
        arguments: dict[str, Any],
        timeout: float | None = None,
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
                content=[{"type": "text", "text": f"Error: {e!s}"}],
                isError=True,
            )

        # _send_request returned None - this means timeout
        logger.error(f"Tool '{name}' call failed: request timed out")
        return MCPToolResult(
            content=[
                {
                    "type": "text",
                    "text": f"Error: Tool '{name}' request timed out after {timeout}s",
                }
            ],
            isError=True,
        )

    def get_cached_tools(self) -> list[MCPToolSchema]:
        """Get cached tools list (from connection time)."""
        return self._tools

    async def read_resource(
        self,
        uri: str,
        timeout: float | None = None,
    ) -> dict[str, Any] | None:
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
                "resources/read",
                {"uri": uri},
                timeout=timeout,
            )
            return result
        except Exception as e:
            logger.error("resources/read error for %s: %s", uri, e)
            return None

    async def list_resources(
        self,
        timeout: float | None = None,
    ) -> dict[str, Any] | None:
        """List resources from the MCP server via resources/list.

        Returns:
            Response dict with 'resources' list, or None on error.
        """
        timeout = timeout or self.timeout
        try:
            result = await self._send_request(
                "resources/list",
                {},
                timeout=timeout,
            )
            return result
        except Exception as e:
            logger.error("resources/list error: %s", e)
            return None

    # ========================================================================
    # MCP Protocol Capabilities (Phase 1)
    # ========================================================================

    async def ping(self, timeout: float | None = None) -> bool:
        """Send ping to check connection health.

        Args:
            timeout: Operation timeout in seconds

        Returns:
            True if ping successful, False otherwise
        """
        timeout = timeout or self.timeout
        try:
            result = await self._send_request("ping", {}, timeout=timeout)
            return result is not None
        except Exception as e:
            logger.error(f"Ping failed: {e}")
            return False

    async def list_prompts(self, timeout: float | None = None) -> list[dict[str, Any]]:
        """List available prompt templates.

        Args:
            timeout: Operation timeout in seconds

        Returns:
            List of prompt definitions
        """
        timeout = timeout or self.timeout
        try:
            result = await self._send_request("prompts/list", {}, timeout=timeout)
            if result:
                return cast(list[dict[str, Any]], result.get("prompts", []))
            return []
        except Exception as e:
            logger.error(f"list_prompts error: {e}")
            return []

    async def get_prompt(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any] | None:
        """Get a specific prompt template with arguments.

        Args:
            name: Prompt name
            arguments: Prompt arguments
            timeout: Operation timeout in seconds

        Returns:
            Prompt definition with messages, or None on error
        """
        timeout = timeout or self.timeout
        try:
            result = await self._send_request(
                "prompts/get",
                {"name": name, "arguments": arguments or {}},
                timeout=timeout,
            )
            return result
        except Exception as e:
            logger.error(f"get_prompt error for {name}: {e}")
            return None

    async def subscribe_resource(
        self,
        uri: str,
        timeout: float | None = None,
    ) -> bool:
        """Subscribe to resource update notifications.

        Args:
            uri: Resource URI to subscribe to
            timeout: Operation timeout in seconds

        Returns:
            True if subscription successful, False otherwise
        """
        timeout = timeout or self.timeout
        try:
            result = await self._send_request(
                "resources/subscribe",
                {"uri": uri},
                timeout=timeout,
            )
            return result is not None
        except Exception as e:
            logger.error(f"subscribe_resource error for {uri}: {e}")
            return False

    async def unsubscribe_resource(
        self,
        uri: str,
        timeout: float | None = None,
    ) -> bool:
        """Unsubscribe from resource update notifications.

        Args:
            uri: Resource URI to unsubscribe from
            timeout: Operation timeout in seconds

        Returns:
            True if unsubscription successful, False otherwise
        """
        timeout = timeout or self.timeout
        try:
            result = await self._send_request(
                "resources/unsubscribe",
                {"uri": uri},
                timeout=timeout,
            )
            return result is not None
        except Exception as e:
            logger.error(f"unsubscribe_resource error for {uri}: {e}")
            return False

    async def set_logging_level(
        self,
        level: str,
        timeout: float | None = None,
    ) -> bool:
        """Set server logging level.

        Args:
            level: Logging level (debug, info, notice, warning, error, critical, alert, emergency)
            timeout: Operation timeout in seconds

        Returns:
            True if successful, False otherwise
        """
        timeout = timeout or self.timeout
        try:
            result = await self._send_request(
                "logging/setLevel",
                {"level": level},
                timeout=timeout,
            )
            return result is not None
        except Exception as e:
            logger.error(f"set_logging_level error: {e}")
            return False

    async def _send_request(
        self,
        method: str,
        params: dict[str, Any],
        timeout: float = DEFAULT_TIMEOUT,
    ) -> dict[str, Any] | None:
        """Send a JSON-RPC request and wait for response.

        The lock is only held during request ID generation and pending_requests
        access, not during the actual WebSocket send operation. This improves
        concurrency by allowing multiple requests to be sent in parallel.

        Raises:
            ConnectionError: If the WebSocket connection is closed or lost.
        """
        if not self._ws or self._ws.closed:
            raise ConnectionError(f"WebSocket not connected to {self.url}")

        # Only hold lock for ID generation and pending_requests access
        async with self._request_id_lock:
            self._request_id += 1
            request_id = self._request_id
            # Create future for response
            future: asyncio.Future[Any] = asyncio.get_event_loop().create_future()
            self._pending_requests[request_id] = future

        # Build request outside of lock
        request = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
            "id": request_id,
        }

        try:
            logger.debug(f"Sending WebSocket request: {method} (id={request_id})")
            # Send without holding lock - allows concurrent sends
            await self._ws.send_json(request)

            # Wait for response with timeout
            result = await asyncio.wait_for(future, timeout=timeout)
            return cast(dict[str, Any] | None, result)

        except TimeoutError:
            async with self._request_id_lock:
                self._pending_requests.pop(request_id, None)
            error_msg = f"MCP request '{method}' timed out after {timeout}s (url={self.url})"
            logger.error(error_msg)
            return None
        except (ConnectionError, ConnectionResetError, RuntimeError) as e:
            async with self._request_id_lock:
                self._pending_requests.pop(request_id, None)
            error_str = str(e)
            if "closed" in error_str.lower() or "connection" in error_str.lower():
                logger.error(f"MCP WebSocket connection lost: {e}")
                self._connected = False
                raise ConnectionError(f"WebSocket connection lost: {e}") from e
            logger.error(f"MCP request error: {e}")
            raise
        except Exception as e:
            async with self._request_id_lock:
                self._pending_requests.pop(request_id, None)
            logger.error(f"MCP request error: {e}")
            return None

    async def _send_notification(self, method: str, params: dict[str, Any]) -> None:
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

    async def _send_response(
        self,
        request_id: int,
        result: dict[str, Any] | None = None,
        error: dict[str, Any] | None = None,
    ) -> None:
        """Send a JSON-RPC response to a server request."""
        if not self._ws or self._ws.closed:
            return

        response: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id}

        if error:
            response["error"] = error
        else:
            response["result"] = result or {}

        try:
            logger.debug(f"Sending response for request {request_id}")
            await self._ws.send_json(response)
        except Exception as e:
            logger.error(f"Response error: {e}")

    async def _handle_server_request(
        self, request_id: int, method: str, params: dict[str, Any]
    ) -> None:
        """Handle server-initiated requests."""
        try:
            if method == "sampling/createMessage":
                await self._handle_sampling_request(request_id, params)
            elif method == "elicitation/create":
                await self._handle_elicitation_request(request_id, params)
            elif method == "roots/list":
                await self._handle_roots_list_request(request_id, params)
            else:
                # Unknown method - return error
                await self._send_response(
                    request_id,
                    error={
                        "code": -32601,
                        "message": f"Method not found: {method}",
                    },
                )
        except Exception as e:
            logger.error(f"Error handling server request {method}: {e}")
            await self._send_response(
                request_id,
                error={"code": -32603, "message": f"Internal error: {e!s}"},
            )

    async def _handle_sampling_request(self, request_id: int, params: dict[str, Any]) -> None:
        """Handle sampling/createMessage request from server."""
        if not self.on_sampling_request:
            await self._send_response(
                request_id,
                error={
                    "code": -32601,
                    "message": "Sampling not supported - no handler registered",
                },
            )
            return

        try:
            result = await self.on_sampling_request(params)
            await self._send_response(request_id, result=result)
        except Exception as e:
            logger.error(f"Sampling handler error: {e}")
            await self._send_response(
                request_id,
                error={"code": -32603, "message": f"Sampling failed: {e!s}"},
            )

    async def _handle_elicitation_request(self, request_id: int, params: dict[str, Any]) -> None:
        """Handle elicitation/create request from server."""
        if not self.on_elicitation_request:
            await self._send_response(
                request_id,
                error={
                    "code": -32601,
                    "message": "Elicitation not supported - no handler registered",
                },
            )
            return

        try:
            result = await self.on_elicitation_request(params)
            await self._send_response(request_id, result=result)
        except Exception as e:
            logger.error(f"Elicitation handler error: {e}")
            await self._send_response(
                request_id,
                error={"code": -32603, "message": f"Elicitation failed: {e!s}"},
            )

    async def _handle_roots_list_request(self, request_id: int, params: dict[str, Any]) -> None:
        """Handle roots/list request from server."""
        if self.on_roots_list:
            try:
                result = await self.on_roots_list(params)
                await self._send_response(request_id, result=result)
            except Exception as e:
                logger.error(f"Roots list handler error: {e}")
                await self._send_response(
                    request_id,
                    error={"code": -32603, "message": f"Roots list failed: {e!s}"},
                )
        else:
            # Return default empty roots list
            await self._send_response(request_id, result={"roots": self._roots})

    # ========================================================================
    # MCP Protocol Capabilities (Phase 2)
    # ========================================================================

    async def set_roots(self, roots: list[dict[str, Any]]) -> None:
        """Set the client's roots and notify the server.

        Args:
            roots: List of root definitions with 'uri' and optional 'name'
        """
        self._roots = roots
        await self.notify_roots_list_changed()

    async def notify_roots_list_changed(self) -> None:
        """Notify the server that the roots list has changed."""
        await self._send_notification("notifications/roots/list_changed", {})

    async def complete(
        self,
        ref: dict[str, Any],
        argument: dict[str, Any],
        context: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any] | None:
        """Request completion suggestions from the server.

        Args:
            ref: Reference to the prompt or resource template
                - For prompts: {"type": "ref/prompt", "name": "prompt_name"}
                - For resources: {"type": "ref/resource", "uri": "template_uri"}
            argument: Current argument being completed
                - {"name": "arg_name", "value": "current_value"}
            context: Optional context for better suggestions
            timeout: Operation timeout in seconds

        Returns:
            Completion result with 'values' list, or None on error

        Reference: https://modelcontextprotocol.io/specification/2025-11-25
        """
        timeout = timeout or self.timeout
        params: dict[str, Any] = {"ref": ref, "argument": argument}
        if context:
            params["context"] = context

        try:
            result = await self._send_request("completion/complete", params, timeout=timeout)
            return result
        except Exception as e:
            logger.error(f"complete error: {e}")
            return None
