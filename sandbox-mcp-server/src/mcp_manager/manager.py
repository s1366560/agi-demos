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

# Timeout for tool discovery (tools/list) - should be quick
TOOL_DISCOVER_TIMEOUT = 15

# Timeout for tool calls (default, overridden by tool-specific timeout when available)
TOOL_CALL_TIMEOUT = 60


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


@dataclass
class _SSEConnection:
    """Active JSON-RPC connection to a legacy SSE MCP server.

    Legacy SSE protocol:
      1. GET /sse -> persistent SSE stream, receives 'endpoint' event with messages URL
      2. POST to messages URL with JSON-RPC payload
      3. Read JSON-RPC responses from the SSE stream
    """

    server: ManagedServer
    session: Any = field(default=None)  # aiohttp.ClientSession
    messages_url: str = ""  # URL from the 'endpoint' SSE event
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
        self._sse_connections: Dict[str, "_SSEConnection"] = {}
        self._tools_cache: Dict[str, List[MCPToolInfo]] = {}
        # StreamableHTTP session tracking
        self._session_ids: Dict[str, str] = {}  # server_name -> Mcp-Session-Id
        self._network_request_id: int = 0
        # Shared aiohttp session for network requests (lazy init)
        self._http_session: Optional[Any] = None
        # Resource subscription tracking: server_name -> {subscription_id: uri}
        self._subscriptions: Dict[str, Dict[str, str]] = {}

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
                args.extend(["--chrome-arg=--no-sandbox", "--chrome-arg=--disable-dev-shm-usage"])
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
                    elif server_type == "sse":
                        await self._init_sse_connection(server)
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
                            elif server_type == "sse":
                                await self._init_sse_connection(server)
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
            error_msg = str(e)
            stderr_text = await self._capture_server_stderr(name)
            if stderr_text:
                error_msg = f"{error_msg}\n--- Server stderr ---\n{stderr_text}"
            return {"success": False, "error": error_msg}

    def _is_process_alive(self, name: str) -> bool:
        """Check if a server process is actually running.

        This checks the actual process state, not just the tracked status.
        Returns True if process exists and hasn't exited.
        """
        server = self._tracker.get_server(name)
        if not server or not server.process:
            return False
        # Check if process has exited (returncode is set when process ends)
        return server.process.returncode is None

    async def _capture_server_stderr(self, name: str) -> str:
        """Read available stderr from a managed server process.

        Useful for diagnosing why a server failed to start or crashed.
        Returns up to 2000 chars of stderr, or empty string if unavailable.

        Note: This uses a short timeout and may return empty if no data
        is immediately available (process still running with no stderr output).
        """
        server = self._tracker.get_server(name)
        if not server or not server.process or not server.process.stderr:
            return ""
        try:
            # Try to read stderr with a very short timeout
            # Use read(n) which may block, so we wrap in wait_for
            # If process is still running and has no stderr, this will timeout
            stderr_bytes = await asyncio.wait_for(
                server.process.stderr.read(4096),
                timeout=0.5,
            )
            if stderr_bytes:
                return stderr_bytes.decode("utf-8", errors="replace")[:2000]
        except asyncio.TimeoutError:
            # No stderr data available within timeout - this is normal for running processes
            logger.debug(f"No stderr data available for '{name}' within timeout")
        except Exception as e:
            logger.debug(f"Could not read stderr for '{name}': {e}")
        return ""

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

        # Clean up SSE connection
        await self._close_sse_connection(name)

        # Clean up tools cache
        self._tools_cache.pop(name, None)

        # Clean up subscriptions
        self._subscriptions.pop(name, None)

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
        elif server.server_type == "sse" and server_name in self._sse_connections:
            return await self._send_sse_request(server_name, method, params, timeout)
        else:
            return await self._send_network_request(server, method, params, timeout)

    async def _send_notification(
        self,
        server_name: str,
        method: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Unified notification dispatcher: routes to stdio, websocket, or HTTP.

        Notifications are one-way messages that don't expect a response.
        """
        server = self._tracker.get_server(server_name)
        if not server:
            raise ValueError(f"Server '{server_name}' not found")

        if server.server_type == "stdio":
            await self._send_stdio_notification(server_name, method, params)
        elif server.server_type == "websocket" and server_name in self._ws_connections:
            await self._send_ws_notification(server_name, method, params)
        elif server.server_type == "sse" and server_name in self._sse_connections:
            await self._send_sse_notification(server_name, method, params)
        else:
            await self._send_http_notification(server_name, method, params)

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

        Raises:
            RuntimeError: If server is unresponsive (timeout) with diagnostic info.
        """
        server = self._tracker.get_server(name)
        if not server:
            raise ValueError(f"Server '{name}' not found")
        if server.status != ServerStatus.RUNNING:
            raise ValueError(f"Server '{name}' is not running (status: {server.status.value})")

        # Check if process is actually alive before attempting request
        if not self._is_process_alive(name):
            server.status = ServerStatus.CRASHED
            server.error = "Process exited unexpectedly"
            stderr_text = await self._capture_server_stderr(name)
            if stderr_text:
                server.error += f"\n--- stderr ---\n{stderr_text[:1000]}"
            raise RuntimeError(
                f"MCP server '{name}' process has exited. "
                f"stderr: {stderr_text[:500] if stderr_text else '(none)'}"
            )

        try:
            result = await self._send_request(name, "tools/list", timeout=TOOL_DISCOVER_TIMEOUT)
            tools = self._parse_tools_from_result(result)
            self._tools_cache[name] = tools
            return [t.to_dict() for t in tools]

        except TimeoutError as e:
            # Server is unresponsive - mark as failed and collect diagnostics
            server.status = ServerStatus.FAILED
            server.error = f"Tool discovery timed out after {TOOL_DISCOVER_TIMEOUT}s"

            # Check if process died during the request
            if not self._is_process_alive(name):
                server.status = ServerStatus.CRASHED
                server.error = "Process died during tool discovery"
                stderr_text = await self._capture_server_stderr(name)
                if stderr_text:
                    server.error += f"\n--- stderr ---\n{stderr_text[:2000]}"

            # Capture stderr for debugging
            stderr_text = await self._capture_server_stderr(name)
            if stderr_text:
                server.error += f"\n--- Server stderr ---\n{stderr_text[:2000]}"

            logger.error(
                f"MCP server '{name}' unresponsive during tool discovery: {e}\n"
                f"Process alive: {self._is_process_alive(name)}\n"
                f"stderr: {stderr_text[:500] if stderr_text else '(none)'}"
            )

            # Stop the unresponsive server
            await self.stop_server(name)

            raise RuntimeError(
                f"MCP server '{name}' is unresponsive and has been stopped. Error: {e}"
            ) from e

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

        # Check if process is actually alive before attempting request
        if not self._is_process_alive(server_name):
            server.status = ServerStatus.CRASHED
            server.error = "Process exited unexpectedly"
            stderr_text = await self._capture_server_stderr(server_name)
            if stderr_text:
                server.error += f"\n--- stderr ---\n{stderr_text[:1000]}"
            return MCPCallResult(
                content=[
                    {
                        "type": "text",
                        "text": f"Server '{server_name}' process has exited. "
                        f"stderr: {stderr_text[:500] if stderr_text else '(none)'}",
                    }
                ],
                is_error=True,
                error_message=server.error,
            ).to_dict()

        try:
            # Use tool-specific timeout if available (e.g., bash tool's timeout param)
            tool_timeout = arguments.get("timeout")
            timeout = TOOL_CALL_TIMEOUT
            if tool_timeout and isinstance(tool_timeout, (int, float)):
                timeout = int(tool_timeout) + 30

            raw = await self._send_request(
                server_name,
                "tools/call",
                {"name": tool_name, "arguments": arguments},
                timeout=timeout,
            )
            content = raw.get("content", [{"type": "text", "text": str(raw)}])
            is_error = raw.get("isError", False)
            return MCPCallResult(content=content, is_error=is_error).to_dict()

        except TimeoutError as e:
            # Tool call timed out - check if process is still alive
            logger.warning(f"Tool '{tool_name}' on '{server_name}' timed out after {timeout}s")

            if not self._is_process_alive(server_name):
                server.status = ServerStatus.CRASHED
                server.error = f"Process died during tool call: {tool_name}"
                stderr_text = await self._capture_server_stderr(server_name)
                if stderr_text:
                    server.error += f"\n--- stderr ---\n{stderr_text[:1000]}"
                return MCPCallResult(
                    content=[
                        {
                            "type": "text",
                            "text": f"Server '{server_name}' process died during tool call. "
                            f"stderr: {stderr_text[:500] if stderr_text else '(none)'}",
                        }
                    ],
                    is_error=True,
                    error_message=server.error,
                ).to_dict()

            return MCPCallResult(
                content=[
                    {
                        "type": "text",
                        "text": f"Tool '{tool_name}' timed out after {timeout}s. "
                        f"Server is still running but unresponsive.",
                    }
                ],
                is_error=True,
                error_message=str(e),
            ).to_dict()

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

        # Ensure uri is a plain string (MCP SDK may use Pydantic AnyUrl)
        uri = str(uri)

        try:
            result = await self._send_request(server_name, "resources/read", {"uri": uri})
            contents = result.get("contents", [])
            for item in contents:
                if isinstance(item, dict):
                    text = item.get("text")
                    if text:
                        return str(text)
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

    async def ping(self, server_name: str) -> bool:
        """Ping a managed MCP server to check if it's responsive.

        Args:
            server_name: Server name.

        Returns:
            True if server responds to ping, False otherwise.
        """
        server = self._tracker.get_server(server_name)
        if not server or server.status != ServerStatus.RUNNING:
            return False

        try:
            await self._send_request(server_name, "ping")
            return True
        except Exception as e:
            logger.warning(f"Ping failed for '{server_name}': {e}")
            return False

    async def list_resource_templates(self, server_name: str) -> list:
        """List resource templates from a managed MCP server via resources/templates/list.

        Args:
            server_name: Server name.

        Returns:
            List of resource template descriptors, or empty list on failure.
        """
        server = self._tracker.get_server(server_name)
        if not server or server.status != ServerStatus.RUNNING:
            return []

        try:
            result = await self._send_request(server_name, "resources/templates/list")
            return result.get("resourceTemplates", [])
        except Exception as e:
            logger.error(f"Error listing resource templates from '{server_name}': {e}")
            return []

    async def list_prompts(self, server_name: str) -> list:
        """List prompts from a managed MCP server via prompts/list.

        Args:
            server_name: Server name.

        Returns:
            List of prompt descriptors, or empty list on failure.
        """
        server = self._tracker.get_server(server_name)
        if not server or server.status != ServerStatus.RUNNING:
            return []

        try:
            result = await self._send_request(server_name, "prompts/list")
            return result.get("prompts", [])
        except Exception as e:
            logger.error(f"Error listing prompts from '{server_name}': {e}")
            return []

    async def get_prompt(
        self,
        server_name: str,
        name: str,
        arguments: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Get a prompt from a managed MCP server via prompts/get.

        Args:
            server_name: Server name.
            name: Prompt name.
            arguments: Optional arguments for the prompt.

        Returns:
            Prompt response with messages, or None on failure.
        """
        server = self._tracker.get_server(server_name)
        if not server or server.status != ServerStatus.RUNNING:
            return None

        try:
            result = await self._send_request(
                server_name,
                "prompts/get",
                {"name": name, "arguments": arguments or {}},
            )
            return result
        except Exception as e:
            logger.error(f"Error getting prompt '{name}' from '{server_name}': {e}")
            return None

    async def set_log_level(
        self,
        server_name: str,
        level: str,
    ) -> bool:
        """Set the logging level on a managed MCP server via logging/setLevel.

        Args:
            server_name: Server name.
            level: Log level (debug, info, notice, warning, error, critical, alert, emergency).

        Returns:
            True if notification was sent successfully, False otherwise.
        """
        server = self._tracker.get_server(server_name)
        if not server or server.status != ServerStatus.RUNNING:
            return False

        try:
            await self._send_notification(
                server_name,
                "logging/setLevel",
                {"level": level},
            )
            return True
        except Exception as e:
            logger.error(f"Error setting log level on '{server_name}': {e}")
            return False

    async def subscribe_resource(
        self,
        server_name: str,
        uri: str,
    ) -> Optional[str]:
        """Subscribe to resource updates on a managed MCP server via resources/subscribe.

        Args:
            server_name: Server name.
            uri: Resource URI to subscribe to.

        Returns:
            Subscription ID if successful, None on failure.
        """
        server = self._tracker.get_server(server_name)
        if not server or server.status != ServerStatus.RUNNING:
            return None

        try:
            result = await self._send_request(
                server_name,
                "resources/subscribe",
                {"uri": uri},
            )
            subscription_id = result.get("subscriptionId")
            if not subscription_id:
                logger.warning(
                    f"No subscriptionId in response from '{server_name}' for uri '{uri}'"
                )
                return None

            # Track subscription internally
            if server_name not in self._subscriptions:
                self._subscriptions[server_name] = {}
            self._subscriptions[server_name][subscription_id] = uri

            logger.info(f"Subscribed to resource '{uri}' on '{server_name}': {subscription_id}")
            return subscription_id
        except Exception as e:
            logger.error(f"Error subscribing to resource on '{server_name}': {e}")
            return None

    async def unsubscribe_resource(
        self,
        server_name: str,
        subscription_id: str,
    ) -> bool:
        """Unsubscribe from resource updates on a managed MCP server via resources/unsubscribe.

        Args:
            server_name: Server name.
            subscription_id: Subscription ID to unsubscribe from.

        Returns:
            True if successful, False on failure.
        """
        server = self._tracker.get_server(server_name)
        if not server or server.status != ServerStatus.RUNNING:
            return False

        # Check if subscription exists in our tracking
        if server_name not in self._subscriptions:
            return False
        if subscription_id not in self._subscriptions[server_name]:
            return False

        try:
            await self._send_request(
                server_name,
                "resources/unsubscribe",
                {"subscriptionId": subscription_id},
            )

            # Remove from internal tracking
            del self._subscriptions[server_name][subscription_id]
            # Clean up empty server entry
            if not self._subscriptions[server_name]:
                del self._subscriptions[server_name]

            logger.info(f"Unsubscribed from resource on '{server_name}': {subscription_id}")
            return True
        except Exception as e:
            logger.error(f"Error unsubscribing from resource on '{server_name}': {e}")
            return False

    def get_active_subscriptions(self, server_name: str) -> Dict[str, str]:
        """Get active subscriptions for a server.

        Args:
            server_name: Server name.

        Returns:
            Dict mapping subscription_id -> uri for the server.
            Returns empty dict if server has no subscriptions.
        """
        if server_name not in self._subscriptions:
            return {}
        # Return a copy to prevent external mutation
        return dict(self._subscriptions[server_name])

    async def shutdown(self) -> None:
        """Shutdown all managed servers."""
        for name in list(self._connections.keys()):
            conn = self._connections.pop(name, None)
            if conn and conn._reader_task:
                conn._reader_task.cancel()
        for name in list(self._ws_connections.keys()):
            await self._close_ws_connection(name)
        for name in list(self._sse_connections.keys()):
            await self._close_sse_connection(name)
        # Close shared HTTP session
        if self._http_session and not self._http_session.closed:
            await self._http_session.close()
            self._http_session = None
        # Clear all subscriptions
        self._subscriptions.clear()
        await self._tracker.stop_all()

    # -- Stdio protocol methods --

    async def _init_stdio_connection(self, server: ManagedServer) -> None:
        """Initialize MCP JSON-RPC connection over stdio."""
        conn = _StdioConnection(server=server)
        self._connections[server.name] = conn

        # Check if process is still running before attempting initialization
        if server.process and server.process.returncode is not None:
            stderr_text = await self._capture_server_stderr(server.name)
            exit_code = server.process.returncode
            error_msg = f"MCP server '{server.name}' exited immediately with code {exit_code}"
            if stderr_text:
                error_msg = f"{error_msg}\n--- Server stderr ---\n{stderr_text}"
            logger.error(error_msg)
            raise RuntimeError(error_msg)

        # Start reading responses
        conn._reader_task = asyncio.create_task(self._read_stdio_responses(server.name))

        # Send initialize request
        try:
            await self._send_stdio_request(
                server.name,
                "initialize",
                {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {
                        "roots": {"listChanged": True},
                        "extensions": {
                            "io.modelcontextprotocol/ui": {
                                "mimeTypes": ["text/html;profile=mcp-app"],
                            },
                        },
                    },
                    "clientInfo": {"name": "sandbox-mcp-manager", "version": "1.0.0"},
                },
                timeout=MCP_INIT_TIMEOUT,
            )
            conn._initialized = True
            logger.info(f"MCP stdio connection initialized for '{server.name}'")

            # Send initialized notification
            await self._send_stdio_notification(server.name, "notifications/initialized")

        except Exception as e:
            # Check if process exited during initialization
            if server.process and server.process.returncode is not None:
                stderr_text = await self._capture_server_stderr(server.name)
                exit_code = server.process.returncode
                error_msg = (
                    f"MCP server '{server.name}' exited with code {exit_code} during initialization"
                )
                if stderr_text:
                    error_msg = f"{error_msg}\n--- Server stderr ---\n{stderr_text}"
                logger.error(error_msg)
                raise RuntimeError(error_msg) from e

            stderr_text = await self._capture_server_stderr(server.name)
            if stderr_text:
                raise RuntimeError(
                    f"Failed to initialize MCP for '{server.name}': {e}\n"
                    f"--- Server stderr ---\n{stderr_text}"
                ) from e
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

        server = self._tracker.get_server(name)
        if server and server.process and server.process.returncode is not None:
            stderr_text = await self._capture_server_stderr(name)
            exit_code = server.process.returncode
            error_msg = f"MCP server '{name}' exited with code {exit_code}"
            if stderr_text:
                error_msg = f"{error_msg}\n--- Server stderr ---\n{stderr_text}"
            raise RuntimeError(error_msg)

        # If the reader task stopped (e.g. idle timeout), restart it before
        # sending the request so responses can be received.
        if conn._reader_task is None or conn._reader_task.done():
            logger.info("Stdio reader for '%s' was stopped; restarting before request", name)
            conn._reader_task = asyncio.create_task(self._read_stdio_responses(name))

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
            # Wait for response with periodic process status check
            start_time = asyncio.get_event_loop().time()
            check_interval = 0.5  # Check every 500ms
            while True:
                try:
                    remaining = timeout - (asyncio.get_event_loop().time() - start_time)
                    if remaining <= 0:
                        raise asyncio.TimeoutError()
                    response = await asyncio.wait_for(
                        asyncio.shield(future), timeout=min(check_interval, remaining)
                    )
                    # Got response
                    if "error" in response:
                        raise RuntimeError(
                            f"MCP error: {response['error'].get('message', 'Unknown error')}"
                        )
                    return response.get("result", {})
                except asyncio.TimeoutError:
                    # Check if process exited
                    if server and server.process and server.process.returncode is not None:
                        conn._pending.pop(request_id, None)
                        stderr_text = await self._capture_server_stderr(name)
                        exit_code = server.process.returncode
                        error_msg = f"MCP server '{name}' exited with code {exit_code}"
                        if stderr_text:
                            error_msg = f"{error_msg}\n--- Server stderr ---\n{stderr_text}"
                        raise RuntimeError(error_msg)
                    # Process still running, continue waiting
                    if asyncio.get_event_loop().time() - start_time >= timeout:
                        conn._pending.pop(request_id, None)
                        raise TimeoutError(f"MCP request '{method}' timed out after {timeout}s")
        except (RuntimeError, TimeoutError):
            raise
        except Exception:
            conn._pending.pop(request_id, None)
            raise

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

        # Idle timeout: if no data for 300s, assume server hung
        idle_timeout = 300

        try:
            while True:
                try:
                    line = await asyncio.wait_for(
                        conn.stdout.readline(),
                        timeout=idle_timeout,
                    )
                except asyncio.TimeoutError:
                    logger.warning(f"Stdio reader for '{name}' idle for {idle_timeout}s, stopping")
                    break
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
                            await asyncio.sleep(0.5 * (2**attempt))
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
                err_str = str(e)
                if "Connect call failed" in err_str or "Cannot connect" in err_str:
                    msg = (
                        f"Cannot connect to MCP server '{server.name}' at {server.url}. "
                        f"The server may not be running or the port is incorrect."
                    )
                else:
                    msg = (
                        f"HTTP request to MCP server '{server.name}' "
                        f"at {server.url} failed: {err_str}"
                    )
                last_error = RuntimeError(msg)
                if attempt < max_retries - 1:
                    await asyncio.sleep(0.5 * (2**attempt))
                    continue
                raise last_error

        raise last_error or RuntimeError(
            f"Request to MCP server '{server.name}' at {server.url} failed after retries"
        )

    async def _send_http_notification(
        self,
        server_name: str,
        method: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Send a JSON-RPC notification via HTTP POST (no response expected)."""
        import aiohttp

        server = self._tracker.get_server(server_name)
        if not server or not server.url:
            raise ValueError(f"No URL configured for network server '{server_name}'")

        notification = {
            "jsonrpc": "2.0",
            "method": method,
        }
        if params is not None:
            notification["params"] = params

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        session_id = self._session_ids.get(server_name)
        if session_id:
            headers["Mcp-Session-Id"] = session_id

        try:
            session = await self._get_http_session()
            async with session.post(
                server.url,
                json=notification,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status >= 400:
                    body = await resp.text()
                    logger.warning(
                        f"HTTP {resp.status} from '{server.url}' "
                        f"for notification '{method}': {body[:200]}"
                    )
                # Store session ID from response
                new_session_id = resp.headers.get("Mcp-Session-Id")
                if new_session_id:
                    self._session_ids[server_name] = new_session_id
        except aiohttp.ClientError as e:
            logger.warning(f"HTTP notification to MCP server '{server_name}' failed: {e}")

    async def _read_sse_response(self, resp, request_id: int) -> Dict[str, Any]:
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
                        raise RuntimeError(f"MCP error: {data['error'].get('message', 'Unknown')}")
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
                    "capabilities": {
                        "roots": {"listChanged": True},
                        "extensions": {
                            "io.modelcontextprotocol/ui": {
                                "mimeTypes": ["text/html;profile=mcp-app"],
                            },
                        },
                    },
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
            stderr_text = await self._capture_server_stderr(server.name)
            if stderr_text:
                raise RuntimeError(
                    f"Failed to initialize network MCP for '{server.name}': {e}\n"
                    f"--- Server stderr ---\n{stderr_text}"
                ) from e
            logger.error(f"Failed to initialize network MCP for '{server.name}': {e}")
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
            conn._reader_task = asyncio.create_task(self._read_ws_responses(server.name))

            # Send initialize (register future BEFORE send to avoid race with reader)
            req_id = conn.next_id()
            future: asyncio.Future = asyncio.get_event_loop().create_future()
            conn._pending[req_id] = future

            await ws.send_json(
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {
                            "roots": {"listChanged": True},
                            "extensions": {
                                "io.modelcontextprotocol/ui": {
                                    "mimeTypes": ["text/html;profile=mcp-app"],
                                },
                            },
                        },
                        "clientInfo": {"name": "sandbox-mcp-manager", "version": "1.0.0"},
                    },
                }
            )

            # Wait for response
            result = await asyncio.wait_for(future, timeout=MCP_INIT_TIMEOUT)
            conn._initialized = True
            logger.info(
                f"MCP WebSocket connection initialized for '{server.name}': "
                f"server={result.get('serverInfo', {}).get('name', 'unknown')}"
            )

            # Send initialized notification
            await ws.send_json(
                {
                    "jsonrpc": "2.0",
                    "method": "notifications/initialized",
                }
            )

        except Exception as e:
            await session.close()
            self._ws_connections.pop(server.name, None)
            stderr_text = await self._capture_server_stderr(server.name)
            if stderr_text:
                raise RuntimeError(
                    f"Failed to init WebSocket MCP for '{server.name}': {e}\n"
                    f"--- Server stderr ---\n{stderr_text}"
                ) from e
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

    async def _send_ws_notification(
        self,
        server_name: str,
        method: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Send a JSON-RPC notification over WebSocket (no response expected)."""
        conn = self._ws_connections.get(server_name)
        if not conn or not conn.ws:
            raise RuntimeError(f"No WebSocket connection for '{server_name}'")

        notification: Dict[str, Any] = {
            "jsonrpc": "2.0",
            "method": method,
        }
        if params is not None:
            notification["params"] = params

        await conn.ws.send_json(notification)

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

    # -- Legacy SSE protocol methods --

    async def _init_sse_connection(self, server: ManagedServer) -> None:
        """Initialize a persistent SSE connection to a legacy MCP SSE server.

        Legacy SSE protocol:
          1. GET /sse -> persistent SSE stream
          2. Server sends 'endpoint' event with the messages URL
          3. Client POSTs JSON-RPC to the messages URL
          4. Responses arrive on the SSE stream
        """
        import aiohttp

        if not server.url:
            raise ValueError(f"No URL for SSE server '{server.name}'")

        session = aiohttp.ClientSession()
        try:
            # Establish persistent SSE stream
            resp = await session.get(
                server.url,
                headers={"Accept": "text/event-stream"},
                timeout=aiohttp.ClientTimeout(total=None),
            )
            if resp.status != 200:
                body = await resp.text()
                raise RuntimeError(
                    f"SSE connection to '{server.url}' returned HTTP {resp.status}: {body[:200]}"
                )

            conn = _SSEConnection(server=server, session=session)
            self._sse_connections[server.name] = conn

            # Read the 'endpoint' event to get the messages URL
            endpoint_url = await self._read_sse_endpoint(resp, server, timeout=10)
            conn.messages_url = endpoint_url

            # Start background reader for JSON-RPC responses
            conn._reader_task = asyncio.create_task(self._read_sse_stream(server.name, resp))

            # Send initialize request
            req_id = conn.next_id()
            future: asyncio.Future = asyncio.get_event_loop().create_future()
            conn._pending[req_id] = future

            await session.post(
                conn.messages_url,
                json={
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {
                            "roots": {"listChanged": True},
                            "extensions": {
                                "io.modelcontextprotocol/ui": {
                                    "mimeTypes": ["text/html;profile=mcp-app"],
                                },
                            },
                        },
                        "clientInfo": {
                            "name": "sandbox-mcp-manager",
                            "version": "1.0.0",
                        },
                    },
                },
                headers={"Content-Type": "application/json"},
                timeout=aiohttp.ClientTimeout(total=MCP_INIT_TIMEOUT),
            )

            result = await asyncio.wait_for(future, timeout=MCP_INIT_TIMEOUT)
            conn._initialized = True
            logger.info(
                f"MCP SSE connection initialized for '{server.name}': "
                f"server={result.get('serverInfo', {}).get('name', 'unknown')}, "
                f"messages_url={conn.messages_url}"
            )

            # Send initialized notification (fire-and-forget)
            try:
                await session.post(
                    conn.messages_url,
                    json={
                        "jsonrpc": "2.0",
                        "method": "notifications/initialized",
                    },
                    headers={"Content-Type": "application/json"},
                    timeout=aiohttp.ClientTimeout(total=5),
                )
            except Exception:
                pass  # Notifications are best-effort

        except Exception as e:
            await session.close()
            self._sse_connections.pop(server.name, None)
            logger.warning(f"Failed to init SSE MCP for '{server.name}': {e}")
            raise

    async def _read_sse_endpoint(self, resp, server: ManagedServer, timeout: int = 10) -> str:
        """Read the 'endpoint' event from an SSE stream to get the messages URL."""
        event_type = ""

        async def _read_endpoint_inner() -> str:
            nonlocal event_type
            async for line_bytes in resp.content:
                line = line_bytes.decode("utf-8").rstrip("\n").rstrip("\r")

                if not line:
                    event_type = ""
                    continue
                if line.startswith(":"):
                    continue
                if line.startswith("event: "):
                    event_type = line[7:].strip()
                    continue
                if line.startswith("data: ") and event_type == "endpoint":
                    messages_path = line[6:].strip()
                    # Resolve relative path to absolute URL
                    if messages_path.startswith("/"):
                        from urllib.parse import urlparse

                        parsed = urlparse(server.url)
                        return f"{parsed.scheme}://{parsed.netloc}{messages_path}"
                    return messages_path

            raise RuntimeError(
                f"SSE stream from '{server.name}' closed without sending 'endpoint' event"
            )

        try:
            return await asyncio.wait_for(_read_endpoint_inner(), timeout=timeout)
        except asyncio.TimeoutError:
            raise RuntimeError(
                f"Timeout waiting for 'endpoint' event from SSE server "
                f"'{server.name}' at {server.url}"
            )

    async def _read_sse_stream(self, server_name: str, resp) -> None:
        """Background task: read JSON-RPC responses from a legacy SSE stream."""
        conn = self._sse_connections.get(server_name)
        if not conn:
            return

        event_type = ""
        data_buffer = ""

        try:
            async for line_bytes in resp.content:
                line = line_bytes.decode("utf-8").rstrip("\n").rstrip("\r")

                if not line:
                    # Empty line = end of event
                    if event_type == "message" and data_buffer:
                        try:
                            data = json.loads(data_buffer)
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
                            pass
                    event_type = ""
                    data_buffer = ""
                    continue

                if line.startswith(":"):
                    continue
                if line.startswith("event: "):
                    event_type = line[7:].strip()
                elif line.startswith("data: "):
                    data_buffer += line[6:]
        except asyncio.CancelledError:
            return
        except Exception as e:
            logger.error(f"SSE reader error for '{server_name}': {e}")
        finally:
            for future in conn._pending.values():
                if not future.done():
                    future.set_exception(RuntimeError("SSE connection closed"))
            conn._pending.clear()

    async def _send_sse_request(
        self,
        server_name: str,
        method: str,
        params: Optional[Dict[str, Any]] = None,
        timeout: int = TOOL_CALL_TIMEOUT,
    ) -> Dict[str, Any]:
        """Send a JSON-RPC request via legacy SSE transport."""
        import aiohttp

        conn = self._sse_connections.get(server_name)
        if not conn or not conn.messages_url:
            raise RuntimeError(
                f"No SSE connection for '{server_name}'. The server may need to be restarted."
            )

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

        try:
            async with conn.session.post(
                conn.messages_url,
                json=request,
                headers={"Content-Type": "application/json"},
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as resp:
                if resp.status >= 400:
                    body = await resp.text()
                    conn._pending.pop(req_id, None)
                    if not future.done():
                        future.cancel()
                    raise RuntimeError(
                        f"HTTP {resp.status} from SSE server '{server_name}' "
                        f"messages endpoint: {body[:300]}"
                    )
        except aiohttp.ClientError as e:
            conn._pending.pop(req_id, None)
            if not future.done():
                future.cancel()
            raise RuntimeError(f"Cannot send request to SSE server '{server_name}': {e}") from e

        return await asyncio.wait_for(future, timeout=timeout)

    async def _send_sse_notification(
        self,
        server_name: str,
        method: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Send a JSON-RPC notification via legacy SSE transport (no response expected)."""
        import aiohttp

        conn = self._sse_connections.get(server_name)
        if not conn or not conn.messages_url:
            raise RuntimeError(
                f"No SSE connection for '{server_name}'. The server may need to be restarted."
            )

        notification: Dict[str, Any] = {
            "jsonrpc": "2.0",
            "method": method,
        }
        if params is not None:
            notification["params"] = params

        async with conn.session.post(
            conn.messages_url,
            json=notification,
            headers={"Content-Type": "application/json"},
            timeout=aiohttp.ClientTimeout(total=30),
        ) as resp:
            if resp.status >= 400:
                body = await resp.text()
                logger.warning(
                    f"HTTP {resp.status} from SSE server '{server_name}' "
                    f"notification endpoint: {body[:200]}"
                )

    async def _close_sse_connection(self, server_name: str) -> None:
        """Close an SSE connection."""
        conn = self._sse_connections.pop(server_name, None)
        if conn:
            if conn._reader_task and not conn._reader_task.done():
                conn._reader_task.cancel()
            if conn.session and not conn.session.closed:
                await conn.session.close()
