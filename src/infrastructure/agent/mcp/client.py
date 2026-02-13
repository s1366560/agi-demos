"""
MCP Client implementation for connecting to MCP servers.

Supports multiple transport protocols:
- stdio: Standard input/output (subprocess)
- sse: Server-Sent Events (HTTP streaming)
- http: HTTP request/response
- websocket: WebSocket bidirectional communication
"""

import asyncio
import json
import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

import aiohttp
import httpx

logger = logging.getLogger(__name__)


class MCPTransport(ABC):
    """Abstract base class for MCP transport implementations."""

    @abstractmethod
    async def connect(self) -> None:
        """Establish connection to MCP server."""
        pass

    @abstractmethod
    async def disconnect(self) -> None:
        """Close connection to MCP server."""
        pass

    @abstractmethod
    async def send_request(self, method: str, params: Optional[dict] = None) -> dict:
        """
        Send a request to the MCP server.

        Args:
            method: MCP method name (e.g., "tools/list", "tools/call")
            params: Optional parameters for the method

        Returns:
            Response data from server
        """
        pass

    @abstractmethod
    async def list_tools(self) -> list[dict]:
        """List all available tools from the MCP server."""
        pass

    @abstractmethod
    async def call_tool(self, tool_name: str, arguments: dict) -> dict:
        """
        Call a tool on the MCP server.

        Args:
            tool_name: Name of the tool to call
            arguments: Tool arguments

        Returns:
            Tool execution result
        """
        pass


class StdioTransport(MCPTransport):
    """MCP transport using stdio (subprocess communication)."""

    def __init__(self, config: dict):
        import os

        self.config = config
        self.process: Optional[asyncio.subprocess.Process] = None
        self.command = config.get("command")
        self.args = config.get("args", [])
        # Merge custom env with system env, or use None to inherit system env
        custom_env = config.get("env")
        if custom_env:
            # Merge with system environment
            self.env = {**os.environ, **custom_env}
        else:
            # Use None to inherit parent's environment (including PATH)
            self.env = None
        self._request_id = 0
        self._initialized = False

    async def connect(self) -> None:
        """Start subprocess and establish stdio connection."""
        try:
            logger.info(f"Starting MCP server: {self.command} {self.args}")
            self.process = await asyncio.create_subprocess_exec(
                self.command,
                *self.args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=self.env,
            )
            logger.info(f"Started MCP server process: {self.command} (pid={self.process.pid})")

            # Perform MCP initialization handshake
            await self._initialize()
        except Exception as e:
            logger.error(f"Failed to start MCP server process: {e}", exc_info=True)
            raise

    async def _initialize(self) -> None:
        """Perform MCP protocol initialization handshake."""
        if self._initialized:
            return

        # Step 1: Send initialize request
        init_params = {
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
            "clientInfo": {"name": "MemStack", "version": "0.2.0"},
        }

        result = await self.send_request("initialize", init_params)
        logger.info(f"MCP server initialized: {result.get('serverInfo', {})}")

        # Step 2: Send initialized notification (no response expected)
        await self._send_notification("notifications/initialized", {})

        self._initialized = True

    async def _send_notification(self, method: str, params: dict) -> None:
        """Send a JSON-RPC notification (no response expected)."""
        if not self.process or not self.process.stdin:
            raise RuntimeError("MCP server process not started")

        notification = {"jsonrpc": "2.0", "method": method, "params": params}
        notification_json = json.dumps(notification) + "\n"
        self.process.stdin.write(notification_json.encode())
        await self.process.stdin.drain()

    async def disconnect(self) -> None:
        """Terminate subprocess."""
        if self.process:
            self.process.terminate()
            await self.process.wait()
            self.process = None
            self._initialized = False
            logger.info("MCP server process terminated")

    async def send_request(self, method: str, params: Optional[dict] = None) -> dict:
        """Send JSON-RPC request via stdin and read response from stdout."""
        if not self.process or not self.process.stdin or not self.process.stdout:
            raise RuntimeError("MCP server process not started")

        self._request_id += 1
        request = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": method,
            "params": params or {},
        }

        # Write request to stdin
        request_json = json.dumps(request) + "\n"
        logger.debug(f"Sending MCP request: {method} (id={self._request_id})")
        self.process.stdin.write(request_json.encode())
        await self.process.stdin.drain()

        # Read response from stdout with timeout
        try:
            logger.debug("Waiting for MCP response (timeout=30s)...")
            response_line = await asyncio.wait_for(self.process.stdout.readline(), timeout=30.0)
        except asyncio.TimeoutError:
            # Check if process is still running
            if self.process.returncode is not None:
                stderr = await self.process.stderr.read()
                logger.error(
                    f"MCP process exited with code {self.process.returncode}, stderr: {stderr.decode()[:500]}"
                )
            raise RuntimeError(f"Timeout waiting for response to {method}")

        if not response_line:
            stderr = await self.process.stderr.read()
            logger.error(f"MCP server closed connection, stderr: {stderr.decode()[:500]}")
            raise RuntimeError("MCP server closed connection")

        logger.debug(f"Received MCP response: {response_line.decode()[:200]}...")
        response = json.loads(response_line.decode())

        if "error" in response:
            raise RuntimeError(f"MCP server error: {response['error']}")

        return response.get("result", {})

    async def list_tools(self) -> list[dict]:
        """List all available tools."""
        result = await self.send_request("tools/list")
        return result.get("tools", [])

    async def call_tool(self, tool_name: str, arguments: dict) -> dict:
        """Call a tool on the server."""
        params = {"name": tool_name, "arguments": arguments}
        return await self.send_request("tools/call", params)


