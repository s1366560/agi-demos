"""
Clarification Tool for Human-in-the-Loop Interaction.

This tool allows the agent to ask clarifying questions during planning phase
when encountering ambiguous requirements or multiple valid approaches.
"""

import asyncio
import logging
import uuid
from enum import Enum
from typing import Any, Dict, List, Optional

from src.infrastructure.agent.tools.base import AgentTool

logger = logging.getLogger(__name__)


class ClarificationType(str, Enum):
    """Type of clarification needed."""

    SCOPE = "scope"  # Clarify task scope or boundaries
    APPROACH = "approach"  # Choose between multiple approaches
    PREREQUISITE = "prerequisite"  # Clarify prerequisites or assumptions
    PRIORITY = "priority"  # Clarify priority or order
    CUSTOM = "custom"  # Custom clarification question


class ClarificationOption:
    """
    A clarification option the user can choose.

    Attributes:
        id: Unique identifier for this option
        label: Short label (e.g., "Use caching")
        description: Detailed explanation
        recommended: Whether this is the recommended option
    """

    def __init__(
        self, id: str, label: str, description: Optional[str] = None, recommended: bool = False
    ):
        self.id = id
        self.label = label
        self.description = description
        self.recommended = recommended

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "label": self.label,
            "description": self.description,
            "recommended": self.recommended,
        }


class ClarificationRequest:
    """
    A pending clarification request.

    Attributes:
        request_id: Unique ID for this clarification
        question: The clarification question
        clarification_type: Type of clarification
        options: List of predefined options
        allow_custom: Whether user can provide custom answer
        context: Additional context for the question
        future: Future that resolves when user answers
    """

    def __init__(
        self,
        request_id: str,
        question: str,
        clarification_type: ClarificationType,
        options: List[ClarificationOption],
        allow_custom: bool = True,
        context: Optional[Dict[str, Any]] = None,
    ):
        self.request_id = request_id
        self.question = question
        self.clarification_type = clarification_type
        self.options = options
        self.allow_custom = allow_custom
        self.context = context or {}
        self.future: asyncio.Future = asyncio.Future()

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for SSE event."""
        return {
            "request_id": self.request_id,
            "question": self.question,
            "clarification_type": self.clarification_type.value,
            "options": [opt.to_dict() for opt in self.options],
            "allow_custom": self.allow_custom,
            "context": self.context,
        }

    def resolve(self, answer: str):
        """Resolve the future with user's answer."""
        if not self.future.done():
            self.future.set_result(answer)

    def cancel(self):
        """Cancel the clarification request."""
        if not self.future.done():
            self.future.cancel()


class ClarificationManager:
    """
    Manager for pending clarification requests.

    Thread-safe manager for handling multiple clarification requests.
    """

    def __init__(self):
        self._pending_requests: Dict[str, ClarificationRequest] = {}
        self._lock = asyncio.Lock()

    async def create_request(
        self,
        question: str,
        clarification_type: ClarificationType,
        options: List[ClarificationOption],
        allow_custom: bool = True,
        context: Optional[Dict[str, Any]] = None,
        timeout: float = 300.0,  # 5 minutes default
    ) -> str:
        """
        Create a new clarification request and wait for user response.

        Args:
            question: The clarification question
            clarification_type: Type of clarification
            options: List of predefined options
            allow_custom: Whether user can provide custom answer
            context: Additional context
            timeout: Maximum time to wait for response (seconds)

        Returns:
            User's answer (option ID or custom text)

        Raises:
            asyncio.TimeoutError: If user doesn't respond within timeout
            asyncio.CancelledError: If request is cancelled
        """
        request_id = str(uuid.uuid4())

        async with self._lock:
            request = ClarificationRequest(
                request_id=request_id,
                question=question,
                clarification_type=clarification_type,
                options=options,
                allow_custom=allow_custom,
                context=context,
            )
            self._pending_requests[request_id] = request

        logger.info(f"Created clarification request {request_id}: {question}")

        try:
            # Wait for user response with timeout
            answer = await asyncio.wait_for(request.future, timeout=timeout)
            logger.info(f"Received answer for {request_id}: {answer}")
            return answer
        except asyncio.TimeoutError:
            logger.warning(f"Clarification request {request_id} timed out")
            raise
        except asyncio.CancelledError:
            logger.warning(f"Clarification request {request_id} was cancelled")
            raise
        finally:
            # Clean up
            async with self._lock:
                self._pending_requests.pop(request_id, None)

    async def respond(self, request_id: str, answer: str) -> bool:
        """
        Respond to a clarification request.

        Args:
            request_id: ID of the clarification request
            answer: User's answer

        Returns:
            True if request was found and resolved, False otherwise
        """
        async with self._lock:
            request = self._pending_requests.get(request_id)
            if request:
                request.resolve(answer)
                logger.info(f"Responded to clarification {request_id}")
                return True
            else:
                logger.warning(f"Clarification request {request_id} not found")
                return False

    async def cancel_request(self, request_id: str) -> bool:
        """
        Cancel a clarification request.

        Args:
            request_id: ID of the clarification request

        Returns:
            True if request was found and cancelled, False otherwise
        """
        async with self._lock:
            request = self._pending_requests.get(request_id)
            if request:
                request.cancel()
                self._pending_requests.pop(request_id, None)
                logger.info(f"Cancelled clarification {request_id}")
                return True
            else:
                logger.warning(f"Clarification request {request_id} not found")
                return False

    def get_request(self, request_id: str) -> Optional[ClarificationRequest]:
        """Get a clarification request by ID."""
        return self._pending_requests.get(request_id)

    def get_pending_requests(self) -> List[ClarificationRequest]:
        """Get all pending clarification requests."""
        return list(self._pending_requests.values())


# Global clarification manager instance
_clarification_manager = ClarificationManager()


def get_clarification_manager() -> ClarificationManager:
    """Get the global clarification manager instance."""
    return _clarification_manager


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
