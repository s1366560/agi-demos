"""List active agent sessions spawned from the current session."""

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
    name="agent_sessions",
    description=(
        "List active agent sessions spawned from the current session, including child sessions."
    ),
    parameters={
        "type": "object",
        "properties": {
            "include_children": {
                "type": "boolean",
                "description": ("Include descendant sessions recursively"),
                "default": True,
            },
        },
        "required": [],
    },
    permission=None,
    category="multi_agent",
)
async def agent_sessions_tool(
    ctx: ToolContext,
    *,
    include_children: bool = True,
) -> ToolResult:
    """List active agent sessions."""
    orchestrator = _current_agent_orchestrator_v2()
    try:
        records = await orchestrator.get_agent_sessions(
            parent_session_id=ctx.session_id,
            include_children=include_children,
        )
        result: list[dict[str, Any]] = [
            {
                "child_session_id": rec.child_session_id,
                "child_agent_id": rec.child_agent_id,
                "parent_agent_id": rec.parent_agent_id,
                "status": rec.status,
                "mode": rec.mode.value,
                "task_summary": rec.task_summary,
                "created_at": rec.created_at.isoformat(),
            }
            for rec in records
        ]
        return ToolResult(output=json.dumps(result, indent=2, ensure_ascii=False))
    except ValueError as exc:
        return ToolResult(
            output=json.dumps({"error": str(exc)}, ensure_ascii=False),
            is_error=True,
        )
    except Exception:
        logger.exception("agent_sessions failed")
        return ToolResult(
            output=json.dumps(
                {"error": "Internal error in agent_sessions"},
                ensure_ascii=False,
            ),
            is_error=True,
        )
