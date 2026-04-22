"""Multi-agent structured action toolset (Track B · Agent First).

These 7 tools carry ALL subjective decisions an agent can make inside a
multi-agent conversation. By exposing each decision as a structured
tool-call, we enforce the AGENTS.md "Agent First" rule:

    No subjective judgment is hardcoded, inferred from regex, or pulled
    from a policy dictionary. Every decision point is an explicit
    tool-call the LLM must make.

Each tool:
- Has a strict JSON-schema for its parameters (the LLM MUST fill them).
- Validates structure only (non-empty ids, enum membership, length caps).
- Emits exactly one :class:`AgentDomainEvent` via ``ctx.emit()`` so the
  event becomes the append-only decision log.
- Returns a :class:`ToolResult` summarising the action for the LLM's
  next reasoning step.

The tools are intentionally runtime-light: they do not touch the
database directly. Persistence of decision events is handled by the
standard agent event pipeline, which already fans events out to the
``agent_execution_events`` sink and the WebSocket bridge.
"""

from __future__ import annotations

import json
import logging

from src.domain.events.agent_events import (
    AgentConflictMarkedEvent,
    AgentEscalatedEvent,
    AgentGoalCompletedEvent,
    AgentHumanInputRequestedEvent,
    AgentProgressDeclaredEvent,
    AgentTaskAssignedEvent,
    AgentTaskRefusedEvent,
)
from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.define import tool_define
from src.infrastructure.agent.tools.result import ToolResult

logger = logging.getLogger(__name__)

__all__ = [
    "assign_task_tool",
    "declare_progress_tool",
    "escalate_tool",
    "mark_conflict_tool",
    "refuse_task_tool",
    "request_human_input_tool",
    "signal_goal_complete_tool",
]


# ---------------------------------------------------------------------------
# Shared validation helpers (structural only — no subjective judgment)
# ---------------------------------------------------------------------------

_MAX_TEXT_LEN = 4000
_MAX_TITLE_LEN = 500
_MAX_URGENCY = {"normal", "high", "blocking"}
_MAX_SEVERITY = {"low", "medium", "high", "critical"}
_MAX_PROGRESS_STATUS = {"in_progress", "blocked", "done", "needs_review"}


def _require_non_empty(value: str, field: str) -> str | ToolResult:
    """Validate that a string field is non-empty and trim to max length."""
    if not isinstance(value, str):
        return ToolResult(output=f"{field} must be a string.", is_error=True)
    trimmed = value.strip()
    if not trimmed:
        return ToolResult(output=f"{field} cannot be empty.", is_error=True)
    return trimmed[:_MAX_TEXT_LEN]


def _require_enum(value: str, allowed: set[str], field: str) -> str | ToolResult:
    """Validate that *value* is in *allowed*."""
    if value not in allowed:
        return ToolResult(
            output=f"{field} must be one of {sorted(allowed)}; got {value!r}.",
            is_error=True,
        )
    return value


def _actor_agent_id(ctx: ToolContext) -> str:
    """Resolve the actor agent id from the tool context.

    Falls back to ``ctx.agent_name`` if the runtime context did not
    populate ``agent_id``. The application service is expected to set
    ``runtime_context['agent_id']`` for multi-agent conversations.
    """
    runtime = ctx.runtime_context or {}
    agent_id = runtime.get("agent_id")
    if isinstance(agent_id, str) and agent_id:
        return agent_id
    return ctx.agent_name or "unknown_agent"


def _result(title: str, payload: dict[str, object]) -> ToolResult:
    """Build a ToolResult with a JSON body and structured metadata."""
    return ToolResult(
        output=json.dumps(payload, ensure_ascii=False),
        title=title,
        metadata=payload,
    )


# ---------------------------------------------------------------------------
# 1. assign_task — coordinator → worker
# ---------------------------------------------------------------------------


