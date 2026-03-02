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
from typing import Any

from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.define import tool_define
from src.infrastructure.agent.tools.result import ToolResult

logger = logging.getLogger(__name__)

__all__ = [
    "clarification_tool",
    "configure_clarification",
]


# === New @tool_define based implementation ===


# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_clarification_hitl_handler: Any = None


def configure_clarification(hitl_handler: Any) -> None:
    """Configure the HITL handler used by the clarification tool.

    Called at agent startup to inject the RayHITLHandler instance.
    """
    global _clarification_hitl_handler
    _clarification_hitl_handler = hitl_handler


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
    if _clarification_hitl_handler is None:
        return ToolResult(
            output=("HITL handler not configured. Cannot request user clarification."),
            is_error=True,
        )

    if not question.strip():
        return ToolResult(
            output="Clarification question cannot be empty.",
            is_error=True,
        )

    hitl_context: dict[str, Any] | None = {"info": context} if context else None

    try:
        answer: str = await _clarification_hitl_handler.request_clarification(
            question=question,
            options=[],
            clarification_type="custom",
            allow_custom=True,
            timeout_seconds=300.0,
            context=hitl_context,
        )
    except Exception as exc:
        logger.error("Clarification request failed: %s", exc)
        return ToolResult(
            output=f"Clarification request failed: {exc!s}",
            is_error=True,
        )

    logger.info("Clarification answered: %s", answer)
    return ToolResult(
        output=answer,
        title="User Clarification",
        metadata={
            "question": question,
            "answer": answer,
        },
    )
