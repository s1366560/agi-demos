"""
Clarification Tool for Human-in-the-Loop Interaction.

This tool allows the agent to ask clarifying questions during planning phase
when encountering ambiguous requirements or multiple valid approaches.

Cross-Process Communication:
- Uses Redis Streams for reliable cross-process HITL responses (primary)
- Falls back to Redis Pub/Sub for backward compatibility
- Worker process subscribes to Redis Stream for responses
- API process publishes responses to Redis Stream

Database Persistence:
- Stores HITL requests in database for recovery after page refresh
- Enables frontend to query pending requests on reconnection

Architecture:
- ClarificationManager inherits from BaseHITLManager for common HITL infrastructure
- ClarificationRequest extends BaseHITLRequest for type-specific request handling

NOTE: This file re-exports from the new HITL infrastructure for backward compatibility.
New code should import directly from src.infrastructure.agent.hitl.
"""

import logging
from typing import Any, Dict, List, Optional

# Re-export from new HITL infrastructure for backward compatibility
from src.infrastructure.agent.hitl.clarification_manager import (
    ClarificationManager,
    ClarificationOption,
    ClarificationRequest,
    ClarificationType,
    get_clarification_manager,
    set_clarification_manager,
)
from src.infrastructure.agent.tools.base import AgentTool

logger = logging.getLogger(__name__)

# Re-export for backward compatibility
__all__ = [
    "ClarificationType",
    "ClarificationOption",
    "ClarificationRequest",
    "ClarificationManager",
    "get_clarification_manager",
    "set_clarification_manager",
    "ClarificationTool",
]


class ClarificationTool(AgentTool):
    """
    Tool for asking clarifying questions during planning.

    This tool triggers a human-in-the-loop interaction where the agent
    asks the user to clarify ambiguous requirements or choose between
    multiple valid approaches.

    Usage:
        clarification = ClarificationTool()
        answer = await clarification.execute(
            question="Should I use caching?",
            clarification_type="approach",
            options=[
                {"id": "cache", "label": "Use caching", "recommended": True},
                {"id": "no_cache", "label": "No caching"}
            ]
        )
    """

    def __init__(self, manager: Optional[ClarificationManager] = None):
        """
        Initialize the clarification tool.

        Args:
            manager: Clarification manager to use (defaults to global instance)
        """
        super().__init__(
            name="ask_clarification",
            description=(
                "Ask the user a clarifying question when requirements are ambiguous "
                "or multiple approaches are possible. Use during planning phase to "
                "ensure alignment before execution."
            ),
        )
        self.manager = manager or get_clarification_manager()

    def get_parameters_schema(self) -> Dict[str, Any]:
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
        try:
            ClarificationType(kwargs["clarification_type"])
        except ValueError:
            logger.error(f"Invalid clarification_type: {kwargs['clarification_type']}")
            return False

        # Validate options
        options = kwargs["options"]
        if not isinstance(options, list) or len(options) == 0:
            logger.error("options must be a non-empty list")
            return False

        return True

    async def execute(
        self,
        question: str,
        clarification_type: str,
        options: List[Dict[str, Any]],
        allow_custom: bool = True,
        context: Optional[Dict[str, Any]] = None,
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
            asyncio.TimeoutError: If user doesn't respond within timeout
        """
        # Validate
        if not self.validate_args(
            question=question, clarification_type=clarification_type, options=options
        ):
            raise ValueError("Invalid clarification arguments")

        # Convert options to ClarificationOption objects
        clarification_options = [
            ClarificationOption(
                id=opt["id"],
                label=opt["label"],
                description=opt.get("description"),
                recommended=opt.get("recommended", False),
            )
            for opt in options
        ]

        # Create request
        clarif_type = ClarificationType(clarification_type)
        answer = await self.manager.create_request(
            question=question,
            clarification_type=clarif_type,
            options=clarification_options,
            allow_custom=allow_custom,
            context=context or {},
            timeout=timeout,
        )

        logger.info(f"Clarification answered: {answer}")
        return answer

    def get_output_schema(self) -> Dict[str, Any]:
        """Get output schema for tool composition."""
        return {"type": "string", "description": "User's answer to the clarification question"}
