"""Unified Event Types - Single Source of Truth.

This module provides the SINGLE SOURCE OF TRUTH for all event types in the MemStack system.
All event type definitions should be imported from this module to ensure consistency.

Event Naming Convention:
- Status events: status, start, complete, error
- Thinking events: thought, thought_delta
- Tool events: act, observe
- Text events: text_start, text_delta, text_end
- Plan events: plan_*, step_*
- HITL events: clarification_*, decision_*, env_var_*
- Sandbox events: sandbox_*, desktop_*, terminal_*
- Artifact events: artifact_*

Note: Event type values use flat naming (e.g., "thought", "act") for backward compatibility.
Future versions may use namespaced naming (e.g., "agent.thought", "agent.act").
"""

from enum import Enum
from typing import List, Set


class EventCategory(str, Enum):
    """Event categories for grouping and filtering."""

    AGENT = "agent"  # Agent execution events
    HITL = "hitl"  # Human-in-the-Loop events
    SANDBOX = "sandbox"  # Sandbox environment events
    SYSTEM = "system"  # System-level events
    MESSAGE = "message"  # Message events


class AgentEventType(str, Enum):
    """Unified event types for the Agent system.

    This is the SINGLE SOURCE OF TRUTH for all agent event types.
    Import this class instead of defining event types elsewhere.
    """

    # =========================================================================
    # Status events
    # =========================================================================
    STATUS = "status"
    START = "start"
    COMPLETE = "complete"
    ERROR = "error"

    # =========================================================================
    # Thinking events
    # =========================================================================
    THOUGHT = "thought"
    THOUGHT_DELTA = "thought_delta"

    # =========================================================================
    # Work plan events (multi-level thinking)
    # =========================================================================
    WORK_PLAN = "work_plan"
    STEP_START = "step_start"
    STEP_END = "step_end"
    STEP_FINISH = "step_finish"

    # =========================================================================
    # Tool events
    # =========================================================================
    ACT = "act"
    OBSERVE = "observe"

    # =========================================================================
    # Text events (streaming)
    # =========================================================================
    TEXT_START = "text_start"
    TEXT_DELTA = "text_delta"
    TEXT_END = "text_end"

    # =========================================================================
    # Message events
    # =========================================================================
    MESSAGE = "message"
    USER_MESSAGE = "user_message"
    ASSISTANT_MESSAGE = "assistant_message"

    # =========================================================================
    # Permission events
    # =========================================================================
    PERMISSION_ASKED = "permission_asked"
    PERMISSION_REPLIED = "permission_replied"

    # =========================================================================
    # Doom loop events
    # =========================================================================
    DOOM_LOOP_DETECTED = "doom_loop_detected"
    DOOM_LOOP_INTERVENED = "doom_loop_intervened"

    # =========================================================================
    # Human interaction events (HITL)
    # =========================================================================
    CLARIFICATION_ASKED = "clarification_asked"
    CLARIFICATION_ANSWERED = "clarification_answered"
    DECISION_ASKED = "decision_asked"
    DECISION_ANSWERED = "decision_answered"

    # =========================================================================
    # Environment variable events
    # =========================================================================
    ENV_VAR_REQUESTED = "env_var_requested"
    ENV_VAR_PROVIDED = "env_var_provided"

    # =========================================================================
    # Cost events
    # =========================================================================
    COST_UPDATE = "cost_update"

    # =========================================================================
    # Retry events
    # =========================================================================
    RETRY = "retry"

    # =========================================================================
    # Context events
    # =========================================================================
    COMPACT_NEEDED = "compact_needed"
    CONTEXT_COMPRESSED = "context_compressed"

    # =========================================================================
    # Pattern events
    # =========================================================================
    PATTERN_MATCH = "pattern_match"

    # =========================================================================
    # Skill execution events (L2 layer direct execution)
    # =========================================================================
    SKILL_MATCHED = "skill_matched"
    SKILL_EXECUTION_START = "skill_execution_start"
    SKILL_EXECUTION_COMPLETE = "skill_execution_complete"
    SKILL_FALLBACK = "skill_fallback"

    # =========================================================================
    # Plan Mode events
    # =========================================================================
    PLAN_MODE_ENTER = "plan_mode_enter"
    PLAN_MODE_EXIT = "plan_mode_exit"
    PLAN_CREATED = "plan_created"
    PLAN_UPDATED = "plan_updated"
    PLAN_STATUS_CHANGED = "plan_status_changed"
    PLAN_EXECUTION_START = "plan_execution_start"
    PLAN_EXECUTION_COMPLETE = "plan_execution_complete"
    PLAN_STEP_READY = "plan_step_ready"
    PLAN_STEP_COMPLETE = "plan_step_complete"
    PLAN_STEP_SKIPPED = "plan_step_skipped"
    PLAN_SNAPSHOT_CREATED = "plan_snapshot_created"
    PLAN_ROLLBACK = "plan_rollback"
    REFLECTION_COMPLETE = "reflection_complete"
    ADJUSTMENT_APPLIED = "adjustment_applied"

    # =========================================================================
    # Title generation events
    # =========================================================================
    TITLE_GENERATED = "title_generated"

    # =========================================================================
    # Sandbox events
    # =========================================================================
    SANDBOX_CREATED = "sandbox_created"
    SANDBOX_TERMINATED = "sandbox_terminated"
    SANDBOX_STATUS = "sandbox_status"
    DESKTOP_STARTED = "desktop_started"
    DESKTOP_STOPPED = "desktop_stopped"
    DESKTOP_STATUS = "desktop_status"
    TERMINAL_STARTED = "terminal_started"
    TERMINAL_STOPPED = "terminal_stopped"
    TERMINAL_STATUS = "terminal_status"

    # =========================================================================
    # Artifact events (rich output display)
    # =========================================================================
    ARTIFACT_CREATED = "artifact_created"
    ARTIFACT_READY = "artifact_ready"
    ARTIFACT_ERROR = "artifact_error"
    ARTIFACTS_BATCH = "artifacts_batch"

    # =========================================================================
    # Control events (used by event bus)
    # =========================================================================
    CANCELLED = "cancelled"


