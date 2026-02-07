"""Ray Actor managing a single MCP Server instance.

Replaces MCPServerWorkflow + Activities (Temporal).
Each actor manages one MCP server connection with auto-reconnect.
"""

from __future__ import annotations

import logging
import shlex
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Union

import ray

from src.infrastructure.agent.actor.types import MCPServerActorConfig

logger = logging.getLogger(__name__)

# Lazy imports to avoid import issues in Ray worker
MCPSubprocessClient = None
MCPHttpClient = None
MCPWebSocketClient = None

MCPClient = Union["MCPSubprocessClient", "MCPHttpClient", "MCPWebSocketClient"]


def _ensure_client_imports():
    """Lazy import MCP client classes."""
    global MCPSubprocessClient, MCPHttpClient, MCPWebSocketClient
    if MCPSubprocessClient is None:
        from src.infrastructure.adapters.secondary.temporal.mcp.http_client import (
            MCPHttpClient as _Http,
        )
        from src.infrastructure.adapters.secondary.temporal.mcp.subprocess_client import (
            MCPSubprocessClient as _Sub,
        )
        from src.infrastructure.adapters.secondary.temporal.mcp.websocket_client import (
            MCPWebSocketClient as _Ws,
        )
        MCPSubprocessClient = _Sub
        MCPHttpClient = _Http
        MCPWebSocketClient = _Ws


def _create_client(config: MCPServerActorConfig) -> Any:
    """Create the appropriate MCP client based on transport type."""
    _ensure_client_imports()

    transport_type = config.transport_type.lower()
    timeout_seconds = config.timeout / 1000

    if transport_type in ("local", "stdio"):
        command = config.command
        if not command:
            raise ValueError("Command is required for local MCP server")
        if isinstance(command, str):
            command = shlex.split(command)
        return MCPSubprocessClient(
            command=command[0],
            args=command[1:] if len(command) > 1 else [],
            env=config.environment,
            timeout=timeout_seconds,
        )
    elif transport_type in ("http", "sse"):
        if not config.url:
            raise ValueError("URL is required for remote MCP server")
        return MCPHttpClient(
            url=config.url,
            headers=config.headers,
            timeout=timeout_seconds,
            transport_type=transport_type,
        )
    elif transport_type == "websocket":
        if not config.url:
            raise ValueError("WebSocket URL is required")
        return MCPWebSocketClient(
            url=config.url,
            headers=config.headers,
            timeout=timeout_seconds,
            heartbeat_interval=config.heartbeat_interval,
            reconnect_attempts=config.reconnect_attempts,
        )
    else:
        raise ValueError(f"Unsupported transport type: {transport_type}")


