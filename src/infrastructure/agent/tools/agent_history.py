"""Read the message history of an agent session."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.define import tool_define
from src.infrastructure.agent.tools.result import ToolResult

if TYPE_CHECKING:
    from src.infrastructure.agent.orchestration.orchestrator import (
        AgentOrchestrator,
    )

logger = logging.getLogger(__name__)

_orchestrator: AgentOrchestrator | None = None


def configure_agent_history(
    orchestrator: AgentOrchestrator,
) -> None:
    """Inject orchestrator at agent startup."""
    global _orchestrator
    _orchestrator = orchestrator


@tool_define(
    name="agent_history",
    description=(
        "Read the message history of an agent session. "
        "Useful for reviewing what a spawned agent has done."
    ),
    parameters={
        "type": "object",
        "properties": {
            "session_id": {
                "type": "string",
                "description": ("Session ID to read history from"),
            },
            "limit": {
                "type": "integer",
                "description": ("Maximum number of messages to return"),
                "default": 50,
            },
        },
        "required": ["session_id"],
    },
    permission=None,
    category="multi_agent",
)
async def agent_history_tool(
    ctx: ToolContext,
    *,
    session_id: str,
    limit: int = 50,
) -> ToolResult:
    """Read agent session message history."""
    if _orchestrator is None:
        return ToolResult(
            output=json.dumps({"error": "Multi-agent not configured"}),
            is_error=True,
        )
    try:
        messages = await _orchestrator.get_agent_history(
            session_id=session_id,
            limit=limit,
        )
        result: list[dict[str, Any]] = [
            {
                "id": msg.id,
                "from_agent_id": msg.from_agent_id,
                "to_agent_id": msg.to_agent_id,
                "content": msg.content,
                "message_type": msg.message_type.value,
                "timestamp": msg.timestamp.isoformat(),
            }
            for msg in messages
        ]
        return ToolResult(output=json.dumps(result, indent=2))
    except ValueError as exc:
        return ToolResult(
            output=json.dumps({"error": str(exc)}),
            is_error=True,
        )
    except Exception:
        logger.exception("agent_history failed")
        return ToolResult(
            output=json.dumps({"error": "Internal error in agent_history"}),
            is_error=True,
        )
