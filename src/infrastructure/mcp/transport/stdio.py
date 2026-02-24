"""
Stdio transport for MCP.

Communicates with MCP servers via subprocess stdin/stdout.
"""

import asyncio
import json
import logging
import os
from typing import Any, cast

from src.domain.model.mcp.transport import TransportConfig, TransportType
from src.infrastructure.mcp.transport.base import (
    BaseTransport,
    MCPTransportClosedError,
    MCPTransportError,
)

logger = logging.getLogger(__name__)


class StdioTransport(BaseTransport):
    """
    MCP transport using stdio (subprocess communication).

    Launches an MCP server as a subprocess and communicates
    via JSON-RPC over stdin/stdout.
    """

    def __init__(self, config: TransportConfig | None = None) -> None:
        """Initialize stdio transport."""
        super().__init__(config)
        self._process: asyncio.subprocess.Process | None = None
        self._initialized = False

    async def start(self, config: TransportConfig) -> None:
        """
        Start subprocess and establish stdio connection.

        Args:
            config: Transport configuration with command and args.

        Raises:
            MCPTransportError: If subprocess fails to start.
        """
        if self._is_open:
            logger.debug("Stdio transport already started")
            return

        self._config = config

        if config.transport_type not in (TransportType.LOCAL, TransportType.STDIO):
            raise MCPTransportError(f"Invalid transport type for stdio: {config.transport_type}")

        if not config.command:
            raise MCPTransportError("Command is required for stdio transport")

        try:
            # Prepare command
            command = config.command
            if isinstance(command, str):
                command = [command]

            # Prepare environment
            env = None
            if config.environment:
                env = {**os.environ, **config.environment}

            logger.info(f"Starting MCP server: {' '.join(command)}")

            self._process = await asyncio.create_subprocess_exec(
                command[0],
                *command[1:],
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )

            self._is_open = True
            logger.info(f"Started MCP server process (pid={self._process.pid})")

            # Perform MCP initialization handshake
            await self._initialize()

        except Exception as e:
            logger.error(f"Failed to start MCP server process: {e}", exc_info=True)
            raise MCPTransportError(f"Failed to start subprocess: {e}") from e

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
        if not self._process or not self._process.stdin:
            raise MCPTransportClosedError("Transport not connected")

        notification = {"jsonrpc": "2.0", "method": method, "params": params}
        await self.send(notification)

    async def _send_request(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        """Send a JSON-RPC request and wait for response."""
        request_id = self._next_request_id()

        request = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params or {},
        }

        await self.send(request)
        response = await self.receive(timeout=timeout)

        if "error" in response:
            raise MCPTransportError(f"MCP server error: {response['error']}")

        return cast(dict[str, Any], response.get("result", {}))

    async def stop(self) -> None:
        """Terminate subprocess."""
        if not self._is_open:
            return

        self._is_open = False
        self._initialized = False

        if self._process:
            try:
                self._process.terminate()
                await asyncio.wait_for(self._process.wait(), timeout=5.0)
            except TimeoutError:
                self._process.kill()
                await self._process.wait()
            except Exception as e:
                logger.error(f"Error stopping subprocess: {e}")
            finally:
                self._process = None

        logger.info("Stdio transport stopped")

    async def send(
        self,
        message: dict[str, Any],
        timeout: float | None = None,
    ) -> None:
        """
        Send a message to the subprocess stdin.

        Args:
            message: JSON-RPC message to send.
            timeout: Ignored for stdio (write is synchronous).
        """
        if not self._process or not self._process.stdin:
            raise MCPTransportClosedError("Transport not connected")

        message_json = json.dumps(message) + "\n"
        logger.debug(f"Sending: {message.get('method', 'response')} (id={message.get('id')})")

        self._process.stdin.write(message_json.encode())
        await self._process.stdin.drain()

    async def receive(
        self,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """
        Receive a message from subprocess stdout.

        Args:
            timeout: Receive timeout in seconds (default: 30).

        Returns:
            Parsed JSON-RPC message.

        Raises:
            MCPTransportClosedError: If process has exited.
            MCPTransportError: If read fails.
            asyncio.TimeoutError: If timeout expires.
        """
        if not self._process or not self._process.stdout:
            raise MCPTransportClosedError("Transport not connected")

        timeout = timeout or 30.0

        try:
            logger.debug(f"Waiting for response (timeout={timeout}s)...")
            line = await asyncio.wait_for(self._process.stdout.readline(), timeout=timeout)
        except TimeoutError:
            # Check if process is still running
            if self._process.returncode is not None:
                stderr = await self._process.stderr.read() if self._process.stderr else b""
                logger.error(
                    f"Process exited with code {self._process.returncode}, "
                    f"stderr: {stderr.decode()[:500]}"
                )
            raise

        if not line:
            stderr = await self._process.stderr.read() if self._process.stderr else b""
            logger.error(f"Process closed connection, stderr: {stderr.decode()[:500]}")
            raise MCPTransportClosedError("Process closed connection")

        logger.debug(f"Received: {line.decode()[:200]}...")
        return cast(dict[str, Any], json.loads(line.decode()))

    # High-level API methods

    async def list_tools(self) -> list[dict[str, Any]]:
        """List all available tools from the MCP server."""
        result = await self._send_request("tools/list")
        return cast(list[dict[str, Any]], result.get("tools", []))

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Call a tool on the MCP server."""
        params = {"name": tool_name, "arguments": arguments}
        return await self._send_request("tools/call", params)
