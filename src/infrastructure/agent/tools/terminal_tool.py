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
from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.define import tool_define
from src.infrastructure.agent.tools.result import ToolResult

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


# === New @tool_define based implementation ===

# ---------------------------------------------------------------------------
# Module-level state for dependency injection
# ---------------------------------------------------------------------------

_terminal_sandbox_orchestrator: Any = None
_terminal_sandbox_port: Any = None
_terminal_sandbox_id: str = ""


def configure_terminal(
    sandbox_orchestrator: Any = None,
    sandbox_port: Any = None,
    sandbox_id: str = "",
) -> None:
    """Configure dependencies for the terminal tool."""
    global _terminal_sandbox_orchestrator, _terminal_sandbox_port
    global _terminal_sandbox_id
    _terminal_sandbox_orchestrator = sandbox_orchestrator
    _terminal_sandbox_port = sandbox_port
    _terminal_sandbox_id = sandbox_id


# ---------------------------------------------------------------------------
# Helper functions (extracted from class methods)
# ---------------------------------------------------------------------------


def _fmt_terminal_status(
    status: TerminalStatus,
    success_message: str,
) -> str:
    """Format TerminalStatus into a readable message."""
    parts: list[str] = []
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


def _extract_legacy_text(
    result: dict[str, Any],
    success_message: str,
    fallback_error: str,
) -> str | None:
    """Extract text content from legacy MCP result.

    Returns the text string, or None if result is an error
    or has no content (caller handles those).
    """
    if result.get("is_error"):
        content_list = result.get("content", [])
        if content_list and len(content_list) > 0:
            return f"Error: {content_list[0].get('text', 'Unknown error')}"
        return f"Error: {fallback_error}"
    content_list = result.get("content", [])
    if not content_list:
        return success_message
    return None


def _legacy_text_from_content(
    content_list: list[Any],
) -> str:
    """Get text from the first content item."""
    first = content_list[0]
    if isinstance(first, dict):
        return first.get("text", "")  # type: ignore[no-any-return]
    return str(first)


def _fmt_terminal_legacy_status(data: dict[str, Any]) -> str:
    """Format status data with 'running' field."""
    parts: list[str] = []
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


def _fmt_terminal_legacy(
    result: dict[str, Any],
    success_message: str,
) -> str:
    """Format the result from legacy MCP tool call."""
    import json as _json

    early = _extract_legacy_text(result, success_message, "Terminal operation failed")
    if early is not None:
        return early

    content_list = result.get("content", [])
    text_content = _legacy_text_from_content(content_list)

    try:
        data = _json.loads(text_content)
        if "running" in data:
            return _fmt_terminal_legacy_status(data)
        if data.get("success"):
            parts = [success_message]
            if data.get("url"):
                parts.append(f"URL: {data['url']}")
            if "port" in data:
                parts.append(f"Port: {data['port']}")
            if data.get("pid"):
                parts.append(f"PID: {data['pid']}")
            return " | ".join(parts)
        return f"Error: {data.get('error', 'Unknown error')}"
    except (_json.JSONDecodeError, ValueError):
        return _handle_text_fallback(text_content, success_message)


def _handle_text_fallback(
    text_content: str,
    success_message: str,
) -> str:
    """Handle non-JSON text content from legacy MCP result."""
    if text_content and text_content not in ("success", "ok"):
        text_lower = text_content.lower()
        err_words = ("error", "failed", "invalid", "cannot")
        if any(w in text_lower for w in err_words):
            return f"Error: {text_content}"
    return text_content if text_content else success_message


# ---------------------------------------------------------------------------
# Per-action helpers for terminal_tool()
# ---------------------------------------------------------------------------


async def _terminal_start(
    orchestrator: SandboxOrchestrator | None,
    adapter: SandboxPort | None,
    sandbox_id: str,
    port: int,
) -> ToolResult:
    """Handle the 'start' action for terminal_tool."""
    try:
        if orchestrator:
            config = TerminalConfig(
                port=port,
                shell="/bin/bash",
            )
            status = await orchestrator.start_terminal(sandbox_id, config)
            msg = _fmt_terminal_status(status, "Terminal started successfully")
            return ToolResult(output=msg)
        if adapter:
            mcp_args: dict[str, Any] = {
                "_workspace_dir": "/workspace",
            }
            if port != 7681:
                mcp_args["port"] = port
            raw = await adapter.call_tool(sandbox_id, "start_terminal", mcp_args)
            msg = _fmt_terminal_legacy(raw, "Terminal started successfully")
            return ToolResult(output=msg)
        return ToolResult(
            output=("Error: No orchestrator or sandbox adapter available"),
            is_error=True,
        )
    except Exception as exc:
        logger.error("Failed to start terminal: %s", exc)
        return ToolResult(
            output=f"Error: Failed to start terminal - {exc!s}",
            is_error=True,
        )


