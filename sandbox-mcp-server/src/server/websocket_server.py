"""WebSocket MCP Server implementation.

Provides a WebSocket-based MCP server that exposes file system tools
for remote sandbox operations.

Supports token-based authentication for secure local sandbox connections.
"""

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional
from urllib.parse import parse_qs

import aiohttp
from aiohttp import web
from aiohttp.web_log import AccessLogger

logger = logging.getLogger(__name__)


class _HealthFilterAccessLogger(AccessLogger):
    """Suppress access logs for /health endpoint to reduce noise."""

    def log(self, request, response, req_time):
        if request.path == "/health":
            return
        super().log(request, response, req_time)


@dataclass
class MCPServerInfo:
    """MCP server information."""

    name: str = "sandbox-mcp-server"
    version: str = "0.1.0"
    protocol_version: str = "2024-11-05"


@dataclass
class AuthConfig:
    """Authentication configuration."""

    enabled: bool = False  # Set to True for local sandbox mode
    platform_url: Optional[str] = None  # MemStack platform URL for token validation
    allow_localhost: bool = True  # Allow unauthenticated localhost connections
    static_token: Optional[str] = None  # Optional static token for simple auth


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
    - Token-based authentication (optional, for local sandbox mode)

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
        auth_config: Optional[AuthConfig] = None,
    ):
        """
        Initialize the MCP WebSocket server.

        Args:
            host: Host to bind to
            port: Port to listen on
            workspace_dir: Root directory for file operations
            auth_config: Authentication configuration (None = auth disabled)
        """
        self.host = host
        self.port = port
        self.workspace_dir = workspace_dir
        self.auth_config = auth_config or AuthConfig()

        self._app: Optional[web.Application] = None
        self._runner: Optional[web.AppRunner] = None
        self._site: Optional[web.TCPSite] = None

        self._tools: Dict[str, MCPTool] = {}
        self._clients: Dict[str, web.WebSocketResponse] = {}
        self._client_auth: Dict[str, Dict[str, Any]] = {}  # client_id -> auth info
        self._server_info = MCPServerInfo()

        self._shutdown_event = asyncio.Event()
        self._http_session: Optional[aiohttp.ClientSession] = None

    def register_tool(self, tool: MCPTool) -> None:
        """
        Register a tool with the server.

        Args:
            tool: Tool to register
        """
        self._tools[tool.name] = tool
        logger.info(f"[MCP] Registered tool: {tool.name}")
        logger.debug(f"[MCP] Tool schema: {tool.input_schema}")

    def register_tools(self, tools: list[MCPTool]) -> None:
        """Register multiple tools."""
        for tool in tools:
            self.register_tool(tool)

    async def start(self) -> None:
        """Start the WebSocket server."""
        self._app = web.Application()
        self._app.router.add_get("/", self._handle_websocket)
        self._app.router.add_get("/health", self._handle_health)

        self._runner = web.AppRunner(
            self._app,
            access_log=logging.getLogger("aiohttp.access"),
            access_log_class=_HealthFilterAccessLogger,
        )
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
        self._client_auth.clear()

        # Cleanup HTTP session for token validation
        if self._http_session:
            await self._http_session.close()
            self._http_session = None

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
                "auth_enabled": self.auth_config.enabled,
            }
        )

    async def _authenticate_request(
        self, request: web.Request
    ) -> tuple[bool, Optional[Dict[str, Any]], Optional[str]]:
        """
        Authenticate an incoming WebSocket connection.

        Args:
            request: The incoming HTTP request

        Returns:
            Tuple of (authenticated, auth_info, error_message)
        """
        # If auth is not enabled, allow all connections
        if not self.auth_config.enabled:
            return True, {"mode": "no_auth"}, None

        # Check for localhost bypass
        remote = request.remote or ""
        if self.auth_config.allow_localhost and remote in ("127.0.0.1", "::1", "localhost"):
            logger.debug(f"[Auth] Allowing localhost connection from {remote}")
            return True, {"mode": "localhost", "remote": remote}, None

        # Extract token from query params or headers
        token = None

        # Check query params first (for WebSocket URL: ws://host:port?token=xxx)
        query_string = request.query_string
        if query_string:
            params = parse_qs(query_string)
            token = params.get("token", [None])[0]

        # Fallback to header
        if not token:
            token = request.headers.get("X-Auth-Token") or request.headers.get("Authorization")
            if token and token.startswith("Bearer "):
                token = token[7:]

        if not token:
            return False, None, "Authentication required: no token provided"

        # Check static token if configured
        if self.auth_config.static_token:
            if token == self.auth_config.static_token:
                return True, {"mode": "static_token"}, None
            # Don't fail here, might be a platform token

        # Validate token against platform if configured
        if self.auth_config.platform_url:
            auth_info = await self._validate_platform_token(token)
            if auth_info:
                return True, auth_info, None
            return False, None, "Invalid or expired token"

        return False, None, "Authentication failed: invalid token"

    async def _validate_platform_token(self, token: str) -> Optional[Dict[str, Any]]:
        """
        Validate token against the MemStack platform.

        Args:
            token: Token to validate

        Returns:
            Auth info dict if valid, None otherwise
        """
        if not self.auth_config.platform_url:
            return None

        try:
            if self._http_session is None:
                self._http_session = aiohttp.ClientSession()

            validate_url = f"{self.auth_config.platform_url}/api/v1/sandbox/token/validate"
            async with self._http_session.post(
                validate_url,
                json={"token": token},
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                if resp.status == 200:
                    result = await resp.json()
                    if result.get("valid"):
                        return {
                            "mode": "platform_token",
                            "project_id": result.get("project_id"),
                            "user_id": result.get("user_id"),
                            "sandbox_type": result.get("sandbox_type"),
                        }
                logger.warning(f"[Auth] Token validation failed: status={resp.status}")
                return None
        except Exception as e:
            logger.error(f"[Auth] Error validating token against platform: {e}")
            return None

    async def _handle_websocket(self, request: web.Request) -> web.WebSocketResponse:
        """Handle incoming WebSocket connections with authentication."""
        # Authenticate first
        authenticated, auth_info, error = await self._authenticate_request(request)

        if not authenticated:
            logger.warning(f"[MCP] Authentication failed: {error}")
            ws = web.WebSocketResponse()
            await ws.prepare(request)
            await ws.close(code=4001, message=error.encode() if error else b"Unauthorized")
            return ws

        ws = web.WebSocketResponse(
            heartbeat=300.0,  # 5min ping interval (PONG timeout = 150s) to tolerate long tool calls
            max_msg_size=100 * 1024 * 1024,  # 100MB to support large file imports
        )
        await ws.prepare(request)

        client_id = f"client-{id(ws)}"
        self._clients[client_id] = ws
        self._client_auth[client_id] = auth_info or {}

        # Log connection details
        remote = request.remote or "unknown"
        headers = dict(request.headers)
        user_agent = headers.get("User-Agent", "unknown")
        auth_mode = auth_info.get("mode", "unknown") if auth_info else "unknown"
        logger.info(
            f"[MCP] Client CONNECTED - id={client_id} remote={remote} "
            f"user_agent={user_agent} auth_mode={auth_mode}"
        )
        if auth_info and auth_info.get("project_id"):
            logger.info(f"[MCP] Client project: {auth_info.get('project_id')}")
        logger.debug(f"[MCP] Connection headers: {headers}")

        message_count = 0
        try:
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    message_count += 1
                    try:
                        data = json.loads(msg.data)
                        method = data.get("method", "unknown")
                        request_id = data.get("id")
                        logger.debug(
                            f"[MCP] Message #{message_count} - method={method} id={request_id}"
                        )

                        response = await self._handle_message(data)
                        if response:
                            if ws.closed:
                                logger.debug(
                                    f"[MCP] WS closed before response for {client_id}, "
                                    f"dropping method={method}"
                                )
                                break
                            try:
                                await ws.send_json(response)
                            except (ConnectionResetError, RuntimeError) as send_err:
                                logger.debug(
                                    f"[MCP] Cannot send response to {client_id} "
                                    f"(method={method}): {send_err}"
                                )
                                break
                    except ConnectionResetError:
                        logger.debug(f"[MCP] Connection reset while sending to {client_id}")
                        break
                    except json.JSONDecodeError as e:
                        logger.warning(f"[MCP] Invalid JSON from client {client_id}: {e}")
                        if ws.closed:
                            break
                        await ws.send_json(
                            {
                                "jsonrpc": "2.0",
                                "error": {"code": -32700, "message": f"Parse error: {e}"},
                                "id": None,
                            }
                        )
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    logger.error(f"[MCP] WebSocket error for {client_id}: {ws.exception()}")
                    break

        except asyncio.CancelledError:
            logger.debug(f"[MCP] Client handler cancelled: {client_id}")
        except Exception as e:
            logger.error(f"[MCP] Error handling client {client_id}: {e}", exc_info=True)
        finally:
            self._clients.pop(client_id, None)
            self._client_auth.pop(client_id, None)  # Clean up auth info
            logger.info(
                f"[MCP] Client DISCONNECTED - id={client_id} messages_processed={message_count}"
            )

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
        elif method == "resources/read":
            return await self._handle_read_resource(params)
        elif method == "resources/list":
            return await self._handle_list_resources(params)
        elif method == "resources/templates/list":
            return await self._handle_list_resource_templates(params)
        elif method == "prompts/list":
            return await self._handle_list_prompts(params)
        elif method == "prompts/get":
            return await self._handle_get_prompt(params)
        elif method == "ping":
            return {}
        else:
            raise ValueError(f"Unknown method: {method}")

    async def _handle_initialize(self, params: dict) -> dict:
        """Handle MCP initialize request."""
        client_info = params.get("clientInfo", {})
        protocol_version = params.get("protocolVersion", "unknown")
        capabilities = params.get("capabilities", {})

        logger.info(
            f"[MCP] initialize - client={client_info.get('name', 'unknown')} "
            f"version={client_info.get('version', 'unknown')} "
            f"protocol={protocol_version}"
        )
        logger.debug(f"[MCP] initialize - client capabilities: {capabilities}")

        response = {
            "protocolVersion": self._server_info.protocol_version,
            "capabilities": {
                "tools": {"listChanged": False},
                "resources": {"subscribe": False, "listChanged": False},
                "prompts": {},
            },
            "serverInfo": {
                "name": self._server_info.name,
                "version": self._server_info.version,
            },
        }

        logger.info(
            f"[MCP] initialize - server={self._server_info.name} "
            f"version={self._server_info.version} "
            f"tools_count={len(self._tools)}"
        )

        return response

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
        tool_names = [t["name"] for t in tools]
        logger.info(f"[MCP] tools/list - Returning {len(tools)} tools: {tool_names}")
        return {"tools": tools}

    async def _handle_call_tool(self, params: dict) -> dict:
        """Handle tools/call request."""
        import time as _time

        tool_name = params.get("name")
        arguments = params.get("arguments", {})

        # Log tool call start
        logger.info(f"[MCP] tools/call START - tool={tool_name}")
        logger.debug(f"[MCP] tools/call arguments: {arguments}")

        if tool_name not in self._tools:
            logger.warning(f"[MCP] tools/call FAILED - Unknown tool: {tool_name}")
            logger.debug(f"[MCP] Available tools: {list(self._tools.keys())}")
            return {
                "content": [{"type": "text", "text": f"Unknown tool: {tool_name}"}],
                "isError": True,
            }

        tool = self._tools[tool_name]
        start_time = _time.time()

        # Defense-in-depth: max timeout at WebSocket level (tool max 600s + 60s buffer)
        max_tool_timeout = 660

        try:
            # Inject workspace_dir into arguments for file tools
            arguments["_workspace_dir"] = self.workspace_dir
            try:
                result = await asyncio.wait_for(
                    tool.handler(**arguments),
                    timeout=max_tool_timeout,
                )
            except asyncio.TimeoutError:
                elapsed_ms = (_time.time() - start_time) * 1000
                logger.error(
                    f"[MCP] tools/call TIMEOUT - tool={tool_name} "
                    f"elapsed={elapsed_ms:.1f}ms (limit={max_tool_timeout}s)"
                )
                return {
                    "content": [
                        {
                            "type": "text",
                            "text": f"Error: Tool '{tool_name}' timed out after "
                            f"{max_tool_timeout}s (server-level safety limit)",
                        }
                    ],
                    "isError": True,
                }

            elapsed_ms = (_time.time() - start_time) * 1000

            # Normalize result to MCP format
            if isinstance(result, str):
                response = {
                    "content": [{"type": "text", "text": result}],
                    "isError": False,
                }
            elif isinstance(result, dict):
                if "content" in result:
                    response = result
                else:
                    response = {
                        "content": [{"type": "text", "text": json.dumps(result)}],
                        "isError": False,
                    }
            else:
                response = {
                    "content": [{"type": "text", "text": str(result)}],
                    "isError": False,
                }

            # Log success with timing
            is_error = response.get("isError", False)
            status = "ERROR" if is_error else "OK"
            content_preview = str(response.get("content", []))[:200]
            logger.info(
                f"[MCP] tools/call END - tool={tool_name} status={status} elapsed={elapsed_ms:.1f}ms"
            )
            logger.debug(f"[MCP] tools/call result preview: {content_preview}...")

            return response

        except Exception as e:
            elapsed_ms = (_time.time() - start_time) * 1000
            logger.error(
                f"[MCP] tools/call EXCEPTION - tool={tool_name} elapsed={elapsed_ms:.1f}ms error={e}",
                exc_info=True,
            )
            return {
                "content": [{"type": "text", "text": f"Error: {str(e)}"}],
                "isError": True,
            }

    async def _handle_read_resource(self, params: dict) -> dict:
        """Handle resources/read by proxying to managed MCP servers.

        Routes by URI authority first (e.g. ui://color-picker -> try 'color-picker'
        server first), then falls back to other running servers.
        """
        uri = str(params.get("uri", ""))
        if not uri:
            return {"contents": []}

        from src.tools.mcp_management import _get_manager

        manager = _get_manager(self.workspace_dir)

        # Extract server name from URI authority for smart routing
        # Supported schemes: ui://<server>, app://<server>, mcp-app://<server>
        target_server = None
        for scheme in ("ui://", "app://", "mcp-app://"):
            if uri.startswith(scheme):
                remainder = uri[len(scheme) :]
                target_server = remainder.split("/")[0] if remainder else None
                break

        # Phase 1: Try the target server first (matched by URI authority)
        if target_server:
            text = await manager.read_resource(target_server, uri)
            if text:
                return {
                    "contents": [
                        {
                            "uri": uri,
                            "mimeType": "text/html",
                            "text": text,
                        }
                    ]
                }

        # Phase 2: Fall back to other running servers
        for server_info in await manager.list_servers():
            name = server_info.get("name", "")
            status = server_info.get("status", "")
            if status != "running" or not name:
                continue
            # Skip target server (already tried above)
            if name == target_server:
                continue
            text = await manager.read_resource(name, uri)
            if text:
                return {
                    "contents": [
                        {
                            "uri": uri,
                            "mimeType": "text/html",
                            "text": text,
                        }
                    ]
                }

        logger.warning(f"[MCP] resources/read - no server returned content for {uri}")
        return {"contents": []}

    async def _handle_list_resources(self, params: dict) -> dict:
        """Handle resources/list by aggregating from all managed MCP servers."""
        from src.tools.mcp_management import _get_manager

        manager = _get_manager(self.workspace_dir)
        all_resources = []
        for server_info in await manager.list_servers():
            name = server_info.get("name", "")
            status = server_info.get("status", "")
            if status != "running" or not name:
                continue
            resources = await manager.list_resources(name)
            all_resources.extend(resources)

        return {"resources": all_resources}

    async def _handle_list_resource_templates(self, params: dict) -> dict:
        """Handle resources/templates/list by aggregating from all managed MCP servers."""
        from src.tools.mcp_management import _get_manager

        manager = _get_manager(self.workspace_dir)
        all_templates = []
        for server_info in await manager.list_servers():
            name = server_info.get("name", "")
            status = server_info.get("status", "")
            if status != "running" or not name:
                continue
            templates = await manager.list_resource_templates(name)
            all_templates.extend(templates)

        return {"resourceTemplates": all_templates}

    async def _handle_list_prompts(self, params: dict) -> dict:
        """Handle prompts/list by aggregating from all managed MCP servers."""
        from src.tools.mcp_management import _get_manager

        manager = _get_manager(self.workspace_dir)
        all_prompts = []
        for server_info in await manager.list_servers():
            name = server_info.get("name", "")
            status = server_info.get("status", "")
            if status != "running" or not name:
                continue
            prompts = await manager.list_prompts(name)
            all_prompts.extend(prompts)

        return {"prompts": all_prompts}

    async def _handle_get_prompt(self, params: dict) -> dict:
        """Handle prompts/get by routing to the appropriate managed MCP server."""
        from src.tools.mcp_management import _get_manager

        manager = _get_manager(self.workspace_dir)
        name = params.get("name", "")
        arguments = params.get("arguments", {})

        if not name:
            return {
                "description": "Error: prompt name is required",
                "messages": [],
            }

        # Try to find a server that has this prompt
        for server_info in await manager.list_servers():
            server_name = server_info.get("name", "")
            status = server_info.get("status", "")
            if status != "running" or not server_name:
                continue

            # Check if this server has the prompt
            prompts = await manager.list_prompts(server_name)
            prompt_names = [p.get("name") for p in prompts]
            if name in prompt_names:
                result = await manager.get_prompt(server_name, name, arguments)
                if result:
                    return result

        return {
            "description": f"Prompt '{name}' not found",
            "messages": [],
        }
