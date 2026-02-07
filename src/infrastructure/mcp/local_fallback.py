"""MCP Local Fallback.

In-process MCP client fallback when Ray is unavailable.
Reuses existing MCP client implementations with a simple in-memory registry.
"""

import asyncio
import logging
import shlex
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Lazy imports
MCPSubprocessClient = None
MCPHttpClient = None
MCPWebSocketClient = None


def _ensure_imports():
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


@dataclass
class MCPServerStatus:
    """Status of an MCP server."""

    server_name: str
    tenant_id: str
    connected: bool = False
    tool_count: int = 0
    server_info: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    workflow_id: Optional[str] = None


@dataclass
class MCPToolInfo:
    """Information about an MCP tool."""

    name: str
    server_name: str
    description: Optional[str] = None
    input_schema: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MCPToolCallResult:
    """Result from an MCP tool call."""

    content: List[Dict[str, Any]] = field(default_factory=list)
    is_error: bool = False
    error_message: Optional[str] = None


class MCPLocalFallback:
    """In-process MCP client fallback when Ray is unavailable.

    Provides the same public API as MCPRayAdapter / MCPTemporalAdapter.
    """

    def __init__(self) -> None:
        self._clients: Dict[str, Any] = {}  # key: "{tenant_id}:{server_name}"
        self._tools_cache: Dict[str, List[Dict[str, Any]]] = {}
        self._lock = asyncio.Lock()

    def _key(self, tenant_id: str, server_name: str) -> str:
        return f"{tenant_id}:{server_name}"

    async def start_mcp_server(
        self,
        tenant_id: str,
        server_name: str,
        transport_type: str = "local",
        command: Optional[List[str]] = None,
        environment: Optional[Dict[str, str]] = None,
        url: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: int = 30000,
        heartbeat_interval: int = 30,
        reconnect_attempts: int = 3,
    ) -> MCPServerStatus:
        """Start MCP server in-process."""
        _ensure_imports()
        key = self._key(tenant_id, server_name)
        timeout_seconds = timeout / 1000

        try:
            transport = transport_type.lower()
            if transport in ("local", "stdio"):
                if not command:
                    raise ValueError("Command is required for local MCP server")
                cmd = command
                if isinstance(cmd, str):
                    cmd = shlex.split(cmd)
                client = MCPSubprocessClient(
                    command=cmd[0],
                    args=cmd[1:] if len(cmd) > 1 else [],
                    env=environment,
                    timeout=timeout_seconds,
                )
            elif transport in ("http", "sse"):
                if not url:
                    raise ValueError("URL is required")
                client = MCPHttpClient(
                    url=url,
                    headers=headers,
                    timeout=timeout_seconds,
                    transport_type=transport,
                )
            elif transport == "websocket":
                if not url:
                    raise ValueError("WebSocket URL is required")
                client = MCPWebSocketClient(
                    url=url,
                    headers=headers,
                    timeout=timeout_seconds,
                    heartbeat_interval=heartbeat_interval,
                    reconnect_attempts=reconnect_attempts,
                )
            else:
                raise ValueError(f"Unsupported transport type: {transport}")

            connected = await client.connect(timeout=timeout_seconds)
            if not connected:
                return MCPServerStatus(
                    server_name=server_name,
                    tenant_id=tenant_id,
                    connected=False,
                    error="Failed to connect",
                )

            tools = client.get_cached_tools()
            tools_data = [
                {"name": t.name, "description": t.description, "inputSchema": t.inputSchema}
                for t in tools
            ]

            async with self._lock:
                self._clients[key] = client
                self._tools_cache[key] = tools_data

            return MCPServerStatus(
                server_name=server_name,
                tenant_id=tenant_id,
                connected=True,
                tool_count=len(tools_data),
                server_info=client.server_info,
            )

        except Exception as e:
            logger.exception("Error starting local MCP server: %s", e)
            return MCPServerStatus(
                server_name=server_name,
                tenant_id=tenant_id,
                connected=False,
                error=str(e),
            )

    async def stop_mcp_server(
        self,
        tenant_id: str,
        server_name: str,
    ) -> bool:
        """Stop in-process MCP server."""
        key = self._key(tenant_id, server_name)
        async with self._lock:
            client = self._clients.pop(key, None)
            self._tools_cache.pop(key, None)

        if client:
            try:
                await client.disconnect()
            except Exception as e:
                logger.warning("Error stopping local MCP server: %s", e)
            return True
        return False

    async def call_mcp_tool(
        self,
        tenant_id: str,
        server_name: str,
        tool_name: str,
        arguments: Optional[Dict[str, Any]] = None,
        timeout: Optional[int] = None,
    ) -> MCPToolCallResult:
        """Call tool directly on in-process client.

        If the server is not running, attempts to lazy-start it from DB config.
        """
        key = self._key(tenant_id, server_name)
        client = self._clients.get(key)

        # Lazy-start server if not running
        if not client:
            started = await self._lazy_start_server(tenant_id, server_name)
            if started:
                client = self._clients.get(key)

        if not client:
            return MCPToolCallResult(
                is_error=True,
                error_message=f"MCP server '{server_name}' not found",
            )

        if not client.is_connected:
            return MCPToolCallResult(
                is_error=True,
                error_message=f"MCP server '{server_name}' disconnected",
            )

        timeout_seconds = (timeout or 30000) / 1000
        try:
            result = await client.call_tool(tool_name, arguments or {}, timeout=timeout_seconds)
            return MCPToolCallResult(
                content=result.content,
                is_error=result.isError,
                error_message=None if not result.isError else "Tool returned error",
            )
        except Exception as e:
            return MCPToolCallResult(
                is_error=True,
                error_message=str(e),
            )

    async def _lazy_start_server(self, tenant_id: str, server_name: str) -> bool:
        """Lazy-start an MCP server from DB config when tool is called."""
        try:
            from src.infrastructure.adapters.secondary.persistence.database import (
                async_session_factory,
            )
            from src.infrastructure.adapters.secondary.persistence.sql_mcp_server_repository import (
                SqlMCPServerRepository,
            )

            async with async_session_factory() as session:
                repo = SqlMCPServerRepository(session)
                server = await repo.get_by_name(tenant_id, server_name)

            if not server or not server.get("enabled"):
                return False

            transport_config = server.get("transport_config", {})
            command_str = transport_config.get("command")
            args = transport_config.get("args", [])
            full_command = [command_str] + args if command_str else None

            logger.info("Lazy-starting MCP server '%s' for tool call", server_name)
            await self.start_mcp_server(
                tenant_id=tenant_id,
                server_name=server_name,
                transport_type=server.get("server_type", "local"),
                command=full_command,
                environment=transport_config.get("environment")
                or transport_config.get("env"),
                url=transport_config.get("url"),
                headers=transport_config.get("headers"),
                timeout=transport_config.get("timeout", 30000),
            )
            return True

        except Exception as e:
            logger.warning("Failed to lazy-start MCP server '%s': %s", server_name, e)
            return False

    async def list_tools(
        self,
        tenant_id: str,
        server_name: str,
    ) -> List[MCPToolInfo]:
        """List tools from a specific server."""
        key = self._key(tenant_id, server_name)
        tools = self._tools_cache.get(key, [])
        return [
            MCPToolInfo(
                name=f"mcp__{server_name}__{t.get('name', '')}",
                server_name=server_name,
                description=t.get("description"),
                input_schema=t.get("inputSchema", {}),
            )
            for t in tools
        ]

    async def list_all_tools(
        self,
        tenant_id: str,
    ) -> List[MCPToolInfo]:
        """List all tools from all servers for a tenant.

        Uses a two-tier strategy:
        1. Return tools from running in-memory MCP servers
        2. If no running servers, read discovered_tools directly from DB
           (no subprocess startup required)
        """
        prefix = f"{tenant_id}:"
        has_servers = any(k.startswith(prefix) for k in self._clients)

        # Tier 1: Collect tools from running servers
        all_tools: List[MCPToolInfo] = []
        if has_servers:
            for key, tools in self._tools_cache.items():
                if key.startswith(prefix):
                    server_name = key[len(prefix):]
                    for t in tools:
                        all_tools.append(
                            MCPToolInfo(
                                name=f"mcp__{server_name}__{t.get('name', '')}",
                                server_name=server_name,
                                description=t.get("description"),
                                input_schema=t.get("inputSchema", {}),
                            )
                        )

        # Tier 2: If no running servers, read from DB discovered_tools
        if not all_tools:
            db_tools = await self._load_tools_from_db(tenant_id)
            if db_tools:
                all_tools = db_tools

        return all_tools

    async def _load_tools_from_db(self, tenant_id: str) -> List[MCPToolInfo]:
        """Load tool definitions directly from DB discovered_tools.

        This reads the tool schemas that were stored during frontend sync,
        without requiring the MCP server subprocess to be running.
        Tools loaded this way can still be called via lazy server startup.
        """
        try:
            from src.infrastructure.adapters.secondary.persistence.database import (
                async_session_factory,
            )
            from src.infrastructure.adapters.secondary.persistence.sql_mcp_server_repository import (
                SqlMCPServerRepository,
            )

            async with async_session_factory() as session:
                repo = SqlMCPServerRepository(session)
                servers = await repo.list_by_tenant(tenant_id, enabled_only=True)

            if not servers:
                return []

            tools: List[MCPToolInfo] = []
            for server in servers:
                name = server["name"]
                clean_name = name.replace("-", "_")
                discovered = server.get("discovered_tools") or []
                for t in discovered:
                    tool_name = t.get("name", "")
                    tools.append(
                        MCPToolInfo(
                            name=f"mcp__{clean_name}__{tool_name}",
                            server_name=name,
                            description=t.get("description"),
                            input_schema=t.get("inputSchema", {}),
                        )
                    )

            if tools:
                logger.info(
                    "Loaded %d MCP tools from DB for tenant %s (%d servers)",
                    len(tools),
                    tenant_id,
                    len(servers),
                )
            return tools

        except Exception as e:
            logger.warning("Failed to load MCP tools from DB for tenant %s: %s", tenant_id, e)
            return []

    async def _auto_discover_from_db(self, tenant_id: str) -> None:
        """Auto-discover enabled MCP servers from database and start them."""
        try:
            from src.infrastructure.adapters.secondary.persistence.database import (
                async_session_factory,
            )
            from src.infrastructure.adapters.secondary.persistence.sql_mcp_server_repository import (
                SqlMCPServerRepository,
            )

            async with async_session_factory() as session:
                repo = SqlMCPServerRepository(session)
                servers = await repo.list_by_tenant(tenant_id, enabled_only=True)

            if not servers:
                return

            logger.info(
                "Auto-discovering %d enabled MCP servers for tenant %s",
                len(servers),
                tenant_id,
            )

            for server in servers:
                name = server["name"]
                key = self._key(tenant_id, name)
                if key in self._clients:
                    continue

                transport_config = server.get("transport_config", {})
                command_str = transport_config.get("command")
                args = transport_config.get("args", [])
                full_command = [command_str] + args if command_str else None

                try:
                    await self.start_mcp_server(
                        tenant_id=tenant_id,
                        server_name=name,
                        transport_type=server.get("server_type", "local"),
                        command=full_command,
                        environment=transport_config.get("environment")
                        or transport_config.get("env"),
                        url=transport_config.get("url"),
                        headers=transport_config.get("headers"),
                        timeout=transport_config.get("timeout", 30000),
                    )
                except Exception as e:
                    logger.warning("Auto-discover: failed to start %s: %s", name, e)

        except Exception as e:
            logger.warning("Auto-discover from DB failed for tenant %s: %s", tenant_id, e)

    async def get_server_status(
        self,
        tenant_id: str,
        server_name: str,
    ) -> MCPServerStatus:
        """Get server status."""
        key = self._key(tenant_id, server_name)
        client = self._clients.get(key)
        if not client:
            return MCPServerStatus(
                server_name=server_name,
                tenant_id=tenant_id,
                connected=False,
            )
        return MCPServerStatus(
            server_name=server_name,
            tenant_id=tenant_id,
            connected=client.is_connected,
            tool_count=len(self._tools_cache.get(key, [])),
            server_info=client.server_info,
        )

    async def is_server_running(
        self,
        tenant_id: str,
        server_name: str,
    ) -> bool:
        """Check if an MCP server is running."""
        status = await self.get_server_status(tenant_id, server_name)
        return status.connected

    async def list_servers(
        self,
        tenant_id: str,
    ) -> List[MCPServerStatus]:
        """List all servers for a tenant."""
        prefix = f"{tenant_id}:"
        results: List[MCPServerStatus] = []
        for key, client in self._clients.items():
            if key.startswith(prefix):
                server_name = key[len(prefix) :]
                results.append(
                    MCPServerStatus(
                        server_name=server_name,
                        tenant_id=tenant_id,
                        connected=client.is_connected,
                        tool_count=len(self._tools_cache.get(key, [])),
                        server_info=client.server_info,
                    )
                )
        return results

    async def cleanup_all(self) -> None:
        """Cleanup all clients (for shutdown)."""
        async with self._lock:
            for key, client in list(self._clients.items()):
                try:
                    await client.disconnect()
                except Exception as e:
                    logger.warning("Error cleaning up client %s: %s", key, e)
            self._clients.clear()
            self._tools_cache.clear()
