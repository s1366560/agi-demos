"""
Clarification Manager - Refactored HITL manager for clarification requests.

This module provides the ClarificationManager that inherits from BaseHITLManager
and implements clarification-specific behavior.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional

from src.domain.model.agent.hitl_request import (
    HITLRequest as HITLRequestEntity,
)
from src.domain.model.agent.hitl_request import (
    HITLRequestType,
)
from src.domain.ports.services.hitl_message_bus_port import (
    HITLMessage,
    HITLMessageBusPort,
)
from src.infrastructure.agent.hitl.base_manager import (
    BaseHITLManager,
    BaseHITLRequest,
    HITLManagerConfig,
)

logger = logging.getLogger(__name__)


class ClarificationType(str, Enum):
    """Type of clarification needed."""

    SCOPE = "scope"  # Clarify task scope or boundaries
    APPROACH = "approach"  # Choose between multiple approaches
    PREREQUISITE = "prerequisite"  # Clarify prerequisites or assumptions
    PRIORITY = "priority"  # Clarify priority or order
    CUSTOM = "custom"  # Custom clarification question


@dataclass
class ClarificationOption:
    """
    A clarification option the user can choose.

    Attributes:
        id: Unique identifier for this option
        label: Short label (e.g., "Use caching")
        description: Detailed explanation
        recommended: Whether this is the recommended option
    """

    id: str
    label: str
    description: Optional[str] = None
    recommended: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "label": self.label,
            "description": self.description,
            "recommended": self.recommended,
        }


@dataclass
class ClarificationRequest(BaseHITLRequest[str]):
    """
    A pending clarification request.

    Extends BaseHITLRequest with clarification-specific fields.

    Attributes:
        question: The clarification question
        clarification_type: Type of clarification
        options: List of predefined options
        allow_custom: Whether user can provide custom answer
    """

    question: str = ""
    clarification_type: ClarificationType = ClarificationType.CUSTOM
    options: List[ClarificationOption] = field(default_factory=list)
    allow_custom: bool = True

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


class ClarificationManager(BaseHITLManager[str]):
    """
    Manager for pending clarification requests.

    Inherits from BaseHITLManager and implements clarification-specific behavior.
    Uses Redis Streams for reliable cross-process communication.
    Uses database persistence for recovery after page refresh.

    Architecture:
    - Worker process: Creates request, persists to DB, subscribes to Redis Stream, waits for response
    - API process: Receives WebSocket message, updates DB, publishes to Redis Stream
    - Worker process: Receives Redis message, resolves the future
    """

    # HITL type configuration
    request_type = HITLRequestType.CLARIFICATION
    response_key = "answer"

    def __init__(
        self,
        message_bus: Optional[HITLMessageBusPort] = None,
        config: Optional[HITLManagerConfig] = None,
    ):
        """
        Initialize the clarification manager.

        Args:
            message_bus: Optional message bus for cross-process communication
            config: Optional configuration
        """
        super().__init__(message_bus=message_bus, config=config)

    def _create_domain_entity(
        self,
        request: BaseHITLRequest[str],
        tenant_id: str,
        project_id: str,
        conversation_id: str,
        message_id: Optional[str],
        timeout: float,
    ) -> HITLRequestEntity:
        """Create the domain entity for database persistence."""
        clarification_request = request  # Type hint: ClarificationRequest
        return HITLRequestEntity(
            id=request.request_id,
            request_type=HITLRequestType.CLARIFICATION,
            conversation_id=conversation_id,
            message_id=message_id,
            tenant_id=tenant_id,
            project_id=project_id,
            question=getattr(clarification_request, "question", ""),
            options=[
                opt.to_dict() if hasattr(opt, "to_dict") else opt
                for opt in getattr(clarification_request, "options", [])
            ],
            context=request.context,
            metadata={
                "clarification_type": getattr(
                    clarification_request, "clarification_type", ClarificationType.CUSTOM
                ).value,
                "allow_custom": getattr(clarification_request, "allow_custom", True),
            },
            expires_at=datetime.utcnow() + timedelta(seconds=timeout),
        )

    def _parse_response(self, message: HITLMessage) -> str:
        """Parse the clarification response from a message bus message."""
        return message.payload.get(self.response_key, "")

    def _get_response_for_db(self, response: str) -> str:
        """Convert response to string for database storage."""
        return response

    # =========================================================================
    # Convenience methods for creating clarification requests
    # =========================================================================

    async def create_request(
        self,
        question: str,
        clarification_type: ClarificationType,
        options: List[ClarificationOption],
        allow_custom: bool = True,
        context: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None,
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
        import uuid

        timeout = timeout or self._config.default_timeout
        request_id = str(uuid.uuid4())

        request = ClarificationRequest(
            request_id=request_id,
            question=question,
            clarification_type=clarification_type,
            options=options,
            allow_custom=allow_custom,
            context=context or {},
        )

        async with self._lock:
            self._pending_requests[request_id] = request

        logger.info(f"Created clarification request {request_id}: {question}")

        try:
            answer = await self.wait_for_response(
                request_id=request_id,
                timeout=timeout,
            )
            logger.info(f"Received answer for {request_id}: {answer}")
            return answer
        except asyncio.TimeoutError:
            logger.warning(f"Clarification request {request_id} timed out")
            raise
        except asyncio.CancelledError:
            logger.warning(f"Clarification request {request_id} was cancelled")
            raise
        finally:
            await self.unregister_request(request_id)


# Global clarification manager instance
_clarification_manager: Optional[ClarificationManager] = None


def get_clarification_manager() -> ClarificationManager:
    """Get the global clarification manager instance."""
    global _clarification_manager
    if _clarification_manager is None:
        _clarification_manager = ClarificationManager()
    return _clarification_manager


def set_clarification_manager(manager: ClarificationManager) -> None:
    """Set the global clarification manager instance (for DI)."""
    global _clarification_manager
    _clarification_manager = manager
