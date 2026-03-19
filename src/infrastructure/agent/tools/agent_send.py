"""Send a message to another agent's active session."""

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


def configure_agent_send(orchestrator: AgentOrchestrator) -> None:
    """Inject orchestrator at agent startup."""
    global _orchestrator
    _orchestrator = orchestrator


@tool_define(
    name="agent_send",
    description=(
        "Send a message to another agent's active session. "
        "The target agent must have agent-to-agent messaging "
        "enabled."
    ),
    parameters={
        "type": "object",
        "properties": {
            "agent_id": {
                "type": "string",
                "description": "ID of the target agent",
            },
            "message": {
                "type": "string",
                "description": "Message content to send",
            },
            "session_id": {
                "type": "string",
                "description": (
                    "Target session ID. If omitted, sends to agent's most recent session"
                ),
            },
        },
        "required": ["agent_id", "message"],
    },
    permission=None,
    category="multi_agent",
)
async def agent_send_tool(
    ctx: ToolContext,
    *,
    agent_id: str,
    message: str,
    session_id: str | None = None,
) -> ToolResult:
    """Send a message to another agent."""
    if _orchestrator is None:
        return ToolResult(
            output=json.dumps({"error": "Multi-agent not configured"}),
            is_error=True,
        )
    try:
        send_result = await _orchestrator.send_message(
            from_agent_id=ctx.agent_name,
            to_agent_id=agent_id,
            message=message,
            session_id=session_id,
            project_id=ctx.project_id,
        )
        result: dict[str, Any] = {
            "message_id": send_result.message_id,
            "from_agent_id": send_result.from_agent_id,
            "to_agent_id": send_result.to_agent_id,
            "session_id": send_result.session_id,
        }
        return ToolResult(output=json.dumps(result, indent=2))
    except ValueError as exc:
        return ToolResult(
            output=json.dumps({"error": str(exc)}),
            is_error=True,
        )
    except Exception:
        logger.exception("agent_send failed")
        return ToolResult(
            output=json.dumps({"error": "Internal error in agent_send"}),
            is_error=True,
        )
