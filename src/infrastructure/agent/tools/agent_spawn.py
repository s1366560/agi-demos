"""Spawn a sub-agent to handle a delegated task."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from src.domain.model.agent.spawn_mode import SpawnMode
from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.define import tool_define
from src.infrastructure.agent.tools.result import ToolResult

if TYPE_CHECKING:
    from src.infrastructure.agent.orchestration.orchestrator import (
        AgentOrchestrator,
    )

logger = logging.getLogger(__name__)

_orchestrator: AgentOrchestrator | None = None


def configure_agent_spawn(orchestrator: AgentOrchestrator) -> None:
    """Inject orchestrator at agent startup."""
    global _orchestrator
    _orchestrator = orchestrator


@tool_define(
    name="agent_spawn",
    description=(
        "Spawn a sub-agent to handle a delegated task. "
        "Returns spawn info including session_id for tracking."
    ),
    parameters={
        "type": "object",
        "properties": {
            "agent_id": {
                "type": "string",
                "description": "ID of the agent to spawn",
            },
            "message": {
                "type": "string",
                "description": ("Task description / initial message for the spawned agent"),
            },
            "mode": {
                "type": "string",
                "description": (
                    "Spawn mode - 'run' for one-shot task, 'session' for persistent session"
                ),
                "enum": ["run", "session"],
                "default": "run",
            },
        },
        "required": ["agent_id", "message"],
    },
    permission=None,
    category="multi_agent",
)
async def agent_spawn_tool(
    ctx: ToolContext,
    *,
    agent_id: str,
    message: str,
    mode: str = "run",
) -> ToolResult:
    """Spawn a sub-agent to handle a delegated task."""
    if _orchestrator is None:
        return ToolResult(
            output=json.dumps({"error": "Multi-agent not configured"}),
            is_error=True,
        )
    try:
        spawn_result = await _orchestrator.spawn_agent(
            parent_agent_id=ctx.agent_name,
            target_agent_id=agent_id,
            message=message,
            mode=SpawnMode(mode),
            parent_session_id=ctx.session_id,
            project_id=ctx.project_id,
            conversation_id=ctx.conversation_id,
        )
        record = spawn_result.spawn_record
        result: dict[str, Any] = {
            "agent_id": agent_id,
            "session_id": record.child_session_id,
            "mode": mode,
            "status": record.status,
        }
        return ToolResult(output=json.dumps(result, indent=2))
    except ValueError as exc:
        return ToolResult(
            output=json.dumps({"error": str(exc)}),
            is_error=True,
        )
    except Exception:
        logger.exception("agent_spawn failed")
        return ToolResult(
            output=json.dumps({"error": "Internal error in agent_spawn"}),
            is_error=True,
        )
