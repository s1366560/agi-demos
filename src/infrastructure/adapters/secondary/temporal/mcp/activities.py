"""MCP Activities for Temporal.

This module defines Activities for MCP server operations:
- start_mcp_server_activity: Start and initialize an MCP server
- call_mcp_tool_activity: Call a tool on the MCP server
- stop_mcp_server_activity: Stop and cleanup an MCP server

Activities maintain MCP client state in a global registry, allowing
the same client to be reused across multiple activity invocations
within a workflow.
"""

import asyncio
import logging
from typing import Any, Dict, Optional, Union

from temporalio import activity

from src.infrastructure.adapters.secondary.temporal.mcp.http_client import MCPHttpClient
from src.infrastructure.adapters.secondary.temporal.mcp.subprocess_client import MCPSubprocessClient
from src.infrastructure.adapters.secondary.temporal.mcp.websocket_client import MCPWebSocketClient

logger = logging.getLogger(__name__)

# Type alias for MCP clients
MCPClient = Union[MCPSubprocessClient, MCPHttpClient, MCPWebSocketClient]

# Global registry for MCP clients (workflow_id -> client)
# This allows clients to be reused across activity invocations
_mcp_clients: Dict[str, MCPClient] = {}
_clients_lock = asyncio.Lock()


def _get_workflow_id() -> str:
    """Get the workflow ID from the current activity context."""
    info = activity.info()
    return info.workflow_id


async def _get_or_create_client(
    workflow_id: str,
    config: Dict[str, Any],
) -> MCPClient:
    """
    Get an existing client or create a new one.

    Args:
        workflow_id: The workflow ID to use as the client key
        config: MCP server configuration

    Returns:
        MCP client instance
    """
    async with _clients_lock:
        if workflow_id in _mcp_clients:
            client = _mcp_clients[workflow_id]
            if client.is_connected:
                return client
            # Client exists but disconnected, remove it
            del _mcp_clients[workflow_id]

        # Create new client based on transport type
        # Normalize transport type: accept both "stdio"/"local" and case-insensitive
        transport_type = config.get("transport_type", "local").lower()

        if transport_type in ("local", "stdio"):
            command = config.get("command", [])
            if not command:
                raise ValueError("Command is required for local MCP server")

            # Ensure command is a list (may come as string from config)
            if isinstance(command, str):
                import shlex

                command = shlex.split(command)

            client = MCPSubprocessClient(
                command=command[0],
                args=command[1:] if len(command) > 1 else [],
                env=config.get("environment"),
                timeout=config.get("timeout", 30000) / 1000,
            )
        elif transport_type in ("http", "sse"):
            url = config.get("url")
            if not url:
                raise ValueError("URL is required for remote MCP server")

            client = MCPHttpClient(
                url=url,
                headers=config.get("headers"),
                timeout=config.get("timeout", 30000) / 1000,
                transport_type=transport_type,
            )
        elif transport_type == "websocket":
            url = config.get("url")
            if not url:
                raise ValueError("WebSocket URL is required for WebSocket MCP server")

            client = MCPWebSocketClient(
                url=url,
                headers=config.get("headers"),
                timeout=config.get("timeout", 30000) / 1000,
                heartbeat_interval=config.get("heartbeat_interval", 30),
                reconnect_attempts=config.get("reconnect_attempts", 3),
            )
        else:
            raise ValueError(f"Unsupported transport type: {transport_type}")

        _mcp_clients[workflow_id] = client
        return client


async def _remove_client(workflow_id: str) -> Optional[MCPClient]:
    """
    Remove a client from the registry.

    Args:
        workflow_id: The workflow ID

    Returns:
        The removed client, or None if not found
    """
    async with _clients_lock:
        return _mcp_clients.pop(workflow_id, None)