@ray.remote(max_restarts=5, max_task_retries=3, max_concurrency=20)
class MCPServerActor:
    """Ray Actor managing a single MCP Server instance.

    Lifecycle: Created per MCP server, detached lifetime for persistence.
    Actor ID pattern: mcp:{tenant_id}:{server_name}
    """

    def __init__(self) -> None:
        self._client: Optional[Any] = None
        self._config: Optional[MCPServerActorConfig] = None
        self._tools: List[Dict[str, Any]] = []
        self._connected: bool = False
        self._created_at: datetime = datetime.utcnow()
        self._last_activity: datetime = datetime.utcnow()
        self._reconnect_attempts: int = 0
        self._max_reconnect_attempts: int = 3

    @staticmethod
    def actor_id(tenant_id: str, server_name: str) -> str:
        safe_tenant = tenant_id.replace("-", "_").replace(".", "_")
        safe_server = server_name.replace("-", "_").replace(".", "_")
        return f"mcp:{safe_tenant}:{safe_server}"

    async def start(self, config: MCPServerActorConfig) -> Dict[str, Any]:
        """Start MCP server and establish connection."""
        self._config = config
        self._max_reconnect_attempts = config.reconnect_attempts

        logger.info(
            "Starting MCP server: %s (tenant: %s, transport: %s)",
            config.server_name, config.tenant_id, config.transport_type,
        )

        try:
            self._client = _create_client(config)
            timeout_seconds = config.timeout / 1000
            connected = await self._client.connect(timeout=timeout_seconds)

            if not connected:
                await self._cleanup_client()
                return {
                    "server_name": config.server_name,
                    "status": "failed",
                    "error": "Failed to connect to MCP server",
                    "tools": [],
                    "server_info": None,
                }

            self._connected = True
            tools = self._client.get_cached_tools()
            self._tools = [
                {
                    "name": t.name,
                    "description": t.description,
                    "inputSchema": t.inputSchema,
                }
                for t in tools
            ]
            self._last_activity = datetime.utcnow()

            logger.info(
                "MCP server started: %s with %d tools",
                config.server_name, len(self._tools),
            )

            return {
                "server_name": config.server_name,
                "status": "connected",
                "tools": self._tools,
                "server_info": self._client.server_info,
                "error": None,
            }

        except Exception as e:
            logger.exception("Error starting MCP server: %s", e)
            await self._cleanup_client()
            return {
                "server_name": config.server_name,
                "status": "failed",
                "error": str(e),
                "tools": [],
                "server_info": None,
            }

    async def call_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Execute a tool call with auto-reconnect."""
        self._last_activity = datetime.utcnow()

        if not self._client or not self._connected:
            if not await self._try_reconnect():
                return {
                    "content": [{"type": "text", "text": "MCP server not connected"}],
                    "is_error": True,
                    "error_message": "MCP server not connected",
                }

        if not self._client.is_connected:
            if not await self._try_reconnect():
                return {
                    "content": [{"type": "text", "text": "MCP server disconnected"}],
                    "is_error": True,
                    "error_message": "MCP server disconnected",
                }

        timeout_seconds = (timeout or self._config.timeout) / 1000 if self._config else 30

        try:
            result = await self._client.call_tool(tool_name, arguments, timeout=timeout_seconds)
            self._reconnect_attempts = 0
            return {
                "content": result.content,
                "is_error": result.isError,
                "error_message": None if not result.isError else "Tool returned error",
            }
        except Exception as e:
            logger.error("Tool call failed: %s", e)
            return {
                "content": [{"type": "text", "text": f"Error: {e}"}],
                "is_error": True,
                "error_message": str(e),
            }

    async def list_tools(self) -> List[Dict[str, Any]]:
        """Return cached tool schemas."""
        return self._tools

    async def get_status(self) -> Dict[str, Any]:
        """Return current connection status."""
        is_connected = (
            self._connected
            and self._client is not None
            and self._client.is_connected
        )
        return {
            "connected": is_connected,
            "server_info": self._client.server_info if self._client else None,
            "tool_count": len(self._tools),
            "error": None,
            "created_at": self._created_at.isoformat(),
            "last_activity": self._last_activity.isoformat(),
        }

    async def stop(self) -> bool:
        """Gracefully disconnect and cleanup."""
        server_name = self._config.server_name if self._config else "unknown"
        logger.info("Stopping MCP server: %s", server_name)
        await self._cleanup_client()
        return True

    async def health_check(self) -> Dict[str, Any]:
        """Fast health check with auto-reconnect."""
        start = time.time()
        is_connected = (
            self._connected
            and self._client is not None
            and self._client.is_connected
        )

        if not is_connected and self._config:
            reconnected = await self._try_reconnect()
            return {
                "healthy": reconnected,
                "latency_ms": (time.time() - start) * 1000,
                "reconnected": reconnected,
            }

        return {
            "healthy": is_connected,
            "latency_ms": (time.time() - start) * 1000,
            "reconnected": False,
        }

    async def _try_reconnect(self) -> bool:
        """Attempt to reconnect to the MCP server."""
        if not self._config:
            return False

        if self._reconnect_attempts >= self._max_reconnect_attempts:
            logger.warning(
                "Max reconnect attempts reached for %s",
                self._config.server_name,
            )
            return False

        self._reconnect_attempts += 1
        logger.info(
            "Attempting reconnect %d/%d for %s",
            self._reconnect_attempts,
            self._max_reconnect_attempts,
            self._config.server_name,
        )

        await self._cleanup_client()

        try:
            self._client = _create_client(self._config)
            timeout_seconds = self._config.timeout / 1000
            connected = await self._client.connect(timeout=timeout_seconds)

            if connected:
                self._connected = True
                tools = self._client.get_cached_tools()
                self._tools = [
                    {
                        "name": t.name,
                        "description": t.description,
                        "inputSchema": t.inputSchema,
                    }
                    for t in tools
                ]
                self._reconnect_attempts = 0
                logger.info("Reconnected to MCP server: %s", self._config.server_name)
                return True

            await self._cleanup_client()
            return False
        except Exception as e:
            logger.error("Reconnect failed for %s: %s", self._config.server_name, e)
            await self._cleanup_client()
            return False

    async def _cleanup_client(self) -> None:
        """Cleanup the current client."""
        self._connected = False
        if self._client:
            try:
                await self._client.disconnect()
            except Exception as e:
                logger.warning("Error disconnecting client: %s", e)
            self._client = None
