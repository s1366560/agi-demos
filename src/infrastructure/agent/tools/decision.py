"""
Decision Tool for Human-in-the-Loop Interaction.

This tool allows the agent to request user decisions at critical
execution points when multiple approaches exist or confirmation is
needed for risky operations.

Architecture (Ray-based):
- Uses RayHITLHandler for unified HITL handling
- Redis Streams for response delivery
- SSE events for real-time frontend updates

Architecture (LEGACY - Redis-based, deprecated):
- DecisionManager inherits from BaseHITLManager
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
    "decision_tool",
    "make_decision_tool",
]


# === New @tool_define based implementation ===


# ---------------------------------------------------------------------------
# Operation-bound runtime
# ---------------------------------------------------------------------------

@dataclass(frozen=True, kw_only=True, slots=True)
class DecisionToolRuntime:
    """HITL dependency captured by one generation's decision tool."""

    hitl_handler: Any


_decision_tool_runtime: ContextVar[DecisionToolRuntime | None] = ContextVar(
    f"{__name__}.decision_tool_runtime",
    default=None,
)


def _current_decision_hitl_handler() -> Any:
    runtime = _decision_tool_runtime.get()
    return runtime.hitl_handler if runtime is not None else None


def _build_decision_request_id(
    ctx: ToolContext,
    *,
    tenant_id: str | None,
    project_id: str | None,
    payload: dict[str, Any],
) -> str:
    """Build a stable decision request id for HITL resume/preinjection."""
    return _build_stable_hitl_request_id(
        "deci",
        tenant_id=tenant_id,
        project_id=project_id,
        conversation_id=ctx.conversation_id,
        message_id=ctx.message_id,
        call_id=ctx.call_id,
        payload=payload,
    )


def _sanitize_decision_result(value: object) -> str | list[str]:
    """Return a safe decision result for logs and ToolResult metadata."""
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


def _validate_decision_inputs(
    *,
    question: str,
    options: list[str],
    context: str,
    recommendation: str | None,
    selection_mode: str,
    max_selections: int | None,
) -> tuple[str, list[str], str | None, str | None] | ToolResult:
    """Validate and sanitize decision tool inputs."""
    error_message: str | None = None
    if selection_mode not in {"single", "multiple"}:
        error_message = "selection_mode must be either 'single' or 'multiple'."
    elif max_selections is not None and (
        not isinstance(max_selections, int) or max_selections <= 0
    ):
        error_message = "max_selections must be a positive integer."
    elif max_selections is not None and selection_mode != "multiple":
        error_message = "max_selections is only valid when selection_mode is 'multiple'."
    if error_message is not None:
        return ToolResult(output=error_message, is_error=True)

    safe_question = sanitize_hitl_text(question)
    if safe_question is None:
        return ToolResult(
            output="Decision question cannot be empty.",
            is_error=True,
        )

    safe_options: list[str] = []
    for option in options:
        safe_option = sanitize_hitl_text(option)
        if safe_option is None:
            error_message = "Options list cannot contain empty values."
            break
        safe_options.append(safe_option)
    if error_message is not None:
        return ToolResult(output=error_message, is_error=True)

    safe_recommendation = sanitize_hitl_text(recommendation) if recommendation is not None else None
    safe_context = sanitize_hitl_text(context)
    return safe_question, safe_options, safe_context, safe_recommendation


# ---------------------------------------------------------------------------
# Tool definition
# ---------------------------------------------------------------------------