async def _terminal_stop(
    orchestrator: SandboxOrchestrator | None,
    adapter: SandboxPort | None,
    sandbox_id: str,
) -> ToolResult:
    """Handle the 'stop' action for terminal_tool."""
    try:
        if orchestrator:
            success = await orchestrator.stop_terminal(sandbox_id)
            if success:
                return ToolResult(output="Terminal stopped successfully")
            return ToolResult(
                output="Terminal stop operation failed",
                is_error=True,
            )
        if adapter:
            raw = await adapter.call_tool(
                sandbox_id,
                "stop_terminal",
                {"_workspace_dir": "/workspace"},
            )
            msg = _fmt_terminal_legacy(raw, "Terminal stopped successfully")
            return ToolResult(output=msg)
        return ToolResult(
            output=("Error: No orchestrator or sandbox adapter available"),
            is_error=True,
        )
    except Exception as exc:
        logger.error("Failed to stop terminal: %s", exc)
        return ToolResult(
            output=f"Error: Failed to stop terminal - {exc!s}",
            is_error=True,
        )


async def _terminal_status(
    orchestrator: SandboxOrchestrator | None,
    adapter: SandboxPort | None,
    sandbox_id: str,
) -> ToolResult:
    """Handle the 'status' action for terminal_tool."""
    try:
        if orchestrator:
            status = await orchestrator.get_terminal_status(sandbox_id)
            msg = _fmt_terminal_status(status, "Terminal status retrieved")
            return ToolResult(output=msg)
        if adapter:
            raw = await adapter.call_tool(
                sandbox_id,
                "get_terminal_status",
                {"_workspace_dir": "/workspace"},
            )
            msg = _fmt_terminal_legacy(raw, "Terminal status retrieved")
            return ToolResult(output=msg)
        return ToolResult(
            output=("Error: No orchestrator or sandbox adapter available"),
            is_error=True,
        )
    except Exception as exc:
        logger.error("Failed to get terminal status: %s", exc)
        return ToolResult(
            output=(f"Error: Failed to get terminal status - {exc!s}"),
            is_error=True,
        )


# ---------------------------------------------------------------------------
# Tool definition
# ---------------------------------------------------------------------------


@tool_define(
    name="terminal",
    description=(
        "Manage web terminal sessions (ttyd) for browser-based "
        "shell access. Actions: start, stop, status. "
        "Example: action='start', port=7681"
    ),
    parameters={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["start", "stop", "status"],
                "description": (
                    "Action to perform: 'start' to launch "
                    "terminal, 'stop' to shutdown, "
                    "'status' to check state"
                ),
            },
            "port": {
                "type": "integer",
                "description": ("Port for the ttyd WebSocket server"),
                "default": 7681,
            },
        },
        "required": ["action"],
    },
    permission="terminal",
    category="sandbox",
    tags=frozenset({"terminal", "sandbox", "shell"}),
)
async def terminal_tool(
    ctx: ToolContext,
    *,
    action: str,
    port: int = 7681,
) -> ToolResult:
    """Manage web terminal sessions via @tool_define."""
    orchestrator: SandboxOrchestrator | None = _terminal_sandbox_orchestrator
    adapter: SandboxPort | None = _terminal_sandbox_port
    sandbox_id = _terminal_sandbox_id

    if action == "start":
        return await _terminal_start(orchestrator, adapter, sandbox_id, port)
    if action == "stop":
        return await _terminal_stop(orchestrator, adapter, sandbox_id)
    if action == "status":
        return await _terminal_status(orchestrator, adapter, sandbox_id)
    return ToolResult(
        output=(f"Error: Unknown action '{action}'. Valid actions are: start, stop, status"),
        is_error=True,
    )
