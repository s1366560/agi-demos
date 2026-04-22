"""Unit tests for multi-agent Conversation domain extensions (Track B, P2-3 phase-2).

Covers:
- ConversationMode enum semantics
- Roster add/remove + coordinator/focused invariants
- Sender-in-roster write-path check
- Structured mentions (no text parsing)
- Domain events emission + consumption
- to_dict / from_dict round-trip
"""

from __future__ import annotations

import pytest

from src.domain.events.types import AgentEventType
from src.domain.model.agent.conversation import (
    Conversation,
    ConversationMode,
    CoordinatorRequiredError,
    Message,
    MessageRole,
    ParticipantAlreadyPresentError,
    ParticipantLimitError,
    ParticipantNotPresentError,
    SenderNotInRosterError,
)

# ---------------------------------------------------------------------------
# ConversationMode
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestConversationMode:
    def test_values(self) -> None:
        assert ConversationMode.SINGLE_AGENT.value == "single_agent"
        assert ConversationMode.MULTI_AGENT_SHARED.value == "multi_agent_shared"
        assert ConversationMode.MULTI_AGENT_ISOLATED.value == "multi_agent_isolated"
        assert ConversationMode.AUTONOMOUS.value == "autonomous"

    def test_is_multi_agent(self) -> None:
        assert not ConversationMode.SINGLE_AGENT.is_multi_agent
        assert ConversationMode.MULTI_AGENT_SHARED.is_multi_agent
        assert ConversationMode.MULTI_AGENT_ISOLATED.is_multi_agent
        assert ConversationMode.AUTONOMOUS.is_multi_agent

    def test_requires_coordinator(self) -> None:
        assert ConversationMode.AUTONOMOUS.requires_coordinator
        assert not ConversationMode.MULTI_AGENT_SHARED.requires_coordinator


# ---------------------------------------------------------------------------
# Conversation roster
# ---------------------------------------------------------------------------


def _conv(**overrides: object) -> Conversation:
    defaults: dict[str, object] = {
        "project_id": "proj-1",
        "tenant_id": "tenant-1",
        "user_id": "user-1",
        "title": "multi-agent chat",
    }
    defaults.update(overrides)
    return Conversation(**defaults)  # type: ignore[arg-type]


@pytest.mark.unit
class TestRoster:
    def test_resolve_mode_override_wins(self) -> None:
        conv = _conv(conversation_mode=ConversationMode.MULTI_AGENT_SHARED)
        assert conv.resolve_mode("single_agent") == ConversationMode.MULTI_AGENT_SHARED

    def test_resolve_mode_inherits_project(self) -> None:
        conv = _conv()
        assert conv.resolve_mode("multi_agent_isolated") == ConversationMode.MULTI_AGENT_ISOLATED

    def test_add_participant_emits_event(self) -> None:
        conv = _conv()
        conv.add_participant(
            "agent-a",
            effective_mode=ConversationMode.MULTI_AGENT_SHARED,
            actor_id="user-1",
            role="participant",
        )
        assert conv.has_participant("agent-a")
        events = conv.consume_pending_events()
        assert len(events) == 1
        assert events[0].event_type == AgentEventType.CONVERSATION_PARTICIPANT_JOINED
        assert events[0].agent_id == "agent-a"  # type: ignore[attr-defined]
        # Drained once
        assert conv.consume_pending_events() == []

    def test_add_participant_duplicate_rejected(self) -> None:
        conv = _conv(participant_agents=["agent-a"])
        with pytest.raises(ParticipantAlreadyPresentError):
            conv.add_participant("agent-a", effective_mode=ConversationMode.MULTI_AGENT_SHARED)

    def test_single_agent_mode_blocks_second_add(self) -> None:
        conv = _conv(participant_agents=["agent-a"])
        with pytest.raises(ParticipantLimitError):
            conv.add_participant("agent-b", effective_mode=ConversationMode.SINGLE_AGENT)

    def test_remove_clears_coordinator_and_focused(self) -> None:
        conv = _conv(
            participant_agents=["agent-a", "agent-b"],
            coordinator_agent_id="agent-a",
            focused_agent_id="agent-a",
        )
        conv.remove_participant("agent-a", actor_id="user-1", reason="test")
        assert conv.coordinator_agent_id is None
        assert conv.focused_agent_id is None
        events = conv.consume_pending_events()
        assert len(events) == 1
        assert events[0].event_type == AgentEventType.CONVERSATION_PARTICIPANT_LEFT

    def test_remove_missing_raises(self) -> None:
        conv = _conv()
        with pytest.raises(ParticipantNotPresentError):
            conv.remove_participant("agent-a")

    def test_set_coordinator_requires_roster_membership(self) -> None:
        conv = _conv()
        with pytest.raises(ParticipantNotPresentError):
            conv.set_coordinator("agent-a")
        conv.participant_agents.append("agent-a")
        conv.set_coordinator("agent-a")
        assert conv.coordinator_agent_id == "agent-a"
        conv.set_coordinator(None)
        assert conv.coordinator_agent_id is None

    def test_set_focused_requires_roster_membership(self) -> None:
        conv = _conv()
        with pytest.raises(ParticipantNotPresentError):
            conv.set_focused_agent("agent-a")


