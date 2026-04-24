"""
Workspace Task Protocol (WTP) tools for leader agents (Phase 3).

Leaders use these tools to dispatch task assignments and cancellations to
workspace workers over the A2A bus. They replace the previous "leader calls
``stream_chat_v2`` directly" model with a structured, observable verb:

    workspace_assign_task  → emits ``task.assign``  + schedules worker session
    workspace_cancel_task  → emits ``task.cancel``  (worker inbox loop honours it)

Both tools reject:

* calls made from non-leader sessions (``workspace_session_role != "leader"``)
* a ``worker_agent_id`` that equals the leader agent id (leader-as-worker guard,
  commit 71c401c8, reinforced here at the tool boundary)

The actual worker session bootstrap still goes through
``schedule_worker_session`` so we keep a single code path for attempt row
creation + conversation binding. The tool simply adds a typed, auditable
message to the bus (and the Phase 2 supervisor fan-in) in addition to the
stream-based launch.
"""

from __future__ import annotations

import json
import logging
import uuid
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

logger = logging.getLogger(__name__)

_orchestrator: AgentOrchestrator | None = None


def configure_workspace_leader_wtp(orchestrator: AgentOrchestrator) -> None:
    """Inject the orchestrator used by leader-side WTP tools."""
    global _orchestrator
    _orchestrator = orchestrator


def _runtime_string(ctx: ToolContext, key: str) -> str:
    value = ctx.runtime_context.get(key)
    return value.strip() if isinstance(value, str) else ""


def _require_leader_role(ctx: ToolContext) -> str | None:
    role = _runtime_string(ctx, "workspace_session_role")
    if role != "leader":
        return (
            "workspace_assign_task / workspace_cancel_task may only be called from "
            f"a workspace leader session (current role: {role or 'none'})"
        )
    if not _runtime_string(ctx, "workspace_id"):
        return "workspace_id is missing from runtime_context — is this a workspace session?"
    return None


def _deny(error: str, **extra: Any) -> ToolResult:
    payload: dict[str, Any] = {"error": error}
    payload.update(extra)
    return ToolResult(output=json.dumps(payload), is_error=True)


def _append_tool_result(output: ToolResult, extra_key: str, extra_value: Any) -> ToolResult:
    try:
        parsed_output = json.loads(output.output)
    except (TypeError, ValueError):
        enriched: dict[str, Any] = {"output": output.output}
    else:
        enriched = parsed_output if isinstance(parsed_output, dict) else {"output": parsed_output}
    enriched[extra_key] = extra_value
    return ToolResult(output=json.dumps(enriched, indent=2), is_error=output.is_error)


async def _send_envelope(
    ctx: ToolContext,
    envelope: WtpEnvelope,
    *,
    to_agent_id: str,
) -> tuple[ToolResult, SendResult | None]:
    """Deliver envelope; return (ToolResult, SendResult-or-None)."""
    if _orchestrator is None:
        return _deny("workspace leader WTP not configured (multi-agent disabled?)"), None

    sender_agent_ref = _runtime_string(ctx, "selected_agent_id") or ctx.agent_name
    sender_agent_name = _runtime_string(ctx, "selected_agent_name") or ctx.agent_name
    leader_binding_id = _runtime_string(ctx, "workspace_agent_binding_id")
    metadata = envelope.to_metadata()
    if leader_binding_id:
        metadata = {
            **metadata,
            "workspace_agent_binding_id": leader_binding_id,
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
            "workspace_leader_wtp send failed (verb=%s task=%s)",
            envelope.verb.value,
            envelope.task_id,
        )
        return (
            _deny("internal error while sending WTP envelope", verb=envelope.verb.value),
            None,
        )

    if isinstance(result, SendDenied):
        return (
            ToolResult(
                output=json.dumps(
                    {"error": "send_denied", "verb": envelope.verb.value, **result.to_dict()}
                ),
                is_error=True,
            ),
            None,
        )

    assert isinstance(result, SendResult)

    # Fan-in to the Phase 2 WorkspaceSupervisor stream for observability.
    from src.infrastructure.agent.workspace.workspace_supervisor import (
        publish_envelope_default,
    )

    try:
        enriched_metadata = dict(envelope.extra_metadata)
        enriched_metadata.setdefault("leader_agent_id", sender_agent_ref)
        enriched_metadata.setdefault("worker_agent_id", to_agent_id)
        actor_user_id = _runtime_string(ctx, "user_id") or ctx.user_id or ""
        if actor_user_id:
            enriched_metadata.setdefault("actor_user_id", actor_user_id)
        if leader_binding_id:
            enriched_metadata.setdefault("workspace_agent_binding_id", leader_binding_id)
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
        logger.debug("workspace_leader_wtp: enrichment failed; publishing raw")
        enriched_envelope = envelope
    _ = await publish_envelope_default(enriched_envelope)

    await ctx.emit(
        AgentMessageSentEvent(
            from_agent_id=result.from_agent_id,
            to_agent_id=result.to_agent_id,
            from_agent_name=sender_agent_name,
            to_agent_name=to_agent_id,
            message_preview=f"[{envelope.verb.value}] {envelope.to_content()[:180]}",
        ).to_event_dict()
    )
    return (
        ToolResult(
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
        ),
        result,
    )


