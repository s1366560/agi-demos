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
from collections.abc import Callable
from typing import Any

from src.infrastructure.agent.hitl.ray_hitl_handler import RayHITLHandler
from src.infrastructure.agent.tools.base import AgentTool
from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.define import tool_define
from src.infrastructure.agent.tools.result import ToolResult

logger = logging.getLogger(__name__)

__all__ = [
    "ClarificationTool",
    "clarification_tool",
    "configure_clarification",
]


class ClarificationTool(AgentTool):
    """
    Tool for asking clarifying questions during planning.

    This tool triggers a human-in-the-loop interaction where the agent
    asks the user to clarify ambiguous requirements or choose between
    multiple valid approaches.

    Usage:
        clarification = ClarificationTool(hitl_handler)
        answer = await clarification.execute(
            question="Should I use caching?",
            clarification_type="approach",
            options=[
                {"id": "cache", "label": "Use caching", "recommended": True},
                {"id": "no_cache", "label": "No caching"}
            ]
        )
    """

    def __init__(
        self,
        hitl_handler: RayHITLHandler | None = None,
        emit_sse_callback: Callable[..., Any] | None = None,
    ) -> None:
        """
        Initialize the clarification tool.

        Args:
            hitl_handler: RayHITLHandler instance (required for execution)
            emit_sse_callback: Optional callback for SSE events
        """
        super().__init__(
            name="ask_clarification",
            description=(
                "Ask the user a clarifying question when requirements are ambiguous "
                "or multiple approaches are possible. Use during planning phase to "
                "ensure alignment before execution."
            ),
        )
        self._hitl_handler = hitl_handler
        self._emit_sse_callback = emit_sse_callback

    def set_hitl_handler(self, handler: RayHITLHandler) -> None:
        """Set the HITL handler (for late binding)."""
        self._hitl_handler = handler

    def get_parameters_schema(self) -> dict[str, Any]:
        """Get the parameters schema for LLM function calling."""
        return {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "The clarification question to ask the user",
                },
                "clarification_type": {
                    "type": "string",
                    "enum": ["scope", "approach", "prerequisite", "priority", "custom"],
                    "description": (
                        "Type of clarification: scope (what to include/exclude), "
                        "approach (how to solve), prerequisite (what's needed first), "
                        "priority (what's more important), or custom"
                    ),
                },
                "options": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {
                                "type": "string",
                                "description": "Unique identifier for the option",
                            },
                            "label": {
                                "type": "string",
                                "description": "Display label for the option",
                            },
                            "description": {
                                "type": "string",
                                "description": "Optional detailed description",
                            },
                            "recommended": {
                                "type": "boolean",
                                "description": "Whether this is the recommended option",
                            },
                        },
                        "required": ["id", "label"],
                    },
                    "description": "List of options for the user to choose from",
                },
                "allow_custom": {
                    "type": "boolean",
                    "description": (
                        "Whether the user can provide a custom answer instead of choosing an option"
                    ),
                    "default": True,
                },
                "context": {
                    "type": "object",
                    "description": "Additional context information to show the user",
                },
            },
            "required": ["question", "clarification_type", "options"],
        }

    def validate_args(self, **kwargs: Any) -> bool:
        """Validate clarification arguments."""
        if "question" not in kwargs:
            logger.error("Missing required argument: question")
            return False

        if "clarification_type" not in kwargs:
            logger.error("Missing required argument: clarification_type")
            return False

        if "options" not in kwargs:
            logger.error("Missing required argument: options")
            return False

        # Validate clarification type
        valid_types = ["scope", "approach", "prerequisite", "priority", "custom"]
        if kwargs["clarification_type"] not in valid_types:
            logger.error(f"Invalid clarification_type: {kwargs['clarification_type']}")
            return False

        # Validate options
        options = kwargs["options"]
        if not isinstance(options, list) or len(options) == 0:
            logger.error("options must be a non-empty list")
            return False

        return True

    async def execute(  # type: ignore[override]
        self,
        question: str,
        clarification_type: str,
        options: list[dict[str, Any]],
        allow_custom: bool = True,
        context: dict[str, Any] | None = None,
        timeout: float = 300.0,
    ) -> str:
        """
        Execute clarification request.

        Args:
            question: The clarification question to ask
            clarification_type: Type of clarification (scope/approach/prerequisite/priority/custom)
            options: List of option dicts with id, label, description, recommended
            allow_custom: Whether to allow custom user input
            context: Additional context information
            timeout: Maximum wait time in seconds

        Returns:
            User's answer (option ID or custom text)

        Raises:
            ValueError: If arguments are invalid
            RuntimeError: If HITL handler not set
            asyncio.TimeoutError: If user doesn't respond within timeout
        """
        # Validate
        if not self.validate_args(
            question=question, clarification_type=clarification_type, options=options
        ):
            raise ValueError("Invalid clarification arguments")

        if self._hitl_handler is None:
            raise RuntimeError("HITL handler not set. Call set_hitl_handler() first.")

        # Use RayHITLHandler
        answer = await self._hitl_handler.request_clarification(
            question=question,
            options=options,
            clarification_type=clarification_type,
            allow_custom=allow_custom,
            timeout_seconds=timeout,
            context=context,
        )

        logger.info(f"Clarification answered: {answer}")
        return answer

    def get_output_schema(self) -> dict[str, Any]:
        """Get output schema for tool composition."""
        return {"type": "string", "description": "User's answer to the clarification question"}


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
    name="clarification",
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
