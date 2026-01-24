"""AgentExecutionEvent entity for persisting SSE events during agent execution.

This entity stores all Server-Sent Events (SSE) emitted during agent execution,
enabling event replay for reconnection and conversation switching scenarios.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict

from src.domain.shared_kernel import Entity


class AgentEventType(str, Enum):
    """Types of SSE events emitted during agent execution."""

    # Message events (for unified timeline)
    USER_MESSAGE = "user_message"
    ASSISTANT_MESSAGE = "assistant_message"

    # Basic message events
    MESSAGE = "message"
    THOUGHT = "thought"
    ACT = "act"
    OBSERVE = "observe"

    # Text streaming events
    TEXT_START = "text_start"
    TEXT_DELTA = "text_delta"
    TEXT_END = "text_end"

    # Work plan events
    WORK_PLAN = "work_plan"
    STEP_START = "step_start"
    STEP_END = "step_end"
    PATTERN_MATCH = "pattern_match"

    # Decision events
    DECISION_ASKED = "decision_asked"
    DECISION_ANSWERED = "decision_answered"
    CLARIFICATION_ASKED = "clarification_asked"
    CLARIFICATION_ANSWERED = "clarification_answered"

    # Skill execution events (L2 layer)
    SKILL_MATCHED = "skill_matched"
    SKILL_EXECUTION_START = "skill_execution_start"
    SKILL_TOOL_START = "skill_tool_start"
    SKILL_TOOL_RESULT = "skill_tool_result"
    SKILL_EXECUTION_COMPLETE = "skill_execution_complete"
    SKILL_FALLBACK = "skill_fallback"

    # Terminal events
    COMPLETE = "complete"
    ERROR = "error"

    # Doom loop detection
    DOOM_LOOP_DETECTED = "doom_loop_detected"


@dataclass(kw_only=True)
class AgentExecutionEvent(Entity):
    """
    A single SSE event during agent execution.

    This entity captures all events emitted during the agent's ReAct loop,
    storing them for replay purposes when a client reconnects or switches
    between conversations.

    Attributes:
        conversation_id: The conversation this event belongs to
        message_id: The message this event is associated with
        event_type: Type of SSE event (thought, act, observe, etc.)
        event_data: JSON payload of the event
        sequence_number: Monotonically increasing number for ordering
        created_at: When this event was created
    """

    conversation_id: str
    message_id: str
    event_type: AgentEventType | str
    event_data: Dict[str, Any] = field(default_factory=dict)
    sequence_number: int = 0
    created_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API response."""
        return {
            "id": self.id,
            "conversation_id": self.conversation_id,
            "message_id": self.message_id,
            "event_type": self.event_type,
            "event_data": self.event_data,
            "sequence_number": self.sequence_number,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def to_sse_format(self) -> Dict[str, Any]:
        """Convert to SSE event format for streaming."""
        return {
            "type": self.event_type,
            "data": self.event_data,
            "timestamp": self.created_at.isoformat() if self.created_at else None,
        }
