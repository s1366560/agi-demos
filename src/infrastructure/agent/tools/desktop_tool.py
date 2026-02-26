"""Desktop management tool for ReAct agent.

Provides tools for starting, stopping, and checking the status of
remote desktop sessions in sandbox environments.

Refactored to use SandboxOrchestrator for unified sandbox service management.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, override

if TYPE_CHECKING:
    from src.domain.ports.services.sandbox_port import SandboxPort


from src.application.services.sandbox_orchestrator import (
    DesktopConfig,
    DesktopStatus,
    SandboxOrchestrator,
)
from src.infrastructure.agent.tools.base import AgentTool
from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.define import tool_define
from src.infrastructure.agent.tools.result import ToolResult

logger = logging.getLogger(__name__)


class DesktopTool(AgentTool):
    """
    Tool for managing remote desktop sessions.

    Provides the ability to start, stop, and check the status of
    desktop environments accessible via KasmVNC in a web browser.

    Uses SandboxOrchestrator for unified sandbox service management.

    Actions:
        - start: Launch the remote desktop server
        - stop: Stop the running desktop server
        - status: Get current desktop status

    Example:
        tool = DesktopTool(orchestrator=orchestrator, sandbox_id="sb-123")
        result = await tool.execute(action="start", resolution="1920x1080")
    """

    def __init__(
        self,
        orchestrator: SandboxOrchestrator | None = None,
        sandbox_adapter: SandboxPort | None = None,
        sandbox_id: str = "test_sandbox",
    ) -> None:
        """
        Initialize the DesktopTool.

        Args:
            orchestrator: SandboxOrchestrator for unified sandbox operations
            sandbox_adapter: Legacy adapter for backwards compatibility (deprecated)
            sandbox_id: ID of the sandbox to manage
        """
        super().__init__(
            name="desktop",
            description="Manage remote desktop sessions (KasmVNC) for browser-based GUI access. "
            "Actions: start, stop, status. Example: action='start', resolution='1920x1080'",
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
                    "description": "Action to perform: 'start' to launch desktop, 'stop' to shutdown, 'status' to check state",
                },
                "resolution": {
                    "type": "string",
                    "description": "Screen resolution (e.g., '1920x1080', '2560x1440')",
                    "default": "1920x1080",
                },
                "display": {
                    "type": "string",
                    "description": "X11 display number (e.g., ':1', ':2')",
                    "default": ":1",
                },
                "port": {
                    "type": "integer",
                    "description": "Port for KasmVNC web server",
                    "default": 6080,
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
            # Use SandboxOrchestrator if available
            if self._orchestrator:
                config = DesktopConfig(
                    resolution=kwargs.get("resolution", "1280x720"),
                    display=kwargs.get("display", ":1"),
                    port=kwargs.get("port", 6080),
                )
                status = await self._orchestrator.start_desktop(self._sandbox_id, config)
                return self._format_status(status, "Desktop started successfully")
            else:
                # Fallback to direct adapter call (legacy path)
                return await self._start_desktop_legacy(**kwargs)

        except Exception as e:
            logger.error(f"Failed to start desktop: {e}")
            return f"Error: Failed to start desktop - {e!s}"

    async def _start_desktop_legacy(self, **kwargs: Any) -> str:
        """Legacy start_desktop using direct adapter call."""
        if not self._sandbox_adapter:
            return "Error: No orchestrator or sandbox adapter available"

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

        return self._format_legacy_result(result, "Desktop started successfully")

    async def _stop_desktop(self) -> str:
        """
        Stop the remote desktop server.

        Returns:
            Status message
        """
        try:
            if self._orchestrator:
                success = await self._orchestrator.stop_desktop(self._sandbox_id)
                if success:
                    return "Desktop stopped successfully"
                else:
                    return "Desktop stop operation failed"
            else:
                return await self._stop_desktop_legacy()

        except Exception as e:
            logger.error(f"Failed to stop desktop: {e}")
            return f"Error: Failed to stop desktop - {e!s}"

    async def _stop_desktop_legacy(self) -> str:
        """Legacy stop_desktop using direct adapter call."""
        if not self._sandbox_adapter:
            return "Error: No orchestrator or sandbox adapter available"

        result = await self._sandbox_adapter.call_tool(
            self._sandbox_id,
            "stop_desktop",
            {"_workspace_dir": "/workspace"},
        )

        return self._format_legacy_result(result, "Desktop stopped successfully")

    async def _get_desktop_status(self) -> str:
        """
        Get the current desktop status.

        Returns:
            Status message with desktop information
        """
        try:
            if self._orchestrator:
                status = await self._orchestrator.get_desktop_status(self._sandbox_id)
                return self._format_status(status, "Desktop status retrieved")
            else:
                return await self._get_desktop_status_legacy()

        except Exception as e:
            logger.error(f"Failed to get desktop status: {e}")
            return f"Error: Failed to get desktop status - {e!s}"

    async def _get_desktop_status_legacy(self) -> str:
        """Legacy get_desktop_status using direct adapter call."""
        if not self._sandbox_adapter:
            return "Error: No orchestrator or sandbox adapter available"

        result = await self._sandbox_adapter.call_tool(
            self._sandbox_id,
            "get_desktop_status",
            {"_workspace_dir": "/workspace"},
        )

        return self._format_legacy_result(result, "Desktop status retrieved")

    def _format_status(self, status: DesktopStatus, success_message: str) -> str:
        """
        Format DesktopStatus into a readable message.

        Args:
            status: DesktopStatus object
            success_message: Default message on success

        Returns:
            Formatted status message
        """
        parts = []
        if status.running:
            parts.append("Desktop is running")
        else:
            parts.append("Desktop is not running")

        if status.url:
            parts.append(f"URL: {status.url}")
        if status.port:
            parts.append(f"Port: {status.port}")
        if status.display:
            parts.append(f"Display: {status.display}")
        if status.resolution:
            parts.append(f"Resolution: {status.resolution}")
        if status.pid:
            parts.append(f"PID: {status.pid}")
        if status.running:
            parts.append(f"Encoding: {status.encoding}")
            parts.append(f"Audio: {'on' if status.audio_enabled else 'off'}")
            parts.append(f"Dynamic resize: {'yes' if status.dynamic_resize else 'no'}")

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
            return self._extract_error_content(result, "Desktop operation failed")

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
            parts.append("Desktop is running")
        else:
            parts.append("Desktop is not running")
        if data.get("url"):
            parts.append(f"URL: {data['url']}")
        if "port" in data:
            parts.append(f"Port: {data['port']}")
        if "display" in data:
            parts.append(f"Display: {data['display']}")
        if "resolution" in data:
            parts.append(f"Resolution: {data['resolution']}")
        return " | ".join(parts) if parts else "Desktop status retrieved"

    @staticmethod
    def _format_success_data(data: dict[str, Any], success_message: str) -> str:
        """Format success response data."""
        parts = [success_message]
        if data.get("url"):
            parts.append(f"URL: {data['url']}")
        if "port" in data:
            parts.append(f"Port: {data['port']}")
        if "display" in data:
            parts.append(f"Display: {data['display']}")
        if "resolution" in data:
            parts.append(f"Resolution: {data['resolution']}")
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

_desktop_sandbox_orchestrator: Any = None
_desktop_sandbox_port: Any = None
_desktop_sandbox_id: str = ""


def configure_desktop(
    sandbox_orchestrator: Any = None,
    sandbox_port: Any = None,
    sandbox_id: str = "",
) -> None:
    """Configure dependencies for the desktop tool."""
    global _desktop_sandbox_orchestrator, _desktop_sandbox_port
    global _desktop_sandbox_id
    _desktop_sandbox_orchestrator = sandbox_orchestrator
    _desktop_sandbox_port = sandbox_port
    _desktop_sandbox_id = sandbox_id


# ---------------------------------------------------------------------------
# Helper functions (extracted from class methods)
# ---------------------------------------------------------------------------


def _fmt_desktop_status(
    status: DesktopStatus,
    success_message: str,
) -> str:
    """Format DesktopStatus into a readable message."""
    parts: list[str] = []
    if status.running:
        parts.append("Desktop is running")
    else:
        parts.append("Desktop is not running")
    if status.url:
        parts.append(f"URL: {status.url}")
    if status.port:
        parts.append(f"Port: {status.port}")
    if status.display:
        parts.append(f"Display: {status.display}")
    if status.resolution:
        parts.append(f"Resolution: {status.resolution}")
    if status.pid:
        parts.append(f"PID: {status.pid}")
    if status.running:
        parts.append(f"Encoding: {status.encoding}")
        parts.append(f"Audio: {'on' if status.audio_enabled else 'off'}")
        parts.append(f"Dynamic resize: {'yes' if status.dynamic_resize else 'no'}")
    return " | ".join(parts) if parts else success_message


def _fmt_desktop_legacy(
    result: dict[str, Any],
    success_message: str,
) -> str:
    """Format the result from legacy MCP tool call."""
    import json as _json

    early = _extract_desktop_legacy_text(result, success_message)
    if early is not None:
        return early

    content_list = result.get("content", [])
    text_content = _desktop_text_from_content(content_list)

    try:
        data = _json.loads(text_content)
        if "running" in data:
            return _fmt_desktop_legacy_status(data)
        if data.get("success"):
            return _fmt_desktop_legacy_success(data, success_message)
        return f"Error: {data.get('error', 'Unknown error')}"
    except (_json.JSONDecodeError, ValueError):
        return _desktop_text_fallback(text_content, success_message)


def _extract_desktop_legacy_text(
    result: dict[str, Any],
    success_message: str,
) -> str | None:
    """Extract text or return early for error/empty results."""
    if result.get("is_error"):
        content_list = result.get("content", [])
        if content_list and len(content_list) > 0:
            return f"Error: {content_list[0].get('text', 'Unknown error')}"
        return "Error: Desktop operation failed"
    content_list = result.get("content", [])
    if not content_list:
        return success_message
    return None


def _desktop_text_from_content(
    content_list: list[Any],
) -> str:
    """Get text from the first content item."""
    first = content_list[0]
    if isinstance(first, dict):
        return first.get("text", "")  # type: ignore[no-any-return]
    return str(first)


def _fmt_desktop_legacy_status(
    data: dict[str, Any],
) -> str:
    """Format status data with 'running' field."""
    parts: list[str] = []
    if data.get("running"):
        parts.append("Desktop is running")
    else:
        parts.append("Desktop is not running")
    if data.get("url"):
        parts.append(f"URL: {data['url']}")
    if "port" in data:
        parts.append(f"Port: {data['port']}")
    if "display" in data:
        parts.append(f"Display: {data['display']}")
    if "resolution" in data:
        parts.append(f"Resolution: {data['resolution']}")
    return " | ".join(parts) if parts else "Desktop status retrieved"


def _fmt_desktop_legacy_success(
    data: dict[str, Any],
    success_message: str,
) -> str:
    """Format success data from legacy MCP result."""
    parts = [success_message]
    if data.get("url"):
        parts.append(f"URL: {data['url']}")
    if "port" in data:
        parts.append(f"Port: {data['port']}")
    if "display" in data:
        parts.append(f"Display: {data['display']}")
    if "resolution" in data:
        parts.append(f"Resolution: {data['resolution']}")
    return " | ".join(parts)


def _desktop_text_fallback(
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
# Per-action helpers for desktop_tool()
# ---------------------------------------------------------------------------


async def _desktop_start(
    orchestrator: SandboxOrchestrator | None,
    adapter: SandboxPort | None,
    sandbox_id: str,
    resolution: str,
    display: str,
    port: int,
) -> ToolResult:
    """Handle the 'start' action for desktop_tool."""
    try:
        if orchestrator:
            config = DesktopConfig(
                resolution=resolution,
                display=display,
                port=port,
            )
            status = await orchestrator.start_desktop(sandbox_id, config)
            msg = _fmt_desktop_status(status, "Desktop started successfully")
            return ToolResult(output=msg)
        if adapter:
            mcp_args: dict[str, Any] = {
                "_workspace_dir": "/workspace",
            }
            if resolution != "1920x1080":
                mcp_args["resolution"] = resolution
            if display != ":1":
                mcp_args["display"] = display
            if port != 6080:
                mcp_args["port"] = port
            raw = await adapter.call_tool(sandbox_id, "start_desktop", mcp_args)
            msg = _fmt_desktop_legacy(raw, "Desktop started successfully")
            return ToolResult(output=msg)
        return ToolResult(
            output=("Error: No orchestrator or sandbox adapter available"),
            is_error=True,
        )
    except Exception as exc:
        logger.error("Failed to start desktop: %s", exc)
        return ToolResult(
            output=(f"Error: Failed to start desktop - {exc!s}"),
            is_error=True,
        )


async def _desktop_stop(
    orchestrator: SandboxOrchestrator | None,
    adapter: SandboxPort | None,
    sandbox_id: str,
) -> ToolResult:
    """Handle the 'stop' action for desktop_tool."""
    try:
        if orchestrator:
            success = await orchestrator.stop_desktop(sandbox_id)
            if success:
                return ToolResult(output="Desktop stopped successfully")
            return ToolResult(
                output="Desktop stop operation failed",
                is_error=True,
            )
        if adapter:
            raw = await adapter.call_tool(
                sandbox_id,
                "stop_desktop",
                {"_workspace_dir": "/workspace"},
            )
            msg = _fmt_desktop_legacy(raw, "Desktop stopped successfully")
            return ToolResult(output=msg)
        return ToolResult(
            output=("Error: No orchestrator or sandbox adapter available"),
            is_error=True,
        )
    except Exception as exc:
        logger.error("Failed to stop desktop: %s", exc)
        return ToolResult(
            output=(f"Error: Failed to stop desktop - {exc!s}"),
            is_error=True,
        )


async def _desktop_get_status(
    orchestrator: SandboxOrchestrator | None,
    adapter: SandboxPort | None,
    sandbox_id: str,
) -> ToolResult:
    """Handle the 'status' action for desktop_tool."""
    try:
        if orchestrator:
            status = await orchestrator.get_desktop_status(sandbox_id)
            msg = _fmt_desktop_status(status, "Desktop status retrieved")
            return ToolResult(output=msg)
        if adapter:
            raw = await adapter.call_tool(
                sandbox_id,
                "get_desktop_status",
                {"_workspace_dir": "/workspace"},
            )
            msg = _fmt_desktop_legacy(raw, "Desktop status retrieved")
            return ToolResult(output=msg)
        return ToolResult(
            output=("Error: No orchestrator or sandbox adapter available"),
            is_error=True,
        )
    except Exception as exc:
        logger.error("Failed to get desktop status: %s", exc)
        return ToolResult(
            output=(f"Error: Failed to get desktop status - {exc!s}"),
            is_error=True,
        )


# ---------------------------------------------------------------------------
# Tool definition
# ---------------------------------------------------------------------------


@tool_define(
    name="desktop",
    description=(
        "Manage remote desktop sessions (KasmVNC) for "
        "browser-based GUI access. "
        "Actions: start, stop, status. "
        "Example: action='start', resolution='1920x1080'"
    ),
    parameters={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["start", "stop", "status"],
                "description": (
                    "Action to perform: 'start' to launch "
                    "desktop, 'stop' to shutdown, "
                    "'status' to check state"
                ),
            },
            "resolution": {
                "type": "string",
                "description": ("Screen resolution (e.g., '1920x1080', '2560x1440')"),
                "default": "1920x1080",
            },
            "display": {
                "type": "string",
                "description": ("X11 display number (e.g., ':1', ':2')"),
                "default": ":1",
            },
            "port": {
                "type": "integer",
                "description": ("Port for KasmVNC web server"),
                "default": 6080,
            },
        },
        "required": ["action"],
    },
    permission="desktop",
    category="sandbox",
    tags=frozenset({"desktop", "sandbox", "ui"}),
)
async def desktop_tool(
    ctx: ToolContext,
    *,
    action: str,
    resolution: str = "1920x1080",
    display: str = ":1",
    port: int = 6080,
) -> ToolResult:
    """Manage remote desktop sessions via @tool_define."""
    orchestrator: SandboxOrchestrator | None = _desktop_sandbox_orchestrator
    adapter: SandboxPort | None = _desktop_sandbox_port
    sandbox_id = _desktop_sandbox_id

    if action == "start":
        return await _desktop_start(
            orchestrator,
            adapter,
            sandbox_id,
            resolution,
            display,
            port,
        )
    if action == "stop":
        return await _desktop_stop(orchestrator, adapter, sandbox_id)
    if action == "status":
        return await _desktop_get_status(orchestrator, adapter, sandbox_id)
    return ToolResult(
        output=(f"Error: Unknown action '{action}'. Valid actions are: start, stop, status"),
        is_error=True,
    )
