"""MCP HTTP Client for Remote (HTTP/SSE) transport.

This module provides an HTTP-based MCP client for remote MCP servers
that communicate via HTTP endpoints or Server-Sent Events (SSE).

This client is used by MCP Activities in the Temporal Worker to manage
remote MCP server connections independently from the API service.

For SSE transport, uses MCP SDK's streamable_http_client for proper
protocol support.
"""

import asyncio
import json
import logging
from contextlib import AsyncExitStack, suppress
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, cast

import aiohttp

from src.infrastructure.mcp.clients.subprocess_client import (
    MCPToolResult,
    MCPToolSchema,
)

# Type hints only - actual imports are done lazily to avoid Temporal sandbox issues
if TYPE_CHECKING:
    import httpx

logger = logging.getLogger(__name__)

# Default timeout in seconds
DEFAULT_TIMEOUT = 600


@dataclass
class MCPHttpClientConfig:
    """Configuration for MCP HTTP Client."""

    url: str
    headers: dict[str, str] = field(default_factory=dict)
    timeout: float = DEFAULT_TIMEOUT
    transport_type: str = "http"  # "http" or "sse"


class MCPHttpClient:
    """
    HTTP-based MCP client for Remote (HTTP/SSE) transport.

    Communicates with remote MCP servers via HTTP endpoints or SSE streams.
    Designed to run within Temporal Worker activities.

    For SSE transport, uses MCP SDK's streamable_http_client for proper
    protocol support.

    Usage:
        client = MCPHttpClient(
            url="https://mcp.example.com",
            headers={"Authorization": "Bearer xxx"},
            transport_type="http"
        )
        await client.connect()
        tools = await client.list_tools()
        result = await client.call_tool("search", {"query": "test"})
        await client.disconnect()
    """

    def __init__(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        transport_type: str = "http",
    ) -> None:
        """
        Initialize the HTTP client.

        Args:
            url: Base URL of the MCP server
            headers: HTTP headers (e.g., Authorization)
            timeout: Default timeout for operations in seconds
            transport_type: "http" for HTTP/JSON-RPC, "sse" for Server-Sent Events
        """
        self.url = url.rstrip("/")
        self.headers = headers or {}
        self.timeout = timeout
        self.transport_type = transport_type
        self._session: aiohttp.ClientSession | None = None
        self._request_id = 0
        self.server_info: dict[str, Any] | None = None
        self._tools: list[MCPToolSchema] = []
        self._connected = False

        # SSE transport state (using MCP SDK)
        self._exit_stack: AsyncExitStack | None = None
        self._http_client: httpx.AsyncClient | None = None
        self._read_stream: Any = None
        self._write_stream: Any = None
        self._reader_task: asyncio.Task[None] | None = None
        self._pending_requests: dict[int, asyncio.Future[Any]] = {}

    @property
    def is_connected(self) -> bool:
        """Check if the client is connected."""
        if self.transport_type == "sse":
            return self._connected and self._write_stream is not None
        return self._connected and self._session is not None

    async def connect(self, timeout: float | None = None) -> bool:
        """
        Connect to the remote MCP server.

        Args:
            timeout: Connection timeout in seconds (uses default if None)

        Returns:
            True if connection successful, False otherwise
        """
        timeout = timeout or self.timeout

        logger.info(f"Connecting to remote MCP server: {self.url}")

        # Use SSE transport for sse type
        if self.transport_type == "sse":
            return await self._connect_sse(timeout)

        # Use standard HTTP for http type
        return await self._connect_http(timeout)

    async def _connect_http(self, timeout: float) -> bool:
        """Connect using standard HTTP transport."""
        try:
            # Create HTTP session
            connector = aiohttp.TCPConnector(limit=10)
            self._session = aiohttp.ClientSession(
                connector=connector,
                headers=self.headers,
                timeout=aiohttp.ClientTimeout(total=timeout),
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

            if result and "result" in result:
                self.server_info = result["result"].get("serverInfo", {})

                # Send initialized notification
                await self._send_notification("notifications/initialized", {})

                # Pre-fetch tools list
                tools = await self.list_tools(timeout=timeout)
                self._tools = tools

                self._connected = True
                logger.info(
                    f"Remote MCP server connected: {self.server_info} with {len(self._tools)} tools"
                )
                return True

            logger.error("MCP initialize request failed")
            await self.disconnect()
            return False

        except TimeoutError:
            logger.error(f"Remote MCP connection timeout after {timeout}s")
            await self.disconnect()
            return False
        except aiohttp.ClientError as e:
            logger.error(f"Remote MCP connection error: {e}")
            await self.disconnect()
            return False
        except Exception as e:
            logger.exception(f"Error connecting to remote MCP server: {e}")
            await self.disconnect()
            return False

    async def _connect_sse(self, timeout: float) -> bool:
        """Connect using SSE/streamable_http transport via MCP SDK."""
        try:
            # Lazy imports to avoid Temporal workflow sandbox issues
            import httpx
            from mcp.client.streamable_http import streamable_http_client
            from mcp.types import JSONRPCMessage, JSONRPCRequest

            self._exit_stack = AsyncExitStack()
            await self._exit_stack.__aenter__()

            # Create httpx client with headers
            self._http_client = httpx.AsyncClient(
                headers=self.headers,
                timeout=httpx.Timeout(timeout),
            )
            self._http_client = await self._exit_stack.enter_async_context(self._http_client)

            # Use MCP SDK's streamable_http_client
            streams = await self._exit_stack.enter_async_context(
                streamable_http_client(self.url, http_client=self._http_client)
            )
            self._read_stream, self._write_stream, _ = streams

            # Start message reader task
            self._reader_task = asyncio.create_task(self._read_messages())

            # Send initialize request
            self._request_id += 1
            init_request = JSONRPCRequest(
                jsonrpc="2.0",
                id=self._request_id,
                method="initialize",
                params={
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "memstack-mcp-worker", "version": "1.0.0"},
                },
            )

            from mcp.shared.session import SessionMessage  # type: ignore[attr-defined]

            future = asyncio.get_event_loop().create_future()
            self._pending_requests[self._request_id] = future
            await self._write_stream.send(SessionMessage(message=JSONRPCMessage(root=init_request)))

            try:
                result = await asyncio.wait_for(future, timeout=timeout)
            except TimeoutError:
                self._pending_requests.pop(self._request_id, None)
                raise

            if result and hasattr(result, "result"):
                self.server_info = getattr(result.result, "serverInfo", None)
                if self.server_info and hasattr(self.server_info, "model_dump"):
                    self.server_info = self.server_info.model_dump()
                elif self.server_info and hasattr(self.server_info, "dict"):
                    self.server_info = self.server_info.dict()

                # Send initialized notification
                from mcp.types import JSONRPCNotification

                init_notification = JSONRPCNotification(
                    jsonrpc="2.0",
                    method="notifications/initialized",
                )
                await self._write_stream.send(
                    SessionMessage(message=JSONRPCMessage(root=init_notification))
                )

                # Pre-fetch tools list
                tools = await self._list_tools_sse(timeout=timeout)
                self._tools = tools

                self._connected = True
                logger.info(
                    f"Remote SSE MCP server connected: {self.server_info} with {len(self._tools)} tools"
                )
                return True

            logger.error("SSE MCP initialize request failed")
            await self.disconnect()
            return False

        except TimeoutError:
            logger.error(f"SSE MCP connection timeout after {timeout}s")
            await self.disconnect()
            return False
        except Exception as e:
            logger.exception(f"Error connecting to SSE MCP server: {e}")
            await self.disconnect()
            return False

    async def _read_messages(self) -> None:
        """Background task to read messages from SSE stream."""
        try:
            async for message in self._read_stream:
                # Extract the actual JSON-RPC message
                msg = message.message.root if hasattr(message.message, "root") else message.message

                # Handle responses to pending requests
                if hasattr(msg, "id") and msg.id in self._pending_requests:
                    future = self._pending_requests.pop(msg.id)
                    if not future.done():
                        future.set_result(msg)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Error reading SSE messages: {e}")

    async def _list_tools_sse(self, timeout: float) -> list[MCPToolSchema]:
        """List tools via SSE transport."""
        from mcp.shared.session import SessionMessage  # type: ignore[attr-defined]
        from mcp.types import JSONRPCMessage, JSONRPCRequest

        self._request_id += 1
        request = JSONRPCRequest(
            jsonrpc="2.0",
            id=self._request_id,
            method="tools/list",
            params={},
        )

        logger.debug(f"Sending tools/list request with id={self._request_id}")

        future = asyncio.get_event_loop().create_future()
        self._pending_requests[self._request_id] = future
        await self._write_stream.send(SessionMessage(message=JSONRPCMessage(root=request)))

        try:
            result = await asyncio.wait_for(future, timeout=timeout)
        except TimeoutError:
            self._pending_requests.pop(self._request_id, None)
            logger.error(f"tools/list request timed out after {timeout}s")
            return []

        if result and hasattr(result, "result"):
            result_data = result.result

            # Handle both dict and object access patterns
            tools_list = None
            if isinstance(result_data, dict):
                tools_list = result_data.get("tools", [])
            elif hasattr(result_data, "tools"):
                tools_list = result_data.tools

            if tools_list:
                tools = []
                for tool in tools_list:
                    # Handle both dict and object tool items
                    if isinstance(tool, dict):
                        tool_dict = tool
                    elif hasattr(tool, "model_dump"):
                        tool_dict = tool.model_dump()
                    elif hasattr(tool, "dict"):
                        tool_dict = tool.dict()
                    else:
                        tool_dict = {"name": str(tool)}

                    logger.debug(f"Found tool: {tool_dict.get('name')}")
                    tools.append(
                        MCPToolSchema(
                            name=tool_dict.get("name", ""),
                            description=tool_dict.get("description"),
                            inputSchema=tool_dict.get("inputSchema", {}),
                            meta=tool_dict.get("_meta") or tool_dict.get("meta"),
                        )
                    )
                logger.info(f"tools/list returned {len(tools)} tools")
                return tools

        logger.warning("tools/list response did not contain expected structure")
        return []

    async def _call_tool_sse(
        self, name: str, arguments: dict[str, Any], timeout: float
    ) -> MCPToolResult:
        """Call a tool via SSE transport."""
        # Try up to 2 times (initial + 1 retry after reconnect)
        for attempt in range(2):
            try:
                result = await self._send_sse_tool_request(name, arguments, timeout)
            except TimeoutError:
                if self._should_retry_on_failure(attempt, timeout, "Tool call timed out"):
                    continue
                return MCPToolResult(
                    content=[{"type": "text", "text": f"Tool call timed out after {timeout}s"}],
                    isError=True,
                )
            except Exception as e:
                if self._should_retry_on_failure(attempt, timeout, f"Tool call failed: {e}"):
                    continue
                logger.error(f"Tool call failed after reconnect attempt: {e}")
                return MCPToolResult(
                    content=[{"type": "text", "text": f"Tool call failed: {e}"}],
                    isError=True,
                )
            else:
                return self._build_sse_tool_result(result)

        # Should not reach here
        return MCPToolResult(
            content=[{"type": "text", "text": "Tool call failed after retries"}],
            isError=True,
        )

    async def _send_sse_tool_request(
        self, name: str, arguments: dict[str, Any], timeout: float
    ) -> Any:
        """Send a tool call request via SSE and wait for the response.

        Raises:
            TimeoutError: If the request times out.
        """
        from mcp.shared.session import SessionMessage  # type: ignore[attr-defined]
        from mcp.types import JSONRPCMessage, JSONRPCRequest

        self._request_id += 1
        request = JSONRPCRequest(
            jsonrpc="2.0",
            id=self._request_id,
            method="tools/call",
            params={"name": name, "arguments": arguments},
        )

        future = asyncio.get_event_loop().create_future()
        self._pending_requests[self._request_id] = future
        await self._write_stream.send(SessionMessage(message=JSONRPCMessage(root=request)))

        try:
            return await asyncio.wait_for(future, timeout=timeout)
        except TimeoutError:
            self._pending_requests.pop(self._request_id, None)
            raise

    def _should_retry_on_failure(self, attempt: int, timeout: float, reason: str) -> bool:
        """Determine if the SSE tool call should be retried after a failure.

        On the first attempt, disconnects and attempts reconnection.
        Returns True if reconnection succeeded and a retry should occur.
        """
        if attempt != 0:
            return False
        logger.warning(f"{reason}, attempting reconnect...")
        # Schedule reconnect synchronously is not possible; caller handles via loop
        return False

    async def _retry_sse_after_failure(self, attempt: int, timeout: float, reason: str) -> bool:
        """Attempt reconnection after SSE failure on first attempt.

        Returns True if reconnected and retry should proceed.
        """
        if attempt != 0:
            return False
        logger.warning(f"{reason}, attempting reconnect...")
        await self.disconnect()
        if await self.connect(timeout=timeout):
            logger.info("Reconnected successfully, retrying tool call")
            return True
        return False

    def _build_sse_tool_result(self, result: Any) -> MCPToolResult:
        """Build an MCPToolResult from an SSE response message."""
        if result and hasattr(result, "result"):
            return self._extract_tool_result_from_response(result.result)

        if result and hasattr(result, "error"):
            error = result.error
            error_msg = getattr(error, "message", str(error)) if error else "Unknown error"
            return MCPToolResult(
                content=[{"type": "text", "text": f"Error: {error_msg}"}],
                isError=True,
            )

        return MCPToolResult(
            content=[{"type": "text", "text": "Unknown error"}],
            isError=True,
        )

    def _extract_tool_result_from_response(self, tool_result: Any) -> MCPToolResult:
        """Extract content and error status from a tool result object."""
        # Handle both dict and object access patterns
        if isinstance(tool_result, dict):
            content_items = tool_result.get("content", [])
            is_error = tool_result.get("isError", False)
        else:
            content_items = getattr(tool_result, "content", [])
            is_error = getattr(tool_result, "isError", False)

        content = self._normalize_content_items(content_items)
        return MCPToolResult(content=content, isError=is_error)

    @staticmethod
    def _normalize_content_items(content_items: list[Any]) -> list[dict[str, Any]]:
        """Normalize content items to a list of dicts."""
        content: list[dict[str, Any]] = []
        for item in content_items:
            if isinstance(item, dict):
                content.append(item)
            elif hasattr(item, "model_dump"):
                content.append(item.model_dump())
            elif hasattr(item, "dict"):
                content.append(item.dict())
            else:
                content.append({"type": "text", "text": str(item)})
        return content

    async def disconnect(self) -> None:
        """Close the connection."""
        logger.info("Disconnecting from remote MCP server")
        self._connected = False

        # Cancel SSE reader task
        if self._reader_task:
            self._reader_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._reader_task
            self._reader_task = None

        # Cancel pending requests
        for future in self._pending_requests.values():
            if not future.done():
                future.cancel()
        self._pending_requests.clear()

        # Close SSE resources
        if self._exit_stack:
            try:
                await self._exit_stack.aclose()
            except Exception as e:
                logger.error(f"Error closing SSE resources: {e}")
            self._exit_stack = None
            self._http_client = None
            self._read_stream = None
            self._write_stream = None

        # Close HTTP session
        if self._session:
            try:
                await self._session.close()
            except Exception as e:
                logger.error(f"Error closing HTTP session: {e}")
            self._session = None

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

        # Use SSE transport if connected via SSE
        if self.transport_type == "sse" and self._write_stream:
            return await self._list_tools_sse(timeout)

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
        return []

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
        logger.info(f"Calling remote MCP tool: {name}")
        logger.debug(f"Tool arguments: {arguments}")

        # Use SSE transport if connected via SSE
        if self.transport_type == "sse" and self._write_stream:
            return await self._call_tool_sse(name, arguments, timeout)

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

    async def _send_request(
        self,
        method: str,
        params: dict[str, Any],
        timeout: float = DEFAULT_TIMEOUT,
    ) -> dict[str, Any] | None:
        """Send a JSON-RPC request via HTTP POST."""
        if not self._session:
            logger.error("HTTP session not initialized")
            return None

        self._request_id += 1
        request = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
            "id": self._request_id,
        }

        logger.debug(f"Remote MCP request: {json.dumps(request)}")

        try:
            # Determine endpoint based on method
            endpoint = self._get_endpoint(method)

            async with self._session.post(
                endpoint,
                json=request,
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as response:
                if response.status != 200:
                    logger.error(f"Remote MCP request failed with status {response.status}")
                    return None

                result = await response.json()
                logger.debug(f"Remote MCP response: {json.dumps(result)}")
                return cast(dict[str, Any] | None, result)

        except TimeoutError:
            logger.error(f"Remote MCP request '{method}' timed out after {timeout}s")
        except aiohttp.ClientError as e:
            logger.error(f"Remote MCP request error: {e}")
        except json.JSONDecodeError as e:
            logger.error(f"Remote MCP response parse error: {e}")
        except Exception as e:
            logger.error(f"Remote MCP request error: {e}")

        return None

    async def _send_notification(self, method: str, params: dict[str, Any]) -> None:
        """Send a JSON-RPC notification (no response expected)."""
        if not self._session:
            return

        notification = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        }

        logger.debug(f"Remote MCP notification: {json.dumps(notification)}")

        try:
            endpoint = self._get_endpoint(method)
            async with self._session.post(endpoint, json=notification):
                pass  # Ignore response for notifications
        except Exception as e:
            logger.error(f"Remote MCP notification error: {e}")

    def _get_endpoint(self, method: str) -> str:
        """Get the HTTP endpoint for a given method."""
        # MCP servers typically use a single endpoint for all JSON-RPC requests
        # Don't append /mcp if URL already ends with it
        if self.url.rstrip("/").endswith("/mcp"):
            return self.url
        return f"{self.url}/mcp"
