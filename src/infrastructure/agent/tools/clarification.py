"""
Clarification Tool for Human-in-the-Loop Interaction.

This tool allows the agent to ask clarifying questions during
planning phase when encountering ambiguous requirements or
multiple valid approaches.

Architecture (Ray-based):
- Uses RayHITLHandler for unified HITL handling
- Redis Streams for response delivery
- SSE events for real-time frontend updates

Architecture (LEGACY - Redis-based, deprecated):
- ClarificationManager inherits from BaseHITLManager
- Redis Streams for cross-process communication
"""

from __future__ import annotations

import logging
from contextvars import ContextVar
from dataclasses import dataclass, replace
from typing import Any

from src.infrastructure.agent.hitl.utils import (
    build_stable_hitl_request_id as _build_stable_hitl_request_id,
    sanitize_hitl_text,
    scope_hitl_handler as _scope_hitl_handler,
)
from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.define import ToolInfo, tool_define
from src.infrastructure.agent.tools.result import ToolResult

logger = logging.getLogger(__name__)

__all__ = [
    "clarification_tool",
    "make_clarification_tool",
]


# === New @tool_define based implementation ===


# ---------------------------------------------------------------------------
# Operation-bound runtime
# ---------------------------------------------------------------------------

@dataclass(frozen=True, kw_only=True, slots=True)
class ClarificationToolRuntime:
    """HITL dependency captured by one generation's clarification tool."""

    hitl_handler: Any


_clarification_tool_runtime: ContextVar[ClarificationToolRuntime | None] = ContextVar(
    f"{__name__}.clarification_tool_runtime",
    default=None,
)


def _current_clarification_hitl_handler() -> Any:
    runtime = _clarification_tool_runtime.get()
    return runtime.hitl_handler if runtime is not None else None


def _build_clarification_request_id(
    ctx: ToolContext,
    *,
    tenant_id: str | None,
    project_id: str | None,
    question: str,
    context: dict[str, Any] | None,
) -> str:
    """Build a stable clarification request id for HITL resume/preinjection."""
    payload = {
        "question": question,
        "options": [],
        "clarification_type": "custom",
        "allow_custom": True,
        "context": context or {},
    }
    return _build_stable_hitl_request_id(
        "clar",
        tenant_id=tenant_id,
        project_id=project_id,
        conversation_id=ctx.conversation_id,
        message_id=ctx.message_id,
        call_id=ctx.call_id,
        payload=payload,
    )


def _sanitize_clarification_result(value: object) -> str | list[str]:
    """Return a safe clarification result for logs and ToolResult metadata."""
    if isinstance(value, str):
        return sanitize_hitl_text(value) or ""
    if not isinstance(value, list):
        return ""
    sanitized_items: list[str] = []
    for item in value:
        sanitized_item = sanitize_hitl_text(item)
        if sanitized_item is not None:
            sanitized_items.append(sanitized_item)
    return sanitized_items


# ---------------------------------------------------------------------------
# Tool definition
# ---------------------------------------------------------------------------


@tool_define(
    name="ask_clarification",
    description=(
        "Ask the user a clarifying question when requirements are "
        "ambiguous or multiple approaches are possible. Use during "
        "planning phase to ensure alignment before execution."
    ),
    parameters={
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": ("The clarification question to ask the user"),
            },
            "context": {
                "type": "string",
                "description": ("Additional context information to show the user"),
            },
        },
        "required": ["question"],
    },
    permission=None,
    category="hitl",
    tags=frozenset({"hitl", "clarification"}),
)
async def clarification_tool(
    ctx: ToolContext,
    *,
    question: str,
    context: str = "",
) -> ToolResult:
    """Ask the user a clarifying question and wait for response."""
    base_hitl_handler = _current_clarification_hitl_handler()
    if base_hitl_handler is None:
        return ToolResult(
            output=("HITL handler not configured. Cannot request user clarification."),
            is_error=True,
        )

    if not question.strip():
        return ToolResult(
            output="Clarification question cannot be empty.",
            is_error=True,
        )

    safe_question = sanitize_hitl_text(question)
    if safe_question is None:
        return ToolResult(
            output="Clarification question cannot be empty.",
            is_error=True,
        )

    safe_context = sanitize_hitl_text(context)
    hitl_context: dict[str, Any] | None = {"info": safe_context} if safe_context else None
    hitl_handler = _scope_hitl_handler(
        base_hitl_handler,
        tenant_id=ctx.tenant_id or getattr(base_hitl_handler, "tenant_id", ""),
        project_id=ctx.project_id or getattr(base_hitl_handler, "project_id", None),
        conversation_id=ctx.conversation_id,
        message_id=ctx.message_id,
    )
    request_id = _build_clarification_request_id(
        ctx,
        tenant_id=getattr(hitl_handler, "tenant_id", ctx.tenant_id),
        project_id=getattr(hitl_handler, "project_id", ctx.project_id),
        question=safe_question,
        context=hitl_context,
    )

    try:
        answer: str | list[str] = await hitl_handler.request_clarification(
            question=safe_question,
            options=[],
            clarification_type="custom",
            allow_custom=True,
            timeout_seconds=300.0,
            context=hitl_context,
            request_id=request_id,
        )
    except Exception as exc:
        logger.error("Clarification request failed: %s", exc)
        return ToolResult(
            output=f"Clarification request failed: {exc!s}",
            is_error=True,
        )

    safe_answer = _sanitize_clarification_result(answer)
    output = safe_answer if isinstance(safe_answer, str) else ", ".join(safe_answer)
    logger.info("Clarification answered for request %s", request_id)
    return ToolResult(
        output=output,
        title="User Clarification",
        metadata={
            "question": safe_question,
            "answer": safe_answer,
        },
    )


@dataclass(frozen=True, kw_only=True, slots=True)
class _BoundClarificationToolExecutor:
    template: ToolInfo
    runtime: ClarificationToolRuntime

    async def __call__(self, ctx: ToolContext, **kwargs: Any) -> Any:
        token = _clarification_tool_runtime.set(self.runtime)
        try:
            return await self.template.execute(ctx, **kwargs)
        finally:
            _clarification_tool_runtime.reset(token)


def make_clarification_tool(*, hitl_handler: Any) -> ToolInfo:
    """Return a clarification ToolInfo bound to one generation's HITL handler."""
    runtime = ClarificationToolRuntime(hitl_handler=hitl_handler)
    return replace(
        clarification_tool,
        execute=_BoundClarificationToolExecutor(
            template=clarification_tool,
            runtime=runtime,
        ),
    )
