"""List available agents that can be spawned or messaged."""

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


def configure_agent_list(orchestrator: AgentOrchestrator) -> None:
    """Inject orchestrator at agent startup."""
    global _orchestrator
    _orchestrator = orchestrator


@tool_define(
    name="agent_list",
    description=(
        "List available agents that can be spawned or messaged. "
        "Shows agent capabilities and status."
    ),
    parameters={
        "type": "object",
        "properties": {
            "discoverable_only": {
                "type": "boolean",
                "description": "Only show discoverable agents",
                "default": True,
            },
        },
        "required": [],
    },
    permission=None,
    category="multi_agent",
)
async def agent_list_tool(
    ctx: ToolContext,
    *,
    discoverable_only: bool = True,
) -> ToolResult:
    """List available agents."""
    if _orchestrator is None:
        return ToolResult(
            output=json.dumps({"error": "Multi-agent not configured"}),
            is_error=True,
        )
    try:
        agents = await _orchestrator.list_agents(
            project_id=ctx.project_id,
            tenant_id=ctx.tenant_id,
            discoverable_only=discoverable_only,
        )
        result: list[dict[str, Any]] = [
            {
                "id": agent.id,
                "name": agent.name,
                "description": agent.description,
                "can_spawn": agent.can_spawn,
                "agent_to_agent_enabled": (agent.agent_to_agent_enabled),
                "tags": agent.tags,
            }
            for agent in agents
        ]
        return ToolResult(output=json.dumps(result, indent=2))
    except ValueError as exc:
        return ToolResult(
            output=json.dumps({"error": str(exc)}),
            is_error=True,
        )
    except Exception:
        logger.exception("agent_list failed")
        return ToolResult(
            output=json.dumps({"error": "Internal error in agent_list"}),
            is_error=True,
        )
