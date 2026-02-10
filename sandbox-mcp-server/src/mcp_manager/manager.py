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

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }


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


class MCPServerManager:
    """Manages user MCP servers within the sandbox container.

    Handles installation, process lifecycle, tool discovery,
    and proxying tool calls to running MCP servers.
    """

    def __init__(self, workspace_dir: str = "/workspace") -> None:
        self._workspace_dir = workspace_dir
        self._tracker = ProcessTracker()
        self._connections: Dict[str, _StdioConnection] = {}
        self._tools_cache: Dict[str, List[MCPToolInfo]] = {}

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
                    # Wait for server to be ready
                    await asyncio.sleep(2)
                else:
                    # Remote server, just track it
                    server = ManagedServer(
                        name=name,
                        server_type=server_type,
                        command="",
                        status=ServerStatus.RUNNING,
                    )
                    self._tracker._servers[name] = server
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

        # Clean up tools cache
        self._tools_cache.pop(name, None)

        success = await self._tracker.stop_server(name)
        return {"success": success, "name": name}

    async def list_servers(self) -> List[Dict[str, Any]]:
        """List all managed MCP servers."""
        return [s.to_dict() for s in self._tracker.list_servers()]

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

        if server.server_type == "stdio":
            tools = await self._discover_stdio_tools(name)
        else:
            tools = await self._discover_network_tools(server)

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
            if server.server_type == "stdio":
                result = await self._call_stdio_tool(server_name, tool_name, arguments)
            else:
                result = await self._call_network_tool(server, tool_name, arguments)
            return result.to_dict()
        except Exception as e:
            logger.error(f"Error calling tool '{tool_name}' on '{server_name}': {e}")
            return MCPCallResult(
                content=[{"type": "text", "text": f"Error: {str(e)}"}],
                is_error=True,
                error_message=str(e),
            ).to_dict()

    async def shutdown(self) -> None:
        """Shutdown all managed servers."""
        for name in list(self._connections.keys()):
            conn = self._connections.pop(name, None)
            if conn and conn._reader_task:
                conn._reader_task.cancel()
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

    async def _discover_stdio_tools(self, name: str) -> List[MCPToolInfo]:
        """Discover tools from a stdio MCP server."""
        result = await self._send_stdio_request(name, "tools/list")
        tools = []
        for tool_data in result.get("tools", []):
            tools.append(
                MCPToolInfo(
                    name=tool_data.get("name", ""),
                    description=tool_data.get("description", ""),
                    input_schema=tool_data.get("inputSchema", {}),
                )
            )
        return tools

    async def _call_stdio_tool(
        self,
        name: str,
        tool_name: str,
        arguments: Dict[str, Any],
    ) -> MCPCallResult:
        """Call a tool on a stdio MCP server."""
        # Use tool-specific timeout if available (e.g., bash tool's timeout param)
        tool_timeout = arguments.get("timeout")
        timeout = TOOL_CALL_TIMEOUT
        if tool_timeout and isinstance(tool_timeout, (int, float)):
            timeout = int(tool_timeout) + 30  # Add overhead for MCP protocol

        result = await self._send_stdio_request(
            name,
            "tools/call",
            {"name": tool_name, "arguments": arguments},
            timeout=timeout,
        )
        content = result.get("content", [{"type": "text", "text": str(result)}])
        is_error = result.get("isError", False)
        return MCPCallResult(content=content, is_error=is_error)

    # -- Network protocol methods (placeholder for http/sse/websocket) --

    async def _discover_network_tools(self, server: ManagedServer) -> List[MCPToolInfo]:
        """Discover tools from a network MCP server.

        For network servers, we use HTTP to call the tools/list endpoint.
        """
        # For now, return empty. Full implementation requires HTTP/SSE/WS client.
        logger.warning(f"Network tool discovery not yet implemented for '{server.name}'")
        return []

    async def _call_network_tool(
        self,
        server: ManagedServer,
        tool_name: str,
        arguments: Dict[str, Any],
    ) -> MCPCallResult:
        """Call a tool on a network MCP server."""
        # For now, return error. Full implementation requires HTTP/SSE/WS client.
        return MCPCallResult(
            content=[
                {
                    "type": "text",
                    "text": "Network tool calls not yet implemented",
                }
            ],
            is_error=True,
            error_message="Network tool calls not yet implemented",
        )
