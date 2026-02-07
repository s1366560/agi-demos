"""MCP Ray Adapter.

API-side adapter for MCP operations via Ray Actors.
Replaces MCPTemporalAdapter with the same public interface.
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import ray

from src.configuration.ray_config import get_ray_settings
from src.infrastructure.adapters.secondary.ray.client import await_ray
from src.infrastructure.agent.actor.mcp_manager_actor import MCPManagerActor
from src.infrastructure.agent.actor.types import MCPServerActorConfig

logger = logging.getLogger(__name__)


@dataclass
class MCPServerStatus:
    """Status of an MCP server (matches MCPTemporalAdapter.MCPServerStatus)."""

    server_name: str
    tenant_id: str
    connected: bool = False
    tool_count: int = 0
    server_info: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    workflow_id: Optional[str] = None  # Kept for backward compatibility


@dataclass
class MCPToolInfo:
    """Information about an MCP tool (matches MCPTemporalAdapter.MCPToolInfo)."""

    name: str
    server_name: str
    description: Optional[str] = None
    input_schema: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MCPToolCallResult:
    """Result from an MCP tool call (matches Temporal MCPToolCallResult)."""

    content: List[Dict[str, Any]] = field(default_factory=list)
    is_error: bool = False
    error_message: Optional[str] = None


class MCPRayAdapter:
    """API-side adapter for MCP operations via Ray Actors.

    Replaces MCPTemporalAdapter with the same public interface,
    enabling seamless migration from Temporal to Ray.
    """

    def __init__(self) -> None:
        self._manager_cache: Dict[str, Any] = {}  # tenant_id -> actor handle
        self._local_fallback: Optional[Any] = None  # MCPLocalFallback for Ray failure

    async def _get_manager(self, tenant_id: str) -> Any:
        """Get or create MCPManagerActor for a tenant."""
        if tenant_id in self._manager_cache:
            return self._manager_cache[tenant_id]

        settings = get_ray_settings()
        manager_id = MCPManagerActor.actor_id(tenant_id)

        try:
            actor = ray.get_actor(manager_id, namespace=settings.ray_namespace)
        except ValueError:
            actor = MCPManagerActor.options(
                name=manager_id,
                namespace=settings.ray_namespace,
                lifetime="detached",
            ).remote()
            await await_ray(actor.initialize.remote(tenant_id))

        self._manager_cache[tenant_id] = actor
        return actor

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
        """Start an MCP server via Ray Actor."""
        config = MCPServerActorConfig(
            server_name=server_name,
            tenant_id=tenant_id,
            transport_type=transport_type,
            command=command,
            environment=environment,
            url=url,
            headers=headers,
            timeout=timeout,
            heartbeat_interval=heartbeat_interval,
            reconnect_attempts=reconnect_attempts,
        )

        logger.info("Starting MCP server via Ray: %s", server_name)

        try:
            manager = await self._get_manager(tenant_id)
            result = await await_ray(manager.start_server.remote(config))

            return MCPServerStatus(
                server_name=server_name,
                tenant_id=tenant_id,
                connected=result.get("status") == "connected",
                tool_count=len(result.get("tools", [])),
                server_info=result.get("server_info"),
                error=result.get("error"),
            )

        except Exception as e:
            logger.exception("Error starting MCP server: %s", e)
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
        """Stop an MCP server."""
        try:
            manager = await self._get_manager(tenant_id)
            return await await_ray(manager.stop_server.remote(server_name))
        except Exception as e:
            logger.exception("Error stopping MCP server: %s", e)
            return False

    async def call_mcp_tool(
        self,
        tenant_id: str,
        server_name: str,
        tool_name: str,
        arguments: Optional[Dict[str, Any]] = None,
        timeout: Optional[int] = None,
    ) -> MCPToolCallResult:
        """Call a tool on an MCP server.

        If the server is not running, attempts to lazy-start it from DB config.
        If Ray is unavailable, falls back to local MCP client execution.
        """
        try:
            manager = await self._get_manager(tenant_id)
            result = await await_ray(
                manager.call_tool.remote(
                    server_name,
                    tool_name,
                    arguments or {},
                    timeout,
                )
            )

            # If server not found, try lazy-starting from DB
            if result.get("is_error") and "not found" in result.get("error_message", ""):
                started = await self._lazy_start_server(tenant_id, server_name)
                if started:
                    result = await await_ray(
                        manager.call_tool.remote(
                            server_name,
                            tool_name,
                            arguments or {},
                            timeout,
                        )
                    )

            return MCPToolCallResult(
                content=result.get("content", []),
                is_error=result.get("is_error", False),
                error_message=result.get("error_message"),
            )

        except Exception as e:
            # Ray failure — fall back to local MCP client
            logger.warning("Ray MCP call failed, falling back to local: %s", e)
            return await self._call_tool_local(
                tenant_id, server_name, tool_name, arguments, timeout
            )

    async def _call_tool_local(
        self,
        tenant_id: str,
        server_name: str,
        tool_name: str,
        arguments: Optional[Dict[str, Any]] = None,
        timeout: Optional[int] = None,
    ) -> MCPToolCallResult:
        """Call MCP tool via local in-process client (Ray fallback)."""
        try:
            if not self._local_fallback:
                from src.infrastructure.mcp.local_fallback import MCPLocalFallback

                self._local_fallback = MCPLocalFallback()

            result = await self._local_fallback.call_mcp_tool(
                tenant_id=tenant_id,
                server_name=server_name,
                tool_name=tool_name,
                arguments=arguments,
                timeout=timeout,
            )
            return MCPToolCallResult(
                content=result.content,
                is_error=result.is_error,
                error_message=result.error_message,
            )
        except Exception as fallback_err:
            logger.error("Local MCP fallback also failed: %s", fallback_err)
            return MCPToolCallResult(
                is_error=True,
                error_message=str(fallback_err),
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
            status = await self.start_mcp_server(
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
            return status.connected

        except Exception as e:
            logger.warning("Failed to lazy-start MCP server '%s': %s", server_name, e)
            return False

    async def list_tools(
        self,
        tenant_id: str,
        server_name: str,
    ) -> List[MCPToolInfo]:
        """List tools from a specific server."""
        try:
            manager = await self._get_manager(tenant_id)
            tools = await await_ray(manager.list_tools.remote(server_name))

            return [
                MCPToolInfo(
                    name=f"mcp__{server_name}__{tool.get('name', '')}",
                    server_name=server_name,
                    description=tool.get("description"),
                    input_schema=tool.get("inputSchema", {}),
                )
                for tool in tools
            ]

        except Exception as e:
            logger.exception("Error listing MCP tools: %s", e)
            return []

    async def list_all_tools(
        self,
        tenant_id: str,
    ) -> List[MCPToolInfo]:
        """List all tools from all servers for a tenant.

        Uses a two-tier strategy:
        1. Query running Ray MCPManagerActor for tools from active servers
        2. If no tools from running servers, read discovered_tools from DB
        """
        try:
            manager = await self._get_manager(tenant_id)
            tools = await await_ray(manager.list_all_tools.remote())

            if tools:
                return [
                    MCPToolInfo(
                        name=f"mcp__{tool.get('_server_name', 'unknown')}__{tool.get('name', '')}",
                        server_name=tool.get("_server_name", "unknown"),
                        description=tool.get("description"),
                        input_schema=tool.get("inputSchema", {}),
                    )
                    for tool in tools
                ]

            # No running servers — read from DB discovered_tools
            db_tools = await self._load_tools_from_db(tenant_id)
            if db_tools:
                return db_tools

            return []

        except Exception as e:
            logger.exception("Error listing all MCP tools: %s", e)
            # Fallback to DB on Ray failure
            try:
                return await self._load_tools_from_db(tenant_id)
            except Exception:
                return []

    async def _load_tools_from_db(self, tenant_id: str) -> List[MCPToolInfo]:
        """Load tool definitions directly from DB discovered_tools.

        Reads tool schemas stored during frontend sync without starting
        MCP server subprocesses. Tools can still be called via lazy startup.
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

    async def _auto_discover_from_db(self, tenant_id: str) -> bool:
        """Auto-discover enabled MCP servers from database and start them.

        Returns True if any servers were discovered and started.
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
                return False

            logger.info(
                "Auto-discovering %d enabled MCP servers for tenant %s",
                len(servers),
                tenant_id,
            )

            started_any = False
            for server in servers:
                transport_config = server.get("transport_config", {})
                command_str = transport_config.get("command")
                args = transport_config.get("args", [])
                full_command = [command_str] + args if command_str else None

                try:
                    status = await self.start_mcp_server(
                        tenant_id=tenant_id,
                        server_name=server["name"],
                        transport_type=server.get("server_type", "local"),
                        command=full_command,
                        environment=transport_config.get("environment")
                        or transport_config.get("env"),
                        url=transport_config.get("url"),
                        headers=transport_config.get("headers"),
                        timeout=transport_config.get("timeout", 30000),
                    )
                    if status.connected:
                        started_any = True
                except Exception as e:
                    logger.warning("Auto-discover: failed to start %s: %s", server["name"], e)

            return started_any

        except Exception as e:
            logger.warning("Auto-discover from DB failed for tenant %s: %s", tenant_id, e)
            return False

    async def get_server_status(
        self,
        tenant_id: str,
        server_name: str,
    ) -> MCPServerStatus:
        """Get server status."""
        try:
            manager = await self._get_manager(tenant_id)
            status = await await_ray(manager.get_server_status.remote(server_name))

            return MCPServerStatus(
                server_name=server_name,
                tenant_id=tenant_id,
                connected=status.get("connected", False),
                tool_count=status.get("tool_count", 0),
                server_info=status.get("server_info"),
                error=status.get("error"),
            )

        except Exception as e:
            error_str = str(e)
            if "no poller seen" in error_str or "not found" in error_str.lower():
                logger.debug("MCP server '%s' not ready: %s", server_name, e)
            else:
                logger.warning("Error querying MCP server '%s' status: %s", server_name, e)
            return MCPServerStatus(
                server_name=server_name,
                tenant_id=tenant_id,
                connected=False,
                error=None,
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
        """List all MCP servers for a tenant."""
        try:
            manager = await self._get_manager(tenant_id)
            servers = await await_ray(manager.list_servers.remote())

            return [
                MCPServerStatus(
                    server_name=s.get("server_name", ""),
                    tenant_id=tenant_id,
                    connected=s.get("connected", False),
                    tool_count=s.get("tool_count", 0),
                    server_info=s.get("server_info"),
                    error=s.get("error"),
                )
                for s in servers
            ]

        except Exception as e:
            logger.exception("Error listing MCP servers: %s", e)
            return []