# =============================================================================
# Event Type Utilities
# =============================================================================

# Internal events that should not be exposed to frontend
INTERNAL_EVENT_TYPES: Set[AgentEventType] = {
    AgentEventType.COMPACT_NEEDED,  # Internal compression signal
    AgentEventType.RETRY,  # Internal retry logic
}

# Delta events that are not persisted to database (streaming fragments)
DELTA_EVENT_TYPES: Set[AgentEventType] = {
    AgentEventType.THOUGHT_DELTA,
    AgentEventType.TEXT_DELTA,
    AgentEventType.TEXT_START,
    AgentEventType.TEXT_END,
}

# Terminal events that indicate stream completion
TERMINAL_EVENT_TYPES: Set[AgentEventType] = {
    AgentEventType.COMPLETE,
    AgentEventType.ERROR,
    AgentEventType.CANCELLED,
}

# HITL events that require user response
HITL_EVENT_TYPES: Set[AgentEventType] = {
    AgentEventType.CLARIFICATION_ASKED,
    AgentEventType.DECISION_ASKED,
    AgentEventType.ENV_VAR_REQUESTED,
    AgentEventType.PERMISSION_ASKED,
}

# Event categories mapping
EVENT_CATEGORIES: dict[AgentEventType, EventCategory] = {
    # Agent events
    AgentEventType.STATUS: EventCategory.AGENT,
    AgentEventType.START: EventCategory.AGENT,
    AgentEventType.COMPLETE: EventCategory.AGENT,
    AgentEventType.ERROR: EventCategory.AGENT,
    AgentEventType.THOUGHT: EventCategory.AGENT,
    AgentEventType.THOUGHT_DELTA: EventCategory.AGENT,
    AgentEventType.ACT: EventCategory.AGENT,
    AgentEventType.OBSERVE: EventCategory.AGENT,
    AgentEventType.TEXT_START: EventCategory.AGENT,
    AgentEventType.TEXT_DELTA: EventCategory.AGENT,
    AgentEventType.TEXT_END: EventCategory.AGENT,
    AgentEventType.WORK_PLAN: EventCategory.AGENT,
    AgentEventType.STEP_START: EventCategory.AGENT,
    AgentEventType.STEP_END: EventCategory.AGENT,
    AgentEventType.STEP_FINISH: EventCategory.AGENT,
    AgentEventType.CANCELLED: EventCategory.AGENT,
    # HITL events
    AgentEventType.CLARIFICATION_ASKED: EventCategory.HITL,
    AgentEventType.CLARIFICATION_ANSWERED: EventCategory.HITL,
    AgentEventType.DECISION_ASKED: EventCategory.HITL,
    AgentEventType.DECISION_ANSWERED: EventCategory.HITL,
    AgentEventType.ENV_VAR_REQUESTED: EventCategory.HITL,
    AgentEventType.ENV_VAR_PROVIDED: EventCategory.HITL,
    AgentEventType.PERMISSION_ASKED: EventCategory.HITL,
    AgentEventType.PERMISSION_REPLIED: EventCategory.HITL,
    # Sandbox events
    AgentEventType.SANDBOX_CREATED: EventCategory.SANDBOX,
    AgentEventType.SANDBOX_TERMINATED: EventCategory.SANDBOX,
    AgentEventType.SANDBOX_STATUS: EventCategory.SANDBOX,
    AgentEventType.DESKTOP_STARTED: EventCategory.SANDBOX,
    AgentEventType.DESKTOP_STOPPED: EventCategory.SANDBOX,
    AgentEventType.DESKTOP_STATUS: EventCategory.SANDBOX,
    AgentEventType.TERMINAL_STARTED: EventCategory.SANDBOX,
    AgentEventType.TERMINAL_STOPPED: EventCategory.SANDBOX,
    AgentEventType.TERMINAL_STATUS: EventCategory.SANDBOX,
    # Message events
    AgentEventType.MESSAGE: EventCategory.MESSAGE,
    AgentEventType.USER_MESSAGE: EventCategory.MESSAGE,
    AgentEventType.ASSISTANT_MESSAGE: EventCategory.MESSAGE,
    # System events
    AgentEventType.COMPACT_NEEDED: EventCategory.SYSTEM,
    AgentEventType.CONTEXT_COMPRESSED: EventCategory.SYSTEM,
    AgentEventType.COST_UPDATE: EventCategory.SYSTEM,
    AgentEventType.RETRY: EventCategory.SYSTEM,
}


