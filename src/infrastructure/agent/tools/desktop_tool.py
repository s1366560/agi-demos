"""Desktop management tool for ReAct agent.

Provides tools for starting, stopping, and checking the status of
remote desktop sessions in sandbox environments.
"""

import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional

from src.infrastructure.agent.tools.base import AgentTool

logger = logging.getLogger(__name__)


@dataclass
class DesktopStatus:
    """Status of the remote desktop."""

    running: bool
    url: Optional[str] = None
    display: str = ":1"
    resolution: str = "1280x720"
    port: int = 6080


class DesktopTool(AgentTool):
    """
    Tool for managing remote desktop sessions.

    Provides the ability to start, stop, and check the status of
    LXDE desktop environments accessible via noVNC in a web browser.

    Actions:
        - start: Launch the remote desktop server
        - stop: Stop the running desktop server
        - status: Get current desktop status

    Example:
        tool = DesktopTool(sandbox_adapter)
        result = await tool.execute(action="start", resolution="1920x1080")
    """

    def __init__(self, sandbox_adapter: Any, sandbox_id: str = "test_sandbox"):
        """
        Initialize the DesktopTool.

        Args:
            sandbox_adapter: Adapter for communicating with sandbox
            sandbox_id: ID of the sandbox to manage
        """
        super().__init__(
            name="desktop",
            description="Manage remote desktop sessions (LXDE + noVNC) for browser-based GUI access. "
            "Actions: start, stop, status. Example: action='start', resolution='1280x720'",
        )
        self._sandbox_adapter = sandbox_adapter
        self._sandbox_id = sandbox_id

    def get_parameters_schema(self) -> Dict[str, Any]:
        """
        Get the parameters schema for LLM function calling.

        Returns:
            JSON schema describing the tool parameters
        """
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["start", "stop", "status"],
                    "description": "Action to perform: 'start' to launch desktop, 'stop' to shutdown, 'status' to check state",
                },
                "resolution": {
                    "type": "string",
                    "description": "Screen resolution (e.g., '1280x720', '1920x1080')",
                    "default": "1280x720",
                },
                "display": {
                    "type": "string",
                    "description": "X11 display number (e.g., ':1', ':2')",
                    "default": ":1",
                },
                "port": {
                    "type": "integer",
                    "description": "Port for noVNC web server",
                    "default": 6080,
                },
            },
            "required": ["action"],
        }

    def validate_args(self, **kwargs: Any) -> bool:
        """
        Validate tool arguments before execution.

        Args:
            **kwargs: Arguments to validate

        Returns:
            True if arguments are valid, False otherwise
        """
        action = kwargs.get("action")
        if action not in ("start", "stop", "status"):
            return False

        # Validate port if provided
        if "port" in kwargs:
            port = kwargs["port"]
            if not isinstance(port, int) or port < 1024 or port > 65535:
                return False

        return True

    async def execute(self, **kwargs: Any) -> str:
        """
        Execute the desktop tool with the given arguments.

        Args:
            **kwargs: Tool-specific arguments including:
                - action: The action to perform (start/stop/status)
                - resolution: Screen resolution for start action
                - display: X11 display number for start action
                - port: Port number for noVNC server

        Returns:
            String result of the tool execution

        Raises:
            ValueError: If action is invalid
        """
        action = kwargs.get("action")

        if action == "start":
            return await self._start_desktop(**kwargs)
        elif action == "stop":
            return await self._stop_desktop()
        elif action == "status":
            return await self._get_desktop_status()
        else:
            return f"Error: Unknown action '{action}'. Valid actions are: start, stop, status"

    async def _start_desktop(self, **kwargs: Any) -> str:
        """
        Start the remote desktop server.

        Args:
            **kwargs: Optional parameters (resolution, display, port)

        Returns:
            Status message with connection URL
        """
        try:
            # Prepare arguments for MCP tool call
            mcp_args = {"_workspace_dir": "/workspace"}

            if "resolution" in kwargs:
                mcp_args["resolution"] = kwargs["resolution"]
            if "display" in kwargs:
                mcp_args["display"] = kwargs["display"]
            if "port" in kwargs:
                mcp_args["port"] = kwargs["port"]

            # Call MCP tool via sandbox adapter
            result = await self._sandbox_adapter.call_tool(
                self._sandbox_id,
                "start_desktop",
                mcp_args,
            )

            return self._format_result(result, "Desktop started successfully")

        except Exception as e:
            logger.error(f"Failed to start desktop: {e}")
            return f"Error: Failed to start desktop - {str(e)}"

    async def _stop_desktop(self) -> str:
        """
        Stop the remote desktop server.

        Returns:
            Status message
        """
        try:
            result = await self._sandbox_adapter.call_tool(
                self._sandbox_id,
                "stop_desktop",
                {"_workspace_dir": "/workspace"},
            )

            return self._format_result(result, "Desktop stopped successfully")

        except Exception as e:
            logger.error(f"Failed to stop desktop: {e}")
            return f"Error: Failed to stop desktop - {str(e)}"

    async def _get_desktop_status(self) -> str:
        """
        Get the current desktop status.

        Returns:
            Status message with desktop information
        """
        try:
            result = await self._sandbox_adapter.call_tool(
                self._sandbox_id,
                "get_desktop_status",
                {"_workspace_dir": "/workspace"},
            )

            return self._format_result(result, "Desktop status retrieved")

        except Exception as e:
            logger.error(f"Failed to get desktop status: {e}")
            return f"Error: Failed to get desktop status - {str(e)}"

    def _format_result(self, result: Dict[str, Any], success_message: str) -> str:
        """
        Format the result from MCP tool call.

        Args:
            result: Raw result from sandbox adapter
            success_message: Default message on success

        Returns:
            Formatted status message
        """
        if result.get("is_error"):
            content_list = result.get("content", [])
            if content_list and len(content_list) > 0:
                return f"Error: {content_list[0].get('text', 'Unknown error')}"
            return "Error: Desktop operation failed"

        # Parse JSON response
        content_list = result.get("content", [])
        if not content_list:
            return success_message

        text_content = content_list[0].get("text", "")
        try:
            data = json.loads(text_content)

            # Handle status response (has 'running' field)
            if "running" in data:
                parts = []
                if data.get("running"):
                    parts.append("Desktop is running")
                else:
                    parts.append("Desktop is not running")

                if "url" in data and data["url"]:
                    parts.append(f"URL: {data['url']}")
                if "port" in data:
                    parts.append(f"Port: {data['port']}")
                if "display" in data:
                    parts.append(f"Display: {data['display']}")
                if "resolution" in data:
                    parts.append(f"Resolution: {data['resolution']}")

                return " | ".join(parts) if parts else "Desktop status retrieved"

            # Handle success/error response
            if data.get("success"):
                parts = [success_message]
                if "url" in data and data["url"]:
                    parts.append(f"URL: {data['url']}")
                if "port" in data:
                    parts.append(f"Port: {data['port']}")
                if "display" in data:
                    parts.append(f"Display: {data['display']}")
                if "resolution" in data:
                    parts.append(f"Resolution: {data['resolution']}")

                return " | ".join(parts)
            else:
                error = data.get("error", "Unknown error")
                return f"Error: {error}"

        except (json.JSONDecodeError, ValueError):
            # Return raw text if JSON parsing fails - treat as potential error
            if text_content and text_content not in ("success", "ok"):
                # Try to detect if it's an error by content
                text_lower = text_content.lower()
                if any(word in text_lower for word in ("error", "failed", "invalid", "cannot")):
                    return f"Error: {text_content}"
            return text_content if text_content else success_message
