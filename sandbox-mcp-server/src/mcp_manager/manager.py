"""MCP Server Manager for the sandbox container.

Manages the lifecycle of user-configured MCP servers running
inside the sandbox: install, start, stop, discover tools, and proxy tool calls.
"""

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from src.mcp_manager.installer import install_package
from src.mcp_manager.process_tracker import (
    ManagedServer,
    ProcessTracker,
    ServerStatus,
)

logger = logging.getLogger(__name__)

# Timeout for MCP protocol initialization
MCP_INIT_TIMEOUT = 30

# Timeout for tool calls (default, overridden by tool-specific timeout when available)
TOOL_CALL_TIMEOUT = 600


@dataclass
class MCPToolInfo:
    """Tool discovered from a managed MCP server."""

    name: str
    description: str
    input_schema: Dict[str, Any]
    meta: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        result = {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }
        if self.meta:
            result["_meta"] = self.meta
        return result


@dataclass
class MCPCallResult:
    """Result of a tool call to a managed MCP server."""

    content: List[Dict[str, Any]]
    is_error: bool = False
    error_message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "content": self.content,
            "isError": self.is_error,
            "error_message": self.error_message,
        }


@dataclass
class _StdioConnection:
    """Active JSON-RPC connection to a stdio MCP server."""

    server: ManagedServer
    _request_id: int = field(default=0, init=False)
    _pending: Dict[int, asyncio.Future] = field(default_factory=dict, init=False)
    _reader_task: Optional[asyncio.Task] = field(default=None, init=False)
    _initialized: bool = field(default=False, init=False)

    @property
    def stdin(self):
        return self.server.process.stdin

    @property
    def stdout(self):
        return self.server.process.stdout

    def next_id(self) -> int:
        self._request_id += 1
        return self._request_id


@dataclass
class _WebSocketConnection:
    """Active JSON-RPC connection to a WebSocket MCP server."""

    server: ManagedServer
    ws: Any = field(default=None)  # aiohttp.ClientWebSocketResponse
    session: Any = field(default=None)  # aiohttp.ClientSession
    _request_id: int = field(default=0, init=False)
    _pending: Dict[int, asyncio.Future] = field(default_factory=dict, init=False)
    _reader_task: Optional[asyncio.Task] = field(default=None, init=False)
    _initialized: bool = field(default=False, init=False)

    def next_id(self) -> int:
        self._request_id += 1
        return self._request_id


