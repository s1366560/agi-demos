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


def _current_agent_orchestrator_v2() -> AgentOrchestrator:
    """Resolve the orchestrator owned by the pinned V2 operation."""
    from src.infrastructure.plugins.v2.agent_worker_runtime import (
        current_agent_orchestrator_v2,
    )

    return current_agent_orchestrator_v2()


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
    orchestrator = _current_agent_orchestrator_v2()
    try:
        agents = await orchestrator.list_agents(
            project_id=ctx.project_id,
            tenant_id=ctx.tenant_id,
            discoverable_only=discoverable_only,
        )
        result: list[dict[str, Any]] = [
            {
                "id": agent.id,
                "name": agent.name,
                "display_name": agent.display_name,
                "can_spawn": agent.can_spawn,
                "agent_to_agent_enabled": agent.agent_to_agent_enabled,
                "discoverable": agent.discoverable,
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
