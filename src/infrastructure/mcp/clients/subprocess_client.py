"""MCP Subprocess Client for LOCAL (stdio) transport.

This module provides a subprocess-based MCP client for local MCP servers
that communicate via stdin/stdout using the JSON-RPC protocol.

Used by MCP tool adapters to manage MCP server subprocesses.

The local dataclasses (MCPToolSchema, MCPToolResult) are used for
MCP protocol serialization. Domain model equivalents are in:
- src.domain.model.mcp.tool.MCPToolSchema
- src.domain.model.mcp.tool.MCPToolResult
"""

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# Default timeout in seconds
DEFAULT_TIMEOUT = 600


@dataclass
class MCPToolSchema:
    """Schema for an MCP tool.

    DEPRECATED: Use src.domain.model.mcp.tool.MCPToolSchema instead.
    Kept for Temporal activity serialization compatibility.
    """

    name: str
    description: str | None = None
    inputSchema: dict[str, Any] = field(default_factory=dict)
    meta: dict[str, Any] | None = None


@dataclass
class MCPToolResult:
    """Result from an MCP tool call.

    DEPRECATED: Use src.domain.model.mcp.tool.MCPToolResult instead.
    Kept for Temporal activity serialization compatibility.
    """

    content: list[dict[str, Any]] = field(default_factory=list)
    isError: bool = False
    metadata: dict[str, Any] | None = None
    artifact: dict[str, Any] | None = None  # For export_artifact tool results


