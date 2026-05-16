"""
SSE/streamable HTTP transport for MCP.

Uses the official MCP SDK streamable HTTP client so servers registered as
``sse`` use the same transport family that the API and frontend already allow.
"""

import asyncio
import contextlib
import logging
from contextlib import AsyncExitStack
from typing import Any, cast, override

import httpx

from src.domain.model.mcp.transport import TransportConfig, TransportType
from src.infrastructure.mcp._security import tls_verify_default
from src.infrastructure.mcp.transport.base import (
    BaseTransport,
    MCPTransportClosedError,
    MCPTransportError,
)

logger = logging.getLogger(__name__)


class SSETransport(BaseTransport):
    """MCP transport using streamable HTTP/SSE via the MCP SDK."""

    def __init__(self, config: TransportConfig | None = None) -> None:
        """Initialize SSE transport."""
        super().__init__(config)
        self._exit_stack: AsyncExitStack | None = None
        self._http_client: httpx.AsyncClient | None = None
        self._read_stream: Any | None = None
        self._write_stream: Any | None = None
        self._pending_requests: dict[int, asyncio.Future[Any]] = {}
        self._reader_task: asyncio.Task[None] | None = None
        self._initialized = False

    @override
    async def start(self, config: TransportConfig) -> None:
        """
        Establish streamable HTTP/SSE connection to an MCP server.

        Args:
            config: Transport configuration with URL and optional headers.
        """
        if self._is_open:
            logger.debug("SSE transport already started")
            return

        self._config = config

        if config.transport_type != TransportType.SSE:
            raise MCPTransportError(f"Invalid transport type for SSE: {config.transport_type}")

        if not config.url:
            raise MCPTransportError("URL is required for SSE transport")

        from mcp.client.streamable_http import streamable_http_client

        timeout = config.timeout_seconds if config.timeout else 30.0
        self._exit_stack = AsyncExitStack()
        _ = await self._exit_stack.__aenter__()

        try:
            http_client = httpx.AsyncClient(
                headers=config.headers or {},
                timeout=httpx.Timeout(timeout, connect=min(timeout, 10.0)),
                verify=tls_verify_default(),
            )
            self._http_client = await self._exit_stack.enter_async_context(http_client)

            streams = await self._exit_stack.enter_async_context(
                streamable_http_client(config.url, http_client=self._http_client)
            )
            self._read_stream, self._write_stream, _ = streams

            self._is_open = True
            self._reader_task = asyncio.create_task(self._read_messages())
            await self._initialize()

            logger.info(f"SSE transport connected to: {config.url}")
        except Exception as exc:
            await self._cleanup()
            raise MCPTransportError(f"SSE connection failed: {exc}") from exc

    async def _initialize(self) -> None:
        """Perform MCP protocol initialization handshake."""
        if self._initialized:
            return

        init_params: dict[str, Any] = {
            "protocolVersion": "2026-01-26",
            "capabilities": {
                "roots": {"listChanged": True},
                "extensions": {
                    "io.modelcontextprotocol/ui": {
                        "mimeTypes": ["text/html;profile=mcp-app"],
                        "hostCapabilities": {
                            "openLinks": True,
                            "serverTools": True,
                            "serverResources": True,
                            "logging": True,
                            "sandbox": True,
                        },
                    },
                },
            },
            "clientInfo": {"name": "MemStack", "version": "0.2.0"},
        }

        result = await self.send_request("initialize", init_params)
        if result is None:  # pyright: ignore[reportUnnecessaryComparison]
            raise MCPTransportError("Initialization failed: no response from server")

        await self._send_notification("notifications/initialized", {})
        self._initialized = True

    async def _send_notification(self, method: str, params: dict[str, Any]) -> None:
        """Send a JSON-RPC notification over the streamable HTTP write stream."""
        if not self._write_stream:
            raise MCPTransportClosedError("SSE transport not connected")

        from mcp.shared.message import SessionMessage
        from mcp.types import JSONRPCMessage, JSONRPCNotification

        notification = JSONRPCNotification(
            jsonrpc="2.0",
            method=method,
            params=params,
        )
        await self._write_stream.send(SessionMessage(message=JSONRPCMessage(root=notification)))

    async def _read_messages(self) -> None:
        """Read streamable HTTP messages and resolve pending request futures."""
        try:
            async for message in self._read_stream:  # type: ignore[union-attr]
                if isinstance(message, Exception):
                    logger.error(f"Received exception from MCP server: {message}")
                    self._fail_pending(message)
                    continue

                msg = message.message.root if hasattr(message.message, "root") else message.message
                request_id = getattr(msg, "id", None)
                if request_id is None or request_id not in self._pending_requests:
                    continue

                future = self._pending_requests.pop(request_id)
                error = getattr(msg, "error", None)
                if error:
                    future.set_exception(MCPTransportError(f"MCP server error: {error}"))
                elif hasattr(msg, "result"):
                    future.set_result(msg.result)
                else:
                    future.set_result({})
        except asyncio.CancelledError:
            logger.debug("SSE receive loop cancelled")
        except Exception as exc:
            logger.error(f"Error in SSE receive loop: {exc}", exc_info=True)
            self._fail_pending(exc)

    def _fail_pending(self, exc: BaseException) -> None:
        """Fail all currently pending request futures."""
        for future in self._pending_requests.values():
            if not future.done():
                future.set_exception(exc)
        self._pending_requests.clear()

    @override
    async def stop(self) -> None:
        """Close streamable HTTP/SSE connection."""
        if not self._is_open and self._exit_stack is None:
            return

        self._is_open = False
        self._initialized = False
        await self._cleanup()
        logger.info("SSE transport stopped")

    async def _cleanup(self) -> None:
        """Clean up stream, HTTP client, and pending request resources."""
        if self._reader_task and not self._reader_task.done():
            _ = self._reader_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._reader_task
            self._reader_task = None

        if self._exit_stack:
            _ = await self._exit_stack.__aexit__(None, None, None)
            self._exit_stack = None

        self._http_client = None
        self._read_stream = None
        self._write_stream = None
        self._fail_pending(MCPTransportClosedError("SSE transport closed"))

    async def send_request(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Send a JSON-RPC request over streamable HTTP/SSE."""
        if not self._write_stream:
            raise MCPTransportClosedError("SSE transport not connected")

        from mcp.shared.message import SessionMessage
        from mcp.types import JSONRPCMessage, JSONRPCRequest

        request_id = self._next_request_id()
        future: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        self._pending_requests[request_id] = future

        request = JSONRPCRequest(
            jsonrpc="2.0",
            id=request_id,
            method=method,
            params=params or {},
        )

        try:
            await self._write_stream.send(SessionMessage(message=JSONRPCMessage(root=request)))
            wait_timeout = timeout or (self.config.timeout_seconds if self.config else 30.0)
            result = await asyncio.wait_for(future, timeout=wait_timeout)

            if hasattr(result, "model_dump"):
                return cast(dict[str, Any], result.model_dump())
            if isinstance(result, dict):
                return cast(dict[str, Any], result)
            return {"result": result}
        except TimeoutError:
            _ = self._pending_requests.pop(request_id, None)
            raise MCPTransportError(f"Timeout waiting for response to {method}") from None
        except Exception:
            _ = self._pending_requests.pop(request_id, None)
            raise

    @override
    async def cancel_request(self, request_id: int) -> None:
        """Send a cancellation notification for an in-flight SSE request."""
        try:
            await self._send_notification(
                "notifications/cancelled",
                {"requestId": request_id, "reason": "Client cancelled"},
            )
        except MCPTransportClosedError:
            logger.debug(f"Cannot cancel request {request_id}: transport closed")

    async def list_tools(self) -> list[dict[str, Any]]:
        """List all available tools from the MCP server."""
        result = await self.send_request("tools/list")
        tools = result.get("tools", [])
        return cast(
            list[dict[str, Any]],
            [tool.model_dump() if hasattr(tool, "model_dump") else tool for tool in tools],
        )

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Call a tool on the MCP server."""
        params = {"name": tool_name, "arguments": arguments}
        return await self.send_request("tools/call", params)

    async def list_prompts(self) -> list[dict[str, Any]]:
        """List available prompts from the MCP server."""
        result = await self.send_request("prompts/list")
        prompts = result.get("prompts", [])
        return cast(
            list[dict[str, Any]],
            [
                prompt.model_dump() if hasattr(prompt, "model_dump") else prompt
                for prompt in prompts
            ],
        )

    async def get_prompt(
        self,
        prompt_name: str,
        arguments: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Get a prompt from the MCP server."""
        params: dict[str, Any] = {"name": prompt_name}
        if arguments:
            params["arguments"] = arguments
        return await self.send_request("prompts/get", params)
