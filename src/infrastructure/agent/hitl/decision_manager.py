"""
Decision Manager - Refactored HITL manager for decision requests.

This module provides the DecisionManager that inherits from BaseHITLManager
and implements decision-specific behavior.
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


class DecisionType(str, Enum):
    """Type of decision needed."""

    BRANCH = "branch"  # Choose execution branch
    METHOD = "method"  # Choose implementation method
    CONFIRMATION = "confirmation"  # Confirm a risky operation
    RISK = "risk"  # Acknowledge and proceed with risk
    CUSTOM = "custom"  # Custom decision point


@dataclass
class DecisionOption:
    """
    A decision option the user can choose.

    Attributes:
        id: Unique identifier for this option
        label: Short label (e.g., "Proceed with deletion")
        description: Detailed explanation
        recommended: Whether this is the recommended option
        estimated_time: Optional estimated time for this option
        estimated_cost: Optional estimated cost/resources
        risks: Optional list of risks associated with this option
    """

    id: str
    label: str
    description: Optional[str] = None
    recommended: bool = False
    estimated_time: Optional[str] = None
    estimated_cost: Optional[str] = None
    risks: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "label": self.label,
            "description": self.description,
            "recommended": self.recommended,
            "estimated_time": self.estimated_time,
            "estimated_cost": self.estimated_cost,
            "risks": self.risks,
        }


@dataclass
class DecisionRequest(BaseHITLRequest[str]):
    """
    A pending decision request.

    Extends BaseHITLRequest with decision-specific fields.

    Attributes:
        question: The decision question
        decision_type: Type of decision
        options: List of decision options
        allow_custom: Whether user can provide custom response
        default_option: Default option if user doesn't respond
    """

    question: str = ""
    decision_type: DecisionType = DecisionType.CUSTOM
    options: List[DecisionOption] = field(default_factory=list)
    allow_custom: bool = False
    default_option: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for SSE event."""
        return {
            "request_id": self.request_id,
            "question": self.question,
            "decision_type": self.decision_type.value,
            "options": [opt.to_dict() for opt in self.options],
            "allow_custom": self.allow_custom,
            "context": self.context,
            "default_option": self.default_option,
        }


class DecisionManager(BaseHITLManager[str]):
    """
    Manager for pending decision requests.

    Inherits from BaseHITLManager and implements decision-specific behavior.
    Uses Redis Streams for reliable cross-process communication.
    Uses database persistence for recovery after page refresh.

    Architecture:
    - Worker process: Creates request, persists to DB, subscribes to Redis Stream, waits for response
    - API process: Receives WebSocket message, updates DB, publishes to Redis Stream
    - Worker process: Receives Redis message, resolves the future
    """

    # HITL type configuration
    request_type = HITLRequestType.DECISION
    response_key = "decision"

    def __init__(
        self,
        message_bus: Optional[HITLMessageBusPort] = None,
        config: Optional[HITLManagerConfig] = None,
    ):
        """
        Initialize the decision manager.

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
        decision_request = request  # Type hint: DecisionRequest
        return HITLRequestEntity(
            id=request.request_id,
            request_type=HITLRequestType.DECISION,
            conversation_id=conversation_id,
            message_id=message_id,
            tenant_id=tenant_id,
            project_id=project_id,
            question=getattr(decision_request, "question", ""),
            options=[
                opt.to_dict() if hasattr(opt, "to_dict") else opt
                for opt in getattr(decision_request, "options", [])
            ],
            context=request.context,
            metadata={
                "decision_type": getattr(
                    decision_request, "decision_type", DecisionType.CUSTOM
                ).value,
                "allow_custom": getattr(decision_request, "allow_custom", False),
                "default_option": getattr(decision_request, "default_option", None),
            },
            expires_at=datetime.utcnow() + timedelta(seconds=timeout),
        )

    def _parse_response(self, message: HITLMessage) -> str:
        """Parse the decision response from a message bus message."""
        return message.payload.get(self.response_key, "")

    def _get_response_for_db(self, response: str) -> str:
        """Convert response to string for database storage."""
        return response

    # =========================================================================
    # Convenience methods for creating decision requests
    # =========================================================================

    async def create_request(
        self,
        question: str,
        decision_type: DecisionType,
        options: List[DecisionOption],
        allow_custom: bool = False,
        context: Optional[Dict[str, Any]] = None,
        default_option: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> str:
        """
        Create a new decision request and wait for user response.

        Args:
            question: The decision question
            decision_type: Type of decision
            options: List of decision options
            allow_custom: Whether user can provide custom response
            context: Additional context
            default_option: Default option if timeout (option ID)
            timeout: Maximum time to wait for response (seconds)

        Returns:
            User's decision (option ID or custom text)

        Raises:
            asyncio.TimeoutError: If user doesn't respond within timeout and no default
            asyncio.CancelledError: If request is cancelled
        """
        import uuid

        timeout = timeout or self._config.default_timeout
        request_id = str(uuid.uuid4())

        request = DecisionRequest(
            request_id=request_id,
            question=question,
            decision_type=decision_type,
            options=options,
            allow_custom=allow_custom,
            context=context or {},
            default_option=default_option,
        )

        async with self._lock:
            self._pending_requests[request_id] = request

        logger.info(f"Created decision request {request_id}: {question}")

        try:
            decision = await self.wait_for_response(
                request_id=request_id,
                timeout=timeout,
                default_response=default_option,
            )
            logger.info(f"Received decision for {request_id}: {decision}")
            return decision
        except asyncio.TimeoutError:
            if default_option:
                logger.warning(
                    f"Decision request {request_id} timed out, using default: {default_option}"
                )
                return default_option
            raise
        except asyncio.CancelledError:
            logger.warning(f"Decision request {request_id} was cancelled")
            raise
        finally:
            await self.unregister_request(request_id)


# Global decision manager instance
_decision_manager: Optional[DecisionManager] = None


def get_decision_manager() -> DecisionManager:
    """Get the global decision manager instance."""
    global _decision_manager
    if _decision_manager is None:
        _decision_manager = DecisionManager()
    return _decision_manager


def set_decision_manager(manager: DecisionManager) -> None:
    """Set the global decision manager instance (for DI)."""
    global _decision_manager
    _decision_manager = manager
