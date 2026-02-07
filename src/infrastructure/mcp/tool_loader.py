"""MCP Tool Loader.

Loads tools from MCP servers and converts them to AgentTool instances.
Replaces MCPTemporalToolLoader -- works with any MCP adapter backend.
"""

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional

from src.infrastructure.agent.tools.base import AgentTool
from src.infrastructure.mcp.tool_adapter import MCPToolAdapter

logger = logging.getLogger(__name__)


class MCPToolLoader:
    """MCP Tool Loader.

    Loads tools from MCP servers (via MCPRayAdapter or MCPLocalFallback)
    and provides them as AgentTool instances for use with the ReAct Agent.

    Replaces MCPTemporalToolLoader with identical interface.
    """

    def __init__(
        self,
        mcp_adapter: Any,
        tenant_id: str,
        permission_manager: Optional[Any] = None,
        health_check_timeout: float = 2.0,
    ):
        self.mcp_adapter = mcp_adapter
        self.tenant_id = tenant_id
        self.permission_manager = permission_manager
        self._cached_tools: Dict[str, AgentTool] = {}
        self._tools_loaded = False
        self._health_check_timeout = health_check_timeout

        self._last_health_check: float = 0.0
        self._health_check_cache_ttl: float = 30.0
        self._last_health_status: Optional[bool] = None

    async def check_health(
        self,
        timeout: Optional[float] = None,
        use_cache: bool = True,
    ) -> Dict[str, Any]:
        """Check if MCP servers are healthy."""
        now = time.time()
        timeout = timeout or self._health_check_timeout

        if use_cache and self._last_health_status is not None:
            cache_age = now - self._last_health_check
            if cache_age < self._health_check_cache_ttl:
                return {
                    "healthy": self._last_health_status,
                    "cached": True,
                    "cache_age_seconds": cache_age,
                }

        start_time = time.time()

        try:
            await asyncio.wait_for(
                self.mcp_adapter.list_all_tools(self.tenant_id),
                timeout=timeout,
            )

            latency_ms = (time.time() - start_time) * 1000
            self._last_health_status = True
            self._last_health_check = now

            return {"healthy": True, "cached": False, "latency_ms": latency_ms}

        except asyncio.TimeoutError:
            self._last_health_status = False
            self._last_health_check = now
            return {
                "healthy": False,
                "error": f"Health check timed out after {timeout}s",
                "cached": False,
                "latency_ms": (time.time() - start_time) * 1000,
            }
        except Exception as e:
            self._last_health_status = False
            self._last_health_check = now
            return {
                "healthy": False,
                "error": str(e),
                "cached": False,
                "latency_ms": (time.time() - start_time) * 1000,
            }

    async def load_all_tools(self, refresh: bool = False) -> Dict[str, AgentTool]:
        """Load tools from all connected MCP servers."""
        if self._tools_loaded and not refresh:
            return dict(self._cached_tools)

        tools: Dict[str, AgentTool] = {}

        try:
            all_tools = await self.mcp_adapter.list_all_tools(self.tenant_id)

            for tool_info in all_tools:
                try:
                    if hasattr(tool_info, "server_name"):
                        server_name = tool_info.server_name
                    else:
                        server_name = tool_info.get("server_name", "unknown")
                    adapter = MCPToolAdapter(
                        mcp_adapter=self.mcp_adapter,
                        server_name=server_name,
                        tool_info=tool_info,
                        tenant_id=self.tenant_id,
                        permission_manager=self.permission_manager,
                    )
                    tools[adapter.name] = adapter
                except Exception as e:
                    logger.error("Failed to create adapter for tool %s: %s", tool_info, e)

            logger.info("Total MCP tools loaded: %d", len(tools))

        except Exception as e:
            logger.error("Failed to load MCP tools: %s", e)

        self._cached_tools = tools
        self._tools_loaded = True
        return dict(tools)

    async def load_server_tools(self, server_name: str) -> Dict[str, AgentTool]:
        """Load tools from a specific MCP server."""
        tools: Dict[str, AgentTool] = {}

        try:
            tool_infos = await self.mcp_adapter.list_tools(
                tenant_id=self.tenant_id,
                server_name=server_name,
            )

            for tool_info in tool_infos:
                adapter = MCPToolAdapter(
                    mcp_adapter=self.mcp_adapter,
                    server_name=server_name,
                    tool_info=tool_info,
                    tenant_id=self.tenant_id,
                    permission_manager=self.permission_manager,
                )
                tools[adapter.name] = adapter

            logger.info("Loaded %d tools from MCP server '%s'", len(tools), server_name)

        except Exception as e:
            logger.error("Error loading tools from MCP server '%s': %s", server_name, e)
            raise

        return tools

    async def get_tool(self, tool_name: str) -> Optional[AgentTool]:
        """Get a specific MCP tool by name."""
        if not self._tools_loaded:
            await self.load_all_tools()
        return self._cached_tools.get(tool_name)

    async def get_tools_by_server(self, server_name: str) -> List[AgentTool]:
        """Get all tools from a specific MCP server."""
        if not self._tools_loaded:
            await self.load_all_tools()

        clean_server = server_name.replace("-", "_")
        prefix = f"mcp__{clean_server}__"
        return [tool for name, tool in self._cached_tools.items() if name.startswith(prefix)]

    def clear_cache(self) -> None:
        """Clear the cached tools."""
        self._cached_tools = {}
        self._tools_loaded = False

    async def refresh(self) -> Dict[str, AgentTool]:
        """Refresh all MCP tools."""
        self.clear_cache()
        return await self.load_all_tools()

    @property
    def is_loaded(self) -> bool:
        return self._tools_loaded

    @property
    def tool_count(self) -> int:
        return len(self._cached_tools)

    def list_tool_names(self) -> List[str]:
        return list(self._cached_tools.keys())

    def get_tool_info(self) -> List[Dict[str, Any]]:
        info = []
        for name, tool in self._cached_tools.items():
            if isinstance(tool, MCPToolAdapter):
                info.append({
                    "name": name,
                    "server": tool.server_name,
                    "original_name": tool.original_tool_name,
                    "description": tool.description,
                    "source": "mcp",
                })
            else:
                info.append({"name": name, "description": tool.description})
        return info


# Backward compatibility alias
MCPTemporalToolLoader = MCPToolLoader