class HTTPTransport(MCPTransport):
    """MCP transport using HTTP request/response."""

    def __init__(self, config: dict):
        self.config = config
        self.base_url = config.get("url")
        self.headers = config.get("headers", {})
        self.timeout = config.get("timeout", 30)
        self.client: Optional[httpx.AsyncClient] = None

    async def connect(self) -> None:
        """Initialize HTTP client."""
        self.client = httpx.AsyncClient(
            base_url=self.base_url, headers=self.headers, timeout=self.timeout
        )
        logger.info(f"Connected to MCP server via HTTP: {self.base_url}")

    async def disconnect(self) -> None:
        """Close HTTP client."""
        if self.client:
            await self.client.aclose()
            self.client = None
            logger.info("HTTP client closed")

    async def send_request(self, method: str, params: Optional[dict] = None) -> dict:
        """Send HTTP POST request with JSON-RPC payload."""
        if not self.client:
            raise RuntimeError("HTTP client not initialized")

        request = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}

        try:
            response = await self.client.post("/rpc", json=request)
            response.raise_for_status()
            data = response.json()

            if "error" in data:
                raise RuntimeError(f"MCP server error: {data['error']}")

            return data.get("result", {})
        except httpx.HTTPError as e:
            logger.error(f"HTTP request failed: {e}")
            raise

    async def list_tools(self) -> list[dict]:
        """List all available tools."""
        result = await self.send_request("tools/list")
        return result.get("tools", [])

    async def call_tool(self, tool_name: str, arguments: dict) -> dict:
        """Call a tool on the server."""
        params = {"name": tool_name, "arguments": arguments}
        return await self.send_request("tools/call", params)


