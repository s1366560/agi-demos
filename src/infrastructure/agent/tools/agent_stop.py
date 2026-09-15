"""Stop a spawned agent session."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from src.domain.events.agent_events import AgentStoppedEvent
from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.define import tool_define
from src.infrastructure.agent.tools.result import ToolResult

if TYPE_CHECKING:
    from src.infrastructure.agent.orchestration.orchestrator import (
        AgentOrchestrator,
    )

logger = logging.getLogger(__name__)


def _current_agent_orchestrator_v2() -> AgentOrchestrator:
    """Resolve the orchestrator owned by the pinned V2 operation."""
    from src.infrastructure.plugins.v2.agent_worker_runtime import (
        current_agent_orchestrator_v2,
    )

    return current_agent_orchestrator_v2()


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
    permission="delegate",
    category="multi_agent",
)
async def agent_stop_tool(
    ctx: ToolContext,
    *,
    session_id: str,
    cascade: bool = True,
) -> ToolResult:
    """Stop a spawned agent session."""
    orchestrator = _current_agent_orchestrator_v2()
    try:
        stopped = await orchestrator.stop_agent(
            agent_id=ctx.agent_name,
            session_id=session_id,
            project_id=ctx.project_id,
            cascade=cascade,
            conversation_id=ctx.conversation_id,
        )
        for sid in stopped:
            await ctx.emit(
                AgentStoppedEvent(
                    agent_id=sid,
                    agent_name=sid,
                    reason="stopped by parent agent",
                    stopped_by=ctx.agent_name,
                ).to_event_dict()
            )
        result: dict[str, Any] = {
            "stopped_sessions": stopped,
            "count": len(stopped),
        }
        if not stopped:
            result["status"] = "already_completed"
            result["detail"] = (
                f"Session {session_id} has no running tasks to stop. "
                "It may have already completed or been stopped previously."
            )
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
