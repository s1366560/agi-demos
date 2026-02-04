"""
HITL Types - Unified Type Definitions for Human-in-the-Loop Interactions.

This module provides the SINGLE SOURCE OF TRUTH for all HITL type definitions.
All HITL-related code should import types from here.

These types are designed to:
1. Be serializable for Temporal workflows
2. Support automatic TypeScript generation
3. Provide strong typing throughout the codebase

Type Generation:
    Run `make generate-types` to generate TypeScript types from these definitions.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Union

# =============================================================================
# HITL Request Types
# =============================================================================


class HITLType(str, Enum):
    """Type of HITL interaction."""

    CLARIFICATION = "clarification"
    DECISION = "decision"
    ENV_VAR = "env_var"
    PERMISSION = "permission"


class HITLStatus(str, Enum):
    """Status of an HITL request.

    Lifecycle:
        PENDING → ANSWERED → COMPLETED
        PENDING → TIMEOUT
        PENDING → CANCELLED
    """

    PENDING = "pending"  # Waiting for user response
    ANSWERED = "answered"  # User provided response, awaiting processing
    COMPLETED = "completed"  # Agent finished processing
    TIMEOUT = "timeout"  # Request timed out
    CANCELLED = "cancelled"  # Request was cancelled


# =============================================================================
# Clarification Types
# =============================================================================


class ClarificationType(str, Enum):
    """Type of clarification needed."""

    SCOPE = "scope"  # Clarify task scope or boundaries
    APPROACH = "approach"  # Choose between multiple approaches
    PREREQUISITE = "prerequisite"  # Clarify prerequisites or assumptions
    PRIORITY = "priority"  # Clarify priority or order
    CONFIRMATION = "confirmation"  # Yes/No confirmation
    CUSTOM = "custom"  # Custom clarification question


@dataclass
class ClarificationOption:
    """An option for clarification questions."""

    id: str
    label: str
    description: Optional[str] = None
    recommended: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "description": self.description,
            "recommended": self.recommended,
        }


@dataclass
class ClarificationRequestData:
    """Data for a clarification request."""

    question: str
    clarification_type: ClarificationType = ClarificationType.CUSTOM
    options: List[ClarificationOption] = field(default_factory=list)
    allow_custom: bool = True
    context: Dict[str, Any] = field(default_factory=dict)
    default_value: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "question": self.question,
            "clarification_type": self.clarification_type.value,
            "options": [opt.to_dict() for opt in self.options],
            "allow_custom": self.allow_custom,
            "context": self.context,
            "default_value": self.default_value,
        }


# =============================================================================
# Decision Types
# =============================================================================


class DecisionType(str, Enum):
    """Type of decision needed."""

    BRANCH = "branch"  # Choose execution branch
    METHOD = "method"  # Choose implementation method
    CONFIRMATION = "confirmation"  # Confirm a risky operation
    RISK = "risk"  # Acknowledge and proceed with risk
    SINGLE_CHOICE = "single_choice"  # Select one option
    MULTI_CHOICE = "multi_choice"  # Select multiple options
    CUSTOM = "custom"  # Custom decision point


class RiskLevel(str, Enum):
    """Risk level for decision options."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class DecisionOption:
    """An option for decision requests."""

    id: str
    label: str
    description: Optional[str] = None
    recommended: bool = False
    risk_level: Optional[RiskLevel] = None
    estimated_time: Optional[str] = None
    estimated_cost: Optional[str] = None
    risks: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "description": self.description,
            "recommended": self.recommended,
            "risk_level": self.risk_level.value if self.risk_level else None,
            "estimated_time": self.estimated_time,
            "estimated_cost": self.estimated_cost,
            "risks": self.risks,
        }


@dataclass
class DecisionRequestData:
    """Data for a decision request."""

    question: str
    decision_type: DecisionType = DecisionType.CUSTOM
    options: List[DecisionOption] = field(default_factory=list)
    allow_custom: bool = False
    default_option: Optional[str] = None
    max_selections: Optional[int] = None
    context: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "question": self.question,
            "decision_type": self.decision_type.value,
            "options": [opt.to_dict() for opt in self.options],
            "allow_custom": self.allow_custom,
            "default_option": self.default_option,
            "max_selections": self.max_selections,
            "context": self.context,
        }


# =============================================================================
# Environment Variable Types
# =============================================================================


class EnvVarInputType(str, Enum):
    """Input type for environment variable fields."""

    TEXT = "text"
    PASSWORD = "password"
    URL = "url"
    API_KEY = "api_key"
    FILE_PATH = "file_path"