class SSETransport(MCPTransport):
    """MCP transport using Streamable HTTP (MCP SDK)."""

    def __init__(self, config: dict):
        self.config = config
        self.url = config.get("url")
        self.headers = config.get("headers", {})
        self._session = None
        self._read_stream = None
        self._write_stream = None
        self._request_id = 0
        self._pending_requests: dict[int, asyncio.Future] = {}
        self._reader_task = None

    async def connect(self) -> None:
        """Initialize streamable HTTP client using MCP SDK."""
        from contextlib import AsyncExitStack

        import httpx
        from mcp.client.streamable_http import streamable_http_client

        self._exit_stack = AsyncExitStack()
        await self._exit_stack.__aenter__()

        try:
            # Create httpx client with headers
            http_client = httpx.AsyncClient(headers=self.headers, timeout=httpx.Timeout(30.0))
            self._http_client = await self._exit_stack.enter_async_context(http_client)

            # Use MCP SDK's streamable_http_client
            streams = await self._exit_stack.enter_async_context(
                streamable_http_client(self.url, http_client=self._http_client)
            )
            self._read_stream, self._write_stream, _ = streams

            # Start reader task to process incoming messages
            self._reader_task = asyncio.create_task(self._read_messages())

            # Perform MCP initialization handshake
            await self._initialize()

            logger.info(f"Connected to MCP server via streamable HTTP: {self.url}")
        except Exception as e:
            await self._exit_stack.__aexit__(type(e), e, e.__traceback__)
            raise

    async def _initialize(self) -> None:
        """Perform MCP protocol initialization handshake."""
        from mcp.shared.message import SessionMessage
        from mcp.types import (
            ClientCapabilities,
            Implementation,
            InitializeRequest,
            InitializeRequestParams,
            JSONRPCMessage,
            JSONRPCNotification,
            JSONRPCRequest,
        )

        # Send initialize request
        init_request = InitializeRequest(
            method="initialize",
            params=InitializeRequestParams(
                protocolVersion="2024-11-05",
                capabilities=ClientCapabilities(
                    roots={"listChanged": True},
                    sampling={},
                ),
                clientInfo=Implementation(name="MemStack", version="0.2.0"),
            ),
        )

        self._request_id += 1
        request_id = self._request_id

        # Create future for response
        future: asyncio.Future = asyncio.Future()
        self._pending_requests[request_id] = future

        # Send message - wrap JSONRPCRequest in JSONRPCMessage
        # Inject SEP-1865 UI extension capability into the raw params
        params_dict = init_request.params.model_dump() if init_request.params else {}
        if "capabilities" in params_dict:
            params_dict["capabilities"]["extensions"] = {
                "io.modelcontextprotocol/ui": {
                    "mimeTypes": ["text/html;profile=mcp-app"],
                },
            }
        jsonrpc_request = JSONRPCRequest(
            jsonrpc="2.0",
            id=request_id,
            method=init_request.method,
            params=params_dict,
        )
        await self._write_stream.send(SessionMessage(message=JSONRPCMessage(root=jsonrpc_request)))

        # Wait for response
        try:
            result = await asyncio.wait_for(future, timeout=30.0)
            logger.info(f"MCP server initialized: {result}")
        except asyncio.TimeoutError:
            self._pending_requests.pop(request_id, None)
            raise RuntimeError("Timeout waiting for initialize response")

        # Send initialized notification - wrap in JSONRPCMessage
        notification = JSONRPCNotification(
            jsonrpc="2.0",
            method="notifications/initialized",
            params={},
        )
        await self._write_stream.send(SessionMessage(message=JSONRPCMessage(root=notification)))

    async def _read_messages(self) -> None:
        """Background task to read incoming messages."""
        try:
            async for message in self._read_stream:
                if isinstance(message, Exception):
                    logger.error(f"Received exception from MCP server: {message}")
                    # Fail all pending requests
                    for future in self._pending_requests.values():
                        if not future.done():
                            future.set_exception(message)
                    self._pending_requests.clear()
                    continue

                # Process JSON-RPC response - message.message is JSONRPCMessage, access .root
                msg = message.message.root if hasattr(message.message, "root") else message.message
                if hasattr(msg, "id") and msg.id is not None:
                    request_id = msg.id
                    if request_id in self._pending_requests:
                        future = self._pending_requests.pop(request_id)
                        if hasattr(msg, "error") and msg.error:
                            future.set_exception(RuntimeError(f"MCP error: {msg.error}"))
                        elif hasattr(msg, "result"):
                            future.set_result(msg.result)
                        else:
                            future.set_result(None)
        except Exception as e:
            logger.error(f"Error in message reader: {e}")
            # Fail all pending requests
            for future in self._pending_requests.values():
                if not future.done():
                    future.set_exception(e)
            self._pending_requests.clear()

    async def disconnect(self) -> None:
        """Close streamable HTTP client."""
        if self._reader_task:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
            self._reader_task = None

        if hasattr(self, "_exit_stack") and self._exit_stack:
            await self._exit_stack.__aexit__(None, None, None)
            self._exit_stack = None

        self._read_stream = None
        self._write_stream = None
        self._pending_requests.clear()
        logger.info("Streamable HTTP client closed")

    async def send_request(self, method: str, params: Optional[dict] = None) -> dict:
        """Send request via streamable HTTP."""
        if not self._write_stream:
            raise RuntimeError("Streamable HTTP client not initialized")

        from mcp.shared.message import SessionMessage
        from mcp.types import JSONRPCMessage, JSONRPCRequest

        self._request_id += 1
        request_id = self._request_id

        # Create future for response
        future: asyncio.Future = asyncio.Future()
        self._pending_requests[request_id] = future

        # Send request - wrap JSONRPCRequest in JSONRPCMessage
        request = JSONRPCRequest(
            jsonrpc="2.0",
            id=request_id,
            method=method,
            params=params,
        )
        await self._write_stream.send(SessionMessage(message=JSONRPCMessage(root=request)))

        # Wait for response
        try:
            result = await asyncio.wait_for(future, timeout=30.0)
            # Handle result that may be a Pydantic model or dict
            if hasattr(result, "model_dump"):
                return result.model_dump()
            elif isinstance(result, dict):
                return result
            else:
                return {"result": result}
        except asyncio.TimeoutError:
            self._pending_requests.pop(request_id, None)
            raise RuntimeError(f"Timeout waiting for response to {method}")

    async def list_tools(self) -> list[dict]:
        """List all available tools."""
        result = await self.send_request("tools/list")
        tools = result.get("tools", [])
        # Convert Pydantic models to dicts if needed
        return [t.model_dump() if hasattr(t, "model_dump") else t for t in tools]

    async def call_tool(self, tool_name: str, arguments: dict) -> dict:
        """Call a tool on the server."""
        params = {"name": tool_name, "arguments": arguments}
        return await self.send_request("tools/call", params)


