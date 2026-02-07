"""Per-tenant MCP Server manager Ray Actor.

Manages multiple MCPServerActor instances for a single tenant.
Replaces MCPTemporalAdapter's server orchestration logic.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import ray

from src.configuration.ray_config import get_ray_settings
from src.infrastructure.adapters.secondary.ray.client import await_ray
from src.infrastructure.agent.actor.mcp_server_actor import MCPServerActor
from src.infrastructure.agent.actor.types import MCPServerActorConfig

logger = logging.getLogger(__name__)


@ray.remote(max_restarts=3, max_concurrency=10)
class MCPManagerActor:
    """Per-tenant MCP Server manager.

    Manages lifecycle of MCPServerActor instances for a tenant.
    Actor ID pattern: mcp-mgr:{tenant_id}
    """

    def __init__(self) -> None:
        self._servers: Dict[str, Any] = {}  # server_name -> actor handle
        self._tenant_id: Optional[str] = None
        self._created_at: datetime = datetime.utcnow()

    @staticmethod
    def actor_id(tenant_id: str) -> str:
        safe_tenant = tenant_id.replace("-", "_").replace(".", "_")
        return f"mcp-mgr:{safe_tenant}"

    async def initialize(self, tenant_id: str) -> None:
        """Initialize with tenant context."""
        self._tenant_id = tenant_id
        logger.info("MCPManagerActor initialized for tenant: %s", tenant_id)

    async def start_server(self, config: MCPServerActorConfig) -> Dict[str, Any]:
        """Create and start an MCPServerActor."""
        server_name = config.server_name
        settings = get_ray_settings()

        # Stop existing server if running
        if server_name in self._servers:
            await self._stop_server_actor(server_name)

        actor_id = MCPServerActor.actor_id(config.tenant_id, server_name)

        try:
            actor = MCPServerActor.options(
                name=actor_id,
                namespace=settings.ray_namespace,
                lifetime="detached",
            ).remote()

            result = await await_ray(actor.start.remote(config))
            if result.get("status") == "connected":
                self._servers[server_name] = actor
            else:
                # Cleanup failed actor
                try:
                    ray.kill(actor)
                except Exception:
                    pass

            return result

        except Exception as e:
            logger.exception("Error starting MCP server %s: %s", server_name, e)
            return {
                "server_name": server_name,
                "status": "failed",
                "error": str(e),
                "tools": [],
                "server_info": None,
            }

    async def stop_server(self, server_name: str) -> bool:
        """Stop and cleanup an MCPServerActor."""
        return await self._stop_server_actor(server_name)

    async def call_tool(
        self,
        server_name: str,
        tool_name: str,
        arguments: Dict[str, Any],
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Route tool call to the correct MCPServerActor."""
        actor = self._servers.get(server_name)
        if not actor:
            # Try to find existing actor in Ray
            actor = await self._find_existing_actor(server_name)
            if not actor:
                return {
                    "content": [{"type": "text", "text": f"MCP server '{server_name}' not found"}],
                    "is_error": True,
                    "error_message": f"MCP server '{server_name}' not found",
                }

        try:
            return await await_ray(actor.call_tool.remote(tool_name, arguments, timeout))
        except Exception as e:
            logger.error("Tool call failed on %s: %s", server_name, e)
            return {
                "content": [{"type": "text", "text": f"Error: {e}"}],
                "is_error": True,
                "error_message": str(e),
            }

    async def list_tools(self, server_name: str) -> List[Dict[str, Any]]:
        """List tools from a specific server."""
        actor = self._servers.get(server_name)
        if not actor:
            actor = await self._find_existing_actor(server_name)
            if not actor:
                return []

        try:
            return await await_ray(actor.list_tools.remote())
        except Exception as e:
            logger.error("Error listing tools from %s: %s", server_name, e)
            return []

    async def list_all_tools(self) -> List[Dict[str, Any]]:
        """Aggregate tools from all running servers."""
        all_tools: List[Dict[str, Any]] = []
        for server_name, actor in list(self._servers.items()):
            try:
                tools = await await_ray(actor.list_tools.remote())
                for tool in tools:
                    tool["_server_name"] = server_name
                all_tools.extend(tools)
            except Exception as e:
                logger.warning("Error listing tools from %s: %s", server_name, e)
        return all_tools

    async def list_servers(self) -> List[Dict[str, Any]]:
        """List all managed MCP servers with status."""
        results: List[Dict[str, Any]] = []
        for server_name, actor in list(self._servers.items()):
            try:
                status = await await_ray(actor.get_status.remote())
                status["server_name"] = server_name
                status["tenant_id"] = self._tenant_id
                results.append(status)
            except Exception as e:
                logger.warning("Error getting status for %s: %s", server_name, e)
                results.append({
                    "server_name": server_name,
                    "tenant_id": self._tenant_id,
                    "connected": False,
                    "error": str(e),
                })
        return results

    async def get_server_status(self, server_name: str) -> Dict[str, Any]:
        """Get status of a specific server."""
        actor = self._servers.get(server_name)
        if not actor:
            actor = await self._find_existing_actor(server_name)
            if not actor:
                return {
                    "server_name": server_name,
                    "tenant_id": self._tenant_id,
                    "connected": False,
                    "error": None,
                }

        try:
            status = await await_ray(actor.get_status.remote())
            status["server_name"] = server_name
            status["tenant_id"] = self._tenant_id
            return status
        except Exception as e:
            logger.warning("Error getting status for %s: %s", server_name, e)
            return {
                "server_name": server_name,
                "tenant_id": self._tenant_id,
                "connected": False,
                "error": str(e),
            }

    async def health_check_all(self) -> Dict[str, Any]:
        """Health check all managed servers."""
        results: Dict[str, Any] = {}
        for server_name, actor in list(self._servers.items()):
            try:
                results[server_name] = await await_ray(actor.health_check.remote())
            except Exception as e:
                results[server_name] = {"healthy": False, "error": str(e)}
        return results

    async def shutdown(self) -> bool:
        """Stop all servers and cleanup."""
        for server_name in list(self._servers.keys()):
            await self._stop_server_actor(server_name)
        return True

    async def _stop_server_actor(self, server_name: str) -> bool:
        """Stop a specific MCPServerActor."""
        actor = self._servers.pop(server_name, None)
        if not actor:
            return False

        try:
            await await_ray(actor.stop.remote())
        except Exception as e:
            logger.warning("Error stopping MCP server %s: %s", server_name, e)

        try:
            ray.kill(actor)
        except Exception:
            pass
        return True

    async def _find_existing_actor(self, server_name: str) -> Optional[Any]:
        """Try to find an existing MCPServerActor in the Ray cluster."""
        if not self._tenant_id:
            return None

        settings = get_ray_settings()
        actor_id = MCPServerActor.actor_id(self._tenant_id, server_name)

        try:
            actor = ray.get_actor(actor_id, namespace=settings.ray_namespace)
            self._servers[server_name] = actor
            return actor
        except ValueError:
            return None
        except Exception as e:
            logger.debug("Error finding actor %s: %s", actor_id, e)
            return None