@tool_define(
    name="assign_task",
    description=(
        "Assign a task to another agent in the conversation. Only the "
        "coordinator (or the single agent in solo mode) should call "
        "this. Provide a clear task_title and a prose rationale "
        "explaining WHY this agent was chosen — the rationale is "
        "recorded verbatim in the decision log."
    ),
    parameters={
        "type": "object",
        "properties": {
            "target_agent_id": {
                "type": "string",
                "description": "The agent_id of the assignee (must be a conversation participant).",
            },
            "task_title": {
                "type": "string",
                "description": "Short, actionable title for the task.",
            },
            "rationale": {
                "type": "string",
                "description": (
                    "Prose explaining why this agent should do this task. "
                    "Audited as-is; do NOT use a template or placeholder."
                ),
            },
            "task_id": {
                "type": "string",
                "description": "Optional existing task id to bind this assignment to.",
            },
        },
        "required": ["target_agent_id", "task_title", "rationale"],
    },
    permission=None,
    category="multi_agent",
    tags=frozenset({"multi_agent", "coordination", "agent_first"}),
)
async def assign_task_tool(
    ctx: ToolContext,
    *,
    target_agent_id: str,
    task_title: str,
    rationale: str,
    task_id: str | None = None,
) -> ToolResult:
    """Assign a task to another agent."""
    target = _require_non_empty(target_agent_id, "target_agent_id")
    if isinstance(target, ToolResult):
        return target
    title = _require_non_empty(task_title, "task_title")
    if isinstance(title, ToolResult):
        return title
    rationale_clean = _require_non_empty(rationale, "rationale")
    if isinstance(rationale_clean, ToolResult):
        return rationale_clean
    title = title[:_MAX_TITLE_LEN]

    event = AgentTaskAssignedEvent(
        conversation_id=ctx.conversation_id,
        actor_agent_id=_actor_agent_id(ctx),
        target_agent_id=target,
        task_title=title,
        rationale=rationale_clean,
        task_id=task_id if isinstance(task_id, str) and task_id else None,
    )
    await ctx.emit(event)
    return _result(
        "Task assigned",
        {
            "target_agent_id": target,
            "task_title": title,
            "task_id": event.task_id,
            "assigned_by": event.actor_agent_id,
        },
    )


# ---------------------------------------------------------------------------
# 2. refuse_task — worker declines a task with reason
# ---------------------------------------------------------------------------


@tool_define(
    name="refuse_task",
    description=(
        "Refuse a task that was assigned to you. Provide a prose reason "
        "and optionally suggest a reassignment target. Use this when "
        "you genuinely cannot or should not perform the task — do not "
        "use it to avoid work."
    ),
    parameters={
        "type": "object",
        "properties": {
            "task_id": {
                "type": "string",
                "description": "The task_id being refused (if known).",
            },
            "reason": {
                "type": "string",
                "description": "Prose reason for refusal. Audited verbatim.",
            },
            "suggested_reassignment": {
                "type": "string",
                "description": "Optional agent_id better suited to the task.",
            },
        },
        "required": ["reason"],
    },
    permission=None,
    category="multi_agent",
    tags=frozenset({"multi_agent", "coordination", "agent_first"}),
)
async def refuse_task_tool(
    ctx: ToolContext,
    *,
    reason: str,
    task_id: str | None = None,
    suggested_reassignment: str | None = None,
) -> ToolResult:
    """Refuse an assigned task with a prose reason."""
    reason_clean = _require_non_empty(reason, "reason")
    if isinstance(reason_clean, ToolResult):
        return reason_clean

    event = AgentTaskRefusedEvent(
        conversation_id=ctx.conversation_id,
        actor_agent_id=_actor_agent_id(ctx),
        task_id=task_id if isinstance(task_id, str) and task_id else None,
        reason=reason_clean,
        suggested_reassignment=(
            suggested_reassignment
            if isinstance(suggested_reassignment, str) and suggested_reassignment
            else None
        ),
    )
    await ctx.emit(event)
    return _result(
        "Task refused",
        {
            "task_id": event.task_id,
            "reason": reason_clean,
            "suggested_reassignment": event.suggested_reassignment,
            "refused_by": event.actor_agent_id,
        },
    )


# ---------------------------------------------------------------------------
# 3. request_human_input — any agent → human operator
# ---------------------------------------------------------------------------


@tool_define(
    name="request_human_input",
    description=(
        "Raise a question to the human operator. Use when agent-only "
        "reasoning cannot resolve the issue (missing info, policy "
        "decision, risky action). The urgency field lets you signal "
        "whether work can continue while waiting."
    ),
    parameters={
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "The question for the human. Plain prose.",
            },
            "context": {
                "type": "string",
                "description": "Optional background context to help the human answer.",
            },
            "urgency": {
                "type": "string",
                "enum": ["normal", "high", "blocking"],
                "description": (
                    "blocking = work halts until answered; "
                    "high = answer soon, work may continue in parallel; "
                    "normal = informational."
                ),
                "default": "normal",
            },
        },
        "required": ["question"],
    },
    permission=None,
    category="multi_agent",
    tags=frozenset({"multi_agent", "hitl", "agent_first"}),
)
async def request_human_input_tool(
    ctx: ToolContext,
    *,
    question: str,
    context: str = "",
    urgency: str = "normal",
) -> ToolResult:
    """Request input from the human operator."""
    question_clean = _require_non_empty(question, "question")
    if isinstance(question_clean, ToolResult):
        return question_clean
    urgency_ok = _require_enum(urgency, _MAX_URGENCY, "urgency")
    if isinstance(urgency_ok, ToolResult):
        return urgency_ok
    context_clean = context.strip()[:_MAX_TEXT_LEN] if isinstance(context, str) else ""

    event = AgentHumanInputRequestedEvent(
        conversation_id=ctx.conversation_id,
        actor_agent_id=_actor_agent_id(ctx),
        question=question_clean,
        urgency=urgency_ok,
        context=context_clean,
    )
    await ctx.emit(event)
    return _result(
        "Human input requested",
        {
            "question": question_clean,
            "urgency": urgency_ok,
            "requested_by": event.actor_agent_id,
        },
    )