@dataclass
class EnvVarField:
    """A field in an environment variable request."""

    name: str  # Variable name (e.g., "OPENAI_API_KEY")
    label: str  # Display label
    description: Optional[str] = None
    required: bool = True
    secret: bool = False  # Whether to mask input
    input_type: EnvVarInputType = EnvVarInputType.TEXT
    default_value: Optional[str] = None
    placeholder: Optional[str] = None
    pattern: Optional[str] = None  # Validation regex

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label,
            "description": self.description,
            "required": self.required,
            "secret": self.secret,
            "input_type": self.input_type.value,
            "default_value": self.default_value,
            "placeholder": self.placeholder,
            "pattern": self.pattern,
        }


@dataclass
class EnvVarRequestData:
    """Data for an environment variable request."""

    tool_name: str  # Tool that needs the env vars
    fields: List[EnvVarField]
    message: Optional[str] = None
    allow_save: bool = True  # Whether to save for future sessions
    context: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "fields": [f.to_dict() for f in self.fields],
            "message": self.message,
            "allow_save": self.allow_save,
            "context": self.context,
        }


# =============================================================================
# Permission Types
# =============================================================================


class PermissionAction(str, Enum):
    """Action for permission response."""

    ALLOW = "allow"  # Allow this action
    DENY = "deny"  # Deny this action
    ALLOW_ALWAYS = "allow_always"  # Allow and remember for this tool
    DENY_ALWAYS = "deny_always"  # Deny and remember for this tool


@dataclass
class PermissionRequestData:
    """Data for a permission request."""

    tool_name: str
    action: str  # Description of the action
    risk_level: RiskLevel = RiskLevel.MEDIUM
    details: Dict[str, Any] = field(default_factory=dict)
    description: Optional[str] = None
    allow_remember: bool = True
    default_action: Optional[PermissionAction] = None
    context: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "action": self.action,
            "risk_level": self.risk_level.value,
            "details": self.details,
            "description": self.description,
            "allow_remember": self.allow_remember,
            "default_action": self.default_action.value if self.default_action else None,
            "context": self.context,
        }


# =============================================================================
# Unified HITL Request
# =============================================================================


@dataclass
class HITLRequest:
    """Unified HITL request that can represent any type of interaction."""

    request_id: str
    hitl_type: HITLType
    conversation_id: str
    message_id: Optional[str] = None

    # Type-specific data (only one will be set)
    clarification_data: Optional[ClarificationRequestData] = None
    decision_data: Optional[DecisionRequestData] = None
    env_var_data: Optional[EnvVarRequestData] = None
    permission_data: Optional[PermissionRequestData] = None

    # Common fields
    status: HITLStatus = HITLStatus.PENDING
    timeout_seconds: float = 300.0
    created_at: datetime = field(default_factory=datetime.utcnow)
    expires_at: Optional[datetime] = None

    # Tenant context
    tenant_id: Optional[str] = None
    project_id: Optional[str] = None
    user_id: Optional[str] = None

    def __post_init__(self):
        if self.expires_at is None:
            from datetime import timedelta

            self.expires_at = self.created_at + timedelta(seconds=self.timeout_seconds)

    @property
    def question(self) -> str:
        """Get the question/prompt for display."""
        if self.clarification_data:
            return self.clarification_data.question
        if self.decision_data:
            return self.decision_data.question
        if self.env_var_data:
            return self.env_var_data.message or f"Please provide environment variables for {self.env_var_data.tool_name}"
        if self.permission_data:
            return self.permission_data.description or f"Allow {self.permission_data.tool_name} to {self.permission_data.action}?"
        return ""

    @property
    def type_specific_data(self) -> Dict[str, Any]:
        """Get the type-specific data as a dictionary."""
        if self.clarification_data:
            return self.clarification_data.to_dict()
        if self.decision_data:
            return self.decision_data.to_dict()
        if self.env_var_data:
            return self.env_var_data.to_dict()
        if self.permission_data:
            return self.permission_data.to_dict()
        return {}

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "request_id": self.request_id,
            "hitl_type": self.hitl_type.value,
            "conversation_id": self.conversation_id,
            "message_id": self.message_id,
            "status": self.status.value,
            "timeout_seconds": self.timeout_seconds,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "tenant_id": self.tenant_id,
            "project_id": self.project_id,
            "user_id": self.user_id,
            "question": self.question,
            **self.type_specific_data,
        }


# =============================================================================
# HITL Response Types
# =============================================================================