class WebSocketTransport(MCPTransport):
    """MCP transport using WebSocket for bidirectional communication.

    This transport provides:
    - Bidirectional communication (server can push messages)
    - Persistent connection (no repeated handshakes)
    - Cross-network support (can connect to remote servers)
    - Real-time streaming for long-running operations
    """

    def __init__(self, config: dict):
        """
        Initialize WebSocket transport.

        Args:
            config: Configuration dict with:
                - url: WebSocket URL (ws:// or wss://)
                - headers: Optional HTTP headers for connection
                - timeout: Request timeout in seconds (default: 30)
                - heartbeat_interval: Ping interval in seconds (default: 30)
                - reconnect_attempts: Max reconnection attempts (default: 3)
        """
        self.url = config.get("url")
        if not self.url:
            raise ValueError("WebSocket URL is required")

        self.headers = config.get("headers", {})
        self.timeout = config.get("timeout", 30)
        self.heartbeat_interval = config.get("heartbeat_interval", 30)
        self.reconnect_attempts = config.get("reconnect_attempts", 3)

        self._ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self._session: Optional[aiohttp.ClientSession] = None
        self._request_id = 0
        self._pending_requests: Dict[int, asyncio.Future] = {}
        self._receive_task: Optional[asyncio.Task] = None
        self._initialized = False
        self._closed = False

    async def connect(self) -> None:
        """Establish WebSocket connection to MCP server."""
        if self._ws and not self._ws.closed:
            logger.debug("WebSocket already connected")
            return

        try:
            logger.info(f"Connecting to MCP server via WebSocket: {self.url}")

            # Create aiohttp session
            self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.timeout))

            # Connect WebSocket
            self._ws = await self._session.ws_connect(
                self.url,
                headers=self.headers,
                heartbeat=self.heartbeat_interval,
            )

            self._closed = False

            # Start background task to receive messages
            self._receive_task = asyncio.create_task(self._receive_loop())

            # Perform MCP initialization handshake
            await self._initialize()

            logger.info(f"Connected to MCP server via WebSocket: {self.url}")

        except Exception as e:
            logger.error(f"Failed to connect to WebSocket MCP server: {e}", exc_info=True)
            await self._cleanup()
            raise

    async def _initialize(self) -> None:
        """Perform MCP protocol initialization handshake."""
        if self._initialized:
            return

        # Step 1: Send initialize request
        init_params = {
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
            "clientInfo": {"name": "MemStack", "version": "0.2.0"},
        }

        result = await self.send_request("initialize", init_params)
        logger.info(f"MCP server initialized: {result.get('serverInfo', {})}")

        # Step 2: Send initialized notification (no response expected)
        await self._send_notification("notifications/initialized", {})

        self._initialized = True

    async def _send_notification(self, method: str, params: dict) -> None:
        """Send a JSON-RPC notification (no response expected)."""
        if not self._ws or self._ws.closed:
            raise RuntimeError("WebSocket not connected")

        notification = {"jsonrpc": "2.0", "method": method, "params": params}
        await self._ws.send_json(notification)

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
            # For now, just log them

        else:
            logger.warning(f"Received unexpected message: {data}")

    async def disconnect(self) -> None:
        """Close WebSocket connection."""
        if self._closed:
            return

        self._closed = True
        self._initialized = False

        await self._cleanup()
        logger.info("WebSocket MCP client disconnected")

    async def _cleanup(self) -> None:
        """Clean up resources."""
        # Cancel receive task
        if self._receive_task and not self._receive_task.done():
            self._receive_task.cancel()
            try:
                await self._receive_task
            except asyncio.CancelledError:
                pass
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
                future.set_exception(RuntimeError("WebSocket connection closed"))
        self._pending_requests.clear()

    async def send_request(self, method: str, params: Optional[dict] = None) -> dict:
        """
        Send JSON-RPC request and wait for response.

        Args:
            method: MCP method name
            params: Optional parameters

        Returns:
            Response result dict

        Raises:
            RuntimeError: If not connected or request fails
        """
        if not self._ws or self._ws.closed:
            raise RuntimeError("WebSocket not connected")

        self._request_id += 1
        request_id = self._request_id

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
            # Send request
            logger.debug(f"Sending WebSocket request: {method} (id={request_id})")
            await self._ws.send_json(request)

            # Wait for response with timeout
            result = await asyncio.wait_for(future, timeout=self.timeout)
            return result

        except asyncio.TimeoutError:
            self._pending_requests.pop(request_id, None)
            raise RuntimeError(f"Timeout waiting for response to {method}")

        except Exception:
            self._pending_requests.pop(request_id, None)
            raise

    async def list_tools(self) -> list[dict]:
        """List all available tools from the MCP server."""
        result = await self.send_request("tools/list")
        return result.get("tools", [])

    async def call_tool(self, tool_name: str, arguments: dict) -> dict:
        """
        Call a tool on the MCP server.

        Args:
            tool_name: Name of the tool to call
            arguments: Tool arguments

        Returns:
            Tool execution result
        """
        params = {"name": tool_name, "arguments": arguments}
        return await self.send_request("tools/call", params)