class MCPServerManager:
    """Manages user MCP servers within the sandbox container.

    Handles installation, process lifecycle, tool discovery,
    and proxying tool calls to running MCP servers.
    """

    def __init__(self, workspace_dir: str = "/workspace") -> None:
        self._workspace_dir = workspace_dir
        self._tracker = ProcessTracker()
        self._connections: Dict[str, _StdioConnection] = {}
        self._ws_connections: Dict[str, "_WebSocketConnection"] = {}
        self._tools_cache: Dict[str, List[MCPToolInfo]] = {}
        # StreamableHTTP session tracking
        self._session_ids: Dict[str, str] = {}  # server_name -> Mcp-Session-Id
        self._network_request_id: int = 0
        # Shared aiohttp session for network requests (lazy init)
        self._http_session: Optional[Any] = None

    async def install_server(
        self,
        name: str,
        server_type: str,
        transport_config: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Install an MCP server package.

        Args:
            name: Server name.
            server_type: Transport type (stdio, sse, http, websocket).
            transport_config: Transport configuration.

        Returns:
            Installation result dict.
        """
        command = transport_config.get("command", "")
        args = transport_config.get("args", [])
        env = transport_config.get("env", {})

        if not command and server_type in ("http", "sse", "websocket"):
            # Remote servers don't need installation
            return {
                "success": True,
                "message": f"Remote {server_type} server, no installation needed",
            }

        if not command:
            return {"success": False, "error": "No command specified"}

        result = await install_package(command, args, env)
        return {
            "success": result.success,
            "package_manager": result.package_manager.value if result.package_manager else None,
            "output": result.output,
            "error": result.error,
        }

    async def start_server(
        self,
        name: str,
        server_type: str,
        transport_config: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Start an MCP server subprocess.

        Args:
            name: Server name.
            server_type: Transport type (stdio, sse, http, websocket).
            transport_config: Transport configuration.

        Returns:
            Server status dict.
        """
        # Stop existing server with same name
        existing = self._tracker.get_server(name)
        if existing and existing.status == ServerStatus.RUNNING:
            await self.stop_server(name)

        command = transport_config.get("command", "")
        args = list(transport_config.get("args", []))
        env = transport_config.get("env", {})
        url = transport_config.get("url", "")

        # Inject required flags for chrome-devtools-mcp running as root in container
        if any("chrome-devtools-mcp" in str(a) for a in [command] + args):
            joined = " ".join(args)
            if "--no-sandbox" not in joined:
                args.extend(["--chrome-arg=--no-sandbox",
                             "--chrome-arg=--disable-dev-shm-usage"])
            if "--headless" not in joined:
                args.append("--headless")

        try:
            if server_type == "stdio":
                server = await self._tracker.start_stdio_server(
                    name=name,
                    command=command,
                    args=args,
                    env=env,
                    working_dir=self._workspace_dir,
                )
                # Initialize MCP protocol over stdio
                await self._init_stdio_connection(server)
            elif server_type in ("http", "sse", "websocket"):
                if command:
                    # Server needs to be started locally
                    port = self._tracker.allocate_port()
                    server = await self._tracker.start_network_server(
                        name=name,
                        command=command,
                        args=args,
                        env=env,
                        port=port,
                        working_dir=self._workspace_dir,
                    )
                    # Build URL for local network server
                    if server_type == "websocket":
                        server.url = url or f"ws://localhost:{port}/ws"
                    elif server_type == "sse":
                        server.url = url or f"http://localhost:{port}/sse"
                    else:
                        server.url = url or f"http://localhost:{port}/mcp"
                    # Wait for server to be ready (TCP port probe)
                    await self._wait_for_port(port, timeout=15)
                    # Initialize MCP protocol
                    if server_type == "websocket":
                        await self._init_ws_connection(server)
                    else:
                        await self._init_network_connection(server)
                else:
                    # Remote server, just track it
                    server = ManagedServer(
                        name=name,
                        server_type=server_type,
                        command="",
                        url=url,
                        status=ServerStatus.RUNNING,
                    )
                    self._tracker._servers[name] = server
                    # Initialize connection (non-fatal for remote servers)
                    if url:
                        try:
                            if server_type == "websocket":
                                await self._init_ws_connection(server)
                            else:
                                await self._init_network_connection(server)
                        except Exception as e:
                            logger.warning(
                                f"Init failed for remote server '{name}': {e}. "
                                "Server tracked but may not respond to tool calls."
                            )
            else:
                return {"success": False, "error": f"Unknown server type: {server_type}"}

            return {
                "success": True,
                "name": name,
                "status": server.status.value,
                "pid": server.pid,
                "port": server.port,
            }

        except Exception as e:
            logger.error(f"Failed to start MCP server '{name}': {e}")
            return {"success": False, "error": str(e)}

    async def stop_server(self, name: str) -> Dict[str, Any]:
        """Stop a running MCP server.

        Args:
            name: Server name.

        Returns:
            Result dict.
        """
        # Clean up stdio connection
        conn = self._connections.pop(name, None)
        if conn and conn._reader_task:
            conn._reader_task.cancel()

        # Clean up WebSocket connection
        await self._close_ws_connection(name)

        # Clean up tools cache
        self._tools_cache.pop(name, None)

        success = await self._tracker.stop_server(name)
        return {"success": success, "name": name}

    async def list_servers(self) -> List[Dict[str, Any]]:
        """List all managed MCP servers."""
        return [s.to_dict() for s in self._tracker.list_servers()]

    async def _wait_for_port(self, port: int, timeout: int = 15) -> None:
        """Wait until a TCP port is accepting connections."""
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            try:
                _, writer = await asyncio.wait_for(
                    asyncio.open_connection("127.0.0.1", port), timeout=1
                )
                writer.close()
                await writer.wait_closed()
                logger.debug(f"Port {port} is ready")
                return
            except (OSError, asyncio.TimeoutError):
                await asyncio.sleep(0.3)
        logger.warning(f"Port {port} not ready after {timeout}s, proceeding anyway")

    async def _get_http_session(self):
        """Get or create a shared aiohttp ClientSession."""
        import aiohttp

        if self._http_session is None or self._http_session.closed:
            self._http_session = aiohttp.ClientSession()
        return self._http_session

    async def _send_request(
        self,
        server_name: str,
        method: str,
        params: Optional[Dict[str, Any]] = None,
        timeout: int = TOOL_CALL_TIMEOUT,
    ) -> Dict[str, Any]:
        """Unified transport dispatcher: routes to stdio, websocket, or HTTP."""
        server = self._tracker.get_server(server_name)
        if not server:
            raise ValueError(f"Server '{server_name}' not found")

        if server.server_type == "stdio":
            return await self._send_stdio_request(server_name, method, params, timeout)
        elif server.server_type == "websocket" and server_name in self._ws_connections:
            return await self._send_ws_request(server_name, method, params, timeout)
        else:
            return await self._send_network_request(server, method, params, timeout)

    @staticmethod
    def _parse_tools_from_result(result: Dict[str, Any]) -> List["MCPToolInfo"]:
        """Parse tools/list result into MCPToolInfo objects."""
        tools = []
        for t in result.get("tools", []):
            tools.append(
                MCPToolInfo(
                    name=t.get("name", ""),
                    description=t.get("description", ""),
                    input_schema=t.get("inputSchema", {}),
                    meta=t.get("_meta"),
                )
            )
        return tools

    async def discover_tools(self, name: str) -> List[Dict[str, Any]]:
        """Discover tools from a running MCP server.

        Args:
            name: Server name.

        Returns:
            List of tool definitions.
        """
        server = self._tracker.get_server(name)
        if not server:
            raise ValueError(f"Server '{name}' not found")
        if server.status != ServerStatus.RUNNING:
            raise ValueError(f"Server '{name}' is not running (status: {server.status.value})")

        result = await self._send_request(name, "tools/list")
        tools = self._parse_tools_from_result(result)
        self._tools_cache[name] = tools
        return [t.to_dict() for t in tools]

    async def call_tool(
        self,
        server_name: str,
        tool_name: str,
        arguments: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Call a tool on a managed MCP server.

        Args:
            server_name: Server name.
            tool_name: Tool name.
            arguments: Tool arguments.

        Returns:
            Tool call result.
        """
        server = self._tracker.get_server(server_name)
        if not server:
            return MCPCallResult(
                content=[{"type": "text", "text": f"Server '{server_name}' not found"}],
                is_error=True,
                error_message=f"Server '{server_name}' not found",
            ).to_dict()

        if server.status != ServerStatus.RUNNING:
            return MCPCallResult(
                content=[
                    {
                        "type": "text",
                        "text": f"Server '{server_name}' is not running",
                    }
                ],
                is_error=True,
                error_message=f"Server status: {server.status.value}",
            ).to_dict()

        try:
            # Use tool-specific timeout if available (e.g., bash tool's timeout param)
            tool_timeout = arguments.get("timeout")
            timeout = TOOL_CALL_TIMEOUT
            if tool_timeout and isinstance(tool_timeout, (int, float)):
                timeout = int(tool_timeout) + 30

            raw = await self._send_request(
                server_name, "tools/call",
                {"name": tool_name, "arguments": arguments},
                timeout=timeout,
            )
            content = raw.get("content", [{"type": "text", "text": str(raw)}])
            is_error = raw.get("isError", False)
            return MCPCallResult(content=content, is_error=is_error).to_dict()
        except Exception as e:
            logger.error(f"Error calling tool '{tool_name}' on '{server_name}': {e}")
            return MCPCallResult(
                content=[{"type": "text", "text": f"Error: {str(e)}"}],
                is_error=True,
                error_message=str(e),
            ).to_dict()

    async def read_resource(self, server_name: str, uri: str) -> Optional[str]:
        """Read a resource from a managed MCP server via resources/read.

        Args:
            server_name: Server name.
            uri: Resource URI (e.g. 'ui://app/index.html').

        Returns:
            Resource text content, or None on failure.
        """
        server = self._tracker.get_server(server_name)
        if not server or server.status != ServerStatus.RUNNING:
            return None

        try:
            result = await self._send_request(server_name, "resources/read", {"uri": uri})
            contents = result.get("contents", [])
            for item in contents:
                if isinstance(item, dict):
                    text = item.get("text")
                    if text:
                        return text
            return None
        except Exception as e:
            logger.error(f"Error reading resource '{uri}' from '{server_name}': {e}")
            return None

    async def list_resources(self, server_name: str) -> list:
        """List resources from a managed MCP server via resources/list.

        Args:
            server_name: Server name.

        Returns:
            List of resource descriptors, or empty list on failure.
        """
        server = self._tracker.get_server(server_name)
        if not server or server.status != ServerStatus.RUNNING:
            return []

        try:
            result = await self._send_request(server_name, "resources/list")
            return result.get("resources", [])
        except Exception as e:
            logger.error(f"Error listing resources from '{server_name}': {e}")
            return []

    async def shutdown(self) -> None:
        """Shutdown all managed servers."""
        for name in list(self._connections.keys()):
            conn = self._connections.pop(name, None)
            if conn and conn._reader_task:
                conn._reader_task.cancel()
        for name in list(self._ws_connections.keys()):
            await self._close_ws_connection(name)
        # Close shared HTTP session
        if self._http_session and not self._http_session.closed:
            await self._http_session.close()
            self._http_session = None
        await self._tracker.stop_all()

    # -- Stdio protocol methods --

    async def _init_stdio_connection(self, server: ManagedServer) -> None:
        """Initialize MCP JSON-RPC connection over stdio."""
        conn = _StdioConnection(server=server)
        self._connections[server.name] = conn

        # Start reading responses
        conn._reader_task = asyncio.create_task(self._read_stdio_responses(server.name))

        # Send initialize request
        try:
            await self._send_stdio_request(
                server.name,
                "initialize",
                {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "sandbox-mcp-manager", "version": "1.0.0"},
                },
                timeout=MCP_INIT_TIMEOUT,
            )
            conn._initialized = True
            logger.info(f"MCP stdio connection initialized for '{server.name}'")

            # Send initialized notification
            await self._send_stdio_notification(server.name, "notifications/initialized")

        except Exception as e:
            logger.error(f"Failed to initialize MCP for '{server.name}': {e}")
            raise

    async def _send_stdio_request(
        self,
        name: str,
        method: str,
        params: Optional[Dict[str, Any]] = None,
        timeout: int = TOOL_CALL_TIMEOUT,
    ) -> Dict[str, Any]:
        """Send a JSON-RPC request over stdio and wait for response."""
        conn = self._connections.get(name)
        if not conn:
            raise ValueError(f"No stdio connection for '{name}'")

        request_id = conn.next_id()
        request = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
        }
        if params is not None:
            request["params"] = params

        future: asyncio.Future = asyncio.get_event_loop().create_future()
        conn._pending[request_id] = future

        # Write request to stdin
        data = json.dumps(request) + "\n"
        conn.stdin.write(data.encode("utf-8"))
        await conn.stdin.drain()

        try:
            response = await asyncio.wait_for(future, timeout=timeout)
            if "error" in response:
                raise RuntimeError(
                    f"MCP error: {response['error'].get('message', 'Unknown error')}"
                )
            return response.get("result", {})
        except asyncio.TimeoutError:
            conn._pending.pop(request_id, None)
            raise TimeoutError(f"MCP request '{method}' timed out after {timeout}s")

    async def _send_stdio_notification(
        self,
        name: str,
        method: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Send a JSON-RPC notification (no response expected)."""
        conn = self._connections.get(name)
        if not conn:
            return

        notification = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            notification["params"] = params

        data = json.dumps(notification) + "\n"
        conn.stdin.write(data.encode("utf-8"))
        await conn.stdin.drain()

    async def _read_stdio_responses(self, name: str) -> None:
        """Background task to read JSON-RPC responses from stdout."""
        conn = self._connections.get(name)
        if not conn:
            return

        try:
            while True:
                line = await conn.stdout.readline()
                if not line:
                    break  # EOF - process exited

                try:
                    response = json.loads(line.decode("utf-8"))
                except json.JSONDecodeError:
                    continue

                request_id = response.get("id")
                if request_id is not None:
                    future = conn._pending.pop(request_id, None)
                    if future and not future.done():
                        future.set_result(response)

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Error reading stdio for '{name}': {e}")

    # -- Network protocol methods (HTTP/SSE MCP servers) --

    def _next_network_id(self) -> int:
        self._network_request_id += 1
        return self._network_request_id

    async def _send_network_request(
        self,
        server: ManagedServer,
        method: str,
        params: Optional[Dict[str, Any]] = None,
        timeout: int = TOOL_CALL_TIMEOUT,
        max_retries: int = 3,
    ) -> Dict[str, Any]:
        """Send a JSON-RPC request to a network MCP server via HTTP POST.

        Uses the MCP StreamableHTTP transport protocol: JSON-RPC over HTTP POST.
        Tracks Mcp-Session-Id for session continuity. Retries on transient errors.
        """
        import aiohttp

        if not server.url:
            raise ValueError(f"No URL configured for network server '{server.name}'")

        last_error: Optional[Exception] = None
        for attempt in range(max_retries):
            request_id = self._next_network_id()
            request = {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": method,
            }
            if params is not None:
                request["params"] = params

            headers = {
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            }
            session_id = self._session_ids.get(server.name)
            if session_id:
                headers["Mcp-Session-Id"] = session_id

            try:
                session = await self._get_http_session()
                async with session.post(
                    server.url,
                    json=request,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=timeout),
                ) as resp:
                    # Retry on 5xx server errors
                    if resp.status >= 500:
                        body = await resp.text()
                        last_error = RuntimeError(
                            f"HTTP {resp.status} from '{server.url}' "
                            f"for method '{method}': {body[:500]}"
                        )
                        if attempt < max_retries - 1:
                            await asyncio.sleep(0.5 * (2 ** attempt))
                            continue
                        raise last_error

                    if resp.status >= 400:
                        body = await resp.text()
                        raise RuntimeError(
                            f"HTTP {resp.status} from '{server.url}' "
                            f"for method '{method}': {body[:500]}"
                        )

                    # Store session ID from response
                    new_session_id = resp.headers.get("Mcp-Session-Id")
                    if new_session_id:
                        self._session_ids[server.name] = new_session_id

                    content_type = resp.headers.get("Content-Type", "")

                    if "text/event-stream" in content_type:
                        return await self._read_sse_response(resp, request_id)

                    # Standard JSON response
                    response = await resp.json()
                    logger.debug(
                        f"Network response for '{method}' on '{server.name}': "
                        f"{json.dumps(response)[:500]}"
                    )

                    if isinstance(response, list):
                        for item in response:
                            if item.get("id") == request_id:
                                response = item
                                break
                        else:
                            response = response[0] if response else {}

                    if "error" in response:
                        raise RuntimeError(
                            f"MCP error: {response['error'].get('message', 'Unknown')}"
                        )
                    return response.get("result", {})

            except aiohttp.ClientError as e:
                last_error = RuntimeError(f"HTTP request to '{server.url}' failed: {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(0.5 * (2 ** attempt))
                    continue
                raise last_error

        raise last_error or RuntimeError(f"Request to '{server.url}' failed after retries")

    async def _read_sse_response(
        self, resp, request_id: int
    ) -> Dict[str, Any]:
        """Read an SSE stream response and extract the JSON-RPC result."""
        import json as json_mod

        async for line in resp.content:
            text = line.decode("utf-8").strip()
            if not text or text.startswith(":"):
                continue
            if text.startswith("data: "):
                data_str = text[6:]
                try:
                    data = json_mod.loads(data_str)
                    if isinstance(data, dict) and "result" in data:
                        return data.get("result", {})
                    if isinstance(data, dict) and "error" in data:
                        raise RuntimeError(
                            f"MCP error: {data['error'].get('message', 'Unknown')}"
                        )
                except json_mod.JSONDecodeError:
                    continue
        return {}

    async def _init_network_connection(self, server: ManagedServer) -> None:
        """Initialize MCP protocol over HTTP for a network server."""
        try:
            result = await self._send_network_request(
                server,
                "initialize",
                {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "sandbox-mcp-manager", "version": "1.0.0"},
                },
                timeout=MCP_INIT_TIMEOUT,
            )
            logger.info(
                f"MCP network connection initialized for '{server.name}': "
                f"server={result.get('serverInfo', {}).get('name', 'unknown')}"
            )
            # Send initialized notification (fire-and-forget)
            try:
                import aiohttp

                headers = {"Content-Type": "application/json"}
                session_id = self._session_ids.get(server.name)
                if session_id:
                    headers["Mcp-Session-Id"] = session_id
                request = {
                    "jsonrpc": "2.0",
                    "method": "notifications/initialized",
                }
                session = await self._get_http_session()
                async with session.post(
                    server.url,
                    json=request,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=5),
                ):
                    pass
            except Exception:
                pass  # Notifications are best-effort

        except Exception as e:
            logger.error(f"Failed to initialize network MCP for '{server.name}': {e}")
            # Re-raise so caller knows init failed
            raise

    # -- WebSocket protocol methods --

    async def _init_ws_connection(self, server: ManagedServer) -> None:
        """Initialize a persistent WebSocket connection to an MCP server."""
        import aiohttp

        if not server.url:
            raise ValueError(f"No URL for WebSocket server '{server.name}'")

        session = aiohttp.ClientSession()
        try:
            ws = await session.ws_connect(server.url)
            conn = _WebSocketConnection(server=server, ws=ws, session=session)
            self._ws_connections[server.name] = conn

            # Start reader task
            conn._reader_task = asyncio.create_task(
                self._read_ws_responses(server.name)
            )

            # Send initialize (register future BEFORE send to avoid race with reader)
            req_id = conn.next_id()
            future: asyncio.Future = asyncio.get_event_loop().create_future()
            conn._pending[req_id] = future

            await ws.send_json({
                "jsonrpc": "2.0",
                "id": req_id,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "sandbox-mcp-manager", "version": "1.0.0"},
                },
            })

            # Wait for response
            result = await asyncio.wait_for(future, timeout=MCP_INIT_TIMEOUT)
            conn._initialized = True
            logger.info(
                f"MCP WebSocket connection initialized for '{server.name}': "
                f"server={result.get('serverInfo', {}).get('name', 'unknown')}"
            )

            # Send initialized notification
            await ws.send_json({
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
            })

        except Exception as e:
            await session.close()
            self._ws_connections.pop(server.name, None)
            logger.warning(f"Failed to init WebSocket MCP for '{server.name}': {e}")
            raise

    async def _read_ws_responses(self, server_name: str) -> None:
        """Background task: read JSON-RPC responses from WebSocket."""
        import aiohttp

        conn = self._ws_connections.get(server_name)
        if not conn or not conn.ws:
            return

        try:
            async for msg in conn.ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    try:
                        data = json.loads(msg.data)
                        req_id = data.get("id")
                        if req_id is not None and req_id in conn._pending:
                            future = conn._pending.pop(req_id)
                            if "error" in data:
                                future.set_exception(
                                    RuntimeError(data["error"].get("message", "Unknown"))
                                )
                            else:
                                future.set_result(data.get("result", {}))
                    except json.JSONDecodeError:
                        continue
                elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                    break
        except Exception as e:
            logger.error(f"WebSocket reader error for '{server_name}': {e}")
        finally:
            # Cancel all pending futures
            for future in conn._pending.values():
                if not future.done():
                    future.set_exception(RuntimeError("WebSocket connection closed"))
            conn._pending.clear()

    async def _send_ws_request(
        self,
        server_name: str,
        method: str,
        params: Optional[Dict[str, Any]] = None,
        timeout: int = TOOL_CALL_TIMEOUT,
    ) -> Dict[str, Any]:
        """Send a JSON-RPC request over a persistent WebSocket connection."""
        conn = self._ws_connections.get(server_name)
        if not conn or not conn.ws:
            raise RuntimeError(f"No WebSocket connection for '{server_name}'")

        req_id = conn.next_id()
        request: Dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
        }
        if params is not None:
            request["params"] = params

        future: asyncio.Future = asyncio.get_event_loop().create_future()
        conn._pending[req_id] = future

        await conn.ws.send_json(request)
        return await asyncio.wait_for(future, timeout=timeout)

    async def _close_ws_connection(self, server_name: str) -> None:
        """Close a WebSocket connection."""
        conn = self._ws_connections.pop(server_name, None)
        if conn:
            if conn._reader_task and not conn._reader_task.done():
                conn._reader_task.cancel()
            if conn.ws and not conn.ws.closed:
                await conn.ws.close()
            if conn.session and not conn.session.closed:
                await conn.session.close()