# --- Assign -------------------------------------------------------------------


@tool_define(
    name="workspace_assign_task",
    description=(
        "Assign a workspace task to a worker agent over the Workspace Task "
        "Protocol (WTP). Emits a durable ``task.assign`` envelope on the A2A "
        "bus so the worker's inbox loop, the Phase 2 supervisor, and the UI "
        "all see a typed hand-off. Also schedules the worker session so the "
        "brief is delivered end-to-end. Use this instead of plain @-mentions "
        "when you want structured attempt tracking."
    ),
    parameters={
        "type": "object",
        "properties": {
            "task_id": {
                "type": "string",
                "description": "The workspace_tasks.id of the task to assign.",
            },
            "worker_agent_id": {
                "type": "string",
                "description": (
                    "Target worker agent id. MUST be an active member of this "
                    "workspace and MUST NOT equal the leader agent id."
                ),
            },
            "title": {
                "type": "string",
                "description": "Short task title (<80 chars).",
            },
            "description": {
                "type": "string",
                "description": "Full task brief. Include success criteria and any context the worker needs.",
            },
            "attempt_id": {
                "type": "string",
                "description": (
                    "Optional existing attempt id to reuse (for re-dispatch). "
                    "If omitted a fresh attempt row is created by the worker "
                    "session bootstrap."
                ),
            },
            "deadline": {
                "type": "string",
                "description": "Optional ISO-8601 deadline; purely advisory.",
            },
            "success_criteria": {
                "type": "string",
                "description": "Optional explicit acceptance criteria.",
            },
        },
        "required": ["task_id", "worker_agent_id", "title", "description"],
    },
    permission=None,
    category="workspace",
)
async def workspace_assign_task_tool(
    ctx: ToolContext,
    *,
    task_id: str,
    worker_agent_id: str,
    title: str,
    description: str,
    attempt_id: str | None = None,
    deadline: str | None = None,
    success_criteria: str | None = None,
) -> ToolResult:
    role_error = _require_leader_role(ctx)
    if role_error:
        return _deny(role_error)
    workspace_id = _runtime_string(ctx, "workspace_id")
    root_goal_task_id = _runtime_string(ctx, "root_goal_task_id") or None

    leader_agent_id = _runtime_string(ctx, "selected_agent_id") or ctx.agent_name
    if worker_agent_id and leader_agent_id and worker_agent_id == leader_agent_id:
        return _deny(
            "worker_agent_id must not equal leader_agent_id (leader-as-worker guard)",
            leader_agent_id=leader_agent_id,
            worker_agent_id=worker_agent_id,
        )

    # WTP envelope requires a non-empty attempt_id. If the leader did not pass one
    # we synthesise a correlation-style UUID here; the worker lifecycle will
    # materialise the actual attempt row on dispatch.
    effective_attempt_id = attempt_id or str(uuid.uuid4())

    payload: dict[str, Any] = {
        "title": title,
        "description": description,
        "task_id": task_id,
        "attempt_id": effective_attempt_id,
    }
    if deadline:
        payload["deadline"] = deadline
    if success_criteria:
        payload["success_criteria"] = success_criteria

    try:
        envelope = WtpEnvelope(
            verb=WtpVerb.TASK_ASSIGN,
            workspace_id=workspace_id,
            task_id=task_id,
            attempt_id=effective_attempt_id,
            root_goal_task_id=root_goal_task_id,
            payload=payload,
        )
    except WtpValidationError as exc:
        return _deny(f"invalid assign payload: {exc}")

    tool_result, send_result = await _send_envelope(ctx, envelope, to_agent_id=worker_agent_id)
    if send_result is None:
        return tool_result

    # Kick off the worker session (idempotent: cooldown + conversation reuse).
    # Failures are logged upstream; the envelope was already durably published.
    launch_info: dict[str, Any] = {"scheduled": False}
    try:
        from src.infrastructure.adapters.secondary.persistence.database import (
            async_session_factory,
        )
        from src.infrastructure.adapters.secondary.persistence.sql_workspace_task_repository import (
            SqlWorkspaceTaskRepository,
        )
        from src.infrastructure.agent.workspace.worker_launch import schedule_worker_session

        async with async_session_factory() as db:
            task_repo = SqlWorkspaceTaskRepository(db)
            task = await task_repo.find_by_id(task_id)
        if task is None:
            launch_info = {"scheduled": False, "reason": "task_not_found"}
        else:
            actor_user_id = _runtime_string(ctx, "user_id") or ctx.user_id or ""
            schedule_worker_session(
                workspace_id=workspace_id,
                task=task,
                worker_agent_id=worker_agent_id,
                actor_user_id=actor_user_id,
                leader_agent_id=leader_agent_id,
                attempt_id=attempt_id,
                extra_instructions=description if description else None,
            )
            launch_info = {"scheduled": True}
    except Exception as exc:
        logger.warning(
            "workspace_assign_task: schedule_worker_session failed (task=%s): %s",
            task_id,
            exc,
        )
        launch_info = {"scheduled": False, "error": str(exc)}

    return _append_tool_result(tool_result, "launch", launch_info)


