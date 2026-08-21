"""Desktop management MCP tools.

Provides tools for managing the Openbox/X11 desktop served by KasmVNC.
Supports dynamic resolution, clipboard synchronization, and enhanced status.
"""

import logging
from pathlib import Path

from src.server.desktop_manager import DesktopManager, DesktopStatus
from src.server.websocket_server import MCPTool

logger = logging.getLogger(__name__)

# Global desktop manager instances by workspace
_desktop_managers: dict[str, DesktopManager] = {}


def _desktop_features(status: DesktopStatus) -> dict[str, object]:
    """Return capabilities implemented by the standalone KasmVNC runtime."""
    return {
        "dynamic_resize": status.dynamic_resize,
        "clipboard": True,
        "file_transfer": False,
        "audio": status.audio_enabled,
        "encoding": status.encoding,
    }


def get_desktop_manager(workspace_dir: str = "/workspace") -> DesktopManager:
    """Get or create the desktop manager for a workspace."""
    workspace_key = str(Path(workspace_dir).resolve())
    if workspace_key not in _desktop_managers:
        _desktop_managers[workspace_key] = DesktopManager(workspace_dir=workspace_key)
    return _desktop_managers[workspace_key]


async def start_desktop(
    _workspace_dir: str = "/workspace",
    display: str = ":1",
    resolution: str = "1920x1080",
    port: int = 6080,
) -> dict:
    """
    Start the remote desktop server.

    Starts an Openbox/X11 desktop with KasmVNC, accessible via web browser at
    the returned URL. The standalone runtime supports dynamic resize and
    bidirectional clipboard synchronization.

    Args:
        _workspace_dir: Working directory for desktop sessions
        display: X11 display number (default: ":1")
        resolution: Screen resolution (default: "1920x1080")
        port: Port for KasmVNC web server (default: 6080)

    Returns:
        Dictionary with status and connection URL
    """
    manager = get_desktop_manager(_workspace_dir)

    try:
        if manager.is_running():
            status = manager.get_status()
            url = manager.get_web_url()
            return {
                "success": True,
                "message": f"Desktop already running. Open in browser: {url}",
                "url": url,
                "display": status.display,
                "resolution": status.resolution,
                "port": status.port,
                "features": _desktop_features(status),
            }

        manager.display = display
        manager.resolution = resolution
        manager.port = port
        await manager.start()
        status = manager.get_status()
        url = manager.get_web_url()
        return {
            "success": True,
            "message": f"Desktop started successfully (KasmVNC). Open in browser: {url}",
            "url": url,
            "display": status.display,
            "resolution": status.resolution,
            "port": status.port,
            "kasmvnc_pid": status.kasmvnc_pid,
            "features": _desktop_features(status),
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

    Returns:
        Dictionary with desktop status including KasmVNC features
    """
    manager = get_desktop_manager(_workspace_dir)
    status = manager.get_status()

    return {
        "running": status.running,
        "display": status.display,
        "resolution": status.resolution,
        "port": status.port,
        "kasmvnc_pid": status.kasmvnc_pid,
        "url": manager.get_web_url() if status.running else None,
        "audio_enabled": status.audio_enabled,
        "dynamic_resize": status.dynamic_resize,
        "encoding": status.encoding,
    }


async def change_resolution(
    _workspace_dir: str = "/workspace",
    resolution: str = "1920x1080",
) -> dict:
    """
    Change the desktop resolution dynamically without restarting.

    KasmVNC supports live resolution changes via xrandr.

    Args:
        _workspace_dir: Workspace directory
        resolution: New resolution (e.g., "1920x1080", "2560x1440")

    Returns:
        Dictionary with operation status
    """
    manager = get_desktop_manager(_workspace_dir)

    try:
        success = await manager.change_resolution(resolution)
        if success:
            return {
                "success": True,
                "message": f"Resolution changed to {resolution}",
                "resolution": resolution,
            }
        else:
            return {
                "success": False,
                "error": f"Failed to change resolution to {resolution}",
            }
    except Exception as e:
        logger.error(f"Failed to change resolution: {e}")
        return {
            "success": False,
            "error": str(e),
        }


async def restart_desktop(
    _workspace_dir: str = "/workspace",
    display: str = ":1",
    resolution: str = "1920x1080",
    port: int = 6080,
) -> dict:
    """
    Restart the remote desktop server.

    Args:
        _workspace_dir: Working directory for desktop sessions
        display: X11 display number (default: ":1")
        resolution: Screen resolution (default: "1920x1080")
        port: Port for KasmVNC web server (default: 6080)

    Returns:
        Dictionary with operation status
    """
    manager = get_desktop_manager(_workspace_dir)
    manager.display = display
    manager.resolution = resolution
    manager.port = port

    try:
        await manager.restart()
        status = manager.get_status()
        return {
            "success": True,
            "message": "Desktop restarted successfully",
            "url": manager.get_web_url(),
            "display": display,
            "resolution": resolution,
            "port": port,
            "kasmvnc_pid": status.kasmvnc_pid,
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
        description=(
            "Start the Openbox/X11 remote desktop server (KasmVNC) for browser-based "
            "GUI access with dynamic resize and bidirectional clipboard"
        ),
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
                    "description": "Screen resolution (default: '1920x1080')",
                    "default": "1920x1080",
                },
                "port": {
                    "type": "number",
                    "description": "Port for KasmVNC web server (default: 6080)",
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
        description=(
            "Get the current status of the remote desktop "
            "(running, resolution, encoding, audio, features)"
        ),
        input_schema={
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
        handler=get_desktop_status,
    )


def create_change_resolution_tool() -> MCPTool:
    """Create MCP tool for changing resolution dynamically."""
    return MCPTool(
        name="change_resolution",
        description=(
            "Change the desktop resolution dynamically without restarting. "
            "Supported: 1280x720, 1920x1080, 1600x900, 2560x1440"
        ),
        input_schema={
            "type": "object",
            "properties": {
                "resolution": {
                    "type": "string",
                    "description": "New resolution (e.g., '1920x1080')",
                },
            },
            "required": ["resolution"],
            "additionalProperties": False,
        },
        handler=change_resolution,
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
                    "description": "Screen resolution (default: '1920x1080')",
                    "default": "1920x1080",
                },
                "port": {
                    "type": "number",
                    "description": "Port for KasmVNC web server (default: 6080)",
                    "default": 6080,
                },
            },
            "additionalProperties": False,
        },
        handler=restart_desktop,
    )
