"""HITL Request entity for Human-in-the-Loop interactions.

HITL requests track pending human interactions in agent workflows,
enabling recovery after page refresh and audit trails.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional

from src.domain.shared_kernel import Entity


class HITLRequestType(str, Enum):
    """Type of HITL request."""

    CLARIFICATION = "clarification"
    DECISION = "decision"
    ENV_VAR = "env_var"


class HITLRequestStatus(str, Enum):
    """Status of HITL request.

    State transitions:
    - PENDING -> ANSWERED: User provides response
    - ANSWERED -> PROCESSING: Agent picks up the response
    - PROCESSING -> COMPLETED: Agent successfully processed the response
    - PENDING -> TIMEOUT: Request expired without response
    - PENDING -> CANCELLED: Request was cancelled

    Recovery: If Worker restarts while PROCESSING, the request remains
    ANSWERED (since PROCESSING is transient in-memory state). On startup,
    Worker scans for ANSWERED requests and re-triggers Agent execution.
    """

    PENDING = "pending"
    ANSWERED = "answered"
    PROCESSING = "processing"  # Agent is processing the response
    COMPLETED = "completed"  # Agent finished processing
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


@dataclass(kw_only=True)
class HITLRequest(Entity):
    """
    Human-in-the-Loop request for agent interactions.

    Stores pending HITL requests (clarification, decision, env_var) to enable:
    1. Recovery after page refresh - users can see pending requests
    2. Cross-process communication - API can find requests from Worker
    3. Audit trail - track all HITL interactions

    Attributes:
        request_type: Type of request (clarification, decision, env_var)
        conversation_id: ID of the conversation this belongs to
        message_id: ID of the message that triggered this request
        tenant_id: Tenant that owns this request
        project_id: Project this request belongs to
        user_id: User who should respond
        question: The question to ask the user
        options: List of options (for decision type)
        context: Additional context for the request
        metadata: Tool-specific metadata
        status: Current status of the request
        response: User's response when answered
        response_metadata: Additional metadata with response
        created_at: When the request was created
        expires_at: When the request expires
        answered_at: When the request was answered
    """

    request_type: HITLRequestType
    conversation_id: str
    tenant_id: str
    project_id: str
    question: str
    message_id: Optional[str] = None
    user_id: Optional[str] = None
    options: Optional[List[Dict[str, Any]]] = None
    context: Optional[Dict[str, Any]] = None
    metadata: Optional[Dict[str, Any]] = None
    status: HITLRequestStatus = HITLRequestStatus.PENDING
    response: Optional[str] = None
    response_metadata: Optional[Dict[str, Any]] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    expires_at: Optional[datetime] = None
    answered_at: Optional[datetime] = None

    def __post_init__(self):
        """Validate the entity after initialization."""
        if not self.conversation_id:
            raise ValueError("conversation_id is required")
        if not self.tenant_id:
            raise ValueError("tenant_id is required")
        if not self.project_id:
            raise ValueError("project_id is required")
        if not self.question:
            raise ValueError("question is required")

        # Set default expiration if not provided
        if self.expires_at is None:
            self.expires_at = self.created_at + timedelta(minutes=5)

    @property
    def is_pending(self) -> bool:
        """Check if request is still pending."""
        return self.status == HITLRequestStatus.PENDING

    @property
    def is_answered(self) -> bool:
        """Check if request has been answered but not yet processed."""
        return self.status == HITLRequestStatus.ANSWERED

    @property
    def needs_processing(self) -> bool:
        """Check if request needs Agent processing (answered but not completed)."""
        return self.status == HITLRequestStatus.ANSWERED

    @property
    def is_expired(self) -> bool:
        """Check if request has expired."""
        return datetime.utcnow() > self.expires_at if self.expires_at else False

    def answer(
        self,
        response: str,
        response_metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Mark request as answered with given response."""
        if not self.is_pending:
            raise ValueError(f"Cannot answer request with status: {self.status}")

        self.response = response
        self.response_metadata = response_metadata
        self.status = HITLRequestStatus.ANSWERED
        self.answered_at = datetime.utcnow()

    def mark_processing(self) -> None:
        """Mark request as being processed by Agent."""
        if self.status != HITLRequestStatus.ANSWERED:
            raise ValueError(f"Cannot mark processing for status: {self.status}")
        self.status = HITLRequestStatus.PROCESSING

    def mark_completed(self) -> None:
        """Mark request as completed (Agent finished processing)."""
        if self.status not in (HITLRequestStatus.ANSWERED, HITLRequestStatus.PROCESSING):
            raise ValueError(f"Cannot mark completed for status: {self.status}")
        self.status = HITLRequestStatus.COMPLETED

    def mark_timeout(self, default_response: Optional[str] = None) -> None:
        """Mark request as timed out."""
        if not self.is_pending:
            raise ValueError(f"Cannot timeout request with status: {self.status}")

        self.status = HITLRequestStatus.TIMEOUT
        if default_response:
            self.response = default_response
            self.response_metadata = {"is_default": True}

    def cancel(self) -> None:
        """Mark request as cancelled."""
        if not self.is_pending:
            raise ValueError(f"Cannot cancel request with status: {self.status}")

        self.status = HITLRequestStatus.CANCELLED

    @property
    def default_option(self) -> Optional[str]:
        """Get the default option if any (for decision type)."""
        if self.request_type != HITLRequestType.DECISION or not self.options:
            return None

        for option in self.options:
            if isinstance(option, dict) and option.get("is_default"):
                return option.get("value")

        return None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            "id": self.id,
            "request_type": self.request_type.value,
            "conversation_id": self.conversation_id,
            "message_id": self.message_id,
            "tenant_id": self.tenant_id,
            "project_id": self.project_id,
            "user_id": self.user_id,
            "question": self.question,
            "options": self.options,
            "context": self.context,
            "metadata": self.metadata,
            "status": self.status.value,
            "response": self.response,
            "response_metadata": self.response_metadata,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "answered_at": self.answered_at.isoformat() if self.answered_at else None,
        }
