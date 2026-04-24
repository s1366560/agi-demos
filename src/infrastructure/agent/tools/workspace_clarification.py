"""
Workspace Task Protocol (WTP) — clarification round-trip (Phase 6).

Provides two tools and an internal Future registry:

* ``workspace_request_clarification`` (worker): sends a ``task.clarify_request``
  WTP envelope and awaits a ``task.clarify_response`` matched by
  ``correlation_id``. Returns the leader's answer or a timeout error.
* ``workspace_respond_clarification`` (leader): sends ``task.clarify_response``
  carrying the answer back to the worker and reuses the same correlation id.

The worker-side inbox (``WorkspaceInboxLoop`` / supervisor fan-in) calls
:func:`deliver_clarification_response` whenever a ``task.clarify_response``
envelope is observed, which resolves the pending Future so the waiting tool
can return.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any

from src.domain.events.agent_events import AgentMessageSentEvent
from src.domain.model.workspace.wtp_envelope import (
    WtpEnvelope,
    WtpValidationError,
    WtpVerb,
)
from src.infrastructure.agent.orchestration.orchestrator import (
    AgentOrchestrator,
    SendDenied,
    SendResult,
)
from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.define import tool_define
from src.infrastructure.agent.tools.result import ToolResult
from src.infrastructure.agent.workspace.runtime_role_contract import (
    WORKSPACE_ROLE_LEADER,
    WORKSPACE_ROLE_WORKER,
    require_workspace_session_role,
    runtime_context_string,
)

logger = logging.getLogger(__name__)

_orchestrator: AgentOrchestrator | None = None

# correlation_id → Future[str]. Keyed by the request envelope correlation_id.
_pending_clarifications: dict[str, asyncio.Future[str]] = {}

DEFAULT_CLARIFICATION_TIMEOUT_SECONDS = 120.0


def configure_workspace_clarification(orchestrator: AgentOrchestrator) -> None:
    global _orchestrator
    _orchestrator = orchestrator


# --- runtime helpers ---------------------------------------------------------


def _runtime_string(ctx: ToolContext, key: str) -> str | None:
    runtime = getattr(ctx, "runtime_context", None) or {}
    value = runtime_context_string(ctx, key) if isinstance(runtime, dict) else None
    return str(value) if value not in (None, "") else None


def _deny(error: str, **extra: Any) -> ToolResult:
    payload: dict[str, Any] = {"error": error}
    payload.update(extra)
    return ToolResult(output=json.dumps(payload), is_error=True)


async def _send_envelope_generic(
    ctx: ToolContext,
    envelope: WtpEnvelope,
    *,
    to_agent_id: str,
) -> tuple[ToolResult, SendResult | None]:
    if _orchestrator is None:
        return _deny("workspace WTP not configured"), None

    sender_agent_ref = _runtime_string(ctx, "selected_agent_id") or ctx.agent_name
    sender_agent_name = _runtime_string(ctx, "selected_agent_name") or ctx.agent_name

    try:
        metadata = envelope.to_metadata()
        worker_binding_id = _runtime_string(ctx, "workspace_agent_binding_id")
        if worker_binding_id:
            metadata = {
                **metadata,
                "workspace_agent_binding_id": worker_binding_id,
            }
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
            "workspace_clarification send failed (verb=%s correlation=%s)",
            envelope.verb.value,
            envelope.correlation_id,
        )
        return (
            _deny("internal error while sending clarification envelope"),
            None,
        )

    if isinstance(result, SendDenied):
        return (
            ToolResult(
                output=json.dumps(
                    {
                        "error": "send_denied",
                        "verb": envelope.verb.value,
                        **result.to_dict(),
                    }
                ),
                is_error=True,
            ),
            None,
        )

    assert isinstance(result, SendResult)

    await ctx.emit(
        AgentMessageSentEvent(
            from_agent_id=result.from_agent_id,
            to_agent_id=result.to_agent_id,
            from_agent_name=sender_agent_name,
            to_agent_name=result.to_agent_id,
            message_preview=envelope.to_content(),
        )
    )

    tool_result = ToolResult(
        output=json.dumps(
            {
                "wtp_verb": envelope.verb.value,
                "message_id": result.message_id,
                "correlation_id": envelope.correlation_id,
                "to_agent_id": result.to_agent_id,
            }
        ),
        is_error=False,
    )
    return tool_result, result


# --- Delivery hook (called by supervisor / inbox loop) -----------------------


def deliver_clarification_response(envelope: WtpEnvelope) -> bool:
    """Resolve the pending Future for ``envelope.correlation_id``.

    Returns True if a waiter was found and notified, False otherwise.
    Safe to call from any asyncio task.
    """
    if envelope.verb is not WtpVerb.TASK_CLARIFY_RESPONSE:
        return False
    correlation = envelope.correlation_id
    future = _pending_clarifications.pop(correlation, None)
    if future is None or future.done():
        return False
    answer = envelope.payload.get("answer") or ""
    try:
        future.get_loop().call_soon_threadsafe(
            future.set_result, str(answer)
        )
    except RuntimeError:
        try:
            future.set_result(str(answer))
        except Exception:
            return False
    return True


# --- Worker tool: request clarification --------------------------------------


@tool_define(
    name="workspace_request_clarification",
    description=(
        "Ask the workspace leader a clarifying question and wait for the "
        "answer. Blocks until the leader responds or the request times out. "
        "Use when task requirements are ambiguous and you cannot safely "
        "proceed without leader input."
    ),
    parameters={
        "type": "object",
        "properties": {
            "task_id": {
                "type": "string",
                "description": "Task identifier from [workspace-task-binding].",
            },
            "attempt_id": {
                "type": "string",
                "description": "Attempt identifier from [workspace-task-binding].",
            },
            "leader_agent_id": {
                "type": "string",
                "description": "Leader agent id to address.",
            },
            "question": {
                "type": "string",
                "description": "The clarifying question, one concise sentence.",
            },
            "blocking": {
                "type": "boolean",
                "description": "True if the worker cannot proceed until answered.",
            },
            "timeout_seconds": {
                "type": "number",
                "description": (
                    "Optional override (default 120). Requests time out with "
                    "a {'error':'clarification_timeout'} response."
                ),
            },
        },
        "required": ["task_id", "attempt_id", "leader_agent_id", "question"],
    },
)
async def workspace_request_clarification_tool(
    ctx: ToolContext,
    task_id: str,
    attempt_id: str,
    leader_agent_id: str,
    question: str,
    blocking: bool = True,
    timeout_seconds: float | None = None,
) -> ToolResult:
    role_error = require_workspace_session_role(
        ctx,
        expected_role=WORKSPACE_ROLE_WORKER,
        action_label="workspace_request_clarification",
    )
    if role_error:
        return _deny(
            role_error,
            role=_runtime_string(ctx, "workspace_session_role") or "none",
        )

    workspace_id = _runtime_string(ctx, "workspace_id") or ""
    root_goal_task_id = _runtime_string(ctx, "root_goal_task_id") or None

    if not (task_id and attempt_id and leader_agent_id and question.strip()):
        return _deny(
            "task_id, attempt_id, leader_agent_id and non-empty question are required"
        )

    correlation_id = str(uuid.uuid4())
    try:
        envelope = WtpEnvelope(
            verb=WtpVerb.TASK_CLARIFY_REQUEST,
            workspace_id=workspace_id,
            task_id=task_id,
            attempt_id=attempt_id,
            root_goal_task_id=root_goal_task_id,
            correlation_id=correlation_id,
            payload={
                "task_id": task_id,
                "attempt_id": attempt_id,
                "question": question.strip(),
                "blocking": bool(blocking),
            },
        )
    except WtpValidationError as exc:
        return _deny(f"invalid clarification payload: {exc}")

    # Pre-register the future BEFORE sending to avoid any response-before-await race.
    loop = asyncio.get_event_loop()
    future: asyncio.Future[str] = loop.create_future()
    _pending_clarifications[correlation_id] = future

    send_result, _ = await _send_envelope_generic(
        ctx, envelope, to_agent_id=leader_agent_id
    )
    if send_result.is_error:
        _pending_clarifications.pop(correlation_id, None)
        return send_result

    timeout = (
        float(timeout_seconds)
        if timeout_seconds and timeout_seconds > 0
        else DEFAULT_CLARIFICATION_TIMEOUT_SECONDS
    )
    try:
        answer = await asyncio.wait_for(future, timeout=timeout)
    except TimeoutError:
        _pending_clarifications.pop(correlation_id, None)
        return ToolResult(
            output=json.dumps(
                {
                    "error": "clarification_timeout",
                    "correlation_id": correlation_id,
                    "timeout_seconds": timeout,
                }
            ),
            is_error=True,
        )

    return ToolResult(
        output=json.dumps(
            {
                "answer": answer,
                "correlation_id": correlation_id,
            }
        ),
        is_error=False,
    )


# --- Leader tool: respond to clarification -----------------------------------


@tool_define(
    name="workspace_respond_clarification",
    description=(
        "Respond to a worker's clarifying question by answering their "
        "outstanding task.clarify_request. Must be called by the leader with "
        "the correlation_id from the original request."
    ),
    parameters={
        "type": "object",
        "properties": {
            "worker_agent_id": {
                "type": "string",
                "description": "The worker agent that asked the question.",
            },
            "task_id": {"type": "string"},
            "attempt_id": {"type": "string"},
            "correlation_id": {
                "type": "string",
                "description": "correlation_id from the original task.clarify_request.",
            },
            "answer": {
                "type": "string",
                "description": "The answer delivered back to the worker.",
            },
        },
        "required": [
            "worker_agent_id",
            "task_id",
            "attempt_id",
            "correlation_id",
            "answer",
        ],
    },
)
async def workspace_respond_clarification_tool(
    ctx: ToolContext,
    worker_agent_id: str,
    task_id: str,
    attempt_id: str,
    correlation_id: str,
    answer: str,
) -> ToolResult:
    role_error = require_workspace_session_role(
        ctx,
        expected_role=WORKSPACE_ROLE_LEADER,
        action_label="workspace_respond_clarification",
    )
    if role_error:
        return _deny(
            role_error,
            role=_runtime_string(ctx, "workspace_session_role") or "none",
        )

    workspace_id = _runtime_string(ctx, "workspace_id") or ""
    root_goal_task_id = _runtime_string(ctx, "root_goal_task_id") or None
    if not (worker_agent_id and task_id and attempt_id and correlation_id and answer.strip()):
        return _deny(
            "worker_agent_id, task_id, attempt_id, correlation_id and non-empty answer are required"
        )

    try:
        envelope = WtpEnvelope(
            verb=WtpVerb.TASK_CLARIFY_RESPONSE,
            workspace_id=workspace_id,
            task_id=task_id,
            attempt_id=attempt_id,
            root_goal_task_id=root_goal_task_id,
            correlation_id=correlation_id,
            payload={
                "task_id": task_id,
                "attempt_id": attempt_id,
                "answer": answer,
            },
        )
    except WtpValidationError as exc:
        return _deny(f"invalid clarification response payload: {exc}")

    tool_result, _ = await _send_envelope_generic(
        ctx, envelope, to_agent_id=worker_agent_id
    )
    return tool_result


__all__ = [
    "configure_workspace_clarification",
    "deliver_clarification_response",
    "workspace_request_clarification_tool",
    "workspace_respond_clarification_tool",
]