@dataclass
class ClarificationResponse:
    """Response to a clarification request."""

    answer: Union[str, List[str]]  # Option ID(s) or custom text


@dataclass
class DecisionResponse:
    """Response to a decision request."""

    decision: Union[str, List[str]]  # Option ID(s)


@dataclass
class EnvVarResponse:
    """Response to an environment variable request."""

    values: Dict[str, str]  # Variable name → value
    save: bool = False  # Save for future sessions


@dataclass
class PermissionResponse:
    """Response to a permission request."""

    action: PermissionAction
    remember: bool = False


@dataclass
class HITLResponse:
    """Unified HITL response."""

    request_id: str
    hitl_type: HITLType

    # Type-specific response (only one will be set)
    clarification_response: Optional[ClarificationResponse] = None
    decision_response: Optional[DecisionResponse] = None
    env_var_response: Optional[EnvVarResponse] = None
    permission_response: Optional[PermissionResponse] = None

    # Response metadata
    responded_at: datetime = field(default_factory=datetime.utcnow)
    user_id: Optional[str] = None

    @property
    def response_value(self) -> Any:
        """Get the response value for the Agent."""
        if self.clarification_response:
            return self.clarification_response.answer
        if self.decision_response:
            return self.decision_response.decision
        if self.env_var_response:
            return self.env_var_response.values
        if self.permission_response:
            return self.permission_response.action.value
        return None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        result = {
            "request_id": self.request_id,
            "hitl_type": self.hitl_type.value,
            "responded_at": self.responded_at.isoformat() if self.responded_at else None,
            "user_id": self.user_id,
        }

        if self.clarification_response:
            result["answer"] = self.clarification_response.answer
        elif self.decision_response:
            result["decision"] = self.decision_response.decision
        elif self.env_var_response:
            result["values"] = self.env_var_response.values
            result["save"] = self.env_var_response.save
        elif self.permission_response:
            result["action"] = self.permission_response.action.value
            result["remember"] = self.permission_response.remember

        return result


# =============================================================================
# Temporal Signal Types
# =============================================================================


@dataclass
class HITLSignalPayload:
    """Payload for HITL response Temporal Signal.

    This is sent from API to Workflow when user responds to HITL request.
    """

    request_id: str
    hitl_type: HITLType
    response_data: Dict[str, Any]  # Type-specific response data
    user_id: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "request_id": self.request_id,
            "hitl_type": self.hitl_type.value,
            "response_data": self.response_data,
            "user_id": self.user_id,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "HITLSignalPayload":
        return cls(
            request_id=data["request_id"],
            hitl_type=HITLType(data["hitl_type"]),
            response_data=data.get("response_data", {}),
            user_id=data.get("user_id"),
            timestamp=(
                datetime.fromisoformat(data["timestamp"])
                if data.get("timestamp")
                else datetime.utcnow()
            ),
        )


# Temporal Signal name constant
HITL_RESPONSE_SIGNAL = "hitl_response"


# =============================================================================
# Utility Functions
# =============================================================================


def create_clarification_request(
    request_id: str,
    conversation_id: str,
    question: str,
    options: List[ClarificationOption],
    clarification_type: ClarificationType = ClarificationType.CUSTOM,
    allow_custom: bool = True,
    timeout_seconds: float = 300.0,
    **kwargs,
) -> HITLRequest:
    """Factory function to create a clarification request."""
    return HITLRequest(
        request_id=request_id,
        hitl_type=HITLType.CLARIFICATION,
        conversation_id=conversation_id,
        timeout_seconds=timeout_seconds,
        clarification_data=ClarificationRequestData(
            question=question,
            clarification_type=clarification_type,
            options=options,
            allow_custom=allow_custom,
            context=kwargs.get("context", {}),
            default_value=kwargs.get("default_value"),
        ),
        **{k: v for k, v in kwargs.items() if k not in ("context", "default_value")},
    )


def create_decision_request(
    request_id: str,
    conversation_id: str,
    question: str,
    options: List[DecisionOption],
    decision_type: DecisionType = DecisionType.SINGLE_CHOICE,
    allow_custom: bool = False,
    timeout_seconds: float = 300.0,
    **kwargs,
) -> HITLRequest:
    """Factory function to create a decision request."""
    return HITLRequest(
        request_id=request_id,
        hitl_type=HITLType.DECISION,
        conversation_id=conversation_id,
        timeout_seconds=timeout_seconds,
        decision_data=DecisionRequestData(
            question=question,
            decision_type=decision_type,
            options=options,
            allow_custom=allow_custom,
            default_option=kwargs.get("default_option"),
            max_selections=kwargs.get("max_selections"),
            context=kwargs.get("context", {}),
        ),
        **{
            k: v
            for k, v in kwargs.items()
            if k not in ("context", "default_option", "max_selections")
        },
    )