@tool_define(
    name="request_decision",
    description=(
        "Request a decision from the user at a critical execution "
        "point. Use when multiple approaches exist, confirmation is "
        "needed for risky operations, or a choice must be made "
        "between execution branches."
    ),
    parameters={
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": ("The decision question to ask the user"),
            },
            "options": {
                "type": "array",
                "items": {"type": "string"},
                "description": ("List of options for the user to choose from"),
            },
            "context": {
                "type": "string",
                "description": ("Additional context information to show the user"),
            },
            "recommendation": {
                "type": "string",
                "description": ("Optional recommended option for the user"),
            },
            "selection_mode": {
                "type": "string",
                "enum": ["single", "multiple"],
                "description": (
                    "Selection mode: 'single' for one choice, "
                    "'multiple' for selecting several options"
                ),
                "default": "single",
            },
            "max_selections": {
                "type": "integer",
                "description": (
                    "Maximum number of selections allowed "
                    "(only used when selection_mode is 'multiple')"
                ),
            },
        },
        "required": ["question", "options"],
    },
    permission=None,
    category="hitl",
    tags=frozenset({"hitl", "decision"}),
)
async def decision_tool(
    ctx: ToolContext,
    *,
    question: str,
    options: list[str],
    context: str = "",
    recommendation: str | None = None,
    selection_mode: str = "single",
    max_selections: int | None = None,
) -> ToolResult:
    """Request a decision from the user and wait for response."""
    base_hitl_handler = _current_decision_hitl_handler()
    if base_hitl_handler is None:
        return ToolResult(
            output=("HITL handler not configured. Cannot request user decisions."),
            is_error=True,
        )

    validated_inputs = _validate_decision_inputs(
        question=question,
        options=options,
        context=context,
        recommendation=recommendation,
        selection_mode=selection_mode,
        max_selections=max_selections,
    )
    if isinstance(validated_inputs, ToolResult):
        return validated_inputs
    safe_question, safe_options, safe_context, safe_recommendation = validated_inputs
    if safe_recommendation not in safe_options:
        safe_recommendation = None
    allow_custom = len(safe_options) == 0

    # Build option dicts from string list for the HITL handler
    option_dicts: list[dict[str, Any]] = []
    for i, opt in enumerate(safe_options):
        entry: dict[str, Any] = {"id": str(i), "label": opt}
        if safe_recommendation and opt == safe_recommendation:
            entry["recommended"] = True
        option_dicts.append(entry)

    hitl_context: dict[str, Any] | None = {"info": safe_context} if safe_context else None
    hitl_handler = _scope_hitl_handler(
        base_hitl_handler,
        tenant_id=ctx.tenant_id or getattr(base_hitl_handler, "tenant_id", ""),
        project_id=ctx.project_id or getattr(base_hitl_handler, "project_id", None),
        conversation_id=ctx.conversation_id,
        message_id=ctx.message_id,
    )
    request_payload = {
        "question": safe_question,
        "options": option_dicts,
        "decision_type": "custom",
        "allow_custom": allow_custom,
        "context": hitl_context or {},
        "selection_mode": selection_mode,
        "max_selections": max_selections,
    }
    request_id = _build_decision_request_id(
        ctx,
        tenant_id=getattr(hitl_handler, "tenant_id", ctx.tenant_id),
        project_id=getattr(hitl_handler, "project_id", ctx.project_id),
        payload=request_payload,
    )

    try:
        decision: str | list[str] = await hitl_handler.request_decision(
            question=safe_question,
            options=option_dicts,
            decision_type="custom",
            allow_custom=allow_custom,
            timeout_seconds=300.0,
            default_option=None,
            context=hitl_context,
            selection_mode=selection_mode,
            max_selections=max_selections,
            request_id=request_id,
        )
    except Exception as exc:
        logger.error("Decision request failed: %s", exc)
        return ToolResult(
            output=f"Decision request failed: {exc!s}",
            is_error=True,
        )

    safe_decision = _sanitize_decision_result(decision)
    output = safe_decision if isinstance(safe_decision, str) else ", ".join(safe_decision)
    logger.info("Decision received for request %s", request_id)
    return ToolResult(
        output=output,
        title="User Decision",
        metadata={
            "question": safe_question,
            "options": safe_options,
            "decision": safe_decision,
        },
    )


@dataclass(frozen=True, kw_only=True, slots=True)
class _BoundDecisionToolExecutor:
    template: ToolInfo
    runtime: DecisionToolRuntime

    async def __call__(self, ctx: ToolContext, **kwargs: Any) -> Any:
        token = _decision_tool_runtime.set(self.runtime)
        try:
            return await self.template.execute(ctx, **kwargs)
        finally:
            _decision_tool_runtime.reset(token)


def make_decision_tool(*, hitl_handler: Any) -> ToolInfo:
    """Return a decision ToolInfo bound to one generation's HITL handler."""
    runtime = DecisionToolRuntime(hitl_handler=hitl_handler)
    return replace(
        decision_tool,
        execute=_BoundDecisionToolExecutor(
            template=decision_tool,
            runtime=runtime,
        ),
    )
