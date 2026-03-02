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
from typing import Any

from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.define import tool_define
from src.infrastructure.agent.tools.result import ToolResult

logger = logging.getLogger(__name__)

__all__ = [
    "configure_decision",
    "decision_tool",
]


# === New @tool_define based implementation ===


# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_decision_hitl_handler: Any = None


def configure_decision(hitl_handler: Any) -> None:
    """Configure the HITL handler used by the decision tool.

    Called at agent startup to inject the RayHITLHandler instance.
    """
    global _decision_hitl_handler
    _decision_hitl_handler = hitl_handler


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
    if _decision_hitl_handler is None:
        return ToolResult(
            output=("HITL handler not configured. Cannot request user decisions."),
            is_error=True,
        )

    if not question.strip():
        return ToolResult(
            output="Decision question cannot be empty.",
            is_error=True,
        )

    if not options:
        return ToolResult(
            output="Options list cannot be empty.",
            is_error=True,
        )

    # Build option dicts from string list for the HITL handler
    option_dicts: list[dict[str, Any]] = []
    for i, opt in enumerate(options):
        entry: dict[str, Any] = {"id": str(i), "label": opt}
        if recommendation and opt == recommendation:
            entry["recommended"] = True
        option_dicts.append(entry)

    hitl_context: dict[str, Any] | None = {"info": context} if context else None

    try:
        decision: str = await _decision_hitl_handler.request_decision(
            question=question,
            options=option_dicts,
            decision_type="custom",
            allow_custom=False,
            timeout_seconds=300.0,
            default_option=None,
            context=hitl_context,
            selection_mode=selection_mode,
            max_selections=max_selections,
        )
    except Exception as exc:
        logger.error("Decision request failed: %s", exc)
        return ToolResult(
            output=f"Decision request failed: {exc!s}",
            is_error=True,
        )

    logger.info("Decision made: %s", decision)
    return ToolResult(
        output=decision,
        title="User Decision",
        metadata={
            "question": question,
            "options": options,
            "decision": decision,
        },
    )
