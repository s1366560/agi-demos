"""Stop a spawned agent session."""

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


def configure_agent_stop(orchestrator: AgentOrchestrator) -> None:
    """Inject orchestrator at agent startup."""
    global _orchestrator
    _orchestrator = orchestrator


@tool_define(
    name="agent_stop",
    description=("Stop a spawned agent session. Can cascade to stop all child sessions."),
    parameters={
        "type": "object",
        "properties": {
            "session_id": {
                "type": "string",
                "description": ("Session ID of the agent to stop"),
            },
            "cascade": {
                "type": "boolean",
                "description": ("Also stop all child agent sessions"),
                "default": True,
            },
        },
        "required": ["session_id"],
    },
    permission=None,
    category="multi_agent",
)
async def agent_stop_tool(
    ctx: ToolContext,
    *,
    session_id: str,
    cascade: bool = True,
) -> ToolResult:
    """Stop a spawned agent session."""
    if _orchestrator is None:
        return ToolResult(
            output=json.dumps({"error": "Multi-agent not configured"}),
            is_error=True,
        )
    try:
        stopped = await _orchestrator.stop_agent(
            agent_id=ctx.agent_name,
            session_id=session_id,
            project_id=ctx.project_id,
            cascade=cascade,
            conversation_id=ctx.conversation_id,
        )
        result: dict[str, Any] = {
            "stopped_sessions": stopped,
            "count": len(stopped),
        }
        return ToolResult(output=json.dumps(result, indent=2))
    except ValueError as exc:
        return ToolResult(
            output=json.dumps({"error": str(exc)}),
            is_error=True,
        )
    except Exception:
        logger.exception("agent_stop failed")
        return ToolResult(
            output=json.dumps({"error": "Internal error in agent_stop"}),
            is_error=True,
        )
