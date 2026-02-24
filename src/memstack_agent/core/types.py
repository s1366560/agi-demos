"""Core type definitions for memstack-agent.

This module provides the foundational types used throughout the framework.
All types are immutable (frozen dataclass) and have zero external dependencies.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ProcessorState(str, Enum):
    """State of the agent processor during ReAct loop.

    The processor transitions through these states:
    - IDLE: Not processing
    - THINKING: LLM is generating thoughts/actions
    - ACTING: Executing tool calls
    - OBSERVING: Processing tool results
    - WAITING_PERMISSION: Awaiting user permission
    - WAITING_CLARIFICATION: Awaiting user clarification (HITL)
    - WAITING_DECISION: Awaiting user decision (HITL)
    - WAITING_ENV_VAR: Awaiting environment variables (HITL)
    - RETRYING: Backing off for retry
    - COMPLETED: Processing finished successfully
    - ERROR: Processing failed with error
    """

    IDLE = "idle"
    THINKING = "thinking"
    ACTING = "acting"
    OBSERVING = "observing"
    WAITING_PERMISSION = "waiting_permission"
    WAITING_CLARIFICATION = "waiting_clarification"
    WAITING_DECISION = "waiting_decision"
    WAITING_ENV_VAR = "waiting_env_var"
    RETRYING = "retrying"
    COMPLETED = "completed"
    ERROR = "error"


class EventCategory(str, Enum):
    """Categories for grouping and filtering events.

    Events are categorized to support:
    - Selective event subscription
    - Event filtering by type
    - UI component routing
    """

    AGENT = "agent"  # Agent execution events
    HITL = "hitl"  # Human-in-the-Loop events
    SANDBOX = "sandbox"  # Sandbox environment events
    SYSTEM = "system"  # System-level events
    MESSAGE = "message"  # Message events


class EventType(str, Enum):
    """All event types emitted by the framework.

    This is the single source of truth for event types.
    Event naming convention:
    - Status: status, start, complete, error
    - Thinking: thought, thought_delta
    - Tool: act, observe
    - Text: text_start, text_delta, text_end
    - HITL: clarification_*, decision_*, env_var_*
    """

    # Status events
    STATUS = "status"
    START = "start"
    COMPLETE = "complete"
    ERROR = "error"

    # Thinking events
    THOUGHT = "thought"
    THOUGHT_DELTA = "thought_delta"

    # Tool events
    ACT = "act"
    ACT_DELTA = "act_delta"
    OBSERVE = "observe"

    # Text events (streaming)
    TEXT_START = "text_start"
    TEXT_DELTA = "text_delta"
    TEXT_END = "text_end"

    # Message events
    MESSAGE = "message"
    USER_MESSAGE = "user_message"
    ASSISTANT_MESSAGE = "assistant_message"

    # Permission events
    PERMISSION_ASKED = "permission_asked"
    PERMISSION_REPLIED = "permission_replied"

    # Doom loop events
    DOOM_LOOP_DETECTED = "doom_loop_detected"
    DOOM_LOOP_INTERVENED = "doom_loop_intervened"

    # Human interaction events (HITL)
    CLARIFICATION_ASKED = "clarification_asked"
    CLARIFICATION_ANSWERED = "clarification_answered"
    DECISION_ASKED = "decision_asked"
    DECISION_ANSWERED = "decision_answered"

    # Environment variable events
    ENV_VAR_REQUESTED = "env_var_requested"
    ENV_VAR_PROVIDED = "env_var_provided"

    # Cost events
    COST_UPDATE = "cost_update"

    # Retry events
    RETRY = "retry"

    # Context events
    COMPACT_NEEDED = "compact_needed"
    CONTEXT_COMPRESSED = "context_compressed"
    CONTEXT_STATUS = "context_status"

    # Pattern events
    PATTERN_MATCH = "pattern_match"

    # Skill events
    SKILL_MATCHED = "skill_matched"
    SKILL_EXECUTION_START = "skill_execution_start"
    SKILL_EXECUTION_COMPLETE = "skill_execution_complete"
    SKILL_FALLBACK = "skill_fallback"

    # Sandbox events
    SANDBOX_CREATED = "sandbox_created"
    SANDBOX_TERMINATED = "sandbox_terminated"
    SANDBOX_STATUS = "sandbox_status"

    # SubAgent events
    SUBAGENT_ROUTED = "subagent_routed"
    SUBAGENT_STARTED = "subagent_started"
    SUBAGENT_COMPLETED = "subagent_completed"
    SUBAGENT_FAILED = "subagent_failed"


@dataclass(frozen=True, kw_only=True)
class AgentContext:
    """Immutable context passed through agent execution.

    Contains session-scoped data that doesn't change during
    a single conversation turn:
    - Session/conversation identifiers
    - User/project metadata
    - Configuration limits
    - External service clients (LLM, storage)
    """

    session_id: str
    conversation_id: str
    user_id: str
    project_id: str
    model: str
    max_tokens: int = 200000
    max_steps: int = 50
    metadata: dict[str, Any] = field(default_factory=dict)

    def with_metadata(self, **kwargs: Any) -> "AgentContext":
        """Return a new context with updated metadata.

        This preserves immutability while allowing metadata extension.
        """
        return AgentContext(
            session_id=self.session_id,
            conversation_id=self.conversation_id,
            user_id=self.user_id,
            project_id=self.project_id,
            model=self.model,
            max_tokens=self.max_tokens,
            max_steps=self.max_steps,
            metadata={**self.metadata, **kwargs},
        )


@dataclass(frozen=True, kw_only=True)
class ProcessorConfig:
    """Immutable configuration for the agent processor.

    Includes:
    - Model settings (provider, temperature, limits)
    - Processing limits (max steps, doom loop threshold)
    - Retry configuration (max attempts, backoff)
    - Permission settings (timeout, deny behavior)
    """

    # Model configuration
    model: str
    api_key: str | None = None
    base_url: str | None = None
    temperature: float = 0.0
    max_tokens: int = 4096

    # Processing limits
    max_steps: int = 50
    max_tool_calls_per_step: int = 10
    doom_loop_threshold: int = 3

    # Retry configuration
    max_attempts: int = 5
    initial_delay_ms: int = 2000

    # Permission configuration
    permission_timeout: float = 300.0
    continue_on_deny: bool = False

    # Cost tracking
    context_limit: int = 200000

    def with_model(self, model: str) -> "ProcessorConfig":
        """Return new config with different model."""
        return ProcessorConfig(
            model=model,
            api_key=self.api_key,
            base_url=self.base_url,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            max_steps=self.max_steps,
            max_tool_calls_per_step=self.max_tool_calls_per_step,
            doom_loop_threshold=self.doom_loop_threshold,
            max_attempts=self.max_attempts,
            initial_delay_ms=self.initial_delay_ms,
            permission_timeout=self.permission_timeout,
            continue_on_deny=self.continue_on_deny,
            context_limit=self.context_limit,
        )


# Event category mapping
_EVENT_CATEGORIES: dict[EventType, EventCategory] = {
    # Agent events
    EventType.STATUS: EventCategory.AGENT,
    EventType.START: EventCategory.AGENT,
    EventType.COMPLETE: EventCategory.AGENT,
    EventType.ERROR: EventCategory.AGENT,
    EventType.THOUGHT: EventCategory.AGENT,
    EventType.THOUGHT_DELTA: EventCategory.AGENT,
    EventType.ACT: EventCategory.AGENT,
    EventType.ACT_DELTA: EventCategory.AGENT,
    EventType.OBSERVE: EventCategory.AGENT,
    EventType.TEXT_START: EventCategory.AGENT,
    EventType.TEXT_DELTA: EventCategory.AGENT,
    EventType.TEXT_END: EventCategory.AGENT,
    # HITL events
    EventType.CLARIFICATION_ASKED: EventCategory.HITL,
    EventType.CLARIFICATION_ANSWERED: EventCategory.HITL,
    EventType.DECISION_ASKED: EventCategory.HITL,
    EventType.DECISION_ANSWERED: EventCategory.HITL,
    EventType.ENV_VAR_REQUESTED: EventCategory.HITL,
    EventType.ENV_VAR_PROVIDED: EventCategory.HITL,
    EventType.PERMISSION_ASKED: EventCategory.HITL,
    EventType.PERMISSION_REPLIED: EventCategory.HITL,
    # Sandbox events
    EventType.SANDBOX_CREATED: EventCategory.SANDBOX,
    EventType.SANDBOX_TERMINATED: EventCategory.SANDBOX,
    EventType.SANDBOX_STATUS: EventCategory.SANDBOX,
    # Message events
    EventType.MESSAGE: EventCategory.MESSAGE,
    EventType.USER_MESSAGE: EventCategory.MESSAGE,
    EventType.ASSISTANT_MESSAGE: EventCategory.MESSAGE,
    # System events
    EventType.COMPACT_NEEDED: EventCategory.SYSTEM,
    EventType.CONTEXT_COMPRESSED: EventCategory.SYSTEM,
    EventType.CONTEXT_STATUS: EventCategory.SYSTEM,
    EventType.COST_UPDATE: EventCategory.SYSTEM,
    EventType.RETRY: EventCategory.SYSTEM,
}


def get_event_category(event_type: EventType) -> EventCategory:
    """Get the category for an event type.

    Args:
        event_type: The event type to categorize

    Returns:
        EventCategory for the event type, defaults to AGENT
    """
    return _EVENT_CATEGORIES.get(event_type, EventCategory.AGENT)


def is_terminal_event(event_type: EventType) -> bool:
    """Check if an event type is terminal (ends the stream).

    Args:
        event_type: The event type to check

    Returns:
        True if the event indicates stream completion
    """
    return event_type in {EventType.COMPLETE, EventType.ERROR}
