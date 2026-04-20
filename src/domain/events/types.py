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
- Sandbox events: sandbox_*, desktop_*, terminal_*, http_service_*
- Artifact events: artifact_*

Note: Event type values use flat naming (e.g., "thought", "act") for backward compatibility.
Future versions may use namespaced naming (e.g., "agent.thought", "agent.act").
"""

from enum import Enum


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
    # Tool events
    # =========================================================================
    ACT = "act"
    ACT_DELTA = "act_delta"
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
    CONTEXT_STATUS = "context_status"
    CONTEXT_SUMMARY_GENERATED = "context_summary_generated"

    # =========================================================================
    # Memory events (auto-recall / auto-capture)
    # =========================================================================
    MEMORY_RECALLED = "memory_recalled"
    MEMORY_CAPTURED = "memory_captured"

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
    HTTP_SERVICE_STARTED = "http_service_started"
    HTTP_SERVICE_UPDATED = "http_service_updated"
    HTTP_SERVICE_STOPPED = "http_service_stopped"
    HTTP_SERVICE_ERROR = "http_service_error"

    # =========================================================================
    # Suggestion events (follow-up suggestions)
    # =========================================================================
    SUGGESTIONS = "suggestions"

    # =========================================================================
    # Artifact events (rich output display)
    # =========================================================================
    ARTIFACT_CREATED = "artifact_created"
    ARTIFACT_READY = "artifact_ready"
    ARTIFACT_ERROR = "artifact_error"
    ARTIFACTS_BATCH = "artifacts_batch"
    ARTIFACT_OPEN = "artifact_open"
    ARTIFACT_UPDATE = "artifact_update"
    ARTIFACT_CLOSE = "artifact_close"

    # =========================================================================
    # MCP App events (interactive HTML interfaces)
    # =========================================================================
    MCP_APP_RESULT = "mcp_app_result"
    MCP_APP_REGISTERED = "mcp_app_registered"

    # =========================================================================
    # SubAgent events (L3 layer independent execution)
    # =========================================================================
    SUBAGENT_ROUTED = "subagent_routed"
    SUBAGENT_STARTED = "subagent_started"
    SUBAGENT_COMPLETED = "subagent_completed"
    SUBAGENT_FAILED = "subagent_failed"
    SUBAGENT_SPAWNING = "subagent_spawning"
    SUBAGENT_DOOM_LOOP = "subagent_doom_loop"
    SUBAGENT_RETRY = "subagent_retry"
    SUBAGENT_QUEUED = "subagent_queued"
    SUBAGENT_KILLED = "subagent_killed"
    SUBAGENT_STEERED = "subagent_steered"
    SUBAGENT_DEPTH_LIMITED = "subagent_depth_limited"
    SUBAGENT_SESSION_UPDATE = "subagent_session_update"
    SUBAGENT_SPAWN_REJECTED = "subagent_spawn_rejected"
    SUBAGENT_ANNOUNCE_RETRY = "subagent_announce_retry"
    SUBAGENT_ORPHAN_DETECTED = "subagent_orphan_detected"
    SUBAGENT_ANNOUNCE_SENT = "subagent_announce_sent"
    SUBAGENT_ANNOUNCE_RECEIVED = "subagent_announce_received"
    SUBAGENT_ANNOUNCE_EXPIRED = "subagent_announce_expired"
    TOOL_POLICY_DENIED = "tool_policy_denied"

    # =========================================================================
    # Control events (used by event bus)
    # =========================================================================
    CANCELLED = "cancelled"

    # =========================================================================
    # Task list events (agent todo tracking)
    # =========================================================================
    TASK_LIST_UPDATED = "task_list_updated"
    TASK_UPDATED = "task_updated"
    TASK_START = "task_start"
    TASK_COMPLETE = "task_complete"

    # =========================================================================
    # Tool update events (real-time tool hot-plug)
    # =========================================================================
    TOOLS_UPDATED = "tools_updated"

    # =========================================================================
    # Progress events (long-running operation updates)
    # =========================================================================
    PROGRESS = "progress"

    # =========================================================================
    # MCP Elicitation events (MCP server -> user requests)
    # =========================================================================
    ELICITATION_ASKED = "elicitation_asked"
    ELICITATION_ANSWERED = "elicitation_answered"

    # =========================================================================
    # Canvas events (A2UI dynamic UI blocks)
    # =========================================================================
    CANVAS_UPDATED = "canvas_updated"
    A2UI_ACTION_ASKED = "a2ui_action_asked"
    A2UI_ACTION_ANSWERED = "a2ui_action_answered"

    # =========================================================================
    # Agent routing & orchestration events
    # =========================================================================
    PLAN_SUGGESTED = "plan_suggested"
    SELECTION_TRACE = "selection_trace"
    POLICY_FILTERED = "policy_filtered"
    PARALLEL_STARTED = "parallel_started"
    PARALLEL_COMPLETED = "parallel_completed"
    BACKGROUND_LAUNCHED = "background_launched"

    # =========================================================================
    # Multi-agent inter-agent communication events
    # =========================================================================
    AGENT_SPAWNED = "agent_spawned"
    AGENT_COMPLETED = "agent_completed"
    AGENT_MESSAGE_SENT = "agent_message_sent"
    AGENT_MESSAGE_RECEIVED = "agent_message_received"
    AGENT_STOPPED = "agent_stopped"

    # =========================================================================
    # SubAgent delegation events (explicit delegation flow for UX)
    # =========================================================================
    SUBAGENT_DELEGATION = "subagent_delegation"

    # =========================================================================
    # Context engine & session lifecycle events (Phase 3)
    # =========================================================================
    CONTEXT_COMPACTED = "context_compacted"
    SESSION_FORKED = "session_forked"
    SESSION_MERGED = "session_merged"

    # =========================================================================
    # Graph orchestration events (multi-agent DAG execution)
    # =========================================================================
    GRAPH_RUN_STARTED = "graph_run_started"
    GRAPH_RUN_COMPLETED = "graph_run_completed"
    GRAPH_RUN_FAILED = "graph_run_failed"
    GRAPH_RUN_CANCELLED = "graph_run_cancelled"
    GRAPH_NODE_STARTED = "graph_node_started"
    GRAPH_NODE_COMPLETED = "graph_node_completed"
    GRAPH_NODE_FAILED = "graph_node_failed"
    GRAPH_NODE_SKIPPED = "graph_node_skipped"
    GRAPH_HANDOFF = "graph_handoff"

    # =========================================================================
    # Workspace collaboration events
    # =========================================================================
    WORKSPACE_MEMBER_JOINED = "workspace_member_joined"
    BLACKBOARD_POST_CREATED = "blackboard_post_created"
    WORKSPACE_TASK_ASSIGNED = "workspace_task_assigned"
    TOPOLOGY_UPDATED = "topology_updated"
    WORKSPACE_TASK_CREATED = "workspace_task_created"
    WORKSPACE_TASK_UPDATED = "workspace_task_updated"
    WORKSPACE_TASK_DELETED = "workspace_task_deleted"
    WORKSPACE_TASK_STATUS_CHANGED = "workspace_task_status_changed"
    BLACKBOARD_POST_UPDATED = "blackboard_post_updated"
    BLACKBOARD_POST_DELETED = "blackboard_post_deleted"
    BLACKBOARD_REPLY_CREATED = "blackboard_reply_created"
    BLACKBOARD_REPLY_DELETED = "blackboard_reply_deleted"
    WORKSPACE_UPDATED = "workspace_updated"
    WORKSPACE_DELETED = "workspace_deleted"
    WORKSPACE_MEMBER_LEFT = "workspace_member_left"
    WORKSPACE_AGENT_BOUND = "workspace_agent_bound"
    WORKSPACE_AGENT_UNBOUND = "workspace_agent_unbound"
    WORKSPACE_MESSAGE_CREATED = "workspace_message_created"

    # Workspace orchestration lifecycle events
    WORKSPACE_GOAL_MATERIALIZED = "workspace_goal_materialized"
    WORKSPACE_DECOMPOSITION_COMPLETE = "workspace_decomposition_complete"
    WORKSPACE_WORKER_DISPATCHED = "workspace_worker_dispatched"
    WORKSPACE_WORKER_REPORT_SUBMITTED = "workspace_worker_report_submitted"
    WORKSPACE_ADJUDICATION_COMPLETE = "workspace_adjudication_complete"
    WORKSPACE_GOAL_COMPLETED = "workspace_goal_completed"


# =============================================================================
# Event Type Utilities
# =============================================================================

# Internal events that should not be exposed to frontend
INTERNAL_EVENT_TYPES: set[AgentEventType] = {
    AgentEventType.COMPACT_NEEDED,  # Internal compression signal
    AgentEventType.RETRY,  # Internal retry logic
}

# Delta events that are not persisted to database (streaming fragments)
DELTA_EVENT_TYPES: set[AgentEventType] = {
    AgentEventType.THOUGHT_DELTA,
    AgentEventType.TEXT_DELTA,
    AgentEventType.TEXT_START,
    AgentEventType.TEXT_END,
    AgentEventType.ACT_DELTA,
}

# Terminal events that indicate stream completion
TERMINAL_EVENT_TYPES: set[AgentEventType] = {
    AgentEventType.COMPLETE,
    AgentEventType.ERROR,
    AgentEventType.CANCELLED,
}

# HITL events that require user response
HITL_EVENT_TYPES: set[AgentEventType] = {
    AgentEventType.CLARIFICATION_ASKED,
    AgentEventType.DECISION_ASKED,
    AgentEventType.ENV_VAR_REQUESTED,
    AgentEventType.PERMISSION_ASKED,
    AgentEventType.ELICITATION_ASKED,
    AgentEventType.A2UI_ACTION_ASKED,
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
    AgentEventType.ACT_DELTA: EventCategory.AGENT,
    AgentEventType.OBSERVE: EventCategory.AGENT,
    AgentEventType.TEXT_START: EventCategory.AGENT,
    AgentEventType.TEXT_DELTA: EventCategory.AGENT,
    AgentEventType.TEXT_END: EventCategory.AGENT,
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
    AgentEventType.ELICITATION_ASKED: EventCategory.HITL,
    AgentEventType.ELICITATION_ANSWERED: EventCategory.HITL,
    AgentEventType.A2UI_ACTION_ASKED: EventCategory.HITL,
    AgentEventType.A2UI_ACTION_ANSWERED: EventCategory.HITL,
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
    AgentEventType.HTTP_SERVICE_STARTED: EventCategory.SANDBOX,
    AgentEventType.HTTP_SERVICE_UPDATED: EventCategory.SANDBOX,
    AgentEventType.HTTP_SERVICE_STOPPED: EventCategory.SANDBOX,
    AgentEventType.HTTP_SERVICE_ERROR: EventCategory.SANDBOX,
    # Message events
    AgentEventType.MESSAGE: EventCategory.MESSAGE,
    AgentEventType.USER_MESSAGE: EventCategory.MESSAGE,
    AgentEventType.ASSISTANT_MESSAGE: EventCategory.MESSAGE,
    # System events
    AgentEventType.COMPACT_NEEDED: EventCategory.SYSTEM,
    AgentEventType.CONTEXT_COMPRESSED: EventCategory.SYSTEM,
    AgentEventType.CONTEXT_STATUS: EventCategory.SYSTEM,
    AgentEventType.CONTEXT_SUMMARY_GENERATED: EventCategory.SYSTEM,
    AgentEventType.COST_UPDATE: EventCategory.SYSTEM,
    AgentEventType.RETRY: EventCategory.SYSTEM,
    # Suggestion events
    AgentEventType.SUGGESTIONS: EventCategory.AGENT,
    # Artifact lifecycle events
    AgentEventType.ARTIFACT_OPEN: EventCategory.AGENT,
    AgentEventType.ARTIFACT_UPDATE: EventCategory.AGENT,
    AgentEventType.ARTIFACT_CLOSE: EventCategory.AGENT,
    # MCP App events
    AgentEventType.MCP_APP_RESULT: EventCategory.AGENT,
    AgentEventType.MCP_APP_REGISTERED: EventCategory.AGENT,
    # Task list events
    AgentEventType.TASK_LIST_UPDATED: EventCategory.AGENT,
    AgentEventType.TASK_UPDATED: EventCategory.AGENT,
    AgentEventType.TASK_START: EventCategory.AGENT,
    AgentEventType.TASK_COMPLETE: EventCategory.AGENT,
    # Tool update events
    AgentEventType.TOOLS_UPDATED: EventCategory.AGENT,
    # Canvas events
    AgentEventType.CANVAS_UPDATED: EventCategory.AGENT,
    # Agent routing & orchestration events
    AgentEventType.PLAN_SUGGESTED: EventCategory.AGENT,
    AgentEventType.SELECTION_TRACE: EventCategory.AGENT,
    AgentEventType.POLICY_FILTERED: EventCategory.AGENT,
    AgentEventType.PARALLEL_STARTED: EventCategory.AGENT,
    AgentEventType.PARALLEL_COMPLETED: EventCategory.AGENT,
    AgentEventType.BACKGROUND_LAUNCHED: EventCategory.AGENT,
    AgentEventType.SUBAGENT_ROUTED: EventCategory.AGENT,
    AgentEventType.SUBAGENT_STARTED: EventCategory.AGENT,
    AgentEventType.SUBAGENT_COMPLETED: EventCategory.AGENT,
    AgentEventType.SUBAGENT_FAILED: EventCategory.AGENT,
    AgentEventType.SUBAGENT_SPAWNING: EventCategory.AGENT,
    AgentEventType.SUBAGENT_DOOM_LOOP: EventCategory.AGENT,
    AgentEventType.SUBAGENT_RETRY: EventCategory.AGENT,
    AgentEventType.SUBAGENT_QUEUED: EventCategory.AGENT,
    AgentEventType.SUBAGENT_KILLED: EventCategory.AGENT,
    AgentEventType.SUBAGENT_STEERED: EventCategory.AGENT,
    AgentEventType.SUBAGENT_DEPTH_LIMITED: EventCategory.AGENT,
    AgentEventType.SUBAGENT_SESSION_UPDATE: EventCategory.AGENT,
    AgentEventType.SUBAGENT_SPAWN_REJECTED: EventCategory.AGENT,
    AgentEventType.SUBAGENT_ANNOUNCE_RETRY: EventCategory.AGENT,
    AgentEventType.SUBAGENT_ORPHAN_DETECTED: EventCategory.AGENT,
    AgentEventType.SUBAGENT_ANNOUNCE_SENT: EventCategory.AGENT,
    AgentEventType.SUBAGENT_ANNOUNCE_RECEIVED: EventCategory.AGENT,
    AgentEventType.SUBAGENT_ANNOUNCE_EXPIRED: EventCategory.AGENT,
    AgentEventType.TOOL_POLICY_DENIED: EventCategory.AGENT,
    # SubAgent delegation events (UX indicator)
    AgentEventType.SUBAGENT_DELEGATION: EventCategory.AGENT,
    # Multi-agent inter-agent communication
    AgentEventType.AGENT_SPAWNED: EventCategory.AGENT,
    AgentEventType.AGENT_COMPLETED: EventCategory.AGENT,
    AgentEventType.AGENT_MESSAGE_SENT: EventCategory.AGENT,
    AgentEventType.AGENT_MESSAGE_RECEIVED: EventCategory.AGENT,
    AgentEventType.AGENT_STOPPED: EventCategory.AGENT,
    # Context engine & session lifecycle events (Phase 3)
    AgentEventType.CONTEXT_COMPACTED: EventCategory.SYSTEM,
    AgentEventType.SESSION_FORKED: EventCategory.AGENT,
    AgentEventType.SESSION_MERGED: EventCategory.AGENT,
    # Graph orchestration events (multi-agent DAG execution)
    AgentEventType.GRAPH_RUN_STARTED: EventCategory.AGENT,
    AgentEventType.GRAPH_RUN_COMPLETED: EventCategory.AGENT,
    AgentEventType.GRAPH_RUN_FAILED: EventCategory.AGENT,
    AgentEventType.GRAPH_RUN_CANCELLED: EventCategory.AGENT,
    AgentEventType.GRAPH_NODE_STARTED: EventCategory.AGENT,
    AgentEventType.GRAPH_NODE_COMPLETED: EventCategory.AGENT,
    AgentEventType.GRAPH_NODE_FAILED: EventCategory.AGENT,
    AgentEventType.GRAPH_NODE_SKIPPED: EventCategory.AGENT,
    AgentEventType.GRAPH_HANDOFF: EventCategory.AGENT,
    # Workspace collaboration events
    AgentEventType.WORKSPACE_MEMBER_JOINED: EventCategory.AGENT,
    AgentEventType.BLACKBOARD_POST_CREATED: EventCategory.AGENT,
    AgentEventType.WORKSPACE_TASK_ASSIGNED: EventCategory.AGENT,
    AgentEventType.TOPOLOGY_UPDATED: EventCategory.AGENT,
    AgentEventType.WORKSPACE_TASK_CREATED: EventCategory.AGENT,
    AgentEventType.WORKSPACE_TASK_UPDATED: EventCategory.AGENT,
    AgentEventType.WORKSPACE_TASK_DELETED: EventCategory.AGENT,
    AgentEventType.WORKSPACE_TASK_STATUS_CHANGED: EventCategory.AGENT,
    AgentEventType.BLACKBOARD_POST_UPDATED: EventCategory.AGENT,
    AgentEventType.BLACKBOARD_POST_DELETED: EventCategory.AGENT,
    AgentEventType.BLACKBOARD_REPLY_CREATED: EventCategory.AGENT,
    AgentEventType.BLACKBOARD_REPLY_DELETED: EventCategory.AGENT,
    AgentEventType.WORKSPACE_UPDATED: EventCategory.AGENT,
    AgentEventType.WORKSPACE_DELETED: EventCategory.AGENT,
    AgentEventType.WORKSPACE_MEMBER_LEFT: EventCategory.AGENT,
    AgentEventType.WORKSPACE_AGENT_BOUND: EventCategory.AGENT,
    AgentEventType.WORKSPACE_AGENT_UNBOUND: EventCategory.AGENT,
    AgentEventType.WORKSPACE_MESSAGE_CREATED: EventCategory.AGENT,
    # Workspace orchestration lifecycle events
    AgentEventType.WORKSPACE_GOAL_MATERIALIZED: EventCategory.AGENT,
    AgentEventType.WORKSPACE_DECOMPOSITION_COMPLETE: EventCategory.AGENT,
    AgentEventType.WORKSPACE_WORKER_DISPATCHED: EventCategory.AGENT,
    AgentEventType.WORKSPACE_WORKER_REPORT_SUBMITTED: EventCategory.AGENT,
    AgentEventType.WORKSPACE_ADJUDICATION_COMPLETE: EventCategory.AGENT,
    AgentEventType.WORKSPACE_GOAL_COMPLETED: EventCategory.AGENT,
}


def get_frontend_event_types() -> list[str]:
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
