"""Workspace execution health verdict tool.

The execution diagnostics endpoint gathers structural facts. This tool records
the agent's subjective judgment over those facts, preserving Agent First
boundaries: code validates the schema; the agent chooses the verdict.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from src.domain.events.agent_events import AgentSupervisorVerdictEvent
from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.define import tool_define
from src.infrastructure.agent.tools.result import ToolResult

logger = logging.getLogger(__name__)

__all__ = ["workspace_health_verdict_tool"]

_MAX_TEXT_LEN = 4000
_MAX_ACTIONS = 10
_MAX_EVIDENCE_ITEMS = 20
_ALLOWED_STATUSES = {"healthy", "stalled", "looping", "goal_drift"}
_ALLOWED_TRIGGERS = {"diagnostics", "tick", "stale", "doom_loop", "manual"}
_ALLOWED_NEXT_ACTIONS = {"continue", "reassign", "escalate", "replan", "pause"}


def _actor_agent_id(ctx: ToolContext) -> str:
    runtime = ctx.runtime_context or {}
    agent_id = runtime.get("agent_id")
    if isinstance(agent_id, str) and agent_id:
        return agent_id
    return ctx.agent_name or "workspace-supervisor"


def _trim_text(value: Any) -> str:
    return str(value).strip()[:_MAX_TEXT_LEN]


def _trim_string_list(values: list[str] | None) -> list[str]:
    if not values:
        return []
    items: list[str] = []
    for value in values[:_MAX_ACTIONS]:
        if isinstance(value, str) and value.strip():
            items.append(_trim_text(value))
    return items


def _bounded_jsonable(value: Any, *, max_items: int = _MAX_EVIDENCE_ITEMS) -> Any:
    """Keep verdict metadata useful without letting diagnostics bloat prompts/logs."""
    if isinstance(value, dict):
        return {
            str(key)[:128]: _bounded_jsonable(item, max_items=max_items)
            for key, item in list(value.items())[:max_items]
        }
    if isinstance(value, list):
        return [_bounded_jsonable(item, max_items=max_items) for item in value[:max_items]]
    if isinstance(value, str):
        return value[:_MAX_TEXT_LEN]
    if isinstance(value, int | float | bool) or value is None:
        return value
    return str(value)[:_MAX_TEXT_LEN]


@tool_define(
    name="workspace_health_verdict",
    description=(
        "Record an agent-judged workspace execution health verdict from the "
        "workspace execution diagnostics snapshot. Use this after inspecting "
        "diagnostics blockers, evidence gaps, pending adjudications, and tool "
        "failures. The verdict must be your judgment, not a keyword or "
        "threshold rule."
    ),
    parameters={
        "type": "object",
        "properties": {
            "workspace_id": {
                "type": "string",
                "description": "Workspace whose execution diagnostics were judged.",
            },
            "status": {
                "type": "string",
                "enum": sorted(_ALLOWED_STATUSES),
                "description": "Agent-judged health verdict for the workspace execution.",
            },
            "rationale": {
                "type": "string",
                "description": "Audit rationale explaining why the diagnostics imply this verdict.",
            },
            "diagnostics_snapshot": {
                "type": "object",
                "description": "Execution diagnostics payload or concise subset used as evidence.",
            },
            "evidence": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Specific observed signals supporting the verdict.",
            },
            "recommended_actions": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Concrete next actions for the coordinator.",
            },
            "trigger": {
                "type": "string",
                "enum": sorted(_ALLOWED_TRIGGERS),
                "description": "Structural trigger that requested the judgment.",
            },
            "next_action": {
                "type": "string",
                "enum": sorted(_ALLOWED_NEXT_ACTIONS),
                "description": "Coordinator action recommended by the judging agent.",
            },
            "confidence": {
                "type": "number",
                "minimum": 0,
                "maximum": 1,
                "description": "Confidence in the verdict from 0 to 1.",
            },
        },
        "required": ["workspace_id", "status", "rationale", "diagnostics_snapshot"],
    },
    permission=None,
    category="multi_agent",
    tags=frozenset({"multi_agent", "workspace", "diagnostics", "agent_first"}),
)
async def workspace_health_verdict_tool(  # noqa: PLR0911
    ctx: ToolContext,
    *,
    workspace_id: str,
    status: str,
    rationale: str,
    diagnostics_snapshot: dict[str, Any],
    evidence: list[str] | None = None,
    recommended_actions: list[str] | None = None,
    trigger: str = "diagnostics",
    next_action: str = "continue",
    confidence: float | None = None,
) -> ToolResult:
    """Emit the agent-judged workspace execution health verdict."""
    if not isinstance(workspace_id, str) or not workspace_id.strip():
        return ToolResult(output="workspace_id cannot be empty.", is_error=True)

    if status not in _ALLOWED_STATUSES:
        return ToolResult(
            output=f"status must be one of {sorted(_ALLOWED_STATUSES)}; got {status!r}.",
            is_error=True,
        )

    if trigger not in _ALLOWED_TRIGGERS:
        return ToolResult(
            output=f"trigger must be one of {sorted(_ALLOWED_TRIGGERS)}; got {trigger!r}.",
            is_error=True,
        )

    if next_action not in _ALLOWED_NEXT_ACTIONS:
        return ToolResult(
            output=(
                f"next_action must be one of {sorted(_ALLOWED_NEXT_ACTIONS)}; "
                f"got {next_action!r}."
            ),
            is_error=True,
        )

    if not isinstance(rationale, str) or not rationale.strip():
        return ToolResult(output="rationale cannot be empty.", is_error=True)

    if not isinstance(diagnostics_snapshot, dict):
        return ToolResult(output="diagnostics_snapshot must be an object.", is_error=True)

    confidence_value: float | None = None
    if confidence is not None:
        try:
            confidence_value = float(confidence)
        except (TypeError, ValueError):
            return ToolResult(output="confidence must be a number between 0 and 1.", is_error=True)
        if confidence_value < 0 or confidence_value > 1:
            return ToolResult(output="confidence must be between 0 and 1.", is_error=True)

    rationale_clean = _trim_text(rationale)
    evidence_items = _trim_string_list(evidence)
    actions = _trim_string_list(recommended_actions)
    workspace_id_clean = workspace_id.strip()

    metadata: dict[str, Any] = {
        "workspace_id": workspace_id_clean,
        "source": "workspace_execution_diagnostics",
        "diagnostics_snapshot": _bounded_jsonable(diagnostics_snapshot),
        "evidence": evidence_items,
        "next_action": next_action,
    }
    if confidence_value is not None:
        metadata["confidence"] = confidence_value

    event = AgentSupervisorVerdictEvent(
        conversation_id=ctx.conversation_id,
        actor_agent_id=_actor_agent_id(ctx),
        status=status,
        rationale=rationale_clean,
        recommended_actions=actions,
        trigger=trigger,
        metadata=metadata,
    )
    await ctx.emit(event)

    payload: dict[str, Any] = {
        "workspace_id": workspace_id_clean,
        "status": status,
        "trigger": trigger,
        "next_action": next_action,
        "recommended_actions": actions,
        "supervisor_agent_id": event.actor_agent_id,
    }
    if confidence_value is not None:
        payload["confidence"] = confidence_value

    return ToolResult(
        output=json.dumps(payload, ensure_ascii=False),
        title=f"Workspace verdict: {status}",
        metadata=payload,
    )
