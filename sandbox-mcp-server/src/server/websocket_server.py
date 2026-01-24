"""WebSocket MCP Server implementation.

Provides a WebSocket-based MCP server that exposes file system tools
for remote sandbox operations.
"""

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

import aiohttp
from aiohttp import web

logger = logging.getLogger(__name__)


@dataclass
class MCPServerInfo:
    """MCP server information."""

    name: str = "sandbox-mcp-server"
    version: str = "0.1.0"
    protocol_version: str = "2024-11-05"


@dataclass
class MCPTool:
    """MCP tool definition."""

    name: str
    description: str
    input_schema: Dict[str, Any]
    handler: Callable[..., Any]


class MCPWebSocketServer:
    """
    WebSocket-based MCP Server.

    Implements the MCP protocol over WebSocket for bidirectional communication
    with MCP clients. Designed to run inside Docker containers as a sandbox
    file system operation server.

    Features:
    - JSON-RPC 2.0 over WebSocket
    - Tool registration and discovery
    - Heartbeat/ping-pong support
    - Graceful shutdown

    Usage:
        server = MCPWebSocketServer(host="0.0.0.0", port=8765)
        server.register_tool(read_tool)
        await server.start()
    """

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 8765,
        workspace_dir: str = "/workspace",
    ):
        """
        Initialize the MCP WebSocket server.

        Args:
            host: Host to bind to
            port: Port to listen on
            workspace_dir: Root directory for file operations
        """
        self.host = host
        self.port = port
        self.workspace_dir = workspace_dir

        self._app: Optional[web.Application] = None
        self._runner: Optional[web.AppRunner] = None
        self._site: Optional[web.TCPSite] = None

        self._tools: Dict[str, MCPTool] = {}
        self._clients: Dict[str, web.WebSocketResponse] = {}
        self._server_info = MCPServerInfo()

        self._shutdown_event = asyncio.Event()

    def register_tool(self, tool: MCPTool) -> None:
        """
        Register a tool with the server.

        Args:
            tool: Tool to register
        """
        self._tools[tool.name] = tool
        logger.info(f"Registered tool: {tool.name}")

    def register_tools(self, tools: list[MCPTool]) -> None:
        """Register multiple tools."""
        for tool in tools:
            self.register_tool(tool)

    async def start(self) -> None:
        """Start the WebSocket server."""
        self._app = web.Application()
        self._app.router.add_get("/", self._handle_websocket)
        self._app.router.add_get("/health", self._handle_health)

        self._runner = web.AppRunner(self._app)
        await self._runner.setup()

        self._site = web.TCPSite(self._runner, self.host, self.port)
        await self._site.start()

        logger.info(f"MCP WebSocket server started on ws://{self.host}:{self.port}")

    async def stop(self) -> None:
        """Stop the WebSocket server."""
        logger.info("Stopping MCP WebSocket server...")

        # Close all client connections
        for client_id, ws in list(self._clients.items()):
            try:
                await ws.close(code=aiohttp.WSCloseCode.GOING_AWAY, message=b"Server shutdown")
            except Exception as e:
                logger.error(f"Error closing client {client_id}: {e}")

        self._clients.clear()

        # Cleanup server
        if self._site:
            await self._site.stop()
        if self._runner:
            await self._runner.cleanup()

        self._shutdown_event.set()
        logger.info("MCP WebSocket server stopped")

    async def wait_closed(self) -> None:
        """Wait for the server to close."""
        await self._shutdown_event.wait()

    async def _handle_health(self, request: web.Request) -> web.Response:
        """Handle health check requests."""
        return web.json_response(
            {
                "status": "healthy",
                "server": self._server_info.name,
                "version": self._server_info.version,
                "tools_count": len(self._tools),
                "clients_count": len(self._clients),
            }
        )

    async def _handle_websocket(self, request: web.Request) -> web.WebSocketResponse:
        """Handle incoming WebSocket connections."""
        ws = web.WebSocketResponse(heartbeat=30.0)
        await ws.prepare(request)

        client_id = f"client-{id(ws)}"
        self._clients[client_id] = ws
        logger.info(f"Client connected: {client_id}")

        try:
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    try:
                        data = json.loads(msg.data)
                        response = await self._handle_message(data)
                        if response:
                            await ws.send_json(response)
                    except json.JSONDecodeError as e:
                        await ws.send_json(
                            {
                                "jsonrpc": "2.0",
                                "error": {"code": -32700, "message": f"Parse error: {e}"},
                                "id": None,
                            }
                        )
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    logger.error(f"WebSocket error: {ws.exception()}")
                    break

        except asyncio.CancelledError:
            logger.debug(f"Client handler cancelled: {client_id}")
        except Exception as e:
            logger.error(f"Error handling client {client_id}: {e}", exc_info=True)
        finally:
            self._clients.pop(client_id, None)
            logger.info(f"Client disconnected: {client_id}")

        return ws

    async def _handle_message(self, data: dict) -> Optional[dict]:
        """
        Handle incoming JSON-RPC message.

        Args:
            data: Parsed JSON-RPC message

        Returns:
            Response dict or None for notifications
        """
        method = data.get("method")
        params = data.get("params", {})
        request_id = data.get("id")

        # Notification (no id) - no response expected
        if request_id is None and method:
            await self._handle_notification(method, params)
            return None

        try:
            result = await self._dispatch_method(method, params)
            return {
                "jsonrpc": "2.0",
                "result": result,
                "id": request_id,
            }
        except Exception as e:
            logger.error(f"Error handling method {method}: {e}", exc_info=True)
            return {
                "jsonrpc": "2.0",
                "error": {
                    "code": -32603,
                    "message": str(e),
                },
                "id": request_id,
            }

    async def _handle_notification(self, method: str, params: dict) -> None:
        """Handle JSON-RPC notifications."""
        if method == "notifications/initialized":
            logger.info("Client initialized")
        else:
            logger.debug(f"Received notification: {method}")

    async def _dispatch_method(self, method: str, params: dict) -> Any:
        """
        Dispatch method call to appropriate handler.

        Args:
            method: Method name
            params: Method parameters

        Returns:
            Method result
        """
        # MCP protocol methods
        if method == "initialize":
            return await self._handle_initialize(params)
        elif method == "tools/list":
            return await self._handle_list_tools()
        elif method == "tools/call":
            return await self._handle_call_tool(params)
        elif method == "ping":
            return {}
        else:
            raise ValueError(f"Unknown method: {method}")

    async def _handle_initialize(self, params: dict) -> dict:
        """Handle MCP initialize request."""
        client_info = params.get("clientInfo", {})
        logger.info(f"Initializing client: {client_info}")

        return {
            "protocolVersion": self._server_info.protocol_version,
            "capabilities": {
                "tools": {"listChanged": False},
            },
            "serverInfo": {
                "name": self._server_info.name,
                "version": self._server_info.version,
            },
        }

    async def _handle_list_tools(self) -> dict:
        """Handle tools/list request."""
        tools = [
            {
                "name": tool.name,
                "description": tool.description,
                "inputSchema": tool.input_schema,
            }
            for tool in self._tools.values()
        ]
        return {"tools": tools}

    async def _handle_call_tool(self, params: dict) -> dict:
        """Handle tools/call request."""
        tool_name = params.get("name")
        arguments = params.get("arguments", {})

        if tool_name not in self._tools:
            return {
                "content": [{"type": "text", "text": f"Unknown tool: {tool_name}"}],
                "isError": True,
            }

        tool = self._tools[tool_name]

        try:
            # Inject workspace_dir into arguments for file tools
            arguments["_workspace_dir"] = self.workspace_dir
            result = await tool.handler(**arguments)

            # Normalize result to MCP format
            if isinstance(result, str):
                return {
                    "content": [{"type": "text", "text": result}],
                    "isError": False,
                }
            elif isinstance(result, dict):
                if "content" in result:
                    return result
                else:
                    return {
                        "content": [{"type": "text", "text": json.dumps(result)}],
                        "isError": False,
                    }
            else:
                return {
                    "content": [{"type": "text", "text": str(result)}],
                    "isError": False,
                }

        except Exception as e:
            logger.error(f"Tool {tool_name} error: {e}", exc_info=True)
            return {
                "content": [{"type": "text", "text": f"Error: {str(e)}"}],
                "isError": True,
            }
