"""WebSocket MCP Server for CUA tools."""

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
    name: str = "cua-mcp-server"
    version: str = "0.1.0"
    protocol_version: str = "2024-11-05"


@dataclass
class MCPTool:
    name: str
    description: str
    input_schema: Dict[str, Any]
    handler: Callable[..., Any]


class MCPWebSocketServer:
    def __init__(self, host: str = "0.0.0.0", port: int = 18766):
        self.host = host
        self.port = port
        self._app: Optional[web.Application] = None
        self._runner: Optional[web.AppRunner] = None
        self._site: Optional[web.TCPSite] = None
        self._tools: Dict[str, MCPTool] = {}
        self._clients: Dict[str, web.WebSocketResponse] = {}
        self._server_info = MCPServerInfo()
        self._shutdown_event = asyncio.Event()

    def register_tool(self, tool: MCPTool) -> None:
        self._tools[tool.name] = tool
        logger.info("Registered tool: %s", tool.name)

    def register_tools(self, tools: list[MCPTool]) -> None:
        for tool in tools:
            self.register_tool(tool)

    async def start(self) -> None:
        self._app = web.Application()
        self._app.router.add_get("/", self._handle_websocket)
        self._app.router.add_get("/health", self._handle_health)

        self._runner = web.AppRunner(self._app)
        await self._runner.setup()

        self._site = web.TCPSite(self._runner, self.host, self.port)
        await self._site.start()

        logger.info("CUA MCP WebSocket server started on ws://%s:%s", self.host, self.port)

    async def stop(self) -> None:
        logger.info("Stopping CUA MCP WebSocket server...")
        for client_id, ws in list(self._clients.items()):
            try:
                await ws.close(code=aiohttp.WSCloseCode.GOING_AWAY, message=b"Server shutdown")
            except Exception as exc:
                logger.error("Error closing client %s: %s", client_id, exc)

        self._clients.clear()

        if self._site:
            await self._site.stop()
        if self._runner:
            await self._runner.cleanup()

        self._shutdown_event.set()
        logger.info("CUA MCP WebSocket server stopped")

    async def wait_closed(self) -> None:
        await self._shutdown_event.wait()

    async def _handle_health(self, request: web.Request) -> web.Response:
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
        ws = web.WebSocketResponse(heartbeat=30.0)
        await ws.prepare(request)

        client_id = f"client-{id(ws)}"
        self._clients[client_id] = ws
        logger.info("Client connected: %s", client_id)

        try:
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    try:
                        data = json.loads(msg.data)
                        response = await self._handle_message(data)
                        if response:
                            await ws.send_json(response)
                    except json.JSONDecodeError as exc:
                        await ws.send_json(
                            {
                                "jsonrpc": "2.0",
                                "error": {"code": -32700, "message": f"Parse error: {exc}"},
                                "id": None,
                            }
                        )
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    logger.error("WebSocket error: %s", ws.exception())
                    break
        except asyncio.CancelledError:
            logger.debug("Client handler cancelled: %s", client_id)
        except Exception as exc:
            logger.error("Error handling client %s: %s", client_id, exc, exc_info=True)
        finally:
            self._clients.pop(client_id, None)
            logger.info("Client disconnected: %s", client_id)

        return ws

    async def _handle_message(self, data: dict) -> Optional[dict]:
        method = data.get("method")
        params = data.get("params") or {}
        request_id = data.get("id")

        if request_id is None and method:
            return None

        if method is None:
            if request_id is None:
                return None
            return {
                "jsonrpc": "2.0",
                "error": {"code": -32600, "message": "Invalid request: missing method"},
                "id": request_id,
            }

        if not isinstance(params, dict):
            raise ValueError("Invalid params: expected object")

        try:
            result = await self._dispatch_method(method, params)
            return {"jsonrpc": "2.0", "result": result, "id": request_id}
        except Exception as exc:
            logger.error("Error handling method %s: %s", method, exc, exc_info=True)
            return {
                "jsonrpc": "2.0",
                "error": {"code": -32603, "message": str(exc)},
                "id": request_id,
            }

    async def _dispatch_method(self, method: str, params: Dict[str, Any]) -> Any:
        if method == "initialize":
            return {
                "serverInfo": {
                    "name": self._server_info.name,
                    "version": self._server_info.version,
                },
                "protocolVersion": self._server_info.protocol_version,
                "capabilities": {"tools": {}},
            }

        if method == "tools/list":
            tools_data = [
                {
                    "name": t.name,
                    "description": t.description,
                    "inputSchema": t.input_schema,
                }
                for t in self._tools.values()
            ]
            return {"tools": tools_data}

        if method == "tools/call":
            tool_name = params.get("name")
            if not tool_name:
                raise ValueError("Tool name is required")
            arguments = params.get("arguments", {}) or {}
            tool = self._tools.get(tool_name)
            if not tool:
                raise ValueError(f"Tool not found: {tool_name}")

            result = await tool.handler(**arguments)
            return {
                "content": [{"type": "text", "text": result}],
                "isError": False,
            }

        raise ValueError(f"Unknown method: {method}")
