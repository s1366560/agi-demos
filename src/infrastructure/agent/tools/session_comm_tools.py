"""Agent-to-agent session communication tools.

Three tools that let agents discover peer sessions, read their
history, and send messages -- enabling multi-agent collaboration
within the same project scope.

Uses the ``@tool_define`` decorator pattern with module-level DI
via ``configure_session_comm()``.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from src.application.services.session_comm_service import (
    SessionCommService,
)
from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.define import tool_define
from src.infrastructure.agent.tools.result import ToolResult

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level DI state
# ---------------------------------------------------------------------------

_session_comm_service: SessionCommService | None = None


def configure_session_comm(service: SessionCommService) -> None:
    """Inject the ``SessionCommService`` at agent startup.

    Args:
        service: A fully constructed ``SessionCommService``.
    """
    global _session_comm_service
    _session_comm_service = service


def _svc() -> SessionCommService:
    """Return the configured service or raise."""
    if _session_comm_service is None:
        raise RuntimeError(
            "session_comm tools not configured -- call configure_session_comm() first"
        )
    return _session_comm_service


def _json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, default=str)


# ---------------------------------------------------------------------------
# peer_sessions_list
# ---------------------------------------------------------------------------


@tool_define(
    name="peer_sessions_list",
    description=(
        "List other active peer agent sessions (conversations) in the "
        "current project. Use this to discover peer agents you can "
        "collaborate with. Returns session IDs, titles, message "
        "counts, and timestamps."
    ),
    parameters={
        "type": "object",
        "properties": {
            "status_filter": {
                "type": "string",
                "description": ("Optional status filter: 'active' or 'archived'. Defaults to all."),
                "enum": ["active", "archived"],
            },
            "limit": {
                "type": "integer",
                "description": ("Maximum number of sessions to return (default 20, max 100)."),
            },
        },
        "required": [],
    },
    permission=None,
    category="session_comm",
)
async def sessions_list_tool(
    ctx: ToolContext,
    *,
    status_filter: str | None = None,
    limit: int = 20,
) -> ToolResult:
    """List peer sessions in the same project."""
    project_id = ctx.project_id
    if not project_id:
        return ToolResult(
            output=_json({"error": "No project_id in context"}),
            is_error=True,
        )

    limit = max(1, min(limit, 100))

    try:
        sessions = await _svc().list_sessions(
            project_id,
            exclude_conversation_id=ctx.conversation_id,
            status_filter=status_filter,
            limit=limit,
        )
        return ToolResult(
            output=_json({"sessions": sessions, "count": len(sessions)}),
        )
    except Exception as exc:
        logger.warning("peer_sessions_list failed: %s", exc)
        return ToolResult(
            output=_json({"error": f"Failed to list sessions: {exc}"}),
            is_error=True,
        )


# ---------------------------------------------------------------------------
# peer_sessions_history
# ---------------------------------------------------------------------------


@tool_define(
    name="peer_sessions_history",
    description=(
        "Read the message history of another peer session (conversation) "
        "in the same project. Use after peer_sessions_list to inspect "
        "what a peer agent has been doing."
    ),
    parameters={
        "type": "object",
        "properties": {
            "conversation_id": {
                "type": "string",
                "description": ("The target conversation ID to read history from."),
            },
            "limit": {
                "type": "integer",
                "description": ("Maximum messages to return (default 50, max 200)."),
            },
        },
        "required": ["conversation_id"],
    },
    permission=None,
    category="session_comm",
)
async def sessions_history_tool(
    ctx: ToolContext,
    *,
    conversation_id: str,
    limit: int = 50,
) -> ToolResult:
    """Read message history from a peer session."""
    project_id = ctx.project_id
    if not project_id:
        return ToolResult(
            output=_json({"error": "No project_id in context"}),
            is_error=True,
        )

    if not conversation_id:
        return ToolResult(
            output=_json({"error": "conversation_id is required"}),
            is_error=True,
        )

    limit = max(1, min(limit, 200))

    try:
        history = await _svc().get_session_history(
            project_id,
            conversation_id,
            limit=limit,
        )
        return ToolResult(output=_json(history))
    except PermissionError as exc:
        return ToolResult(
            output=_json({"error": str(exc)}),
            is_error=True,
        )
    except ValueError as exc:
        return ToolResult(
            output=_json({"error": str(exc)}),
            is_error=True,
        )
    except Exception as exc:
        logger.warning("peer_sessions_history failed: %s", exc)
        return ToolResult(
            output=_json({"error": f"Failed to get history: {exc}"}),
            is_error=True,
        )


# ---------------------------------------------------------------------------
# peer_sessions_send
# ---------------------------------------------------------------------------


@tool_define(
    name="peer_sessions_send",
    description=(
        "Send a message to another peer agent session (conversation) in "
        "the same project. The message appears as a system message "
        "in the target session. Use this for inter-agent "
        "communication and coordination."
    ),
    parameters={
        "type": "object",
        "properties": {
            "conversation_id": {
                "type": "string",
                "description": ("The target conversation ID to send the message to."),
            },
            "content": {
                "type": "string",
                "description": "The message content to send.",
            },
        },
        "required": ["conversation_id", "content"],
    },
    permission=None,
    category="session_comm",
)
async def sessions_send_tool(
    ctx: ToolContext,
    *,
    conversation_id: str,
    content: str,
) -> ToolResult:
    """Send a message to a peer session."""
    project_id = ctx.project_id
    if not project_id:
        return ToolResult(
            output=_json({"error": "No project_id in context"}),
            is_error=True,
        )

    if not conversation_id:
        return ToolResult(
            output=_json({"error": "conversation_id is required"}),
            is_error=True,
        )

    if not content or not content.strip():
        return ToolResult(
            output=_json({"error": "content cannot be empty"}),
            is_error=True,
        )

    try:
        result = await _svc().send_to_session(
            project_id,
            conversation_id,
            content,
            sender_conversation_id=ctx.conversation_id,
        )
        return ToolResult(output=_json(result))
    except (PermissionError, ValueError) as exc:
        return ToolResult(
            output=_json({"error": str(exc)}),
            is_error=True,
        )
    except Exception as exc:
        logger.warning("peer_sessions_send failed: %s", exc)
        return ToolResult(
            output=_json({"error": f"Failed to send message: {exc}"}),
            is_error=True,
        )
