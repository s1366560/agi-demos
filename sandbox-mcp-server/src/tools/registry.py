"""Tool registry for MCP server.

Manages registration and discovery of MCP tools.
"""

import logging
from typing import Dict, List

from src.server.websocket_server import MCPTool
from src.tools.bash_tool import create_bash_tool
from src.tools.file_tools import (
    create_edit_tool,
    create_glob_tool,
    create_grep_tool,
    create_read_tool,
    create_write_tool,
)

logger = logging.getLogger(__name__)


class ToolRegistry:
    """
    Registry for MCP tools.

    Manages tool registration and provides tool discovery.
    """

    def __init__(self, workspace_dir: str = "/workspace"):
        """
        Initialize the tool registry.

        Args:
            workspace_dir: Root directory for file operations
        """
        self.workspace_dir = workspace_dir
        self._tools: Dict[str, MCPTool] = {}

    def register(self, tool: MCPTool) -> None:
        """Register a tool."""
        self._tools[tool.name] = tool
        logger.debug(f"Registered tool: {tool.name}")

    def get(self, name: str) -> MCPTool | None:
        """Get a tool by name."""
        return self._tools.get(name)

    def get_all_tools(self) -> List[MCPTool]:
        """Get all registered tools."""
        return list(self._tools.values())

    def list_names(self) -> List[str]:
        """List all tool names."""
        return list(self._tools.keys())


def get_tool_registry(workspace_dir: str = "/workspace") -> ToolRegistry:
    """
    Create and populate a tool registry with all available tools.

    Args:
        workspace_dir: Root directory for file operations

    Returns:
        Populated tool registry
    """
    registry = ToolRegistry(workspace_dir)

    # Register file tools
    registry.register(create_read_tool())
    registry.register(create_write_tool())
    registry.register(create_edit_tool())
    registry.register(create_glob_tool())
    registry.register(create_grep_tool())

    # Register bash tool
    registry.register(create_bash_tool())

    logger.info(f"Tool registry initialized with {len(registry.list_names())} tools")
    return registry
