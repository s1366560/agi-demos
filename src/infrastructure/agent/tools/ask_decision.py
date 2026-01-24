"""Ask decision tool for ReAct agent.

This tool allows the agent to ask for user decisions
during execution when multiple valid paths exist.
"""

import logging
from typing import Any

from src.infrastructure.agent.tools.base import AgentTool

logger = logging.getLogger(__name__)


class AskDecisionTool(AgentTool):
    """
    Tool for asking decision questions to the user.

    This tool enables human-in-the-loop decision making by allowing the agent
    to request user input when facing multiple valid execution paths.
    """

    def __init__(self):
        """Initialize the ask decision tool."""
        super().__init__(
            name="ask_decision",
            description=(
                "Ask the user to make a decision when multiple valid execution paths exist. "
                "Use this tool when you need user input to choose the best approach. "
                "Input: {"
                "  'question': 'The decision question', "
                "  'options': [{'label': 'Option 1', 'description': 'Details...', 'risk': 'low|medium|high'}, ...], "
                "  'decision_type': 'approach'|'risk'|'priority'|'resource', "
                "  'context': 'Current situation and why decision is needed', "
                "  'recommendation': 'Agent\\'s recommended option (optional)'"
                "}"
            ),
        )

    def validate_args(self, **kwargs: Any) -> bool:
        """Validate decision request arguments."""
        question = kwargs.get("question")
        options = kwargs.get("options")
        decision_type = kwargs.get("decision_type")

        # Question is required
        if not isinstance(question, str) or len(question.strip()) == 0:
            return False

        # Options should be a non-empty list
        if not isinstance(options, list) or len(options) < 2:
            return False

        # Each option should have label and description
        for opt in options:
            if not isinstance(opt, dict):
                return False
            if "label" not in opt or not isinstance(opt["label"], str):
                return False
            if "description" not in opt or not isinstance(opt["description"], str):
                return False

        # Decision type should be valid
        valid_types = ["approach", "risk", "priority", "resource"]
        if decision_type and decision_type not in valid_types:
            return False

        return True

    async def execute(self, **kwargs: Any) -> str:
        """
        Execute decision request.

        This method emits a decision event via SSE and waits for user response.

        Args:
            question: The decision question
            options: List of decision options with details
            decision_type: Type of decision needed
            context: Current situation context
            recommendation: Agent's recommended option

        Returns:
            User's selected option
        """
        question = kwargs.get("question")
        options = kwargs.get("options", [])
        decision_type = kwargs.get("decision_type", "approach")
        _context = kwargs.get("context", "")  # Reserved for future use
        recommendation = kwargs.get("recommendation")

        logger.info(
            f"[AskDecision] Question: {question}, "
            f"Type: {decision_type}, Options: {len(options)}, "
            f"Recommendation: {recommendation}"
        )

        # Format options for display
        options_text = "\n".join(
            [
                f"  - {opt['label']}: {opt['description']} (Risk: {opt.get('risk', 'unknown')})"
                for opt in options
            ]
        )

        # In real implementation, this would:
        # 1. Emit SSE event "decision_asked" with decision_data
        # 2. Suspend agent execution
        # 3. Wait for user response via callback
        # 4. Return user's selected option

        # For now, return a placeholder that indicates human interaction is needed
        return (
            f"[DECISION_REQUESTED] Question: {question}\n"
            f"Type: {decision_type}\n"
            f"Options:\n{options_text}\n"
            f"Recommendation: {recommendation or 'None'}\n"
            f"Waiting for user decision..."
        )
