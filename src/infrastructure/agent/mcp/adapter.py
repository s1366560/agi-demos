"""MCP ToolInfo factories for dynamic MCP registry tools.

Provides the bridge between MCP server tools and the MemStack agent tool
pipeline. Dynamic MCP tools are represented directly as ``ToolInfo`` objects
instead of the retired class-based ``AgentTool`` adapter hierarchy.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any, cast

from src.infrastructure.agent.mcp.registry import MCPServerRegistry

if TYPE_CHECKING:
    from src.infrastructure.agent.tools.define import ToolInfo

logger = logging.getLogger(__name__)


def mcp_tool_name(server_id: str, tool_name: str) -> str:
    """Build standardized MCP tool name with double underscore separator."""
    return f"mcp__{server_id}__{tool_name}"


def create_mcp_tool(
    server_id: str,
    tool_definition: dict[str, Any],
    registry: MCPServerRegistry,
) -> ToolInfo:
    """Create a ToolInfo for an MCP registry tool.

    Each MCP tool has a unique name/description/parameters payload, so dynamic
    MCP tools are built as :class:`ToolInfo` objects directly rather than via
    ``@tool_define`` module globals.

    Args:
        server_id: ID of the MCP server providing this tool.
        tool_definition: MCP tool definition (name, description, inputSchema).
        registry: Registry for accessing the MCP server.

    Returns:
        A :class:`ToolInfo` instance representing this MCP tool.
    """
    from src.infrastructure.agent.tools.context import ToolContext
    from src.infrastructure.agent.tools.define import ToolInfo
    from src.infrastructure.agent.tools.result import ToolResult

    original_name = tool_definition.get("name", "unknown")
    tool_description = tool_definition.get("description", "No description")
    input_schema = tool_definition.get("inputSchema", {})
    parameters: dict[str, Any] = (
        cast(dict[str, Any], input_schema) if isinstance(input_schema, dict) else {}
    )

    name = mcp_tool_name(server_id, original_name)

    async def execute(ctx: ToolContext, **kwargs: Any) -> ToolResult:
        """Execute the MCP tool via the registry."""
        _ = ctx
        try:
            result = await registry.call_tool(
                server_id=server_id,
                tool_name=original_name,
                arguments=kwargs,
            )
            if isinstance(result, str):
                output = result
            elif isinstance(result, dict):
                output = json.dumps(result, indent=2, ensure_ascii=False)
            else:
                output = str(result)
            return ToolResult(output=output)
        except Exception as exc:
            error_msg = f"MCP tool execution failed: {exc!s}"
            logger.error(
                "%s (server=%s, tool=%s)",
                error_msg,
                server_id,
                original_name,
            )
            return ToolResult(output=error_msg, is_error=True)

    return ToolInfo(
        name=name,
        description=f"[MCP] {tool_description}",
        parameters=parameters,
        execute=execute,
        permission=None,
        category="mcp",
        tags=frozenset({"mcp", server_id}),
    )


async def create_mcp_tools_from_server(
    server_id: str,
    registry: MCPServerRegistry,
) -> list[ToolInfo]:
    """Create ToolInfo instances for every tool on an MCP server.

    Args:
        server_id: MCP server identifier.
        registry: MCP server registry.

    Returns:
        List of :class:`ToolInfo` instances.
    """
    try:
        tools = await registry.get_tools(server_id)
        infos: list[ToolInfo] = []
        for tool_def in tools:
            info = create_mcp_tool(
                server_id=server_id,
                tool_definition=tool_def,
                registry=registry,
            )
            infos.append(info)
            logger.info("Created ToolInfo for MCP tool: %s", info.name)
        return infos
    except Exception as exc:
        logger.error(
            "Failed to create tools for server %s: %s",
            server_id,
            exc,
        )
        return []


async def create_all_mcp_tools(registry: MCPServerRegistry) -> list[ToolInfo]:
    """Create ToolInfo instances for every tool on every registered MCP server."""
    infos: list[ToolInfo] = []
    for server_id in registry.get_registered_servers():
        infos.extend(await create_mcp_tools_from_server(server_id, registry))
    logger.info("Created %d MCP ToolInfo objects", len(infos))
    return infos


async def create_mcp_tool_by_name(
    server_id: str,
    tool_name: str,
    registry: MCPServerRegistry,
) -> ToolInfo | None:
    """Create a ToolInfo for a specific MCP server tool name."""
    try:
        tools = await registry.get_tools(server_id)
    except Exception as exc:
        logger.error("Failed to create tool %s for server %s: %s", tool_name, server_id, exc)
        return None

    for tool_def in tools:
        if tool_def.get("name") == tool_name:
            info = create_mcp_tool(
                server_id=server_id,
                tool_definition=tool_def,
                registry=registry,
            )
            logger.info("Created ToolInfo for MCP tool: %s", info.name)
            return info

    logger.warning("Tool %s not found on server %s", tool_name, server_id)
    return None
