"""Terminal management MCP tools.

Provides tools for managing web terminal sessions.
"""

import logging
from typing import Optional

from src.server.websocket_server import MCPTool
from src.server.web_terminal import WebTerminalManager

logger = logging.getLogger(__name__)

# Global terminal manager instance
_terminal_manager: Optional[WebTerminalManager] = None


def get_terminal_manager(workspace_dir: str = "/workspace") -> WebTerminalManager:
    """Get or create the global terminal manager."""
    global _terminal_manager
    if _terminal_manager is None:
        _terminal_manager = WebTerminalManager(workspace_dir=workspace_dir)
    return _terminal_manager


async def start_terminal(
    _workspace_dir: str = "/workspace",
    port: int = 7681,
) -> dict:
    """
    Start the web terminal server.

    Starts a ttyd server that provides browser-based terminal access.
    Once started, you can connect to the terminal via WebSocket at
    ws://localhost:{port}.

    Args:
        _workspace_dir: Working directory for terminal sessions
        port: Port for the ttyd WebSocket server (default: 7681)

    Returns:
        Dictionary with status and connection URL
    """
    manager = get_terminal_manager(_workspace_dir)
    manager.port = port

    try:
        if manager.is_running():
            return {
                "success": True,
                "message": "Terminal already running",
                "url": manager.get_websocket_url(),
                "port": port,
                "pid": manager.process.pid if manager.process else None,
            }

        await manager.start()
        return {
            "success": True,
            "message": "Terminal started successfully",
            "url": manager.get_websocket_url(),
            "port": port,
            "pid": manager.process.pid if manager.process else None,
        }
    except Exception as e:
        logger.error(f"Failed to start terminal: {e}")
        return {
            "success": False,
            "error": str(e),
        }


async def stop_terminal(
    _workspace_dir: str = "/workspace",
) -> dict:
    """
    Stop the web terminal server.

    Stops the running ttyd server if it is active.

    Args:
        _workspace_dir: Workspace directory (for manager identification)

    Returns:
        Dictionary with operation status
    """
    manager = get_terminal_manager(_workspace_dir)

    try:
        if not manager.is_running():
            return {
                "success": True,
                "message": "Terminal was not running",
            }

        await manager.stop()
        return {
            "success": True,
            "message": "Terminal stopped successfully",
        }
    except Exception as e:
        logger.error(f"Failed to stop terminal: {e}")
        return {
            "success": False,
            "error": str(e),
        }


async def get_terminal_status(
    _workspace_dir: str = "/workspace",
) -> dict:
    """
    Get the current status of the web terminal.

    Returns information about whether the terminal is running,
    its port, and process ID.

    Args:
        _workspace_dir: Workspace directory (for manager identification)

    Returns:
        Dictionary with terminal status
    """
    manager = get_terminal_manager(_workspace_dir)
    status = manager.get_status()

    return {
        "running": status.running,
        "port": status.port,
        "pid": status.pid,
        "url": manager.get_websocket_url() if status.running else None,
    }


async def restart_terminal(
    _workspace_dir: str = "/workspace",
    port: int = 7681,
) -> dict:
    """
    Restart the web terminal server.

    Stops and starts the terminal server. Useful for applying
    configuration changes.

    Args:
        _workspace_dir: Working directory for terminal sessions
        port: Port for the ttyd WebSocket server (default: 7681)

    Returns:
        Dictionary with operation status
    """
    manager = get_terminal_manager(_workspace_dir)
    manager.port = port

    try:
        await manager.restart()
        return {
            "success": True,
            "message": "Terminal restarted successfully",
            "url": manager.get_websocket_url(),
            "port": port,
            "pid": manager.process.pid if manager.process else None,
        }
    except Exception as e:
        logger.error(f"Failed to restart terminal: {e}")
        return {
            "success": False,
            "error": str(e),
        }


def create_start_terminal_tool() -> MCPTool:
    """Create MCP tool for starting the web terminal."""
    return MCPTool(
        name="start_terminal",
        description="Start the web terminal server (ttyd) for browser-based shell access",
        input_schema={
            "type": "object",
            "properties": {
                "port": {
                    "type": "number",
                    "description": "Port for the ttyd WebSocket server (default: 7681)",
                    "default": 7681,
                },
            },
            "additionalProperties": False,
        },
        handler=start_terminal,
    )


def create_stop_terminal_tool() -> MCPTool:
    """Create MCP tool for stopping the web terminal."""
    return MCPTool(
        name="stop_terminal",
        description="Stop the web terminal server",
        input_schema={
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
        handler=stop_terminal,
    )


def create_terminal_status_tool() -> MCPTool:
    """Create MCP tool for getting terminal status."""
    return MCPTool(
        name="get_terminal_status",
        description="Get the current status of the web terminal (running, port, PID, URL)",
        input_schema={
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
        handler=get_terminal_status,
    )


def create_restart_terminal_tool() -> MCPTool:
    """Create MCP tool for restarting the web terminal."""
    return MCPTool(
        name="restart_terminal",
        description="Restart the web terminal server",
        input_schema={
            "type": "object",
            "properties": {
                "port": {
                    "type": "number",
                    "description": "Port for the ttyd WebSocket server (default: 7681)",
                    "default": 7681,
                },
            },
            "additionalProperties": False,
        },
        handler=restart_terminal,
    )
