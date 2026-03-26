"""Workspace chat tools for agents.

Allows agents to send messages and read recent messages in the
workspace group chat. Uses ``@tool_define`` decorator with module-level
DI via ``configure_workspace_chat()``.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from src.application.services.workspace_message_service import (
    WorkspaceMessageService,
)
from src.domain.model.workspace.workspace_message import MessageSenderType
from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.define import tool_define
from src.infrastructure.agent.tools.result import ToolResult

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level DI state
# ---------------------------------------------------------------------------

_workspace_message_service: WorkspaceMessageService | None = None
_workspace_id: str | None = None


def configure_workspace_chat(
    service: WorkspaceMessageService,
    workspace_id: str,
) -> None:
    """Inject the ``WorkspaceMessageService`` at agent startup.

    Args:
        service: A fully constructed ``WorkspaceMessageService``.
        workspace_id: The workspace to send/read messages from.
    """
    global _workspace_message_service, _workspace_id
    _workspace_message_service = service
    _workspace_id = workspace_id


def _svc() -> WorkspaceMessageService:
    """Return the configured service or raise."""
    if _workspace_message_service is None:
        raise RuntimeError(
            "workspace_chat tools not configured -- call configure_workspace_chat() first"
        )
    return _workspace_message_service


def _ws_id() -> str:
    """Return the configured workspace ID or raise."""
    if not _workspace_id:
        raise RuntimeError("workspace_chat tools not configured -- no workspace_id")
    return _workspace_id


def _json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, default=str)


# ---------------------------------------------------------------------------
# workspace_chat_send
# ---------------------------------------------------------------------------


@tool_define(
    name="workspace_chat_send",
    description=(
        "Send a message to the workspace group chat. Other team "
        "members and agents will see this message. Use @mentions "
        "to notify specific people or agents."
    ),
    parameters={
        "type": "object",
        "properties": {
            "content": {
                "type": "string",
                "description": "The message content to send.",
            },
            "parent_message_id": {
                "type": "string",
                "description": ("Optional parent message ID for threading."),
            },
        },
        "required": ["content"],
    },
    permission=None,
    category="workspace_chat",
)
async def workspace_chat_send_tool(
    ctx: ToolContext,
    *,
    content: str,
    parent_message_id: str | None = None,
) -> ToolResult:
    """Send a message to the workspace group chat."""
    if not content or not content.strip():
        return ToolResult(
            output=_json({"error": "content cannot be empty"}),
            is_error=True,
        )

    try:
        message = await _svc().send_message(
            workspace_id=_ws_id(),
            sender_id=ctx.conversation_id,
            sender_type=MessageSenderType.AGENT,
            sender_name=ctx.agent_name,
            content=content,
            parent_message_id=parent_message_id,
        )
        return ToolResult(
            output=_json(
                {
                    "status": "sent",
                    "message_id": message.id,
                    "workspace_id": _ws_id(),
                }
            ),
        )
    except RuntimeError:
        return ToolResult(
            output=_json(
                {
                    "error": "Workspace chat is not configured.",
                }
            ),
            is_error=True,
        )
    except Exception as exc:
        logger.warning("workspace_chat_send failed: %s", exc)
        return ToolResult(
            output=_json(
                {
                    "error": f"Failed to send message: {exc}",
                }
            ),
            is_error=True,
        )


# ---------------------------------------------------------------------------
# workspace_chat_read
# ---------------------------------------------------------------------------


@tool_define(
    name="workspace_chat_read",
    description=(
        "Read recent messages from the workspace group chat. "
        "Use to catch up on team discussions and see what others "
        "have said."
    ),
    parameters={
        "type": "object",
        "properties": {
            "limit": {
                "type": "integer",
                "description": ("Maximum number of messages to return (default 20, max 50)."),
            },
        },
        "required": [],
    },
    permission=None,
    category="workspace_chat",
)
async def workspace_chat_read_tool(
    ctx: ToolContext,
    *,
    limit: int = 20,
) -> ToolResult:
    """Read recent messages from the workspace group chat."""
    limit = max(1, min(limit, 50))

    try:
        messages = await _svc().list_messages(
            workspace_id=_ws_id(),
            limit=limit,
        )
        result = [
            {
                "message_id": m.id,
                "sender_id": m.sender_id,
                "sender_type": m.sender_type.value,
                "sender_name": m.metadata.get("sender_name", ""),
                "content": m.content,
                "mentions": m.mentions,
                "created_at": str(m.created_at),
            }
            for m in messages
        ]
        return ToolResult(
            output=_json(
                {
                    "messages": result,
                    "count": len(result),
                }
            ),
        )
    except RuntimeError:
        return ToolResult(
            output=_json(
                {
                    "error": "Workspace chat is not configured.",
                }
            ),
            is_error=True,
        )
    except Exception as exc:
        logger.warning("workspace_chat_read failed: %s", exc)
        return ToolResult(
            output=_json(
                {
                    "error": f"Failed to read messages: {exc}",
                }
            ),
            is_error=True,
        )