# ---------------------------------------------------------------------------
# 4. escalate — raise to coordinator or human
# ---------------------------------------------------------------------------


@tool_define(
    name="escalate",
    description=(
        "Escalate an issue to the coordinator, the human operator, or a "
        "specific agent. Use when a decision is beyond your authority "
        "or when you detect a systemic problem that needs leader "
        "attention. Provide a severity and a prose reason."
    ),
    parameters={
        "type": "object",
        "properties": {
            "escalated_to": {
                "type": "string",
                "description": (
                    "Target of the escalation: 'coordinator', 'human', or a specific agent_id."
                ),
            },
            "reason": {
                "type": "string",
                "description": "Prose reason. Audited verbatim.",
            },
            "severity": {
                "type": "string",
                "enum": ["low", "medium", "high", "critical"],
                "default": "medium",
            },
        },
        "required": ["escalated_to", "reason"],
    },
    permission=None,
    category="multi_agent",
    tags=frozenset({"multi_agent", "coordination", "agent_first"}),
)
async def escalate_tool(
    ctx: ToolContext,
    *,
    escalated_to: str,
    reason: str,
    severity: str = "medium",
) -> ToolResult:
    """Escalate an issue to coordinator / human / peer."""
    target = _require_non_empty(escalated_to, "escalated_to")
    if isinstance(target, ToolResult):
        return target
    reason_clean = _require_non_empty(reason, "reason")
    if isinstance(reason_clean, ToolResult):
        return reason_clean
    severity_ok = _require_enum(severity, _MAX_SEVERITY, "severity")
    if isinstance(severity_ok, ToolResult):
        return severity_ok

    event = AgentEscalatedEvent(
        conversation_id=ctx.conversation_id,
        actor_agent_id=_actor_agent_id(ctx),
        escalated_to=target,
        reason=reason_clean,
        severity=severity_ok,
    )
    await ctx.emit(event)
    return _result(
        "Escalated",
        {
            "escalated_to": target,
            "severity": severity_ok,
            "escalated_by": event.actor_agent_id,
        },
    )


# ---------------------------------------------------------------------------
# 5. mark_conflict — flag a disagreement that needs resolution
# ---------------------------------------------------------------------------


@tool_define(
    name="mark_conflict",
    description=(
        "Signal a conflict or disagreement that should be adjudicated "
        "by the coordinator. Use when you disagree with another agent's "
        "action, an artifact, or a prior decision. Provide a short "
        "summary and concrete evidence (quotes, artifact refs)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "conflict_with": {
                "type": "string",
                "description": (
                    "Identifier of the conflict target: agent_id, "
                    "artifact_id, decision_ref, or message_id."
                ),
            },
            "summary": {
                "type": "string",
                "description": "One-line summary of the disagreement.",
            },
            "evidence": {
                "type": "string",
                "description": "Supporting evidence or quote. Audited verbatim.",
            },
        },
        "required": ["conflict_with", "summary"],
    },
    permission=None,
    category="multi_agent",
    tags=frozenset({"multi_agent", "coordination", "agent_first"}),
)
async def mark_conflict_tool(
    ctx: ToolContext,
    *,
    conflict_with: str,
    summary: str,
    evidence: str = "",
) -> ToolResult:
    """Mark a conflict / disagreement."""
    target = _require_non_empty(conflict_with, "conflict_with")
    if isinstance(target, ToolResult):
        return target
    summary_clean = _require_non_empty(summary, "summary")
    if isinstance(summary_clean, ToolResult):
        return summary_clean
    evidence_clean = evidence.strip()[:_MAX_TEXT_LEN] if isinstance(evidence, str) else ""

    event = AgentConflictMarkedEvent(
        conversation_id=ctx.conversation_id,
        actor_agent_id=_actor_agent_id(ctx),
        conflict_with=target,
        summary=summary_clean,
        evidence=evidence_clean,
    )
    await ctx.emit(event)
    return _result(
        "Conflict marked",
        {
            "conflict_with": target,
            "summary": summary_clean,
            "marked_by": event.actor_agent_id,
        },
    )


