"""Ask clarification tool for ReAct agent.

This tool allows the agent to ask clarification questions to the user
during the planning or execution phase.
"""

import logging
from typing import Any

from src.infrastructure.agent.tools.base import AgentTool

logger = logging.getLogger(__name__)


class AskClarificationTool(AgentTool):
    """
    Tool for asking clarification questions to the user.

    This tool enables human-in-the-loop interaction by allowing the agent
    to request clarification when requirements are ambiguous or incomplete.
    """

    def __init__(self):
        """Initialize the ask clarification tool."""
        super().__init__(
            name="ask_clarification",
            description=(
                "Ask the user a clarification question when requirements are unclear. "
                "Use this tool when you need more information to proceed with planning or execution. "
                "Input: {"
                "  'question': 'The clarification question', "
                "  'options': ['Option 1', 'Option 2', ...], "
                "  'clarification_type': 'requirement'|'constraint'|'preference'|'ambiguity', "
                "  'context': 'Additional context about why clarification is needed'"
                "}"
            ),
        )

    def validate_args(self, **kwargs: Any) -> bool:
        """Validate clarification request arguments."""
        question = kwargs.get("question")
        options = kwargs.get("options")
        clarification_type = kwargs.get("clarification_type")

        # Question is required
        if not isinstance(question, str) or len(question.strip()) == 0:
            return False

        # Options should be a non-empty list
        if not isinstance(options, list) or len(options) < 2:
            return False

        # All options should be strings
        if not all(isinstance(opt, str) for opt in options):
            return False

        # Clarification type should be valid
        valid_types = ["requirement", "constraint", "preference", "ambiguity"]
        if clarification_type and clarification_type not in valid_types:
            return False

        return True

    async def execute(self, **kwargs: Any) -> str:
        """
        Execute clarification request.

        This method emits a clarification event via SSE and waits for user response.

        Args:
            question: The clarification question
            options: List of possible options
            clarification_type: Type of clarification needed
            context: Additional context

        Returns:
            User's selected option or free-text response
        """
        question = kwargs.get("question")
        options = kwargs.get("options", [])
        clarification_type = kwargs.get("clarification_type", "requirement")
        _context = kwargs.get("context", "")  # Reserved for future use

        logger.info(
            f"[AskClarification] Question: {question}, "
            f"Type: {clarification_type}, Options: {len(options)}"
        )

        # In real implementation, this would:
        # 1. Emit SSE event "clarification_asked" with clarification_data
        # 2. Suspend agent execution
        # 3. Wait for user response via callback
        # 4. Return user's response

        # For now, return a placeholder that indicates human interaction is needed
        return (
            f"[CLARIFICATION_REQUESTED] Question: {question}\n"
            f"Options: {', '.join(options)}\n"
            f"Type: {clarification_type}\n"
            f"Waiting for user response..."
        )
