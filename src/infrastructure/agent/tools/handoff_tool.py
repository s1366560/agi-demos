"""Handoff tool for Swarm-pattern agent-to-agent delegation.

Allows an agent within a Swarm graph run to hand off execution
to another node in the same graph. Only valid for graphs using
the SWARM pattern.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.define import tool_define
from src.infrastructure.agent.tools.result import ToolResult

if TYPE_CHECKING:
    from src.infrastructure.agent.orchestration.graph_orchestrator import (
        GraphOrchestrator,
    )

logger = logging.getLogger(__name__)

_graph_orchestrator: GraphOrchestrator | None = None


def configure_handoff(graph_orchestrator: GraphOrchestrator) -> None:
    """Inject GraphOrchestrator at agent startup."""
    global _graph_orchestrator
    _graph_orchestrator = graph_orchestrator


@tool_define(
    name="handoff",
    description=(
        "Hand off execution to another agent node in a Swarm graph. "
        "Only available during a SWARM-pattern graph run. Delegates "
        "the current task to a target node, optionally passing a "
        "context summary describing what has been accomplished."
    ),
    parameters={
        "type": "object",
        "properties": {
            "graph_id": {
                "type": "string",
                "description": "ID of the agent graph",
            },
            "run_id": {
                "type": "string",
                "description": "ID of the current graph run",
            },
            "from_node_id": {
                "type": "string",
                "description": "Node ID of the current agent (source of handoff)",
            },
            "to_node_id": {
                "type": "string",
                "description": "Node ID of the target agent to hand off to",
            },
            "context_summary": {
                "type": "string",
                "description": (
                    "Summary of work completed and context to pass to the target agent"
                ),
                "default": "",
            },
        },
        "required": ["graph_id", "run_id", "from_node_id", "to_node_id"],
    },
    permission=None,
    category="multi_agent",
)
async def handoff_tool(
    ctx: ToolContext,
    *,
    graph_id: str,
    run_id: str,
    from_node_id: str,
    to_node_id: str,
    context_summary: str = "",
) -> ToolResult:
    """Hand off execution to another agent node in a Swarm graph."""
    if _graph_orchestrator is None:
        return ToolResult(
            output=json.dumps({"error": "Graph orchestration not configured"}),
            is_error=True,
        )
    try:
        run, events = await _graph_orchestrator.handoff_node(
            graph_id=graph_id,
            run_id=run_id,
            from_node_id=from_node_id,
            to_node_id=to_node_id,
            context_summary=context_summary,
            parent_session_id=ctx.session_id,
            parent_agent_id=ctx.agent_name,
        )

        for event in events:
            if hasattr(event, "to_event_dict"):
                await ctx.emit(event.to_event_dict())

        result: dict[str, Any] = {
            "graph_id": graph_id,
            "run_id": run_id,
            "from_node_id": from_node_id,
            "to_node_id": to_node_id,
            "status": run.status.value,
            "total_steps": run.total_steps,
        }
        return ToolResult(output=json.dumps(result, indent=2))
    except ValueError as exc:
        return ToolResult(
            output=json.dumps({"error": str(exc)}),
            is_error=True,
        )
    except Exception:
        logger.exception("handoff failed")
        return ToolResult(
            output=json.dumps({"error": "Internal error in handoff"}),
            is_error=True,
        )
