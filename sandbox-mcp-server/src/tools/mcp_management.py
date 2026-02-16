"""MCP Server management tools for the sandbox.

These tools allow the backend to manage user-configured MCP servers
running inside the sandbox container. They are called by the backend
via the existing MCP protocol, NOT exposed to agents directly.
"""

import json
import logging
from typing import Any, Dict, Optional

from src.mcp_manager.manager import MCPServerManager
from src.server.websocket_server import MCPTool

logger = logging.getLogger(__name__)

# Singleton manager instance, created on first use
_manager: Optional[MCPServerManager] = None


def _get_manager(workspace_dir: str = "/workspace") -> MCPServerManager:
    """Get or create the global MCPServerManager instance."""
    global _manager
    if _manager is None:
        _manager = MCPServerManager(workspace_dir=workspace_dir)
    return _manager


async def execute_mcp_server_install(
    name: str,
    server_type: str,
    transport_config: str,
    _workspace_dir: str = "/workspace",
    **kwargs,
) -> Dict[str, Any]:
    """Install an MCP server package in the sandbox.

    Args:
        name: Server name.
        server_type: Transport type (stdio, sse, http, websocket).
        transport_config: JSON string of transport configuration.
        _workspace_dir: Workspace directory (injected).

    Returns:
        Installation result.
    """
    try:
        config = (
            json.loads(transport_config) if isinstance(transport_config, str) else transport_config
        )
        manager = _get_manager(_workspace_dir)
        result = await manager.install_server(name, server_type, config)
        return {
            "content": [{"type": "text", "text": json.dumps(result, indent=2)}],
            "isError": not result.get("success", False),
        }
    except Exception as e:
        logger.error(f"Error installing MCP server '{name}': {e}", exc_info=True)
        return {
            "content": [{"type": "text", "text": f"Error: {str(e)}"}],
            "isError": True,
        }


async def execute_mcp_server_start(
    name: str,
    server_type: str,
    transport_config: str,
    _workspace_dir: str = "/workspace",
    **kwargs,
) -> Dict[str, Any]:
    """Start an MCP server subprocess in the sandbox.

    Args:
        name: Server name.
        server_type: Transport type (stdio, sse, http, websocket).
        transport_config: JSON string of transport configuration.
        _workspace_dir: Workspace directory (injected).

    Returns:
        Server status.
    """
    try:
        config = (
            json.loads(transport_config) if isinstance(transport_config, str) else transport_config
        )
        manager = _get_manager(_workspace_dir)
        result = await manager.start_server(name, server_type, config)
        return {
            "content": [{"type": "text", "text": json.dumps(result, indent=2)}],
            "isError": not result.get("success", False),
        }
    except Exception as e:
        logger.error(f"Error starting MCP server '{name}': {e}", exc_info=True)
        return {
            "content": [{"type": "text", "text": f"Error: {str(e)}"}],
            "isError": True,
        }


async def execute_mcp_server_stop(
    name: str,
    _workspace_dir: str = "/workspace",
    **kwargs,
) -> Dict[str, Any]:
    """Stop a running MCP server in the sandbox.

    Args:
        name: Server name.
        _workspace_dir: Workspace directory (injected).

    Returns:
        Result.
    """
    try:
        manager = _get_manager(_workspace_dir)
        result = await manager.stop_server(name)
        return {
            "content": [{"type": "text", "text": json.dumps(result, indent=2)}],
            "isError": not result.get("success", False),
        }
    except Exception as e:
        logger.error(f"Error stopping MCP server '{name}': {e}", exc_info=True)
        return {
            "content": [{"type": "text", "text": f"Error: {str(e)}"}],
            "isError": True,
        }


async def execute_mcp_server_list(
    _workspace_dir: str = "/workspace",
    **kwargs,
) -> Dict[str, Any]:
    """List all managed MCP servers in the sandbox.

    Args:
        _workspace_dir: Workspace directory (injected).

    Returns:
        List of server statuses.
    """
    try:
        manager = _get_manager(_workspace_dir)
        servers = await manager.list_servers()
        return {
            "content": [{"type": "text", "text": json.dumps(servers, indent=2)}],
            "isError": False,
        }
    except Exception as e:
        logger.error(f"Error listing MCP servers: {e}", exc_info=True)
        return {
            "content": [{"type": "text", "text": f"Error: {str(e)}"}],
            "isError": True,
        }


async def execute_mcp_server_discover_tools(
    name: str,
    _workspace_dir: str = "/workspace",
    **kwargs,
) -> Dict[str, Any]:
    """Discover tools from a running MCP server.

    Args:
        name: Server name.
        _workspace_dir: Workspace directory (injected).

    Returns:
        List of discovered tools.
    """
    try:
        manager = _get_manager(_workspace_dir)
        tools = await manager.discover_tools(name)
        return {
            "content": [{"type": "text", "text": json.dumps(tools, indent=2)}],
            "isError": False,
            "metadata": {"tool_count": len(tools)},
        }
    except Exception as e:
        logger.error(f"Error discovering tools for '{name}': {e}", exc_info=True)
        return {
            "content": [{"type": "text", "text": f"Error: {str(e)}"}],
            "isError": True,
        }