@activity.defn(name="start_mcp_server")
async def start_mcp_server_activity(config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Start and initialize an MCP server.

    This activity:
    1. Creates the appropriate client (subprocess or HTTP)
    2. Establishes the connection
    3. Retrieves the list of available tools
    4. Stores the client in the global registry

    Args:
        config: MCP server configuration (MCPServerConfig as dict)

    Returns:
        Start result with status, tools, and server info
    """
    workflow_id = _get_workflow_id()
    server_name = config.get("server_name", "unknown")
    transport_type = config.get("transport_type", "local")

    logger.info(
        f"Starting MCP server: {server_name} (workflow: {workflow_id}, transport: {transport_type})"
    )

    try:
        # Get or create client
        client = await _get_or_create_client(workflow_id, config)

        # Connect
        timeout = config.get("timeout", 30000) / 1000
        connected = await client.connect(timeout=timeout)

        if not connected:
            # Remove failed client from registry
            await _remove_client(workflow_id)
            return {
                "server_name": server_name,
                "status": "failed",
                "error": "Failed to connect to MCP server",
                "tools": [],
                "server_info": None,
            }

        # Get tools
        tools = client.get_cached_tools()
        tools_data = [
            {
                "name": t.name,
                "description": t.description,
                "inputSchema": t.inputSchema,
            }
            for t in tools
        ]

        logger.info(f"MCP server started: {server_name} with {len(tools_data)} tools")

        # Report heartbeat
        activity.heartbeat(f"Connected with {len(tools_data)} tools")

        return {
            "server_name": server_name,
            "status": "connected",
            "tools": tools_data,
            "server_info": client.server_info,
            "error": None,
        }

    except Exception as e:
        logger.exception(f"Error starting MCP server: {e}")
        # Remove failed client from registry
        await _remove_client(workflow_id)
        return {
            "server_name": server_name,
            "status": "failed",
            "error": str(e),
            "tools": [],
            "server_info": None,
        }


@activity.defn(name="call_mcp_tool")
async def call_mcp_tool_activity(params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Call a tool on the MCP server.

    This activity retrieves the client from the global registry
    and executes the specified tool.

    Args:
        params: Dictionary containing:
            - config: MCP server configuration
            - tool_name: Name of the tool to call
            - arguments: Tool arguments

    Returns:
        Tool call result
    """
    workflow_id = _get_workflow_id()
    config = params.get("config", {})
    tool_name = params.get("tool_name", "")
    arguments = params.get("arguments", {})
    server_name = config.get("server_name", "unknown")

    logger.info(f"Calling MCP tool: {tool_name} on {server_name}")

    try:
        # Get client from registry
        async with _clients_lock:
            client = _mcp_clients.get(workflow_id)

        if not client:
            # Try to reconnect
            logger.warning(f"Client not found, attempting to reconnect: {workflow_id}")
            client = await _get_or_create_client(workflow_id, config)
            connected = await client.connect()
            if not connected:
                return {
                    "content": [{"type": "text", "text": "MCP server not connected"}],
                    "is_error": True,
                    "error_message": "MCP server not connected",
                }

        if not client.is_connected:
            return {
                "content": [{"type": "text", "text": "MCP server disconnected"}],
                "is_error": True,
                "error_message": "MCP server disconnected",
            }

        # Call the tool
        timeout = config.get("timeout", 30000) / 1000
        result = await client.call_tool(tool_name, arguments, timeout=timeout)

        # Report heartbeat
        activity.heartbeat(f"Tool {tool_name} completed")

        return {
            "content": result.content,
            "is_error": result.isError,
            "error_message": None if not result.isError else "Tool returned error",
        }

    except Exception as e:
        logger.exception(f"Error calling MCP tool: {e}")
        return {
            "content": [{"type": "text", "text": f"Error: {str(e)}"}],
            "is_error": True,
            "error_message": str(e),
        }


@activity.defn(name="stop_mcp_server")
async def stop_mcp_server_activity(config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Stop and cleanup an MCP server.

    This activity:
    1. Retrieves the client from the global registry
    2. Disconnects the client
    3. Removes the client from the registry

    Args:
        config: MCP server configuration

    Returns:
        Stop result with status
    """
    workflow_id = _get_workflow_id()
    server_name = config.get("server_name", "unknown")

    logger.info(f"Stopping MCP server: {server_name} (workflow: {workflow_id})")

    try:
        # Remove and disconnect client
        client = await _remove_client(workflow_id)

        if client:
            await client.disconnect()
            logger.info(f"MCP server stopped: {server_name}")
        else:
            logger.warning(f"No client found to stop: {workflow_id}")

        return {
            "server_name": server_name,
            "status": "stopped",
            "error": None,
        }

    except Exception as e:
        logger.exception(f"Error stopping MCP server: {e}")
        return {
            "server_name": server_name,
            "status": "error",
            "error": str(e),
        }


# Utility functions for testing and debugging


def get_active_clients() -> Dict[str, str]:
    """Get a summary of active MCP clients."""
    return {workflow_id: type(client).__name__ for workflow_id, client in _mcp_clients.items()}


async def cleanup_all_clients():
    """Cleanup all MCP clients (for shutdown)."""
    async with _clients_lock:
        for workflow_id, client in list(_mcp_clients.items()):
            try:
                await client.disconnect()
                logger.info(f"Cleaned up client: {workflow_id}")
            except Exception as e:
                logger.error(f"Error cleaning up client {workflow_id}: {e}")
        _mcp_clients.clear()
