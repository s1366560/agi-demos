"""Tests for core events."""

import pytest

from memstack_agent.core.events import (
    ActEvent,
    AgentEvent,
    CompleteEvent,
    ErrorEvent,
    ObserveEvent,
    StartEvent,
    TextDeltaEvent,
    TextEndEvent,
    TextStartEvent,
    ThoughtEvent,
)
from memstack_agent.core.types import EventType


class TestAgentEvent:
    """Tests for AgentEvent base class."""

    def test_create_event(self) -> None:
        """Test creating a basic event."""
        event = AgentEvent(event_type=EventType.START)
        assert event.event_type == EventType.START
        assert isinstance(event.timestamp, float)
        assert event.metadata == {}

    def test_event_to_dict(self) -> None:
        """Test event serialization to dict."""
        event = AgentEvent(
            event_type=EventType.START,
            metadata={"key": "value"},
        )
        result = event.to_dict()
        assert result["type"] == "start"
        assert result["data"] == {"metadata": {"key": "value"}}
        assert "timestamp" in result
        assert result["category"] == "agent"

    def test_event_is_immutable(self) -> None:
        """Test event is frozen (immutable)."""
        from dataclasses import FrozenInstanceError

        event = AgentEvent(event_type=EventType.START)
        with pytest.raises(FrozenInstanceError):
            event.event_type = EventType.ERROR


class TestStartEvent:
    """Tests for StartEvent."""

    def test_create_start_event(self) -> None:
        """Test creating start event."""
        event = StartEvent(
            conversation_id="conv-123",
            user_id="user-456",
            model="gpt-4",
        )
        assert event.event_type == EventType.START
        assert event.conversation_id == "conv-123"
        assert event.user_id == "user-456"
        assert event.model == "gpt-4"

    def test_start_event_to_dict(self) -> None:
        """Test start event serialization."""
        event = StartEvent(
            conversation_id="conv-123",
            user_id="user-456",
            model="gpt-4",
        )
        result = event.to_dict()
        assert result["type"] == "start"
        assert result["data"]["conversation_id"] == "conv-123"
        assert result["data"]["user_id"] == "user-456"
        assert result["data"]["model"] == "gpt-4"


class TestCompleteEvent:
    """Tests for CompleteEvent."""

    def test_create_complete_event(self) -> None:
        """Test creating complete event."""
        event = CompleteEvent(
            conversation_id="conv-123",
            result="Task completed",
        )
        assert event.event_type == EventType.COMPLETE
        assert event.conversation_id == "conv-123"
        assert event.result == "Task completed"
        assert event.trace_url is None

    def test_complete_event_with_cost(self) -> None:
        """Test complete event with cost tracking."""
        event = CompleteEvent(
            conversation_id="conv-123",
            result="Done",
            tokens={"prompt": 100, "completion": 50},
            cost=0.003,
        )
        assert event.tokens == {"prompt": 100, "completion": 50}
        assert event.cost == 0.003


class TestErrorEvent:
    """Tests for ErrorEvent."""

    def test_create_error_event(self) -> None:
        """Test creating error event."""
        event = ErrorEvent(
            conversation_id="conv-123",
            message="Something went wrong",
        )
        assert event.event_type == EventType.ERROR
        assert event.conversation_id == "conv-123"
        assert event.message == "Something went wrong"
        assert event.code is None

    def test_error_event_with_code(self) -> None:
        """Test error event with error code."""
        event = ErrorEvent(
            conversation_id="conv-123",
            message="Invalid input",
            code="INVALID_INPUT",
            details={"field": "query"},
        )
        assert event.code == "INVALID_INPUT"
        assert event.details == {"field": "query"}


class TestThoughtEvent:
    """Tests for ThoughtEvent."""

    def test_create_thought_event(self) -> None:
        """Test creating thought event."""
        event = ThoughtEvent(
            conversation_id="conv-123",
            content="I need to search for information",
        )
        assert event.event_type == EventType.THOUGHT
        assert event.conversation_id == "conv-123"
        assert event.content == "I need to search for information"
        assert event.step_index is None
        assert event.thought_level == "task"

    def test_thought_event_with_step(self) -> None:
        """Test thought event with step index."""
        event = ThoughtEvent(
            conversation_id="conv-123",
            content="Processing step 1",
            step_index=1,
            thought_level="subtask",
        )
        assert event.step_index == 1
        assert event.thought_level == "subtask"


class TestActEvent:
    """Tests for ActEvent."""

    def test_create_act_event(self) -> None:
        """Test creating act event."""
        event = ActEvent(
            conversation_id="conv-123",
            tool_name="search",
            tool_input={"query": "python"},
        )
        assert event.event_type == EventType.ACT
        assert event.conversation_id == "conv-123"
        assert event.tool_name == "search"
        assert event.tool_input == {"query": "python"}
        assert event.status == "running"

    def test_act_event_with_ids(self) -> None:
        """Test act event with call and execution IDs."""
        event = ActEvent(
            conversation_id="conv-123",
            tool_name="search",
            tool_input={"query": "python"},
            call_id="call-abc",
            tool_execution_id="exec-xyz",
        )
        assert event.call_id == "call-abc"
        assert event.tool_execution_id == "exec-xyz"


class TestObserveEvent:
    """Tests for ObserveEvent."""

    def test_create_observe_event(self) -> None:
        """Test creating observe event."""
        event = ObserveEvent(
            conversation_id="conv-123",
            tool_name="search",
            result="Found 10 results",
        )
        assert event.event_type == EventType.OBSERVE
        assert event.conversation_id == "conv-123"
        assert event.tool_name == "search"
        assert event.result == "Found 10 results"
        assert event.error is None

    def test_observe_event_with_error(self) -> None:
        """Test observe event with error."""
        event = ObserveEvent(
            conversation_id="conv-123",
            tool_name="search",
            error="Network timeout",
            duration_ms=5000,
        )
        assert event.error == "Network timeout"
        assert event.duration_ms == 5000
        assert event.status == "completed"


class TestTextEvents:
    """Tests for text streaming events."""

    def test_text_start_event(self) -> None:
        """Test text start event."""
        event = TextStartEvent(conversation_id="conv-123")
        assert event.event_type == EventType.TEXT_START
        assert event.conversation_id == "conv-123"

    def test_text_delta_event(self) -> None:
        """Test text delta event."""
        event = TextDeltaEvent(
            conversation_id="conv-123",
            delta="Hello",
        )
        assert event.event_type == EventType.TEXT_DELTA
        assert event.delta == "Hello"

    def test_text_end_event(self) -> None:
        """Test text end event."""
        event = TextEndEvent(
            conversation_id="conv-123",
            full_text="Hello, world!",
        )
        assert event.event_type == EventType.TEXT_END
        assert event.full_text == "Hello, world!"