def create_env_var_request(
    request_id: str,
    conversation_id: str,
    tool_name: str,
    fields: List[EnvVarField],
    message: Optional[str] = None,
    timeout_seconds: float = 300.0,
    **kwargs,
) -> HITLRequest:
    """Factory function to create an environment variable request."""
    return HITLRequest(
        request_id=request_id,
        hitl_type=HITLType.ENV_VAR,
        conversation_id=conversation_id,
        timeout_seconds=timeout_seconds,
        env_var_data=EnvVarRequestData(
            tool_name=tool_name,
            fields=fields,
            message=message,
            allow_save=kwargs.get("allow_save", True),
            context=kwargs.get("context", {}),
        ),
        **{k: v for k, v in kwargs.items() if k not in ("context", "allow_save")},
    )


def create_permission_request(
    request_id: str,
    conversation_id: str,
    tool_name: str,
    action: str,
    risk_level: RiskLevel = RiskLevel.MEDIUM,
    timeout_seconds: float = 60.0,
    **kwargs,
) -> HITLRequest:
    """Factory function to create a permission request."""
    return HITLRequest(
        request_id=request_id,
        hitl_type=HITLType.PERMISSION,
        conversation_id=conversation_id,
        timeout_seconds=timeout_seconds,
        permission_data=PermissionRequestData(
            tool_name=tool_name,
            action=action,
            risk_level=risk_level,
            details=kwargs.get("details", {}),
            description=kwargs.get("description"),
            allow_remember=kwargs.get("allow_remember", True),
            default_action=kwargs.get("default_action"),
            context=kwargs.get("context", {}),
        ),
        **{
            k: v
            for k, v in kwargs.items()
            if k not in ("context", "details", "description", "allow_remember", "default_action")
        },
    )


# =============================================================================
# Helper Functions
# =============================================================================


def is_request_expired(request: HITLRequest) -> bool:
    """
    Check if a HITL request has expired.

    Args:
        request: The HITL request to check

    Returns:
        True if the request has expired, False otherwise
    """
    if request.expires_at is None:
        return False
    return datetime.now(timezone.utc) > request.expires_at


def get_remaining_time_seconds(request: HITLRequest) -> int | None:
    """
    Get the remaining time in seconds before a request expires.

    Args:
        request: The HITL request to check

    Returns:
        Remaining seconds (can be negative if expired), or None if no expiry set
    """
    if request.expires_at is None:
        return None
    delta = request.expires_at - datetime.now(timezone.utc)
    return int(delta.total_seconds())


# =============================================================================
# HITL Exceptions
# =============================================================================


class HITLPendingException(Exception):
    """
    Exception raised when an HITL request requires user input.

    This exception is used to pause the Agent execution loop and signal
    that the Workflow should wait for a user response via Temporal Signal.

    The exception carries all necessary data to:
    1. Emit SSE event to frontend
    2. Save Agent state for later resumption
    3. Wait for user response in Workflow

    Usage in processor:
        try:
            result = await hitl_handler.request_clarification(...)
        except HITLPendingException as e:
            # Save state and return to workflow
            return {"hitl_pending": True, **e.to_dict()}
    """

    def __init__(
        self,
        request_id: str,
        hitl_type: HITLType,
        request_data: Dict[str, Any],
        conversation_id: str,
        message_id: Optional[str] = None,
        timeout_seconds: float = 300.0,
    ):
        self.request_id = request_id
        self.hitl_type = hitl_type
        self.request_data = request_data
        self.conversation_id = conversation_id
        self.message_id = message_id
        self.timeout_seconds = timeout_seconds

        super().__init__(
            f"HITL request pending: {hitl_type.value} ({request_id})"
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "request_id": self.request_id,
            "hitl_type": self.hitl_type.value,
            "request_data": self.request_data,
            "conversation_id": self.conversation_id,
            "message_id": self.message_id,
            "timeout_seconds": self.timeout_seconds,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "HITLPendingException":
        """Create from dictionary."""
        return cls(
            request_id=data["request_id"],
            hitl_type=HITLType(data["hitl_type"]),
            request_data=data.get("request_data", {}),
            conversation_id=data["conversation_id"],
            message_id=data.get("message_id"),
            timeout_seconds=data.get("timeout_seconds", 300.0),
        )
