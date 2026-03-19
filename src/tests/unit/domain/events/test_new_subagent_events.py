"""Tests for new SubAgent lifecycle hardening events."""

import pytest

from src.domain.events.agent_events import (
    SubAgentAnnounceRetryEvent,
    SubAgentOrphanDetectedEvent,
    SubAgentSpawnRejectedEvent,
)
from src.domain.events.types import AgentEventType


@pytest.mark.unit
class TestSubAgentSpawnRejectedEvent:
    def test_event_type_value(self) -> None:
        event = SubAgentSpawnRejectedEvent(
            subagent_name="researcher",
            rejection_code="concurrency_exceeded",
            rejection_reason="Too many active runs",
        )
        assert event.event_type == AgentEventType.SUBAGENT_SPAWN_REJECTED

    def test_to_event_dict_structure(self) -> None:
        event = SubAgentSpawnRejectedEvent(
            subagent_name="researcher",
            rejection_code="subagent_not_allowed",
            rejection_reason="Not in allowlist",
            requester_id="req-1",
            context={"policy": "restricted"},
        )
        d = event.to_event_dict()
        assert d["type"] == "subagent_spawn_rejected"
        assert d["data"]["subagent_name"] == "researcher"
        assert d["data"]["rejection_code"] == "subagent_not_allowed"
        assert d["data"]["context"] == {"policy": "restricted"}
        assert "event_type" not in d["data"]
        assert "timestamp" not in d["data"]

    def test_frozen_immutability(self) -> None:
        event = SubAgentSpawnRejectedEvent(
            subagent_name="r", rejection_code="x", rejection_reason="y"
        )
        with pytest.raises(Exception):
            event.subagent_name = "other"  # type: ignore[misc]


@pytest.mark.unit
class TestSubAgentAnnounceRetryEvent:
    def test_event_type_value(self) -> None:
        event = SubAgentAnnounceRetryEvent(
            agent_id="a1", session_id="s1", attempt=1, max_retries=3, delay_ms=400
        )
        assert event.event_type == AgentEventType.SUBAGENT_ANNOUNCE_RETRY

    def test_to_event_dict_structure(self) -> None:
        event = SubAgentAnnounceRetryEvent(
            agent_id="a1",
            session_id="s1",
            attempt=2,
            max_retries=3,
            delay_ms=800,
            error="timeout",
            error_category="transient",
        )
        d = event.to_event_dict()
        assert d["type"] == "subagent_announce_retry"
        assert d["data"]["attempt"] == 2
        assert d["data"]["error_category"] == "transient"


@pytest.mark.unit
class TestSubAgentOrphanDetectedEvent:
    def test_event_type_value(self) -> None:
        event = SubAgentOrphanDetectedEvent(
            run_id="r1",
            subagent_name="coder",
            conversation_id="conv-1",
            reason="timeout",
        )
        assert event.event_type == AgentEventType.SUBAGENT_ORPHAN_DETECTED

    def test_to_event_dict_structure(self) -> None:
        event = SubAgentOrphanDetectedEvent(
            run_id="r1",
            subagent_name="coder",
            conversation_id="conv-1",
            reason="parent_gone",
            age_seconds=120.5,
            action_taken="cancelled",
        )
        d = event.to_event_dict()
        assert d["type"] == "subagent_orphan_detected"
        assert d["data"]["reason"] == "parent_gone"
        assert d["data"]["age_seconds"] == 120.5
        assert d["data"]["action_taken"] == "cancelled"