# ---------------------------------------------------------------------------
# 6. declare_progress — periodic progress update
# ---------------------------------------------------------------------------


@tool_define(
    name="declare_progress",
    description=(
        "Report progress on your current task. Use after significant "
        "milestones or when the supervisor tick expects an update. "
        "Provide the task_id, a status, and a concise summary."
    ),
    parameters={
        "type": "object",
        "properties": {
            "task_id": {
                "type": "string",
                "description": "The task_id being reported on.",
            },
            "status": {
                "type": "string",
                "enum": ["in_progress", "blocked", "done", "needs_review"],
                "default": "in_progress",
            },
            "summary": {
                "type": "string",
                "description": "Concise progress summary.",
            },
            "percent_complete": {
                "type": "number",
                "description": "Optional percent (0-100). Used only as a hint.",
                "minimum": 0,
                "maximum": 100,
            },
        },
        "required": ["summary"],
    },
    permission=None,
    category="multi_agent",
    tags=frozenset({"multi_agent", "coordination", "agent_first"}),
)
async def declare_progress_tool(
    ctx: ToolContext,
    *,
    summary: str,
    task_id: str | None = None,
    status: str = "in_progress",
    percent_complete: float | None = None,
) -> ToolResult:
    """Declare progress on an assigned task."""
    summary_clean = _require_non_empty(summary, "summary")
    if isinstance(summary_clean, ToolResult):
        return summary_clean
    status_ok = _require_enum(status, _MAX_PROGRESS_STATUS, "status")
    if isinstance(status_ok, ToolResult):
        return status_ok
    pct: float | None = None
    if percent_complete is not None:
        try:
            pct_val = float(percent_complete)
        except (TypeError, ValueError):
            return ToolResult(output="percent_complete must be numeric.", is_error=True)
        if pct_val < 0 or pct_val > 100:
            return ToolResult(
                output="percent_complete must be between 0 and 100.",
                is_error=True,
            )
        pct = pct_val

    event = AgentProgressDeclaredEvent(
        conversation_id=ctx.conversation_id,
        actor_agent_id=_actor_agent_id(ctx),
        task_id=task_id if isinstance(task_id, str) and task_id else None,
        status=status_ok,
        summary=summary_clean,
        percent_complete=pct,
    )
    await ctx.emit(event)
    return _result(
        "Progress declared",
        {
            "task_id": event.task_id,
            "status": status_ok,
            "percent_complete": pct,
            "declared_by": event.actor_agent_id,
        },
    )


# ---------------------------------------------------------------------------
# 7. signal_goal_complete — coordinator declares the top-level goal done
# ---------------------------------------------------------------------------


@tool_define(
    name="signal_goal_complete",
    description=(
        "Declare the top-level conversation goal complete. Only the "
        "coordinator (or solo agent) should call this. Provide a "
        "prose summary of what was achieved and the list of artifact "
        "ids produced. The event stops the supervisor tick loop."
    ),
    parameters={
        "type": "object",
        "properties": {
            "summary": {
                "type": "string",
                "description": "Prose summary of what was accomplished.",
            },
            "artifacts": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of artifact ids produced by the goal.",
                "default": [],
            },
        },
        "required": ["summary"],
    },
    permission=None,
    category="multi_agent",
    tags=frozenset({"multi_agent", "coordination", "agent_first"}),
)
async def signal_goal_complete_tool(
    ctx: ToolContext,
    *,
    summary: str,
    artifacts: list[str] | None = None,
) -> ToolResult:
    """Signal that the top-level goal is complete."""
    summary_clean = _require_non_empty(summary, "summary")
    if isinstance(summary_clean, ToolResult):
        return summary_clean
    artifact_ids: list[str] = []
    if isinstance(artifacts, list):
        for item in artifacts:
            if isinstance(item, str) and item.strip():
                artifact_ids.append(item.strip())

    event = AgentGoalCompletedEvent(
        conversation_id=ctx.conversation_id,
        actor_agent_id=_actor_agent_id(ctx),
        summary=summary_clean,
        artifacts=artifact_ids,
    )
    await ctx.emit(event)
    return _result(
        "Goal completed",
        {
            "summary": summary_clean,
            "artifacts": artifact_ids,
            "declared_by": event.actor_agent_id,
        },
    )