async def execute_mcp_server_call_tool(
    server_name: str,
    tool_name: str,
    arguments: str = "{}",
    _workspace_dir: str = "/workspace",
    **kwargs,
) -> Dict[str, Any]:
    """Call a tool on a managed MCP server.

    Args:
        server_name: Server name.
        tool_name: Tool name.
        arguments: JSON string of tool arguments.
        _workspace_dir: Workspace directory (injected).

    Returns:
        Tool call result.
    """
    try:
        args = json.loads(arguments) if isinstance(arguments, str) else arguments
        manager = _get_manager(_workspace_dir)

        # Special handling for resources/read proxy
        if tool_name == "__resources_read__":
            uri = args.get("uri", "")
            if not uri:
                return {
                    "content": [{"type": "text", "text": "Error: uri is required for resources/read"}],
                    "isError": True,
                }
            result = await manager.read_resource(server_name, uri)
            if result is None:
                return {
                    "content": [{"type": "text", "text": f"Resource not found: {uri}"}],
                    "isError": True,
                }
            return {
                "content": [{"uri": uri, "mimeType": "text/html;profile=mcp-app", "text": result}],
                "isError": False,
            }

        # Special handling for resources/list proxy
        if tool_name == "__resources_list__":
            result = await manager.list_resources(server_name)
            return {
                "content": result,
                "isError": False,
            }

        result = await manager.call_tool(server_name, tool_name, args)
        return {
            "content": result.get("content", [{"type": "text", "text": str(result)}]),
            "isError": result.get("isError", False),
        }
    except Exception as e:
        logger.error(f"Error calling tool '{tool_name}' on '{server_name}': {e}", exc_info=True)
        return {
            "content": [{"type": "text", "text": f"Error: {str(e)}"}],
            "isError": True,
        }


# -- Tool factory functions --


def create_mcp_server_install_tool() -> MCPTool:
    """Create the mcp_server_install tool."""
    return MCPTool(
        name="mcp_server_install",
        description="Install an MCP server package in the sandbox environment.",
        input_schema={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Unique name for the MCP server",
                },
                "server_type": {
                    "type": "string",
                    "description": "Transport type: stdio, sse, http, or websocket",
                    "enum": ["stdio", "sse", "http", "websocket"],
                },
                "transport_config": {
                    "type": "string",
                    "description": "JSON string of transport configuration",
                },
            },
            "required": ["name", "server_type", "transport_config"],
        },
        handler=execute_mcp_server_install,
    )


def create_mcp_server_start_tool() -> MCPTool:
    """Create the mcp_server_start tool."""
    return MCPTool(
        name="mcp_server_start",
        description="Start an MCP server subprocess in the sandbox.",
        input_schema={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Server name",
                },
                "server_type": {
                    "type": "string",
                    "description": "Transport type: stdio, sse, http, or websocket",
                    "enum": ["stdio", "sse", "http", "websocket"],
                },
                "transport_config": {
                    "type": "string",
                    "description": "JSON string of transport configuration",
                },
            },
            "required": ["name", "server_type", "transport_config"],
        },
        handler=execute_mcp_server_start,
    )


def create_mcp_server_stop_tool() -> MCPTool:
    """Create the mcp_server_stop tool."""
    return MCPTool(
        name="mcp_server_stop",
        description="Stop a running MCP server in the sandbox.",
        input_schema={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Server name to stop",
                },
            },
            "required": ["name"],
        },
        handler=execute_mcp_server_stop,
    )


def create_mcp_server_list_tool() -> MCPTool:
    """Create the mcp_server_list tool."""
    return MCPTool(
        name="mcp_server_list",
        description="List all managed MCP servers and their status.",
        input_schema={
            "type": "object",
            "properties": {},
        },
        handler=execute_mcp_server_list,
    )


def create_mcp_server_discover_tools_tool() -> MCPTool:
    """Create the mcp_server_discover_tools tool."""
    return MCPTool(
        name="mcp_server_discover_tools",
        description="Discover tools from a running MCP server.",
        input_schema={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Server name to discover tools from",
                },
            },
            "required": ["name"],
        },
        handler=execute_mcp_server_discover_tools,
    )


def create_mcp_server_call_tool_tool() -> MCPTool:
    """Create the mcp_server_call_tool tool."""
    return MCPTool(
        name="mcp_server_call_tool",
        description="Call a tool on a managed MCP server.",
        input_schema={
            "type": "object",
            "properties": {
                "server_name": {
                    "type": "string",
                    "description": "Server name",
                },
                "tool_name": {
                    "type": "string",
                    "description": "Tool name to call",
                },
                "arguments": {
                    "type": "string",
                    "description": "JSON string of tool arguments",
                    "default": "{}",
                },
            },
            "required": ["server_name", "tool_name"],
        },
        handler=execute_mcp_server_call_tool,
    )