# --- Cancel -------------------------------------------------------------------


@tool_define(
    name="workspace_cancel_task",
    description=(
        "Cancel a running workspace task assignment. Sends a WTP ``task.cancel`` "
        "envelope to the worker; the worker's inbox loop should honour it as a "
        "graceful-stop signal on its next turn."
    ),
    parameters={
        "type": "object",
        "properties": {
            "task_id": {"type": "string"},
            "worker_agent_id": {"type": "string"},
            "attempt_id": {
                "type": "string",
                "description": "Optional attempt to cancel specifically.",
            },
            "reason": {
                "type": "string",
                "description": "Short human-readable reason for the cancel.",
            },
        },
        "required": ["task_id", "worker_agent_id", "reason"],
    },
    permission=None,
    category="workspace",
)
async def workspace_cancel_task_tool(
    ctx: ToolContext,
    *,
    task_id: str,
    worker_agent_id: str,
    reason: str,
    attempt_id: str | None = None,
) -> ToolResult:
    role_error = _require_leader_role(ctx)
    if role_error:
        return _deny(role_error)
    workspace_id = _runtime_string(ctx, "workspace_id")
    root_goal_task_id = _runtime_string(ctx, "root_goal_task_id") or None

    leader_agent_id = _runtime_string(ctx, "selected_agent_id") or ctx.agent_name
    if worker_agent_id and leader_agent_id and worker_agent_id == leader_agent_id:
        return _deny("worker_agent_id must not equal leader_agent_id")

    effective_attempt_id = attempt_id or str(uuid.uuid4())
    payload: dict[str, Any] = {
        "reason": reason,
        "task_id": task_id,
        "attempt_id": effective_attempt_id,
    }

    try:
        envelope = WtpEnvelope(
            verb=WtpVerb.TASK_CANCEL,
            workspace_id=workspace_id,
            task_id=task_id,
            attempt_id=effective_attempt_id,
            root_goal_task_id=root_goal_task_id,
            payload=payload,
            correlation_id=str(uuid.uuid4()),
        )
    except WtpValidationError as exc:
        return _deny(f"invalid cancel payload: {exc}")

    tool_result, _ = await _send_envelope(ctx, envelope, to_agent_id=worker_agent_id)
    return tool_result


__all__ = [
    "configure_workspace_leader_wtp",
    "workspace_assign_task_tool",
    "workspace_cancel_task_tool",
]
