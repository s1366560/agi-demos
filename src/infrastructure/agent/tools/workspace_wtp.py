"""
Workspace Task Protocol (WTP) tools for worker agents.

These three tools replace the phantom ``report_workspace_task`` referenced by
legacy worker briefs (pain point F9 in the WTP plan) with real, shipping
implementations backed by the existing A2A ``AgentOrchestrator`` transport.

All three tools:

1. Validate the calling session's role via ``ctx.runtime_context``
   (``workspace_session_role == "worker"``). Leaders and non-workspace
   sessions are rejected — they should never emit worker→leader verbs.
2. Build a :class:`WtpEnvelope` with the verb-appropriate payload.
3. Deliver the envelope via ``AgentOrchestrator.send_message`` using the
   envelope's metadata + JSON-serialised content. Policy enforcement
   (``agent_to_agent_enabled``, allowlist, sender-session validation) is
   inherited from the orchestrator unchanged.
4. Emit an ``AgentMessageSentEvent`` so the UI timeline sees the hand-off.

For the two terminal verbs (``task.completed`` / ``task.blocked``) the tool
**additionally** invokes the domain-authoritative
``apply_workspace_worker_report`` path so Postgres state transitions even if
the supervisor (Phase 2) is not yet running. This is intentional
belt-and-suspenders during the phased WTP rollout; Phase 8 will flag-gate
the direct call once the supervisor is load-bearing.

All required identifiers (``task_id``, ``attempt_id``, ``leader_agent_id``)
are tool parameters. Worker agents read them from the
``[workspace-task-binding]`` block in their initial brief. Values resolved
from ``runtime_context`` (``workspace_id``, ``root_goal_task_id``) take
precedence when a binding discrepancy is detected.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from src.domain.events.agent_events import AgentMessageSentEvent
from src.domain.model.workspace.wtp_envelope import WtpEnvelope, WtpValidationError, WtpVerb
from src.infrastructure.agent.orchestration.orchestrator import (
    AgentOrchestrator,
    SendDenied,
    SendResult,
)
from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.define import tool_define
from src.infrastructure.agent.tools.result import ToolResult
from src.infrastructure.agent.workspace.runtime_role_contract import (
    WORKSPACE_ROLE_WORKER,
    require_workspace_session_role,
    runtime_context_string,
)

logger = logging.getLogger(__name__)

_orchestrator: AgentOrchestrator | None = None


def _supervisor_only_terminal_path() -> bool:
    """Phase 8: when ``WORKSPACE_WTP_V1_ONLY`` is truthy, skip the worker-tool-side
    direct call to ``apply_workspace_worker_report`` and rely solely on the
    supervisor fan-in path for terminal transitions.
    """
    raw = os.getenv("WORKSPACE_WTP_V1_ONLY", "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def configure_workspace_wtp(orchestrator: AgentOrchestrator) -> None:
    """Inject the orchestrator used to emit WTP envelopes.

    Called once per worker runtime at agent startup (see
    ``_add_agent_tools`` in ``agent_worker_state``).
    """
    global _orchestrator
    _orchestrator = orchestrator


def _runtime_string(ctx: ToolContext, key: str) -> str:
    return runtime_context_string(ctx, key)


def _require_worker_role(ctx: ToolContext) -> str | None:
    """Return a human-readable error if the caller is not a workspace worker."""
    return require_workspace_session_role(
        ctx,
        expected_role=WORKSPACE_ROLE_WORKER,
        action_label="workspace_report_* tools",
    )


def _deny(error: str, **extra: Any) -> ToolResult:
    payload: dict[str, Any] = {"error": error}
    payload.update(extra)
    return ToolResult(output=json.dumps(payload), is_error=True)


async def _send_envelope(
    ctx: ToolContext,
    envelope: WtpEnvelope,
    *,
    to_agent_id: str,
) -> ToolResult:
    """Shared send path — delivers the envelope and emits the UI event."""
    if _orchestrator is None:
        return _deny("workspace WTP not configured (multi-agent disabled?)")

    sender_agent_ref = _runtime_string(ctx, "selected_agent_id") or ctx.agent_name
    sender_agent_name = _runtime_string(ctx, "selected_agent_name") or ctx.agent_name
    metadata = envelope.to_metadata()
    worker_binding_id = _runtime_string(ctx, "workspace_agent_binding_id")
    if worker_binding_id:
        metadata = {
            **metadata,
            "workspace_agent_binding_id": worker_binding_id,
        }

    try:
        result = await _orchestrator.send_message(
            from_agent_id=sender_agent_ref,
            to_agent_id=to_agent_id,
            message=envelope.to_content(),
            sender_session_id=ctx.session_id,
            project_id=ctx.project_id or None,
            tenant_id=ctx.tenant_id,
            message_type=envelope.default_message_type(),
            metadata=metadata,
        )
    except Exception:
        logger.exception(
            "workspace_wtp send failed (verb=%s task=%s)",
            envelope.verb.value,
            envelope.task_id,
        )
        return _deny("internal error while sending WTP envelope", verb=envelope.verb.value)

    if isinstance(result, SendDenied):
        return ToolResult(
            output=json.dumps(
                {"error": "send_denied", "verb": envelope.verb.value, **result.to_dict()}
            ),
            is_error=True,
        )

    assert isinstance(result, SendResult)

    # Fan-in copy for the WorkspaceSupervisor (Phase 2). Failures are
    # swallowed inside publish_envelope_default — the A2A delivery has
    # already succeeded and we refuse to surface a second error.
    from src.infrastructure.agent.workspace.workspace_supervisor import (
        publish_envelope_default,
    )

    worker_agent_id = _runtime_string(ctx, "selected_agent_id") or ctx.agent_name
    enriched_envelope = envelope
    try:
        enriched_metadata = dict(envelope.extra_metadata)
        enriched_metadata.setdefault("leader_agent_id", to_agent_id)
        enriched_metadata.setdefault("worker_agent_id", worker_agent_id)
        enriched_metadata.setdefault(
            "worker_conversation_id", ctx.session_id or ""
        )
        if worker_binding_id:
            enriched_metadata.setdefault("workspace_agent_binding_id", worker_binding_id)
        actor_user_id = _runtime_string(ctx, "user_id") or ctx.user_id or ""
        if actor_user_id:
            enriched_metadata.setdefault("actor_user_id", actor_user_id)
        enriched_envelope = WtpEnvelope(
            verb=envelope.verb,
            workspace_id=envelope.workspace_id,
            task_id=envelope.task_id,
            attempt_id=envelope.attempt_id,
            payload=envelope.payload,
            correlation_id=envelope.correlation_id,
            root_goal_task_id=envelope.root_goal_task_id,
            parent_message_id=envelope.parent_message_id,
            extra_metadata=enriched_metadata,
        )
    except Exception:
        logger.debug("workspace_wtp: envelope enrichment failed; publishing raw")
    await publish_envelope_default(enriched_envelope)

    await ctx.emit(
        AgentMessageSentEvent(
            from_agent_id=result.from_agent_id,
            to_agent_id=result.to_agent_id,
            from_agent_name=sender_agent_name,
            to_agent_name=to_agent_id,
            message_preview=f"[{envelope.verb.value}] {envelope.to_content()[:180]}",
        ).to_event_dict()
    )
    return ToolResult(
        output=json.dumps(
            {
                "ok": True,
                "verb": envelope.verb.value,
                "message_id": result.message_id,
                "task_id": envelope.task_id,
                "attempt_id": envelope.attempt_id,
                "correlation_id": envelope.correlation_id,
            },
            indent=2,
        ),
    )


async def _apply_terminal_report(
    ctx: ToolContext,
    *,
    workspace_id: str,
    root_goal_task_id: str,
    task_id: str,
    attempt_id: str,
    leader_agent_id: str | None,
    report_type: str,
    summary: str,
    artifacts: list[str] | None,
) -> dict[str, Any]:
    """
    Write a terminal report via the domain-authoritative path.

    Failures are logged but NOT raised: the WTP envelope has already been
    delivered (or denied) and surfacing a second error would hide the first.
    The returned dict is attached to the tool output for observability.
    """
    from src.infrastructure.agent.workspace.workspace_goal_runtime import (
        apply_workspace_worker_report,
    )

    actor_user_id = _runtime_string(ctx, "user_id") or ctx.user_id or ""
    worker_agent_id = _runtime_string(ctx, "selected_agent_id") or ctx.agent_name
    try:
        task = await apply_workspace_worker_report(
            workspace_id=workspace_id,
            root_goal_task_id=root_goal_task_id,
            task_id=task_id,
            attempt_id=attempt_id,
            conversation_id=ctx.session_id,
            actor_user_id=actor_user_id,
            worker_agent_id=worker_agent_id,
            report_type=report_type,
            summary=summary,
            artifacts=artifacts,
            leader_agent_id=leader_agent_id,
        )
    except Exception as exc:
        logger.exception(
            "apply_workspace_worker_report failed (task=%s report_type=%s)",
            task_id,
            report_type,
        )
        return {"applied": False, "error": str(exc)}
    return {
        "applied": True,
        "task_status": getattr(task, "status", None) if task is not None else None,
    }


def _build_terminal_tool_result(send_result: ToolResult, apply_result: dict[str, Any]) -> ToolResult:
    """Merge terminal report apply status into the send result payload."""
    try:
        parsed_output = json.loads(send_result.output)
    except (TypeError, ValueError):
        enriched: dict[str, Any] = {"output": send_result.output}
    else:
        enriched = parsed_output if isinstance(parsed_output, dict) else {"output": parsed_output}
    enriched["applied_report"] = apply_result
    return ToolResult(
        output=json.dumps(enriched, indent=2),
        is_error=send_result.is_error,
    )


# --- Progress -----------------------------------------------------------------


@tool_define(
    name="workspace_report_progress",
    description=(
        "Report intermediate progress on the currently assigned workspace task. "
        "Use this periodically during long-running work so the leader and UI "
        "see forward motion. Does NOT terminate the attempt."
    ),
    parameters={
        "type": "object",
        "properties": {
            "task_id": {
                "type": "string",
                "description": "workspace_task_id from the [workspace-task-binding] block in your brief.",
            },
            "attempt_id": {
                "type": "string",
                "description": "attempt_id from the [workspace-task-binding] block in your brief.",
            },
            "leader_agent_id": {
                "type": "string",
                "description": "leader_agent_id from the [workspace-task-binding] block in your brief.",
            },
            "summary": {
                "type": "string",
                "description": "One-sentence description of what you just accomplished or are about to do.",
            },
            "phase": {
                "type": "string",
                "description": "Optional short label for the current phase (e.g. 'research', 'drafting').",
            },
            "percent": {
                "type": "number",
                "description": "Optional estimated completion percentage (0-100).",
            },
        },
        "required": ["task_id", "attempt_id", "leader_agent_id", "summary"],
    },
    permission=None,
    category="workspace",
)
async def workspace_report_progress_tool(
    ctx: ToolContext,
    *,
    task_id: str,
    attempt_id: str,
    leader_agent_id: str,
    summary: str,
    phase: str | None = None,
    percent: float | None = None,
) -> ToolResult:
    role_error = _require_worker_role(ctx)
    if role_error:
        return _deny(role_error)
    workspace_id = _runtime_string(ctx, "workspace_id")
    root_goal_task_id = _runtime_string(ctx, "root_goal_task_id") or None

    payload: dict[str, Any] = {"summary": summary, "task_id": task_id, "attempt_id": attempt_id}
    if phase:
        payload["phase"] = phase
    if percent is not None:
        payload["percent"] = max(0.0, min(100.0, float(percent)))

    try:
        envelope = WtpEnvelope(
            verb=WtpVerb.TASK_PROGRESS,
            workspace_id=workspace_id,
            task_id=task_id,
            attempt_id=attempt_id,
            root_goal_task_id=root_goal_task_id,
            payload=payload,
        )
    except WtpValidationError as exc:
        return _deny(f"invalid progress payload: {exc}")

    return await _send_envelope(ctx, envelope, to_agent_id=leader_agent_id)


# --- Complete -----------------------------------------------------------------


@tool_define(
    name="workspace_report_complete",
    description=(
        "Announce that the currently assigned workspace task is complete. "
        "Provide a concise summary of what was delivered and any artifact references. "
        "This is a TERMINAL action — the attempt transitions to 'completed' and the "
        "leader will reconcile root-goal progress."
    ),
    parameters={
        "type": "object",
        "properties": {
            "task_id": {"type": "string"},
            "attempt_id": {"type": "string"},
            "leader_agent_id": {"type": "string"},
            "summary": {
                "type": "string",
                "description": "Multi-sentence description of what was delivered and where it lives.",
            },
            "artifacts": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Optional artifact identifiers (filenames, URLs, conversation IDs) produced by this task."
                ),
            },
        },
        "required": ["task_id", "attempt_id", "leader_agent_id", "summary"],
    },
    permission=None,
    category="workspace",
)
async def workspace_report_complete_tool(
    ctx: ToolContext,
    *,
    task_id: str,
    attempt_id: str,
    leader_agent_id: str,
    summary: str,
    artifacts: list[str] | None = None,
) -> ToolResult:
    role_error = _require_worker_role(ctx)
    if role_error:
        return _deny(role_error)
    workspace_id = _runtime_string(ctx, "workspace_id")
    root_goal_task_id = _runtime_string(ctx, "root_goal_task_id") or None

    normalized_artifacts = [a for a in (artifacts or []) if isinstance(a, str) and a]
    payload: dict[str, Any] = {
        "summary": summary,
        "task_id": task_id,
        "attempt_id": attempt_id,
    }
    if normalized_artifacts:
        payload["artifacts"] = normalized_artifacts

    try:
        envelope = WtpEnvelope(
            verb=WtpVerb.TASK_COMPLETED,
            workspace_id=workspace_id,
            task_id=task_id,
            attempt_id=attempt_id,
            root_goal_task_id=root_goal_task_id,
            payload=payload,
        )
    except WtpValidationError as exc:
        return _deny(f"invalid completion payload: {exc}")

    send_result = await _send_envelope(ctx, envelope, to_agent_id=leader_agent_id)

    if _supervisor_only_terminal_path():
        apply_result = {"skipped": True, "reason": "WORKSPACE_WTP_V1_ONLY"}
    else:
        apply_result = await _apply_terminal_report(
            ctx,
            workspace_id=workspace_id,
            root_goal_task_id=root_goal_task_id or "",
            task_id=task_id,
            attempt_id=attempt_id,
            leader_agent_id=leader_agent_id,
            report_type="completed",
            summary=summary,
            artifacts=normalized_artifacts or None,
        )
    return _build_terminal_tool_result(send_result, apply_result)


# --- Blocked ------------------------------------------------------------------


@tool_define(
    name="workspace_report_blocked",
    description=(
        "Announce that the currently assigned workspace task CANNOT proceed. "
        "Use this when a hard blocker is encountered (missing information, failed "
        "external call, permission denied) and you cannot recover. "
        "This is a TERMINAL action — the attempt transitions to 'blocked'."
    ),
    parameters={
        "type": "object",
        "properties": {
            "task_id": {"type": "string"},
            "attempt_id": {"type": "string"},
            "leader_agent_id": {"type": "string"},
            "reason": {
                "type": "string",
                "description": "Concrete, actionable description of why the task is blocked.",
            },
            "evidence": {
                "type": "string",
                "description": "Optional supporting detail (error message, log excerpt, etc.).",
            },
        },
        "required": ["task_id", "attempt_id", "leader_agent_id", "reason"],
    },
    permission=None,
    category="workspace",
)
async def workspace_report_blocked_tool(
    ctx: ToolContext,
    *,
    task_id: str,
    attempt_id: str,
    leader_agent_id: str,
    reason: str,
    evidence: str | None = None,
) -> ToolResult:
    role_error = _require_worker_role(ctx)
    if role_error:
        return _deny(role_error)
    workspace_id = _runtime_string(ctx, "workspace_id")
    root_goal_task_id = _runtime_string(ctx, "root_goal_task_id") or None

    payload: dict[str, Any] = {
        "reason": reason,
        "task_id": task_id,
        "attempt_id": attempt_id,
    }
    if evidence:
        payload["evidence"] = evidence

    try:
        envelope = WtpEnvelope(
            verb=WtpVerb.TASK_BLOCKED,
            workspace_id=workspace_id,
            task_id=task_id,
            attempt_id=attempt_id,
            root_goal_task_id=root_goal_task_id,
            payload=payload,
        )
    except WtpValidationError as exc:
        return _deny(f"invalid blocked payload: {exc}")

    send_result = await _send_envelope(ctx, envelope, to_agent_id=leader_agent_id)

    summary = reason if not evidence else f"{reason}\n\n{evidence}"
    if _supervisor_only_terminal_path():
        apply_result = {"skipped": True, "reason": "WORKSPACE_WTP_V1_ONLY"}
    else:
        apply_result = await _apply_terminal_report(
            ctx,
            workspace_id=workspace_id,
            root_goal_task_id=root_goal_task_id or "",
            task_id=task_id,
            attempt_id=attempt_id,
            leader_agent_id=leader_agent_id,
            report_type="blocked",
            summary=summary,
            artifacts=None,
        )
    return _build_terminal_tool_result(send_result, apply_result)


__all__ = [
    "configure_workspace_wtp",
    "workspace_report_blocked_tool",
    "workspace_report_complete_tool",
    "workspace_report_progress_tool",
]
