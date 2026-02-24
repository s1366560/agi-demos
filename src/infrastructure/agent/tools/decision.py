"""
Decision Tool for Human-in-the-Loop Interaction.

This tool allows the agent to request user decisions at critical execution points
when multiple approaches exist or confirmation is needed for risky operations.

Architecture (Ray-based):
- Uses RayHITLHandler for unified HITL handling
- Redis Streams for response delivery
- SSE events for real-time frontend updates

Architecture (LEGACY - Redis-based, deprecated):
- DecisionManager inherits from BaseHITLManager
- Redis Streams for cross-process communication
"""

import logging
from typing import Any, Callable, Dict, List, Optional

from src.infrastructure.agent.hitl.ray_hitl_handler import RayHITLHandler
from src.infrastructure.agent.tools.base import AgentTool

logger = logging.getLogger(__name__)

__all__ = [
    "DecisionTool",
]


class DecisionTool(AgentTool):
    """
    Tool for requesting user decisions at critical execution points.

    This tool triggers a human-in-the-loop interaction where the agent
    asks the user to make a decision at a critical point, such as choosing
    an execution branch, confirming a risky operation, or selecting a method.

    Usage:
        decision = DecisionTool(hitl_handler)
        choice = await decision.execute(
            question="Delete all user data?",
            decision_type="confirmation",
            options=[
                {
                    "id": "proceed",
                    "label": "Proceed with deletion",
                    "risks": ["Data loss is irreversible"]
                },
                {
                    "id": "cancel",
                    "label": "Cancel operation",
                    "recommended": True
                }
            ]
        )
    """

    def __init__(
        self,
        hitl_handler: Optional[RayHITLHandler] = None,
        emit_sse_callback: Optional[Callable] = None,
    ):
        """
        Initialize the decision tool.

        Args:
            hitl_handler: RayHITLHandler instance (required for execution)
            emit_sse_callback: Optional callback for SSE events
        """
        super().__init__(
            name="request_decision",
            description=(
                "Request a decision from the user at a critical execution point. "
                "Use when multiple approaches exist, confirmation is needed for risky "
                "operations, or a choice must be made between execution branches."
            ),
        )
        self._hitl_handler = hitl_handler
        self._emit_sse_callback = emit_sse_callback

    def set_hitl_handler(self, handler: RayHITLHandler) -> None:
        """Set the HITL handler (for late binding)."""
        self._hitl_handler = handler

    def get_parameters_schema(self) -> Dict[str, Any]:
        """Get the parameters schema for LLM function calling."""
        return {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "The decision question to ask the user",
                },
                "decision_type": {
                    "type": "string",
                    "enum": ["branch", "method", "confirmation", "risk", "custom"],
                    "description": (
                        "Type of decision: branch (choose execution path), "
                        "method (choose approach), confirmation (approve/reject action), "
                        "risk (accept/avoid risk), or custom"
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
                            "estimated_time": {
                                "type": "string",
                                "description": "Estimated time for this option",
                            },
                            "estimated_cost": {
                                "type": "string",
                                "description": "Estimated cost for this option",
                            },
                            "risks": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "List of potential risks with this option",
                            },
                        },
                        "required": ["id", "label"],
                    },
                    "description": "List of options for the user to choose from",
                },
                "allow_custom": {
                    "type": "boolean",
                    "description": (
                        "Whether the user can provide a custom decision "
                        "instead of choosing an option"
                    ),
                    "default": False,
                },
                "default_option": {
                    "type": "string",
                    "description": "Default option ID to use if user doesn't respond within timeout",
                },
                "context": {
                    "type": "object",
                    "description": "Additional context information to show the user",
                },
            },
            "required": ["question", "decision_type", "options"],
        }

    def validate_args(self, **kwargs: Any) -> bool:  # noqa: ANN401
        """Validate decision arguments."""
        if "question" not in kwargs:
            logger.error("Missing required argument: question")
            return False

        if "decision_type" not in kwargs:
            logger.error("Missing required argument: decision_type")
            return False

        if "options" not in kwargs:
            logger.error("Missing required argument: options")
            return False

        # Validate decision type
        valid_types = ["branch", "method", "confirmation", "risk", "custom"]
        if kwargs["decision_type"] not in valid_types:
            logger.error(f"Invalid decision_type: {kwargs['decision_type']}")
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
        decision_type: str,
        options: List[Dict[str, Any]],
        allow_custom: bool = False,
        context: Optional[Dict[str, Any]] = None,
        default_option: Optional[str] = None,
        timeout: float = 300.0,
    ) -> str:
        """
        Execute decision request.

        Args:
            question: The decision question to ask
            decision_type: Type of decision (branch/method/confirmation/risk/custom)
            options: List of option dicts with id, label, description, recommended,
                    estimated_time, estimated_cost, risks
            allow_custom: Whether to allow custom user input
            context: Additional context information
            default_option: Default option ID if user doesn't respond
            timeout: Maximum wait time in seconds

        Returns:
            User's decision (option ID or custom text)

        Raises:
            ValueError: If arguments are invalid
            RuntimeError: If HITL handler not set
            asyncio.TimeoutError: If user doesn't respond within timeout and no default
        """
        # Validate
        if not self.validate_args(question=question, decision_type=decision_type, options=options):
            raise ValueError("Invalid decision arguments")

        if self._hitl_handler is None:
            raise RuntimeError("HITL handler not set. Call set_hitl_handler() first.")

        # Use RayHITLHandler
        decision = await self._hitl_handler.request_decision(
            question=question,
            options=options,
            decision_type=decision_type,
            allow_custom=allow_custom,
            timeout_seconds=timeout,
            default_option=default_option,
            context=context,
        )

        logger.info(f"Decision made: {decision}")
        return decision

    def get_output_schema(self) -> Dict[str, Any]:
        """Get output schema for tool composition."""
        return {"type": "string", "description": "User's decision (option ID or custom text)"}