# ---------------------------------------------------------------------------
# Sender invariant
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSenderInvariant:
    def test_user_message_always_allowed(self) -> None:
        conv = _conv()
        conv.assert_sender_in_roster(None)  # no exception

    def test_agent_sender_must_be_in_roster(self) -> None:
        conv = _conv(participant_agents=["agent-a"])
        conv.assert_sender_in_roster("agent-a")
        with pytest.raises(SenderNotInRosterError):
            conv.assert_sender_in_roster("agent-b")


# ---------------------------------------------------------------------------
# Autonomous invariants
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAutonomousInvariants:
    def test_requires_coordinator(self) -> None:
        conv = _conv(conversation_mode=ConversationMode.AUTONOMOUS)
        with pytest.raises(CoordinatorRequiredError):
            conv.assert_autonomous_invariants(ConversationMode.AUTONOMOUS)

        conv.participant_agents.append("agent-a")
        conv.coordinator_agent_id = "agent-a"
        conv.assert_autonomous_invariants(ConversationMode.AUTONOMOUS)

    def test_coordinator_must_be_in_roster(self) -> None:
        conv = _conv(
            conversation_mode=ConversationMode.AUTONOMOUS,
            coordinator_agent_id="ghost-agent",
        )
        with pytest.raises(ParticipantNotPresentError):
            conv.assert_autonomous_invariants(ConversationMode.AUTONOMOUS)

    def test_non_autonomous_mode_is_a_noop(self) -> None:
        conv = _conv()  # no coordinator
        conv.assert_autonomous_invariants(ConversationMode.MULTI_AGENT_SHARED)


# ---------------------------------------------------------------------------
# Message structured mentions
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMessageStructuredFields:
    def test_default_sender_and_mentions(self) -> None:
        msg = Message(conversation_id="c1", role=MessageRole.USER, content="hi")
        assert msg.sender_agent_id is None
        assert msg.mentions == []

    def test_agent_message_with_mentions(self) -> None:
        msg = Message(
            conversation_id="c1",
            role=MessageRole.ASSISTANT,
            content="routing to @beta",
            sender_agent_id="agent-alpha",
            mentions=["agent-beta", "agent-gamma"],
        )
        assert msg.sender_agent_id == "agent-alpha"
        assert msg.mentions == ["agent-beta", "agent-gamma"]


# ---------------------------------------------------------------------------
# Serialization round-trip
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSerialization:
    def test_conversation_round_trip_preserves_multi_agent_fields(self) -> None:
        original = _conv(
            participant_agents=["agent-a", "agent-b"],
            conversation_mode=ConversationMode.AUTONOMOUS,
            coordinator_agent_id="agent-a",
            focused_agent_id=None,
        )
        restored = Conversation.from_dict(original.to_dict())
        assert restored.participant_agents == ["agent-a", "agent-b"]
        assert restored.conversation_mode == ConversationMode.AUTONOMOUS
        assert restored.coordinator_agent_id == "agent-a"
        assert restored.focused_agent_id is None

    def test_legacy_dict_without_multi_agent_fields(self) -> None:
        """from_dict must tolerate legacy payloads produced before P2-3 phase-2."""
        legacy = {
            "id": "c1",
            "project_id": "p",
            "tenant_id": "t",
            "user_id": "u",
            "title": "old",
            "status": "active",
            "message_count": 0,
            "created_at": "2024-01-01T00:00:00+00:00",
            "updated_at": None,
            "summary": None,
            "fork_source_id": None,
            "fork_context_snapshot": None,
            "merge_strategy": "result_only",
        }
        restored = Conversation.from_dict(legacy)  # type: ignore[arg-type]
        assert restored.participant_agents == []
        assert restored.conversation_mode is None
        assert restored.coordinator_agent_id is None
