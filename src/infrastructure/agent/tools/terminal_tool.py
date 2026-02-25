"""Terminal management tool for ReAct agent.

Provides tools for starting, stopping, and checking the status of
web terminal sessions in sandbox environments.

Refactored to use SandboxOrchestrator for unified sandbox service management.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, override

if TYPE_CHECKING:
    from src.domain.ports.services.sandbox_port import SandboxPort


from src.application.services.sandbox_orchestrator import (
    SandboxOrchestrator,
    TerminalConfig,
    TerminalStatus,
)
from src.infrastructure.agent.tools.base import AgentTool

logger = logging.getLogger(__name__)


class TerminalTool(AgentTool):
    """
    Tool for managing web terminal sessions.

    Provides the ability to start, stop, and check the status of
    ttyd-based terminal sessions accessible via WebSocket.

    Uses SandboxOrchestrator for unified sandbox service management.

    Actions:
        - start: Launch the web terminal server
        - stop: Stop the running terminal server
        - status: Get current terminal status

    Example:
        tool = TerminalTool(orchestrator=orchestrator, sandbox_id="sb-123")
        result = await tool.execute(action="start")
    """

    def __init__(
        self,
        orchestrator: SandboxOrchestrator | None = None,
        sandbox_adapter: SandboxPort | None = None,
        sandbox_id: str = "test_sandbox",
    ) -> None:
        """
        Initialize the TerminalTool.

        Args:
            orchestrator: SandboxOrchestrator for unified sandbox operations
            sandbox_adapter: Legacy adapter for backwards compatibility (deprecated)
            sandbox_id: ID of the sandbox to manage
        """
        super().__init__(
            name="terminal",
            description="Manage web terminal sessions (ttyd) for browser-based shell access. "
            "Actions: start, stop, status. Example: action='start', port=7681",
        )
        self._orchestrator = orchestrator
        self._sandbox_adapter = sandbox_adapter
        self._sandbox_id = sandbox_id

    @override
    def get_parameters_schema(self) -> dict[str, Any]:
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

    @override
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

    @override
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
            # Use SandboxOrchestrator if available
            if self._orchestrator:
                config = TerminalConfig(
                    port=kwargs.get("port", 7681),
                    shell="/bin/bash",
                )
                status = await self._orchestrator.start_terminal(self._sandbox_id, config)
                return self._format_status(status, "Terminal started successfully")
            else:
                # Fallback to direct adapter call (legacy path)
                return await self._start_terminal_legacy(**kwargs)

        except Exception as e:
            logger.error(f"Failed to start terminal: {e}")
            return f"Error: Failed to start terminal - {e!s}"

    async def _start_terminal_legacy(self, **kwargs: Any) -> str:
        """Legacy start_terminal using direct adapter call."""
        if not self._sandbox_adapter:
            return "Error: No orchestrator or sandbox adapter available"

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

        return self._format_legacy_result(result, "Terminal started successfully")

    async def _stop_terminal(self) -> str:
        """
        Stop the web terminal server.

        Returns:
            Status message
        """
        try:
            if self._orchestrator:
                success = await self._orchestrator.stop_terminal(self._sandbox_id)
                if success:
                    return "Terminal stopped successfully"
                else:
                    return "Terminal stop operation failed"
            else:
                return await self._stop_terminal_legacy()

        except Exception as e:
            logger.error(f"Failed to stop terminal: {e}")
            return f"Error: Failed to stop terminal - {e!s}"

    async def _stop_terminal_legacy(self) -> str:
        """Legacy stop_terminal using direct adapter call."""
        if not self._sandbox_adapter:
            return "Error: No orchestrator or sandbox adapter available"

        result = await self._sandbox_adapter.call_tool(
            self._sandbox_id,
            "stop_terminal",
            {"_workspace_dir": "/workspace"},
        )

        return self._format_legacy_result(result, "Terminal stopped successfully")

    async def _get_terminal_status(self) -> str:
        """
        Get the current terminal status.

        Returns:
            Status message with terminal information
        """
        try:
            if self._orchestrator:
                status = await self._orchestrator.get_terminal_status(self._sandbox_id)
                return self._format_status(status, "Terminal status retrieved")
            else:
                return await self._get_terminal_status_legacy()

        except Exception as e:
            logger.error(f"Failed to get terminal status: {e}")
            return f"Error: Failed to get terminal status - {e!s}"

    async def _get_terminal_status_legacy(self) -> str:
        """Legacy get_terminal_status using direct adapter call."""
        if not self._sandbox_adapter:
            return "Error: No orchestrator or sandbox adapter available"

        result = await self._sandbox_adapter.call_tool(
            self._sandbox_id,
            "get_terminal_status",
            {"_workspace_dir": "/workspace"},
        )

        return self._format_legacy_result(result, "Terminal status retrieved")

    def _format_status(self, status: TerminalStatus, success_message: str) -> str:
        """
        Format TerminalStatus into a readable message.

        Args:
            status: TerminalStatus object
            success_message: Default message on success

        Returns:
            Formatted status message
        """
        parts = []
        if status.running:
            parts.append("Terminal is running")
        else:
            parts.append("Terminal is not running")

        if status.url:
            parts.append(f"URL: {status.url}")
        if status.port:
            parts.append(f"Port: {status.port}")
        if status.session_id:
            parts.append(f"Session: {status.session_id}")
        if status.pid:
            parts.append(f"PID: {status.pid}")

        return " | ".join(parts) if parts else success_message

    def _format_legacy_result(self, result: dict[str, Any], success_message: str) -> str:
        """
        Format the result from legacy MCP tool call.
        Args:
            result: Raw result from sandbox adapter
            success_message: Default message on success
            Formatted status message
        """
        if result.get("is_error"):
            return self._extract_error_content(result, "Terminal operation failed")

        content_list = result.get("content", [])
        if not content_list:
            return success_message
        # Extract text from first content item
        text_content = (
            content_list[0].get("text", "")
            if isinstance(content_list[0], dict)
            else str(content_list[0])
        )
        return self._parse_legacy_text(text_content, success_message)

    @staticmethod
    def _extract_error_content(result: dict[str, Any], fallback: str) -> str:
        """Extract error message from MCP result content list."""
        content_list = result.get("content", [])
        if content_list and len(content_list) > 0:
            return f"Error: {content_list[0].get('text', 'Unknown error')}"
        return f"Error: {fallback}"

    def _parse_legacy_text(self, text_content: str, success_message: str) -> str:
        """Parse JSON text content from legacy MCP result."""
        import json

        try:
            data = json.loads(text_content)
            if "running" in data:
                return self._format_status_data(data)
            if data.get("success"):
                return self._format_success_data(data, success_message)
            return f"Error: {data.get('error', 'Unknown error')}"
        except (json.JSONDecodeError, ValueError):
            return self._handle_json_parse_fallback(text_content, success_message)

    @staticmethod
    def _format_status_data(data: dict[str, Any]) -> str:
        """Format status response data with 'running' field."""
        parts = []
        if data.get("running"):
            parts.append("Terminal is running")
        else:
            parts.append("Terminal is not running")
        if data.get("url"):
            parts.append(f"URL: {data['url']}")
        if "port" in data:
            parts.append(f"Port: {data['port']}")
        if data.get("pid"):
            parts.append(f"PID: {data['pid']}")
        return " | ".join(parts) if parts else "Terminal status retrieved"

    @staticmethod
    def _format_success_data(data: dict[str, Any], success_message: str) -> str:
        """Format success response data."""
        parts = [success_message]
        if data.get("url"):
            parts.append(f"URL: {data['url']}")
        if "port" in data:
            parts.append(f"Port: {data['port']}")
        if data.get("pid"):
            parts.append(f"PID: {data['pid']}")
        return " | ".join(parts)

    @staticmethod
    def _handle_json_parse_fallback(text_content: str, success_message: str) -> str:
        """Handle non-JSON text content from legacy MCP result."""
        if text_content and text_content not in ("success", "ok"):
            text_lower = text_content.lower()
            if any(word in text_lower for word in ("error", "failed", "invalid", "cannot")):
                return f"Error: {text_content}"
        return text_content if text_content else success_message