class MCPClient:
    """
    MCP Client for connecting to and interacting with MCP servers.

    Supports multiple transport protocols and provides a unified interface
    for tool discovery and execution.
    """

    def __init__(self, server_type: str, transport_config: dict):
        """
        Initialize MCP client.

        Args:
            server_type: Transport protocol ("stdio", "http", "sse", "websocket")
            transport_config: Configuration for the transport
        """
        self.server_type = server_type
        self.transport_config = transport_config
        self.transport: Optional[MCPTransport] = None
        self._connected = False

    async def connect(self) -> None:
        """Establish connection to MCP server."""
        if self._connected:
            return

        # Create appropriate transport
        if self.server_type == "stdio":
            self.transport = StdioTransport(self.transport_config)
        elif self.server_type == "http":
            self.transport = HTTPTransport(self.transport_config)
        elif self.server_type == "sse":
            self.transport = SSETransport(self.transport_config)
        elif self.server_type == "websocket":
            self.transport = WebSocketTransport(self.transport_config)
        else:
            raise ValueError(f"Unsupported transport type: {self.server_type}")

        await self.transport.connect()
        self._connected = True
        logger.info(f"MCP client connected via {self.server_type}")

    async def disconnect(self) -> None:
        """Close connection to MCP server."""
        if self.transport and self._connected:
            await self.transport.disconnect()
            self._connected = False
            self.transport = None
            logger.info("MCP client disconnected")

    async def list_tools(self) -> list[dict]:
        """
        List all available tools from the MCP server.

        Returns:
            List of tool definitions with name, description, and input schema
        """
        if not self._connected or not self.transport:
            raise RuntimeError("MCP client not connected")

        return await self.transport.list_tools()

    async def call_tool(self, tool_name: str, arguments: dict) -> Any:
        """
        Call a tool on the MCP server.

        Args:
            tool_name: Name of the tool to call
            arguments: Tool arguments as a dictionary

        Returns:
            Tool execution result
        """
        if not self._connected or not self.transport:
            raise RuntimeError("MCP client not connected")

        return await self.transport.call_tool(tool_name, arguments)

    async def health_check(self) -> bool:
        """
        Check if the MCP server is healthy and responsive.

        Returns:
            True if server is healthy, False otherwise
        """
        try:
            await self.list_tools()
            return True
        except Exception as e:
            logger.error(f"MCP server health check failed: {e}")
            return False

    async def __aenter__(self):
        """Async context manager entry."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.disconnect()
