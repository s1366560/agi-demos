"""Desktop management MCP tools.

Provides tools for managing remote desktop sessions.
"""

import logging
from typing import Optional

from src.server.websocket_server import MCPTool
from src.server.desktop_manager import DesktopManager

logger = logging.getLogger(__name__)

# Global desktop manager instance
_desktop_manager: Optional[DesktopManager] = None


def get_desktop_manager(workspace_dir: str = "/workspace") -> DesktopManager:
    """Get or create the global desktop manager."""
    global _desktop_manager
    if _desktop_manager is None:
        _desktop_manager = DesktopManager(workspace_dir=workspace_dir)
    return _desktop_manager


async def start_desktop(
    _workspace_dir: str = "/workspace",
    display: str = ":1",
    resolution: str = "1280x720",
    port: int = 6080,
) -> dict:
    """
    Start the remote desktop server.

    Starts a remote desktop environment with LXDE, accessible via
    noVNC in a web browser at the returned URL.

    Args:
        _workspace_dir: Working directory for desktop sessions
        display: X11 display number (default: ":1")
        resolution: Screen resolution (default: "1280x720")
        port: Port for noVNC web server (default: 6080)

    Returns:
        Dictionary with status and connection URL
    """
    manager = get_desktop_manager(_workspace_dir)
    manager.display = display
    manager.resolution = resolution
    manager.port = port

    try:
        if manager.is_running():
            return {
                "success": True,
                "message": "Desktop already running",
                "url": manager.get_novnc_url(),
                "display": display,
                "resolution": resolution,
                "port": port,
            }

        await manager.start()
        return {
            "success": True,
            "message": "Desktop started successfully",
            "url": manager.get_novnc_url(),
            "display": display,
            "resolution": resolution,
            "port": port,
            "xvfb_pid": manager.xvfb_process.pid if manager.xvfb_process else None,
            "xvnc_pid": manager.xvnc_process.pid if manager.xvnc_process else None,
        }
    except Exception as e:
        logger.error(f"Failed to start desktop: {e}")
        return {
            "success": False,
            "error": str(e),
        }


async def stop_desktop(
    _workspace_dir: str = "/workspace",
) -> dict:
    """
    Stop the remote desktop server.

    Stops the running desktop environment if it is active.

    Args:
        _workspace_dir: Workspace directory (for manager identification)

    Returns:
        Dictionary with operation status
    """
    manager = get_desktop_manager(_workspace_dir)

    try:
        if not manager.is_running():
            return {
                "success": True,
                "message": "Desktop was not running",
            }

        await manager.stop()
        return {
            "success": True,
            "message": "Desktop stopped successfully",
        }
    except Exception as e:
        logger.error(f"Failed to stop desktop: {e}")
        return {
            "success": False,
            "error": str(e),
        }


async def get_desktop_status(
    _workspace_dir: str = "/workspace",
) -> dict:
    """
    Get the current status of the remote desktop.

    Returns information about whether the desktop is running,
    display, resolution, port, and process IDs.

    Args:
        _workspace_dir: Workspace directory (for manager identification)

    Returns:
        Dictionary with desktop status
    """
    manager = get_desktop_manager(_workspace_dir)
    status = manager.get_status()

    return {
        "running": status.running,
        "display": status.display,
        "resolution": status.resolution,
        "port": status.port,
        "xvfb_pid": status.xvfb_pid,
        "xvnc_pid": status.xvnc_pid,
        "url": manager.get_novnc_url() if status.running else None,
    }


async def restart_desktop(
    _workspace_dir: str = "/workspace",
    display: str = ":1",
    resolution: str = "1280x720",
    port: int = 6080,
) -> dict:
    """
    Restart the remote desktop server.

    Stops and starts the desktop server. Useful for applying
    configuration changes.

    Args:
        _workspace_dir: Working directory for desktop sessions
        display: X11 display number (default: ":1")
        resolution: Screen resolution (default: "1280x720")
        port: Port for noVNC web server (default: 6080)

    Returns:
        Dictionary with operation status
    """
    manager = get_desktop_manager(_workspace_dir)
    manager.display = display
    manager.resolution = resolution
    manager.port = port

    try:
        await manager.restart()
        return {
            "success": True,
            "message": "Desktop restarted successfully",
            "url": manager.get_novnc_url(),
            "display": display,
            "resolution": resolution,
            "port": port,
            "xvfb_pid": manager.xvfb_process.pid if manager.xvfb_process else None,
            "xvnc_pid": manager.xvnc_process.pid if manager.xvnc_process else None,
        }
    except Exception as e:
        logger.error(f"Failed to restart desktop: {e}")
        return {
            "success": False,
            "error": str(e),
        }


def create_start_desktop_tool() -> MCPTool:
    """Create MCP tool for starting the remote desktop."""
    return MCPTool(
        name="start_desktop",
        description="Start the remote desktop server (LXDE + noVNC) for browser-based GUI access",
        input_schema={
            "type": "object",
            "properties": {
                "display": {
                    "type": "string",
                    "description": "X11 display number (default: ':1')",
                    "default": ":1",
                },
                "resolution": {
                    "type": "string",
                    "description": "Screen resolution (default: '1280x720')",
                    "default": "1280x720",
                },
                "port": {
                    "type": "number",
                    "description": "Port for noVNC web server (default: 6080)",
                    "default": 6080,
                },
            },
            "additionalProperties": False,
        },
        handler=start_desktop,
    )


def create_stop_desktop_tool() -> MCPTool:
    """Create MCP tool for stopping the remote desktop."""
    return MCPTool(
        name="stop_desktop",
        description="Stop the remote desktop server",
        input_schema={
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
        handler=stop_desktop,
    )


def create_desktop_status_tool() -> MCPTool:
    """Create MCP tool for getting desktop status."""
    return MCPTool(
        name="get_desktop_status",
        description="Get the current status of the remote desktop (running, display, resolution, port, PID, URL)",
        input_schema={
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
        handler=get_desktop_status,
    )


def create_restart_desktop_tool() -> MCPTool:
    """Create MCP tool for restarting the remote desktop."""
    return MCPTool(
        name="restart_desktop",
        description="Restart the remote desktop server",
        input_schema={
            "type": "object",
            "properties": {
                "display": {
                    "type": "string",
                    "description": "X11 display number (default: ':1')",
                    "default": ":1",
                },
                "resolution": {
                    "type": "string",
                    "description": "Screen resolution (default: '1280x720')",
                    "default": "1280x720",
                },
                "port": {
                    "type": "number",
                    "description": "Port for noVNC web server (default: 6080)",
                    "default": 6080,
                },
            },
            "additionalProperties": False,
        },
        handler=restart_desktop,
    )
