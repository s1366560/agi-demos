"""MCP Subprocess Client for LOCAL (stdio) transport.

This module provides a subprocess-based MCP client for local MCP servers
that communicate via stdin/stdout using the JSON-RPC protocol.

This client is used by MCP Activities in the Temporal Worker to manage
MCP server subprocesses independently from the API service.

MIGRATION NOTE:
===============
The local dataclasses (MCPToolSchema, MCPToolResult) are duplicates of
domain models. Use the domain adapter for conversions:

    from src.infrastructure.adapters.secondary.temporal.mcp.domain_adapter import (
        to_domain_tool_result,
        to_domain_tool_schema,
    )

Domain models are in:
- src.domain.model.mcp.tool.MCPToolSchema
- src.domain.model.mcp.tool.MCPToolResult
"""

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Default timeout in seconds
DEFAULT_TIMEOUT = 30


@dataclass
class MCPToolSchema:
    """Schema for an MCP tool.

    DEPRECATED: Use src.domain.model.mcp.tool.MCPToolSchema instead.
    Kept for Temporal activity serialization compatibility.
    """

    name: str
    description: Optional[str] = None
    inputSchema: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MCPToolResult:
    """Result from an MCP tool call.

    DEPRECATED: Use src.domain.model.mcp.tool.MCPToolResult instead.
    Kept for Temporal activity serialization compatibility.
    """

    content: List[Dict[str, Any]] = field(default_factory=list)
    isError: bool = False
    metadata: Optional[Dict[str, Any]] = None
    artifact: Optional[Dict[str, Any]] = None  # For export_artifact tool results


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
        args: Optional[List[str]] = None,
        env: Optional[Dict[str, str]] = None,
        timeout: float = DEFAULT_TIMEOUT,
    ):
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
        self._proc: Optional[asyncio.subprocess.Process] = None
        self._request_id = 0
        self._lock = asyncio.Lock()
        self.server_info: Optional[Dict[str, Any]] = None
        self._tools: List[MCPToolSchema] = []

    @property
    def is_connected(self) -> bool:
        """Check if the client is connected."""
        return self._proc is not None and self._proc.returncode is None

    async def connect(self, timeout: Optional[float] = None) -> bool:
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
                    "capabilities": {},
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
            # Try to read stderr for more info
            if self._proc and self._proc.stderr:
                try:
                    stderr_data = await asyncio.wait_for(self._proc.stderr.read(4096), timeout=1)
                    if stderr_data:
                        logger.error(f"MCP subprocess stderr: {stderr_data.decode()}")
                except asyncio.TimeoutError:
                    pass
            await self.disconnect()
            return False

        except asyncio.TimeoutError:
            logger.error(f"MCP connection timeout after {timeout}s")
            await self.disconnect()
            return False
        except FileNotFoundError:
            logger.error(f"Command not found: {self.command}")
            return False
        except Exception as e:
            logger.exception(f"Error connecting to MCP subprocess: {e}")
            await self.disconnect()
            return False

    async def disconnect(self) -> None:
        """Close the subprocess."""
        if self._proc:
            logger.info("Disconnecting MCP subprocess")
            try:
                self._proc.terminate()
                try:
                    await asyncio.wait_for(self._proc.wait(), timeout=5)
                except asyncio.TimeoutError:
                    logger.warning("MCP subprocess did not terminate, killing")
                    self._proc.kill()
                    await self._proc.wait()
            except Exception as e:
                logger.error(f"Error disconnecting MCP subprocess: {e}")
            finally:
                self._proc = None
                self._tools = []
                self.server_info = None

    async def list_tools(self, timeout: Optional[float] = None) -> List[MCPToolSchema]:
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
                )
                for tool in tools_data
            ]
        return []

    async def call_tool(
        self,
        name: str,
        arguments: Dict[str, Any],
        timeout: Optional[float] = None,
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

    def get_cached_tools(self) -> List[MCPToolSchema]:
        """Get cached tools list (from connection time)."""
        return self._tools

    async def _send_request(
        self,
        method: str,
        params: Dict[str, Any],
        timeout: float = DEFAULT_TIMEOUT,
    ) -> Optional[Dict[str, Any]]:
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

            except asyncio.TimeoutError:
                logger.error(f"MCP request '{method}' timed out after {timeout}s")
            except json.JSONDecodeError as e:
                logger.error(f"MCP response parse error: {e}")
            except Exception as e:
                logger.error(f"MCP request error: {e}")

            return None

    async def _send_notification(self, method: str, params: Dict[str, Any]) -> None:
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