def get_frontend_event_types() -> List[str]:
    """Get all event type values for frontend TypeScript generation.

    Returns:
        List of event type strings that should be exposed to frontend
    """
    return [et.value for et in AgentEventType if et not in INTERNAL_EVENT_TYPES]


def get_event_category(event_type: AgentEventType) -> EventCategory:
    """Get the category of an event type.

    Args:
        event_type: The event type to categorize

    Returns:
        EventCategory for the event type, defaults to AGENT
    """
    return EVENT_CATEGORIES.get(event_type, EventCategory.AGENT)


def is_terminal_event(event_type: AgentEventType) -> bool:
    """Check if an event type is a terminal event.

    Args:
        event_type: The event type to check

    Returns:
        True if the event indicates stream completion
    """
    return event_type in TERMINAL_EVENT_TYPES


def is_delta_event(event_type: AgentEventType) -> bool:
    """Check if an event type is a delta (streaming fragment) event.

    Args:
        event_type: The event type to check

    Returns:
        True if the event is a streaming delta
    """
    return event_type in DELTA_EVENT_TYPES


def is_hitl_event(event_type: AgentEventType) -> bool:
    """Check if an event type requires human interaction.

    Args:
        event_type: The event type to check

    Returns:
        True if the event requires user response
    """
    return event_type in HITL_EVENT_TYPES
