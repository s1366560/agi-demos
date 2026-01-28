"""Terminal management tool for ReAct agent.

Provides tools for starting, stopping, and checking the status of
web terminal sessions in sandbox environments.
"""

import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional

from src.infrastructure.agent.tools.base import AgentTool

logger = logging.getLogger(__name__)


@dataclass
class TerminalStatus:
    """Status of the web terminal."""

    running: bool
    url: Optional[str] = None
    port: int = 7681
    session_id: Optional[str] = None


class TerminalTool(AgentTool):
    """
    Tool for managing web terminal sessions.

    Provides the ability to start, stop, and check the status of
    ttyd-based terminal sessions accessible via WebSocket.

    Actions:
        - start: Launch the web terminal server
        - stop: Stop the running terminal server
        - status: Get current terminal status

    Example:
        tool = TerminalTool(sandbox_adapter)
        result = await tool.execute(action="start")
    """

    def __init__(self, sandbox_adapter: Any, sandbox_id: str = "test_sandbox"):
        """
        Initialize the TerminalTool.

        Args:
            sandbox_adapter: Adapter for communicating with sandbox
            sandbox_id: ID of the sandbox to manage
        """
        super().__init__(
            name="terminal",
            description="Manage web terminal sessions (ttyd) for browser-based shell access. "
            "Actions: start, stop, status. Example: action='start', port=7681",
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
                    "description": "Action to perform: 'start' to launch terminal, 'stop' to shutdown, 'status' to check state",
                },
                "port": {
                    "type": "integer",
                    "description": "Port for the ttyd WebSocket server",
                    "default": 7681,
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
        Execute the terminal tool with the given arguments.

        Args:
            **kwargs: Tool-specific arguments including:
                - action: The action to perform (start/stop/status)
                - port: Port number for ttyd server

        Returns:
            String result of the tool execution

        Raises:
            ValueError: If action is invalid
        """
        action = kwargs.get("action")

        if action == "start":
            return await self._start_terminal(**kwargs)
        elif action == "stop":
            return await self._stop_terminal()
        elif action == "status":
            return await self._get_terminal_status()
        else:
            return f"Error: Unknown action '{action}'. Valid actions are: start, stop, status"

    async def _start_terminal(self, **kwargs: Any) -> str:
        """
        Start the web terminal server.

        Args:
            **kwargs: Optional parameters (port)

        Returns:
            Status message with connection URL
        """
        try:
            # Prepare arguments for MCP tool call
            mcp_args = {"_workspace_dir": "/workspace"}

            if "port" in kwargs:
                mcp_args["port"] = kwargs["port"]

            # Call MCP tool via sandbox adapter
            result = await self._sandbox_adapter.call_tool(
                self._sandbox_id,
                "start_terminal",
                mcp_args,
            )

            return self._format_result(result, "Terminal started successfully")

        except Exception as e:
            logger.error(f"Failed to start terminal: {e}")
            return f"Error: Failed to start terminal - {str(e)}"

    async def _stop_terminal(self) -> str:
        """
        Stop the web terminal server.

        Returns:
            Status message
        """
        try:
            result = await self._sandbox_adapter.call_tool(
                self._sandbox_id,
                "stop_terminal",
                {"_workspace_dir": "/workspace"},
            )

            return self._format_result(result, "Terminal stopped successfully")

        except Exception as e:
            logger.error(f"Failed to stop terminal: {e}")
            return f"Error: Failed to stop terminal - {str(e)}"

    async def _get_terminal_status(self) -> str:
        """
        Get the current terminal status.

        Returns:
            Status message with terminal information
        """
        try:
            result = await self._sandbox_adapter.call_tool(
                self._sandbox_id,
                "get_terminal_status",
                {"_workspace_dir": "/workspace"},
            )

            return self._format_result(result, "Terminal status retrieved")

        except Exception as e:
            logger.error(f"Failed to get terminal status: {e}")
            return f"Error: Failed to get terminal status - {str(e)}"

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
            return "Error: Terminal operation failed"

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
                    parts.append("Terminal is running")
                else:
                    parts.append("Terminal is not running")

                if "url" in data and data["url"]:
                    parts.append(f"URL: {data['url']}")
                if "port" in data:
                    parts.append(f"Port: {data['port']}")
                if "pid" in data and data["pid"]:
                    parts.append(f"PID: {data['pid']}")

                return " | ".join(parts) if parts else "Terminal status retrieved"

            # Handle success/error response
            if data.get("success"):
                parts = [success_message]
                if "url" in data and data["url"]:
                    parts.append(f"URL: {data['url']}")
                if "port" in data:
                    parts.append(f"Port: {data['port']}")
                if "pid" in data and data["pid"]:
                    parts.append(f"PID: {data['pid']}")

                return " | ".join(parts)
            else:
                error = data.get("error", "Unknown error")
                return f"Error: {error}"

        except (json.JSONDecodeError, ValueError):
            # Return raw text if JSON parsing fails
            return text_content if text_content else success_message
