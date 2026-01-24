"""Tool registry for CUA MCP server."""

import logging
from typing import Dict, List

from cua.adapter import CUAAdapter
from cua.config import CUAConfig
from server.websocket_server import MCPTool

logger = logging.getLogger(__name__)


class ToolRegistry:
    def __init__(self):
        self._tools: Dict[str, MCPTool] = {}

    def register(self, tool: MCPTool) -> None:
        self._tools[tool.name] = tool
        logger.debug("Registered tool: %s", tool.name)

    def get_all_tools(self) -> List[MCPTool]:
        return list(self._tools.values())


def get_tool_registry() -> ToolRegistry:
    registry = ToolRegistry()

    config = CUAConfig.from_env()
    adapter = CUAAdapter(config)

    tools = adapter.create_tools()

    for name, tool in tools.items():
        input_schema = {}
        if hasattr(tool, "get_parameters_schema"):
            input_schema = tool.get_parameters_schema()
        registry.register(
            MCPTool(
                name=name,
                description=getattr(tool, "description", ""),
                input_schema=input_schema or {"type": "object", "properties": {}, "required": []},
                handler=tool.safe_execute,
            )
        )

    logger.info("CUA tool registry initialized with %d tools", len(registry.get_all_tools()))
    return registry
