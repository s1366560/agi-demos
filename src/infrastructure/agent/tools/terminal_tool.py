"""Terminal management tool for ReAct agent.

Provides tools for starting, stopping, and checking the status of
web terminal sessions in sandbox environments.

Refactored to use SandboxOrchestrator for unified sandbox service management.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.domain.ports.services.sandbox_port import SandboxPort


from src.application.services.sandbox_orchestrator import (
    SandboxOrchestrator,
    TerminalConfig,
    TerminalStatus,
)
from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.define import tool_define
from src.infrastructure.agent.tools.result import ToolResult

logger = logging.getLogger(__name__)


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
