"""Discover sandbox MCP tools from the toolsets enabled for this server process."""

import json
import logging
import os
from importlib import import_module
from importlib.resources import files

from src.server.websocket_server import MCPTool

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
        self._tools: dict[str, MCPTool] = {}

    def register(self, tool: MCPTool) -> None:
        """Register a tool."""
        if tool.name in self._tools:
            raise ValueError(f"Duplicate sandbox tool: {tool.name}")
        self._tools[tool.name] = tool
        logger.debug(f"Registered tool: {tool.name}")

    def get(self, name: str) -> MCPTool | None:
        """Get a tool by name."""
        return self._tools.get(name)

    def get_all_tools(self) -> list[MCPTool]:
        """Get all registered tools."""
        return list(self._tools.values())

    def list_names(self) -> list[str]:
        """List all tool names."""
        return list(self._tools.keys())


def get_tool_registry(workspace_dir: str = "/workspace") -> ToolRegistry:
    """Load selected bundled groups; managed external MCP packages use the management group."""
    declarations = json.loads(files("src.tools").joinpath("builtin_toolsets.json").read_text())
    configured = os.environ.get("MCP_TOOLSETS")
    enabled = (
        tuple(declarations)
        if configured is None
        else tuple(name.strip() for name in configured.split(",") if name.strip())
    )
    unknown = sorted(set(enabled) - declarations.keys())
    if unknown:
        raise ValueError("Unknown sandbox toolsets: " + ", ".join(unknown))

    registry = ToolRegistry(workspace_dir)
    for name in enabled:
        group = declarations[name]
        module = import_module(group["module"])
        for factory in group["factories"]:
            tool = getattr(module, factory)()
            if not isinstance(tool, MCPTool):
                raise TypeError(f"Invalid sandbox tool factory: {factory}")
            registry.register(tool)
    logger.info("Sandbox toolsets %s supplied %s tools", enabled, len(registry.list_names()))
    return registry
