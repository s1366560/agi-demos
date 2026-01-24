"""
MCP Temporal Tool Loader.

Dynamically loads tools from Temporal MCP servers
and converts them to AgentTool instances.
"""

import logging
from typing import Any, Dict, List, Optional

from src.infrastructure.agent.tools.base import AgentTool
from src.infrastructure.mcp.temporal_tool_adapter import MCPTemporalToolAdapter

logger = logging.getLogger(__name__)


class MCPTemporalToolLoader:
    """
    MCP Temporal Tool Loader.

    Loads tools from Temporal MCP servers (managed via MCPTemporalAdapter)
    and provides them as AgentTool instances for use with the ReAct Agent.

    Features:
    - Automatic tool discovery from connected Temporal MCP servers
    - Tool caching with refresh capability
    - Permission manager integration
    - Error handling for individual server failures

    Usage:
        loader = MCPTemporalToolLoader(mcp_temporal_adapter, tenant_id)
        tools = await loader.load_all_tools()

        # Use with ReActAgent
        agent = ReActAgent(
            model="gpt-4",
            tools={**builtin_tools, **tools},
        )
    """

    def __init__(
        self,
        mcp_temporal_adapter: Any,  # MCPTemporalAdapter
        tenant_id: str,
        permission_manager: Optional[Any] = None,
    ):
        """
        Initialize MCP Temporal Tool Loader.

        Args:
            mcp_temporal_adapter: MCPTemporalAdapter instance for server management
            tenant_id: Tenant ID for filtering servers
            permission_manager: Optional permission manager for access control
        """
        self.mcp_temporal_adapter = mcp_temporal_adapter
        self.tenant_id = tenant_id
        self.permission_manager = permission_manager
        self._cached_tools: Dict[str, AgentTool] = {}
        self._tools_loaded = False

    async def load_all_tools(self, refresh: bool = False) -> Dict[str, AgentTool]:
        """
        Load tools from all connected Temporal MCP servers.

        Args:
            refresh: If True, refresh tools even if already cached

        Returns:
            Dictionary mapping tool names to AgentTool instances
        """
        if self._tools_loaded and not refresh:
            return dict(self._cached_tools)

        tools: Dict[str, AgentTool] = {}

        try:
            # Get all tools from all connected servers
            all_tools = await self.mcp_temporal_adapter.list_all_tools(self.tenant_id)

            for tool_info in all_tools:
                try:
                    # Handle both MCPToolInfo dataclass and dict
                    if hasattr(tool_info, "server_name"):
                        server_name = tool_info.server_name
                    else:
                        server_name = tool_info.get("server_name", "unknown")
                    adapter = MCPTemporalToolAdapter(
                        mcp_temporal_adapter=self.mcp_temporal_adapter,
                        server_name=server_name,
                        tool_info=tool_info,
                        tenant_id=self.tenant_id,
                        permission_manager=self.permission_manager,
                    )
                    tools[adapter.name] = adapter
                    logger.debug(f"Created Temporal MCP tool adapter: {adapter.name}")
                except Exception as e:
                    logger.error(f"Failed to create adapter for tool {tool_info}: {e}")

            logger.info(f"Total Temporal MCP tools loaded: {len(tools)}")

        except Exception as e:
            logger.error(f"Failed to load Temporal MCP tools: {e}")

        self._cached_tools = tools
        self._tools_loaded = True

        return dict(tools)

    async def load_server_tools(self, server_name: str) -> Dict[str, AgentTool]:
        """
        Load tools from a specific Temporal MCP server.

        Args:
            server_name: Name of the MCP server

        Returns:
            Dictionary mapping tool names to AgentTool instances
        """
        tools: Dict[str, AgentTool] = {}

        try:
            tool_infos = await self.mcp_temporal_adapter.list_tools(
                tenant_id=self.tenant_id,
                server_name=server_name,
            )

            for tool_info in tool_infos:
                adapter = MCPTemporalToolAdapter(
                    mcp_temporal_adapter=self.mcp_temporal_adapter,
                    server_name=server_name,
                    tool_info=tool_info,
                    tenant_id=self.tenant_id,
                    permission_manager=self.permission_manager,
                )
                tools[adapter.name] = adapter
                logger.debug(f"Created adapter for Temporal MCP tool: {adapter.name}")

            logger.info(f"Loaded {len(tools)} tools from Temporal MCP server '{server_name}'")

        except Exception as e:
            logger.error(f"Error loading tools from Temporal MCP server '{server_name}': {e}")
            raise

        return tools

    async def get_tool(self, tool_name: str) -> Optional[AgentTool]:
        """
        Get a specific MCP tool by name.

        Args:
            tool_name: Full tool name (e.g., "mcp__filesystem__read_file")

        Returns:
            AgentTool instance or None if not found
        """
        if not self._tools_loaded:
            await self.load_all_tools()

        return self._cached_tools.get(tool_name)

    async def get_tools_by_server(self, server_name: str) -> List[AgentTool]:
        """
        Get all tools from a specific Temporal MCP server.

        Args:
            server_name: Name of the MCP server

        Returns:
            List of AgentTool instances from that server
        """
        if not self._tools_loaded:
            await self.load_all_tools()

        # Clean server name for matching
        clean_server = server_name.replace("-", "_")
        prefix = f"mcp__{clean_server}__"

        return [tool for name, tool in self._cached_tools.items() if name.startswith(prefix)]

    def clear_cache(self) -> None:
        """Clear the cached tools, forcing reload on next access."""
        self._cached_tools = {}
        self._tools_loaded = False
        logger.debug("Temporal MCP tool cache cleared")

    async def refresh(self) -> Dict[str, AgentTool]:
        """
        Refresh all Temporal MCP tools.

        Clears cache and reloads from all connected servers.

        Returns:
            Updated dictionary of tools
        """
        self.clear_cache()
        return await self.load_all_tools()

    @property
    def is_loaded(self) -> bool:
        """Check if tools have been loaded."""
        return self._tools_loaded

    @property
    def tool_count(self) -> int:
        """Get the number of loaded MCP tools."""
        return len(self._cached_tools)

    def list_tool_names(self) -> List[str]:
        """
        Get list of all loaded MCP tool names.

        Returns:
            List of tool names
        """
        return list(self._cached_tools.keys())

    def get_tool_info(self) -> List[Dict[str, Any]]:
        """
        Get information about all loaded tools.

        Returns:
            List of tool info dictionaries
        """
        info = []
        for name, tool in self._cached_tools.items():
            if isinstance(tool, MCPTemporalToolAdapter):
                info.append(
                    {
                        "name": name,
                        "server": tool.server_name,
                        "original_name": tool.original_tool_name,
                        "description": tool.description,
                        "source": "temporal",
                    }
                )
            else:
                info.append(
                    {
                        "name": name,
                        "description": tool.description,
                    }
                )
        return info