class MCPSubprocessClient:
    """
    Subprocess-based MCP client for LOCAL (stdio) transport.

    Uses direct subprocess communication with JSON-RPC protocol.
    Designed to run within Temporal Worker activities.

    Usage:
        client = MCPSubprocessClient(
            command="uvx",
            args=["mcp-server-fetch"],
            env={"API_KEY": "xxx"}
        )
        await client.connect()
        tools = await client.list_tools()
        result = await client.call_tool("fetch", {"url": "https://example.com"})
        await client.disconnect()
    """

    def __init__(
        self,
        command: str,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        """
        Initialize the subprocess client.

        Args:
            command: The command to execute (e.g., "uvx", "npx", "docker")
            args: Command arguments (e.g., ["mcp-server-fetch"])
            env: Additional environment variables
            timeout: Default timeout for operations in seconds
        """
        self.command = command
        self.args = args or []
        self.env = env
        self.timeout = timeout
        self._proc: asyncio.subprocess.Process | None = None
        self._request_id = 0
        self._lock = asyncio.Lock()
        self.server_info: dict[str, Any] | None = None
        self._tools: list[MCPToolSchema] = []

    @property
    def is_connected(self) -> bool:
        """Check if the client is connected."""
        return self._proc is not None and self._proc.returncode is None

    async def connect(self, timeout: float | None = None) -> bool:
        """
        Start the subprocess and initialize the connection.

        Args:
            timeout: Connection timeout in seconds (uses default if None)

        Returns:
            True if connection successful, False otherwise
        """
        timeout = timeout or self.timeout

        # Build environment
        env = os.environ.copy()
        if self.env:
            env.update(self.env)

        logger.info(f"Starting MCP subprocess: {self.command} {' '.join(self.args)}")

        try:
            # Use a larger buffer limit for stdout to handle large responses (e.g., screenshots)
            # Default is 2^16 (65536), we increase to 2^24 (16MB) to handle base64 images
            self._proc = await asyncio.create_subprocess_exec(
                self.command,
                *self.args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
                limit=16 * 1024 * 1024,  # 16MB buffer limit for large responses
            )

            # Send initialize request
            result = await self._send_request(
                "initialize",
                {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {
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

            logger.debug(f"Initialize response: {result}")

            if result and "result" in result:
                self.server_info = result["result"].get("serverInfo", {})

                # Send initialized notification
                await self._send_notification("notifications/initialized", {})

                # Pre-fetch tools list
                tools = await self.list_tools(timeout=timeout)
                self._tools = tools

                logger.info(
                    f"MCP subprocess connected: {self.server_info} with {len(self._tools)} tools"
                )
                return True

            logger.error(f"MCP initialize request failed. Response: {result}")
            stderr_text = await self._read_stderr()
            if stderr_text:
                logger.error(f"MCP subprocess stderr:\n{stderr_text}")
            await self.disconnect()
            return False

        except TimeoutError:
            stderr_text = await self._read_stderr()
            logger.error(
                f"MCP connection timeout after {timeout}s for '{self.command} {' '.join(self.args)}'"
                + (f"\nStderr: {stderr_text}" if stderr_text else "")
            )
            await self.disconnect()
            return False
        except FileNotFoundError:
            logger.error(f"Command not found: {self.command}")
            return False
        except Exception as e:
            stderr_text = await self._read_stderr()
            logger.exception(
                f"Error connecting to MCP subprocess: {e}"
                + (f"\nStderr: {stderr_text}" if stderr_text else "")
            )
            await self.disconnect()
            return False

    async def _read_stderr(self) -> str:
        """Read available stderr from the subprocess. Returns up to 2000 chars."""
        if not self._proc or not self._proc.stderr:
            return ""
        try:
            data = await asyncio.wait_for(self._proc.stderr.read(4096), timeout=2)
            if data:
                return data.decode("utf-8", errors="replace")[:2000]
        except (TimeoutError, Exception):
            pass
        return ""

    async def disconnect(self) -> None:
        """Close the subprocess."""
        if self._proc:
            logger.info("Disconnecting MCP subprocess")
            try:
                self._proc.terminate()
                try:
                    await asyncio.wait_for(self._proc.wait(), timeout=5)
                except TimeoutError:
                    logger.warning("MCP subprocess did not terminate, killing")
                    self._proc.kill()
                    await self._proc.wait()
            except Exception as e:
                logger.error(f"Error disconnecting MCP subprocess: {e}")
            finally:
                self._proc = None
                self._tools = []
                self.server_info = None

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

        if result and "result" in result:
            tools_data = result["result"].get("tools", [])
            return [
                MCPToolSchema(
                    name=tool.get("name", ""),
                    description=tool.get("description"),
                    inputSchema=tool.get("inputSchema", {}),
                    meta=tool.get("_meta"),
                )
                for tool in tools_data
            ]

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        timeout: float | None = None,
    ) -> MCPToolResult:
        """
        Call a tool.

        Args:
            name: Tool name
            arguments: Tool arguments
            timeout: Operation timeout in seconds

        Returns:
            Tool execution result
        """
        timeout = timeout or self.timeout
        logger.info(f"Calling MCP tool: {name}")
        logger.debug(f"Tool arguments: {arguments}")

        result = await self._send_request(
            "tools/call",
            {"name": name, "arguments": arguments},
            timeout=timeout,
        )

        if result and "result" in result:
            return MCPToolResult(
                content=result["result"].get("content", []),
                isError=result["result"].get("isError", False),
            )

        if result and "error" in result:
            error_msg = result["error"]
            if isinstance(error_msg, dict):
                error_msg = error_msg.get("message", str(error_msg))
            return MCPToolResult(
                content=[{"type": "text", "text": f"Error: {error_msg}"}],
                isError=True,
            )

        return MCPToolResult(
            content=[{"type": "text", "text": "Unknown error"}],
            isError=True,
        )

    def get_cached_tools(self) -> list[MCPToolSchema]:
        """Get cached tools list (from connection time)."""
        return self._tools

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
            return result is not None and "result" in result
        except Exception as e:
            logger.error(f"Ping failed: {e}")
            return False

    async def _send_request(
        self,
        method: str,
        params: dict[str, Any],
        timeout: float = DEFAULT_TIMEOUT,
    ) -> dict[str, Any] | None:
        """Send a JSON-RPC request and wait for response."""
        if not self._proc or not self._proc.stdin or not self._proc.stdout:
            logger.error("MCP subprocess not connected")
            return None

        async with self._lock:
            self._request_id += 1
            request = {
                "jsonrpc": "2.0",
                "method": method,
                "params": params,
                "id": self._request_id,
            }

            request_str = json.dumps(request) + "\n"
            logger.debug(f"MCP request: {request_str.strip()}")

            try:
                self._proc.stdin.write(request_str.encode())
                await self._proc.stdin.drain()

                response_bytes = await asyncio.wait_for(
                    self._proc.stdout.readline(),
                    timeout=timeout,
                )
                response_str = response_bytes.decode().strip()
                logger.debug(f"MCP response: {response_str}")

                if response_str:
                    return json.loads(response_str)

            except TimeoutError:
                stderr_text = await self._read_stderr()
                logger.error(
                    f"MCP request '{method}' timed out after {timeout}s"
                    + (f"\nStderr: {stderr_text}" if stderr_text else "")
                )
            except json.JSONDecodeError as e:
                logger.error(f"MCP response parse error: {e}")
            except Exception as e:
                logger.error(f"MCP request error: {e}")

            return None

    async def _send_notification(self, method: str, params: dict[str, Any]) -> None:
        """Send a JSON-RPC notification (no response expected)."""
        if not self._proc or not self._proc.stdin:
            return

        notification = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        }

        notification_str = json.dumps(notification) + "\n"
        logger.debug(f"MCP notification: {notification_str.strip()}")

        try:
            self._proc.stdin.write(notification_str.encode())
            await self._proc.stdin.drain()
        except Exception as e:
            logger.error(f"MCP notification error: {e}")
