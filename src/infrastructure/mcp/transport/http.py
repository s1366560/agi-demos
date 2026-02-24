"""
HTTP transport for MCP.

Simple HTTP request/response transport for MCP servers.
"""

import logging
from typing import Any, cast

import httpx

from src.domain.model.mcp.transport import TransportConfig, TransportType
from src.infrastructure.mcp.transport.base import (
    BaseTransport,
    MCPTransportClosedError,
    MCPTransportError,
)

logger = logging.getLogger(__name__)


class HTTPTransport(BaseTransport):
    """
    MCP transport using HTTP request/response.

    Each request is a synchronous HTTP POST with JSON-RPC payload.
    Simple but lacks streaming and bidirectional communication.
    """

    def __init__(self, config: TransportConfig | None = None) -> None:
        """Initialize HTTP transport."""
        super().__init__(config)
        self._client: httpx.AsyncClient | None = None

    async def start(self, config: TransportConfig) -> None:
        """
        Initialize HTTP client.

        Args:
            config: Transport configuration with URL and headers.
        """
        if self._is_open:
            logger.debug("HTTP transport already started")
            return

        self._config = config

        if config.transport_type != TransportType.HTTP:
            raise MCPTransportError(f"Invalid transport type for HTTP: {config.transport_type}")

        if not config.url:
            raise MCPTransportError("URL is required for HTTP transport")

        timeout = config.timeout_seconds if config.timeout else 30.0

        self._client = httpx.AsyncClient(
            base_url=config.url,
            headers=config.headers or {},
            timeout=timeout,
        )

        self._is_open = True
        logger.info(f"HTTP transport connected to: {config.url}")

    async def stop(self) -> None:
        """Close HTTP client."""
        if not self._is_open:
            return

        self._is_open = False

        if self._client:
            await self._client.aclose()
            self._client = None

        logger.info("HTTP transport stopped")

    async def send(
        self,
        message: dict[str, Any],
        timeout: float | None = None,
    ) -> None:
        """
        Send is combined with receive in HTTP transport.

        For standalone send, this is a no-op. Use send_request instead.
        """
        # HTTP transport doesn't have separate send; it's request/response

    async def receive(
        self,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """
        Receive is combined with send in HTTP transport.

        For standalone receive, this raises an error.
        """
        raise MCPTransportError(
            "HTTP transport doesn't support standalone receive; use send_request"
        )

    async def send_request(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """
        Send HTTP POST request with JSON-RPC payload.

        Args:
            method: MCP method name.
            params: Optional method parameters.
            timeout: Optional request timeout.

        Returns:
            Response result dict.

        Raises:
            MCPTransportClosedError: If not connected.
            MCPTransportError: If request fails.
        """
        if not self._client:
            raise MCPTransportClosedError("HTTP client not initialized")

        request_id = self._next_request_id()

        request = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params or {},
        }

        try:
            logger.debug(f"Sending HTTP request: {method}")
            response = await self._client.post("/rpc", json=request)
            response.raise_for_status()
            data = response.json()

            if "error" in data:
                raise MCPTransportError(f"MCP server error: {data['error']}")

            return cast(dict[str, Any], data.get("result", {}))

        except httpx.HTTPError as e:
            logger.error(f"HTTP request failed: {e}")
            raise MCPTransportError(f"HTTP request failed: {e}") from e

    # High-level API methods

    async def list_tools(self) -> list[dict[str, Any]]:
        """List all available tools from the MCP server."""
        result = await self.send_request("tools/list")
        return cast(list[dict[str, Any]], result.get("tools", []))

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Call a tool on the MCP server."""
        params = {"name": tool_name, "arguments": arguments}
        return await self.send_request("tools/call", params)
