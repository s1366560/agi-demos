"""Tests for unified event serialization (Phase 2)."""

import pytest

from src.domain.events.agent_events import (
    AgentActEvent,
    AgentCompleteEvent,
    AgentErrorEvent,
    AgentObserveEvent,
    AgentTextDeltaEvent,
    AgentThoughtEvent,
)


class TestEventSerialization:
    """Test unified event serialization via to_event_dict()."""

    def test_thought_event_serialization(self):
        """ThoughtEvent should serialize correctly."""
        event = AgentThoughtEvent(content="Thinking...", thought_level="task")
        event_dict = event.to_event_dict()

        assert event_dict["type"] == "thought"
        assert event_dict["data"]["content"] == "Thinking..."
        assert event_dict["data"]["thought_level"] == "task"
        assert "timestamp" in event_dict
        assert "event_type" not in event_dict["data"]
        assert "timestamp" not in event_dict["data"]

    def test_act_event_serialization(self):
        """ActEvent should serialize correctly."""
        event = AgentActEvent(
            tool_name="search",
            tool_input={"query": "test"},
            call_id="call_123",
            status="running"
        )
        event_dict = event.to_event_dict()

        assert event_dict["type"] == "act"
        assert event_dict["data"]["tool_name"] == "search"
        assert event_dict["data"]["tool_input"] == {"query": "test"}
        assert event_dict["data"]["call_id"] == "call_123"
        assert event_dict["data"]["status"] == "running"

    def test_observe_event_serialization(self):
        """ObserveEvent should serialize correctly."""
        event = AgentObserveEvent(
            tool_name="search",
            result="Found 5 results",
            duration_ms=100,
            call_id="call_123",
        )
        event_dict = event.to_event_dict()

        assert event_dict["type"] == "observe"
        assert event_dict["data"]["tool_name"] == "search"
        assert event_dict["data"]["result"] == "Found 5 results"
        assert event_dict["data"]["duration_ms"] == 100

    def test_text_delta_event_serialization(self):
        """TextDeltaEvent should serialize correctly."""
        event = AgentTextDeltaEvent(delta="Hello")
        event_dict = event.to_event_dict()

        assert event_dict["type"] == "text_delta"
        assert event_dict["data"]["delta"] == "Hello"

    def test_complete_event_serialization(self):
        """CompleteEvent should serialize correctly."""
        event = AgentCompleteEvent(result="Done", trace_url="https://trace.url")
        event_dict = event.to_event_dict()

        assert event_dict["type"] == "complete"
        assert event_dict["data"]["result"] == "Done"
        assert event_dict["data"]["trace_url"] == "https://trace.url"

    def test_error_event_serialization(self):
        """ErrorEvent should serialize correctly."""
        event = AgentErrorEvent(message="Something went wrong", code="ERR_001")
        event_dict = event.to_event_dict()

        assert event_dict["type"] == "error"
        assert event_dict["data"]["message"] == "Something went wrong"
        assert event_dict["data"]["code"] == "ERR_001"

    def test_all_events_have_required_fields(self):
        """All event dicts should have type, data, timestamp fields."""
        events = [
            AgentThoughtEvent(content="test", thought_level="task"),
            AgentActEvent(tool_name="test", tool_input={}),
            AgentObserveEvent(tool_name="test", result="ok"),
            AgentTextDeltaEvent(delta="a"),
            AgentCompleteEvent(),
            AgentErrorEvent(message="error"),
        ]

        for event in events:
            event_dict = event.to_event_dict()
            assert "type" in event_dict, f"{event.event_type} missing 'type'"
            assert "data" in event_dict, f"{event.event_type} missing 'data'"
            assert "timestamp" in event_dict, f"{event.event_type} missing 'timestamp'"
            assert isinstance(event_dict["type"], str)
            assert isinstance(event_dict["data"], dict)

    def test_event_dict_is_json_serializable(self):
        """Event dict should be JSON serializable."""
        import json

        event = AgentThoughtEvent(content="Test", thought_level="task")
        event_dict = event.to_event_dict()

        try:
            json.dumps(event_dict)
        except (TypeError, ValueError) as e:
            pytest.fail(f"Event dict is not JSON serializable: {e}")


class TestToolExecutionId:
    """Test tool_execution_id field for act/observe event matching."""

    def test_act_event_with_tool_execution_id(self):
        """ActEvent should include tool_execution_id field."""
        event = AgentActEvent(
            tool_name="MemorySearch",
            tool_input={"query": "test"},
            call_id="call_123",
            status="running",
            tool_execution_id="exec_abc123def456",  # New field
        )
        event_dict = event.to_event_dict()

        assert event_dict["data"]["tool_execution_id"] == "exec_abc123def456"
        assert event_dict["data"]["tool_name"] == "MemorySearch"

    def test_observe_event_with_tool_execution_id(self):
        """ObserveEvent should include tool_execution_id field."""
        event = AgentObserveEvent(
            tool_name="MemorySearch",
            result={"found": 5},
            duration_ms=100,
            call_id="call_123",
            tool_execution_id="exec_abc123def456",  # New field, matches act
        )
        event_dict = event.to_event_dict()

        assert event_dict["data"]["tool_execution_id"] == "exec_abc123def456"
        assert event_dict["data"]["tool_name"] == "MemorySearch"

    def test_act_observe_execution_id_matching(self):
        """Act and Observe events should share the same execution_id."""
        execution_id = "exec_xyz789"

        act_event = AgentActEvent(
            tool_name="WebSearch",
            tool_input={"q": "test"},
            tool_execution_id=execution_id,
        )

        observe_event = AgentObserveEvent(
            tool_name="WebSearch",
            result={"results": []},
            tool_execution_id=execution_id,
        )

        assert act_event.tool_execution_id == observe_event.tool_execution_id
        assert act_event.tool_execution_id == execution_id

    def test_execution_id_uniqueness(self):
        """Different tool executions should have unique execution_ids."""
        import uuid

        # Generate two execution IDs
        id1 = f"exec_{uuid.uuid4().hex[:12]}"
        id2 = f"exec_{uuid.uuid4().hex[:12]}"

        # They should be different
        assert id1 != id2

        # Both should start with "exec_"
        assert id1.startswith("exec_")
        assert id2.startswith("exec_")

        # Both should be valid length (exec_ + 12 hex chars = 17 chars)
        assert len(id1) == 17
        assert len(id2) == 17
