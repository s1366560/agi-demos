"""Agent tool for a generation-pinned friction reflection cycle.

Per Agent-First, the tool is only the structural trigger. Semantic verdicts
come from the tenant LLM client owned by the active V2 Reflection runtime.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.define import tool_define
from src.infrastructure.agent.tools.result import ToolResult
from src.infrastructure.plugins.v2.reflection_runtime import current_reflection_runtime_v2
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error

logger = logging.getLogger(__name__)


def _json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, default=str)


@tool_define(
    name="reflect_friction",
    description=(
        "Run the friction → playbook reflection loop for the current project. "
        "Inspects recent friction signals (task bounces, blocked tasks, retries) "
        "and asks the configured Reflector to create / reinforce / deprecate "
        "playbooks. Returns the list of applied verdicts. "
        "Idempotent within the configured window — safe to call repeatedly."
    ),
    parameters={
        "type": "object",
        "properties": {},
    },
    permission=None,
    category="reflection",
)
async def reflect_friction_tool(ctx: ToolContext) -> ToolResult:
    """Trigger one reflection cycle through the exact pinned generation."""
    project_id = ctx.project_id
    if not project_id:
        return ToolResult(
            output=_json({"error": "No project_id in context"}),
            is_error=True,
        )

    try:
        verdicts = await current_reflection_runtime_v2().reflect_project(
            project_id=project_id,
            tenant_id=ctx.tenant_id or None,
            source="tool",
            run_id=ctx.call_id,
        )
    except Exception as exc:
        logger.exception("reflect_friction failed for %s", project_id)
        code = exc.code if isinstance(exc, RuntimeV2Error) else "reflection_failed"
        return ToolResult(
            output=_json({"error": str(exc), "code": code}),
            is_error=True,
        )

    return ToolResult(
        output=_json(
            {
                "project_id": project_id,
                "applied_count": len(verdicts),
                "verdicts": [
                    {
                        "action": verdict.action.value,
                        "playbook_id": verdict.playbook_id,
                        "rationale": verdict.rationale,
                        "proposed_name": (verdict.proposed_playbook or {}).get("name")
                        if verdict.proposed_playbook
                        else None,
                    }
                    for verdict in verdicts
                ],
            }
        ),
    )


__all__ = ["reflect_friction_tool"]
