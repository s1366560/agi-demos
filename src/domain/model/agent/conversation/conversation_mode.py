"""Conversation mode enum for multi-agent conversations (Track B, P2-3 phase-2).

The mode is a STRUCTURAL protocol fact — it picks routing defaults and HITL
visibility; it is never inferred from message content.

Modes:
- SINGLE_AGENT          : legacy — one agent per conversation.
- MULTI_AGENT_SHARED    : multiple agents share one thread; all messages broadcast.
- MULTI_AGENT_ISOLATED  : multiple agents each have their own thread scoped by
                          ``focused_agent_id``; messages are private by default.
- AUTONOMOUS            : user offline; a ``coordinator_agent_id`` drives the
                          group toward the goal described by the linked
                          ``WorkspaceTask`` until a termination gate fires.
"""

from enum import Enum


class ConversationMode(str, Enum):
    """Conversation-level collaboration mode."""

    SINGLE_AGENT = "single_agent"
    MULTI_AGENT_SHARED = "multi_agent_shared"
    MULTI_AGENT_ISOLATED = "multi_agent_isolated"
    AUTONOMOUS = "autonomous"

    @property
    def is_multi_agent(self) -> bool:
        """Whether this mode permits more than one participant agent."""
        return self != ConversationMode.SINGLE_AGENT

    @property
    def requires_coordinator(self) -> bool:
        """Autonomous mode mandates a coordinator_agent_id."""
        return self == ConversationMode.AUTONOMOUS
