"""Supervisor agent toolset (Track B P2-3 phase-2).

The Supervisor is a narrow role agent whose only tool is ``verdict``. It is
triggered on structural schedule (see ``tick_scheduler.py``) — elapsed time,
doom-loop counter, progress staleness, budget math — but the **classification**
(healthy / stalled / looping / goal_drift / budget_risk) is the Supervisor
Agent's subjective judgment.

Agent First compliance:
    - Triggers are pure numbers (time, counters, cost) — no content parsing.
    - The verdict mapping (signals → status) is done by the LLM, not a
      dictionary or regex.
    - The tool validates only structure (enum membership, non-empty rationale).
"""

from __future__ import annotations

import json
import logging

from src.domain.events.agent_events import AgentSupervisorVerdictEvent
from src.domain.model.agent.conversation.verdict_status import VerdictStatus
from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.define import tool_define
from src.infrastructure.agent.tools.result import ToolResult

logger = logging.getLogger(__name__)

__all__ = ["verdict_tool"]

_MAX_TEXT_LEN = 4000
_MAX_ACTIONS = 10
_ALLOWED_STATUSES = {status.value for status in VerdictStatus}
_ALLOWED_TRIGGERS = {"tick", "doom_loop", "stale", "budget", "manual"}


def _actor_agent_id(ctx: ToolContext) -> str:
    runtime = ctx.runtime_context or {}
    agent_id = runtime.get("agent_id")
    if isinstance(agent_id, str) and agent_id:
        return agent_id
    return ctx.agent_name or "supervisor"


@tool_define(
    name="verdict",
    description=(
        "Report the supervisor's verdict on conversation health. Call this "
        "ONLY from the Supervisor role. The classification is YOUR "
        "judgment based on the conversation state you observed — NOT a "
        "rule-based decision. Provide a prose rationale explaining the "
        "signals that led to this verdict; the rationale is stored "
        "verbatim in the decision log for audit."
    ),
    parameters={
        "type": "object",
        "properties": {
            "status": {
                "type": "string",
                "enum": sorted(_ALLOWED_STATUSES),
                "description": (
                    "Health verdict. 'healthy' = keep going; others require "
                    "coordinator intervention."
                ),
            },
            "rationale": {
                "type": "string",
                "description": (
                    "Prose explanation of signals that led to this verdict. "
                    "Audited as-is; do NOT use a template or placeholder."
                ),
            },
            "recommended_actions": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Concrete next steps for the coordinator (e.g. "
                    "'reassign foo to agent-x', 'escalate to human'). "
                    "Free-form prose per item; at most 10 items."
                ),
            },
            "trigger": {
                "type": "string",
                "enum": sorted(_ALLOWED_TRIGGERS),
                "description": (
                    "Which structural signal caused this verdict to be "
                    "solicited: tick | doom_loop | stale | budget | manual."
                ),
            },
        },
        "required": ["status", "rationale"],
    },
    permission=None,
    category="multi_agent",
    tags=frozenset({"multi_agent", "supervisor", "agent_first"}),
)
async def verdict_tool(
    ctx: ToolContext,
    *,
    status: str,
    rationale: str,
    recommended_actions: list[str] | None = None,
    trigger: str = "tick",
) -> ToolResult:
    """Emit the Supervisor's verdict on conversation health."""
    if status not in _ALLOWED_STATUSES:
        return ToolResult(
            output=(f"status must be one of {sorted(_ALLOWED_STATUSES)}; got {status!r}."),
            is_error=True,
        )

    if trigger not in _ALLOWED_TRIGGERS:
        return ToolResult(
            output=(f"trigger must be one of {sorted(_ALLOWED_TRIGGERS)}; got {trigger!r}."),
            is_error=True,
        )

    if not isinstance(rationale, str) or not rationale.strip():
        return ToolResult(
            output="rationale cannot be empty.",
            is_error=True,
        )
    rationale_clean = rationale.strip()[:_MAX_TEXT_LEN]

    actions: list[str] = []
    if recommended_actions:
        for item in recommended_actions[:_MAX_ACTIONS]:
            if isinstance(item, str) and item.strip():
                actions.append(item.strip()[:_MAX_TEXT_LEN])

    event = AgentSupervisorVerdictEvent(
        conversation_id=ctx.conversation_id,
        actor_agent_id=_actor_agent_id(ctx),
        status=status,
        rationale=rationale_clean,
        recommended_actions=actions,
        trigger=trigger,
    )
    await ctx.emit(event)

    payload: dict[str, object] = {
        "status": status,
        "trigger": trigger,
        "recommended_actions": actions,
        "supervisor_agent_id": event.actor_agent_id,
    }
    return ToolResult(
        output=json.dumps(payload, ensure_ascii=False),
        title=f"Verdict: {status}",
        metadata=payload,
    )
