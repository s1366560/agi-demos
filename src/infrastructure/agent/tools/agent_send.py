"""Send a message to another agent's active session."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from src.domain.events.agent_events import AgentMessageSentEvent
from src.infrastructure.agent.orchestration.orchestrator import (
    AgentOrchestrator,
    SendDenied,
    SendResult,
)
from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.define import tool_define
from src.infrastructure.agent.tools.result import ToolResult

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

_orchestrator: AgentOrchestrator | None = None


def _get_runtime_string(ctx: ToolContext, key: str) -> str:
    """Read a normalized string value from runtime_context."""
    value = ctx.runtime_context.get(key)
    return value.strip() if isinstance(value, str) else ""


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
    sender_agent_ref = _get_runtime_string(ctx, "selected_agent_id") or ctx.agent_name
    sender_agent_name = _get_runtime_string(ctx, "selected_agent_name") or ctx.agent_name

    try:
        result = await _orchestrator.send_message(
            from_agent_id=sender_agent_ref,
            to_agent_id=agent_id,
            message=message,
            session_id=session_id,
            sender_session_id=ctx.session_id,
            project_id=ctx.project_id or None,
            tenant_id=ctx.tenant_id,
        )
    except Exception:
        logger.exception("agent_send failed")
        return ToolResult(
            output=json.dumps({"error": "Internal error in agent_send"}),
            is_error=True,
        )

    # Denial branch — return structured denial payload, no event emitted.
    if isinstance(result, SendDenied):
        return ToolResult(
            output=json.dumps(result.to_dict()),
            is_error=True,
        )

    # Success branch.
    assert isinstance(result, SendResult)
    await ctx.emit(
        AgentMessageSentEvent(
            from_agent_id=result.from_agent_id,
            to_agent_id=result.to_agent_id,
            from_agent_name=sender_agent_name,
            to_agent_name=agent_id,
            message_preview=message[:200],
        ).to_event_dict()
    )
    return ToolResult(
        output=json.dumps(
            {
                "message_id": result.message_id,
                "from_agent_id": result.from_agent_id,
                "to_agent_id": result.to_agent_id,
                "session_id": result.session_id,
            },
            indent=2,
        ),
    )
