"""
WebSocket transport for MCP.

Provides bidirectional communication with MCP servers via WebSocket.
"""

import asyncio
import contextlib
import json
import logging
from typing import Any

import aiohttp

from src.domain.model.mcp.transport import TransportConfig, TransportType
from src.infrastructure.mcp.transport.base import (
    BaseTransport,
    MCPTransportClosedError,
    MCPTransportError,
)

logger = logging.getLogger(__name__)


class WebSocketTransport(BaseTransport):
    """
    MCP transport using WebSocket for bidirectional communication.

    Provides:
    - Bidirectional communication (server can push messages)
    - Persistent connection (no repeated handshakes)
    - Cross-network support (can connect to remote servers)
    - Real-time streaming for long-running operations
    """

    def __init__(self, config: TransportConfig | None = None) -> None:
        """Initialize WebSocket transport."""
        super().__init__(config)
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._session: aiohttp.ClientSession | None = None
        self._pending_requests: dict[int, asyncio.Future] = {}
        self._receive_task: asyncio.Task | None = None
        self._initialized = False
        self._closed = False

    async def start(self, config: TransportConfig) -> None:
        """
        Establish WebSocket connection to MCP server.

        Args:
            config: Transport configuration with URL and options.
        """
        if self._is_open:
            logger.debug("WebSocket transport already started")
            return

        self._config = config

        if config.transport_type != TransportType.WEBSOCKET:
            raise MCPTransportError(
                f"Invalid transport type for WebSocket: {config.transport_type}"
            )

        if not config.url:
            raise MCPTransportError("URL is required for WebSocket transport")

        try:
            logger.info(f"Connecting to MCP server via WebSocket: {config.url}")

            timeout = config.timeout_seconds if config.timeout else 30.0
            # None disables heartbeat; avoids PONG timeout killing long tool calls
            heartbeat = config.heartbeat_interval

            self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout))

            self._ws = await self._session.ws_connect(
                config.url,
                headers=config.headers or {},
                heartbeat=heartbeat,
            )

            self._is_open = True
            self._closed = False

            # Start background task to receive messages
            self._receive_task = asyncio.create_task(self._receive_loop())

            # Perform MCP initialization handshake
            await self._initialize()

            logger.info(f"WebSocket transport connected to: {config.url}")

        except Exception as e:
            logger.error(f"Failed to connect WebSocket: {e}", exc_info=True)
            await self._cleanup()
            raise MCPTransportError(f"WebSocket connection failed: {e}") from e

    async def _initialize(self) -> None:
        """Perform MCP protocol initialization handshake."""
        if self._initialized:
            return

        # Step 1: Send initialize request
        init_params = {
            "protocolVersion": "2024-11-05",
            "capabilities": {"roots": {"listChanged": True}, "sampling": {}},
            "clientInfo": {"name": "MemStack", "version": "0.2.0"},
        }

        result = await self._send_request("initialize", init_params)
        logger.info(f"MCP server initialized: {result.get('serverInfo', {})}")

        # Step 2: Send initialized notification
        await self._send_notification("notifications/initialized", {})

        self._initialized = True

    async def _send_notification(self, method: str, params: dict[str, Any]) -> None:
        """Send a JSON-RPC notification (no response expected)."""
        if not self._ws or self._ws.closed:
            raise MCPTransportClosedError("WebSocket not connected")

        notification = {"jsonrpc": "2.0", "method": method, "params": params}
        await self._ws.send_json(notification)

    async def _send_request(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        """Send a JSON-RPC request and wait for response."""
        if not self._ws or self._ws.closed:
            raise MCPTransportClosedError("WebSocket not connected")

        request_id = self._next_request_id()

        request = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params or {},
        }

        # Create future for response
        future: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending_requests[request_id] = future

        try:
            logger.debug(f"Sending WebSocket request: {method} (id={request_id})")
            await self._ws.send_json(request)

            result = await asyncio.wait_for(future, timeout=timeout)
            return result

        except TimeoutError:
            self._pending_requests.pop(request_id, None)
            raise MCPTransportError(f"Timeout waiting for response to {method}") from None

        except Exception:
            self._pending_requests.pop(request_id, None)
            raise

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

                elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.CLOSE):
                    logger.info("WebSocket connection closed by server")
                    break

        except asyncio.CancelledError:
            logger.debug("WebSocket receive loop cancelled")
        except Exception as e:
            logger.error(f"Error in WebSocket receive loop: {e}", exc_info=True)
        finally:
            # Fail all pending requests
            for future in self._pending_requests.values():
                if not future.done():
                    future.set_exception(MCPTransportClosedError("WebSocket closed"))
            self._pending_requests.clear()

    async def _handle_message(self, data: dict[str, Any]) -> None:
        """Handle incoming JSON-RPC message."""
        request_id = data.get("id")

        if request_id is not None and request_id in self._pending_requests:
            future = self._pending_requests.pop(request_id)

            if "error" in data:
                error = data["error"]
                error_msg = (
                    error.get("message", str(error)) if isinstance(error, dict) else str(error)
                )
                future.set_exception(MCPTransportError(f"MCP server error: {error_msg}"))
            else:
                future.set_result(data.get("result", {}))

        elif "method" in data and "id" not in data:
            # Server-initiated notification
            method = data.get("method")
            logger.debug(f"Received server notification: {method}")

        else:
            logger.warning(f"Received unexpected message: {data}")

    async def stop(self) -> None:
        """Close WebSocket connection."""
        if self._closed:
            return

        self._closed = True
        self._is_open = False
        self._initialized = False

        await self._cleanup()
        logger.info("WebSocket transport stopped")

    async def _cleanup(self) -> None:
        """Clean up resources."""
        # Cancel receive task
        if self._receive_task and not self._receive_task.done():
            self._receive_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._receive_task
            self._receive_task = None

        # Close WebSocket
        if self._ws and not self._ws.closed:
            await self._ws.close()
            self._ws = None

        # Close session
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

        # Fail pending requests
        for future in self._pending_requests.values():
            if not future.done():
                future.set_exception(MCPTransportClosedError("WebSocket closed"))
        self._pending_requests.clear()

    async def send(
        self,
        message: dict[str, Any],
        timeout: float | None = None,
    ) -> None:
        """
        Send a message over WebSocket.

        Args:
            message: JSON-RPC message to send.
            timeout: Ignored for WebSocket send.
        """
        if not self._ws or self._ws.closed:
            raise MCPTransportClosedError("WebSocket not connected")

        await self._ws.send_json(message)

    async def receive(
        self,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """
        Receive is handled by background task.

        For WebSocket, use send_request for request/response pattern.
        """
        raise MCPTransportError(
            "WebSocket transport uses async receive loop; use send_request instead"
        )

    # High-level API methods

    async def list_tools(self) -> list[dict[str, Any]]:
        """List all available tools from the MCP server."""
        result = await self._send_request("tools/list")
        return result.get("tools", [])

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Call a tool on the MCP server."""
        params = {"name": tool_name, "arguments": arguments}
        return await self._send_request("tools/call", params)
