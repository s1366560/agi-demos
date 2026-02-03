"""Tests for Event Mapper and Event Bus.

Tests the unified event system for SSE streaming and event handling.
"""

import json
from datetime import datetime

from src.infrastructure.agent.events.event_mapper import (
    AgentDomainEvent,
    EventBus,
    EventMapper,
    EventType,
    SSEEvent,
    get_event_bus,
    set_event_bus,
)


class TestEventType:
    """Tests for EventType enum."""

    def test_message_events(self) -> None:
        """Should have message event types."""
        assert EventType.USER_MESSAGE.value == "user_message"
        assert EventType.ASSISTANT_MESSAGE.value == "assistant_message"
        assert EventType.SYSTEM_MESSAGE.value == "system_message"

    def test_tool_events(self) -> None:
        """Should have tool event types."""
        assert EventType.TOOL_START.value == "tool_start"
        assert EventType.TOOL_END.value == "tool_end"
        assert EventType.TOOL_ERROR.value == "tool_error"

    def test_state_events(self) -> None:
        """Should have state event types."""
        assert EventType.STATE_CHANGE.value == "state_change"
        assert EventType.PROGRESS.value == "progress"

    def test_error_events(self) -> None:
        """Should have error event types."""
        assert EventType.ERROR.value == "error"
        assert EventType.VALIDATION_ERROR.value == "validation_error"


class TestSSEEvent:
    """Tests for SSEEvent dataclass."""

    def test_to_sse_format(self) -> None:
        """Should convert to SSE format string."""
        event = SSEEvent(
            id="1",
            event=EventType.USER_MESSAGE,
            data={"message": "Hello"},
        )

        result = event.to_sse_format()

        assert "id: 1" in result
        assert "event: user_message" in result
        assert "data: " in result
        assert result.endswith("\n\n")

    def test_to_sse_with_retry(self) -> None:
        """Should include retry if specified."""
        event = SSEEvent(
            id="2",
            event=EventType.TOOL_START,
            data={"tool": "bash"},
            retry=3000,
        )

        result = event.to_sse_format()

        assert "retry: 3000" in result

    def test_to_sse_without_id(self) -> None:
        """Should not include id if not provided."""
        event = SSEEvent(
            id="",
            event=EventType.PROGRESS,
            data={"progress": 50},
        )

        # Create with empty id to simulate None
        event.id = ""
        result = event.to_sse_format()

        # Empty id means no id line
        assert "id: " not in result

    def test_data_json_serialization(self) -> None:
        """Should properly serialize data as JSON."""
        event = SSEEvent(
            id="3",
            event=EventType.ERROR,
            data={"error": "Test error", "code": 500},
        )

        result = event.to_sse_format()

        # Extract and parse data line
        data_line = [l for l in result.split("\n") if l.startswith("data: ")][0]
        data_json = data_line.replace("data: ", "")
        parsed = json.loads(data_json)

        assert parsed["error"] == "Test error"
        assert parsed["code"] == 500


class TestAgentDomainEvent:
    """Tests for AgentDomainEvent."""

    def test_create_minimal_event(self) -> None:
        """Should create event with minimal fields."""
        event = AgentDomainEvent(
            event_type=EventType.USER_MESSAGE,
        )

        assert event.event_type == EventType.USER_MESSAGE
        assert event.data == {}
        assert event.conversation_id is None
        assert isinstance(event.timestamp, datetime)

    def test_create_full_event(self) -> None:
        """Should create event with all fields."""
        event = AgentDomainEvent(
            event_type=EventType.TOOL_START,
            conversation_id="conv-123",
            sandbox_id="sb-456",
            data={"tool": "bash", "args": ["ls"]},
        )

        assert event.conversation_id == "conv-123"
        assert event.sandbox_id == "sb-456"
        assert event.data["tool"] == "bash"

    def test_to_sse(self) -> None:
        """Should convert to SSE event."""
        domain_event = AgentDomainEvent(
            event_type=EventType.ASSISTANT_MESSAGE,
            conversation_id="conv-123",
            data={"message": "Hello!"},
        )

        sse_event = domain_event.to_sse("evt-1")

        assert sse_event.id == "evt-1"
        assert sse_event.event == EventType.ASSISTANT_MESSAGE
        assert sse_event.data["message"] == "Hello!"
        assert "conversation_id" in sse_event.data
        assert sse_event.data["conversation_id"] == "conv-123"


class TestEventMapper:
    """Tests for EventMapper."""

    def test_default_mapper(self) -> None:
        """Should create mapper with defaults."""
        mapper = EventMapper()

        assert mapper._include_timestamp is True
        assert mapper._include_conversation_id is True
        assert mapper._include_sandbox_id is True

    def test_custom_mapper(self) -> None:
        """Should create mapper with custom settings."""
        mapper = EventMapper(
            include_timestamp=False,
            include_conversation_id=False,
            include_sandbox_id=False,
        )

        assert mapper._include_timestamp is False
        assert mapper._include_conversation_id is False
        assert mapper._include_sandbox_id is False

    def test_to_sse_with_all_fields(self) -> None:
        """Should include all fields when configured."""
        mapper = EventMapper()
        event = AgentDomainEvent(
            event_type=EventType.PROGRESS,
            conversation_id="conv-123",
            sandbox_id="sb-456",
            data={"progress": 50},
        )

        sse = mapper.to_sse(event, "evt-1")

        assert "conversation_id" in sse.data
        assert "sandbox_id" in sse.data
        assert "timestamp" in sse.data

    def test_to_sse_without_excluded_fields(self) -> None:
        """Should exclude fields when configured."""
        mapper = EventMapper(
            include_timestamp=False,
            include_conversation_id=False,
            include_sandbox_id=False,
        )
        event = AgentDomainEvent(
            event_type=EventType.ERROR,
            conversation_id="conv-123",
            sandbox_id="sb-456",
            data={"error": "Test"},
        )

        sse = mapper.to_sse(event, "evt-1")

        assert "conversation_id" not in sse.data
        assert "sandbox_id" not in sse.data
        assert "timestamp" not in sse.data

    def test_to_sse_filters_none_values(self) -> None:
        """Should remove None values from data."""
        mapper = EventMapper()
        event = AgentDomainEvent(
            event_type=EventType.TOOL_END,
            data={"tool": "bash", "output": None, "exit_code": 0},
        )

        sse = mapper.to_sse(event, "evt-1")

        # None values should be removed
        assert "output" not in sse.data
        assert sse.data["exit_code"] == 0

    def test_register_transformer(self) -> None:
        """Should apply custom transformer."""
        mapper = EventMapper()

        def transform_progress(event: AgentDomainEvent) -> dict:
            progress = event.data.get("progress", 0)
            return {"progress_pct": f"{progress}%", "status": "running"}

        mapper.register_transformer(EventType.PROGRESS, transform_progress)

        event = AgentDomainEvent(
            event_type=EventType.PROGRESS,
            data={"progress": 75},
        )

        sse = mapper.to_sse(event, "evt-1")

        assert sse.data["progress_pct"] == "75%"
        assert "progress" not in sse.data  # Original key replaced

    def test_filter_blocks_event(self) -> None:
        """Should filter out events that don't match filter."""
        mapper = EventMapper()

        # Only allow progress events
        def progress_only(event: AgentDomainEvent) -> bool:
            return event.event_type == EventType.PROGRESS

        mapper.register_filter(progress_only)

        tool_event = AgentDomainEvent(event_type=EventType.TOOL_START)
        progress_event = AgentDomainEvent(event_type=EventType.PROGRESS)

        assert mapper.to_sse(tool_event, "evt-1") is None
        assert mapper.to_sse(progress_event, "evt-2") is not None

    def test_to_sse_batch(self) -> None:
        """Should convert multiple events to SSE."""
        mapper = EventMapper()
        events = [
            AgentDomainEvent(event_type=EventType.PROGRESS, data={"value": 1}),
            AgentDomainEvent(event_type=EventType.PROGRESS, data={"value": 2}),
            AgentDomainEvent(event_type=EventType.PROGRESS, data={"value": 3}),
        ]

        sse_events = mapper.to_sse_batch(events)

        assert len(sse_events) == 3
        assert all(e.id.startswith("evt_") for e in sse_events)

    def test_to_sse_batch_with_filters(self) -> None:
        """Should filter events in batch conversion."""
        mapper = EventMapper()

        # Filter out events with even values
        def odd_only(event: AgentDomainEvent) -> bool:
            return event.data.get("value", 0) % 2 == 1

        mapper.register_filter(odd_only)

        events = [
            AgentDomainEvent(event_type=EventType.PROGRESS, data={"value": 1}),
            AgentDomainEvent(event_type=EventType.PROGRESS, data={"value": 2}),
            AgentDomainEvent(event_type=EventType.PROGRESS, data={"value": 3}),
        ]

        sse_events = mapper.to_sse_batch(events)

        # Only 1 and 3 should pass
        assert len(sse_events) == 2

    def test_create_sse_stream(self) -> None:
        """Should create complete SSE stream string."""
        mapper = EventMapper()
        events = [
            AgentDomainEvent(event_type=EventType.STREAM_START),
            AgentDomainEvent(event_type=EventType.PROGRESS, data={"msg": "Processing"}),
            AgentDomainEvent(event_type=EventType.STREAM_END),
        ]

        stream = mapper.create_sse_stream(events)

        # Verify SSE format
        lines = stream.strip().split("\n")
        assert any("event: stream_start" in l for l in lines)
        assert any("event: progress" in l for l in lines)
        assert any("event: stream_end" in l for l in lines)
        # Each event should end with blank line
        assert stream.count("\n\n") >= 3


class TestEventBus:
    """Tests for EventBus."""

    def test_subscribe_global(self) -> None:
        """Should subscribe to all events."""
        bus = EventBus()
        received = []

        def callback(event):
            received.append(event)

        unsubscribe = bus.subscribe(callback=callback)

        event1 = AgentDomainEvent(event_type=EventType.PROGRESS)
        event2 = AgentDomainEvent(event_type=EventType.ERROR)

        bus.publish(event1)
        bus.publish(event2)

        assert len(received) == 2

        unsubscribe()
        bus.publish(event1)

        assert len(received) == 2  # No increase after unsubscribe

    def test_subscribe_type_specific(self) -> None:
        """Should subscribe to specific event type."""
        bus = EventBus()
        received = []

        def callback(event):
            received.append(event)

        bus.subscribe(event_type=EventType.PROGRESS, callback=callback)

        bus.publish(AgentDomainEvent(event_type=EventType.PROGRESS))
        bus.publish(AgentDomainEvent(event_type=EventType.ERROR))

        assert len(received) == 1
        assert received[0].event_type == EventType.PROGRESS

    def test_unsubscribe_removes_subscriber(self) -> None:
        """Unsubscribe should stop receiving events."""
        bus = EventBus()
        received = []

        def callback(event):
            received.append(event)

        unsubscribe = bus.subscribe(event_type=EventType.PROGRESS, callback=callback)

        bus.publish(AgentDomainEvent(event_type=EventType.PROGRESS))
        unsubscribe()  # Unsubscribe after first

        bus.publish(AgentDomainEvent(event_type=EventType.PROGRESS))

        assert len(received) == 1

    def test_get_history_all(self) -> None:
        """Should get all event history."""
        bus = EventBus()

        bus.publish(AgentDomainEvent(event_type=EventType.PROGRESS, data={"v": 1}))
        bus.publish(AgentDomainEvent(event_type=EventType.ERROR, data={"e": 1}))

        history = bus.get_history()

        assert len(history) == 2

    def test_get_history_filtered(self) -> None:
        """Should filter history by event type."""
        bus = EventBus()

        bus.publish(AgentDomainEvent(event_type=EventType.PROGRESS, data={"v": 1}))
        bus.publish(AgentDomainEvent(event_type=EventType.ERROR, data={"e": 1}))
        bus.publish(AgentDomainEvent(event_type=EventType.PROGRESS, data={"v": 2}))

        history = bus.get_history(event_type=EventType.PROGRESS)

        assert len(history) == 2
        assert all(e.event_type == EventType.PROGRESS for e in history)

    def test_get_history_limit(self) -> None:
        """Should limit history size."""
        bus = EventBus()

        for i in range(150):
            bus.publish(AgentDomainEvent(
                event_type=EventType.PROGRESS,
                data={"v": i},
            ))

        history = bus.get_history(limit=10)

        assert len(history) == 10
        # Should return most recent (last 10), which are 140-149
        assert history[-1].data.get("v") == 149

    def test_clear_history(self) -> None:
        """Should clear event history."""
        bus = EventBus()

        bus.publish(AgentDomainEvent(event_type=EventType.PROGRESS))
        bus.publish(AgentDomainEvent(event_type=EventType.ERROR))

        assert len(bus.get_history()) == 2

        bus.clear_history()

        assert len(bus.get_history()) == 0

    def test_get_mapper(self) -> None:
        """Should get the event mapper."""
        mapper = EventMapper()
        bus = EventBus(mapper=mapper)

        assert bus.get_mapper() is mapper

    def test_set_mapper(self) -> None:
        """Should allow changing the mapper."""
        bus = EventBus()
        new_mapper = EventMapper(include_timestamp=False)

        bus.set_mapper(new_mapper)

        assert bus.get_mapper()._include_timestamp is False

    def test_callback_exception_doesnt_fail_publish(self) -> None:
        """Should not fail publish when callback raises."""
        bus = EventBus()

        def bad_callback(event):
            raise ValueError("Bad callback")

        bus.subscribe(callback=bad_callback)

        # Should not raise
        bus.publish(AgentDomainEvent(event_type=EventType.PROGRESS))

    def test_max_history_enforced(self) -> None:
        """Should enforce max history limit."""
        bus = EventBus()

        # Publish more than default max_history (1000)
        for i in range(1100):
            bus.publish(AgentDomainEvent(
                event_type=EventType.PROGRESS,
                data={"v": i},
            ))

        history = bus.get_history()

        # Should be capped at 1000
        assert len(history) <= 1000


class TestGlobalEventBus:
    """Tests for global event bus singleton."""

    def test_get_event_bus_returns_singleton(self) -> None:
        """Should return same instance across calls."""
        bus1 = get_event_bus()
        bus2 = get_event_bus()

        assert bus1 is bus2

    def test_set_event_bus_changes_global(self) -> None:
        """Should allow changing global event bus."""
        original = get_event_bus()
        custom = EventBus()

        set_event_bus(custom)

        assert get_event_bus() is custom
        assert get_event_bus() is not original


class TestEventIntegration:
    """Integration tests for event system."""

    def test_end_to_end_sse_stream(self) -> None:
        """Should create complete SSE stream from events."""
        bus = EventBus()

        # Collect SSE events
        sse_events = []

        def sse_collector(event: AgentDomainEvent) -> None:
            mapper = bus.get_mapper()
            sse = mapper.to_sse(event, f"evt_{len(sse_events)}")
            if sse:
                sse_events.append(sse)

        # Subscribe to all events
        bus.subscribe(callback=sse_collector)

        # Publish events
        bus.publish(AgentDomainEvent(
            event_type=EventType.STREAM_START,
            conversation_id="conv-123",
        ))
        bus.publish(AgentDomainEvent(
            event_type=EventType.PROGRESS,
            data={"progress": 50},
        ))
        bus.publish(AgentDomainEvent(
            event_type=EventType.STREAM_END,
        ))

        # Create stream
        mapper = bus.get_mapper()
        stream = mapper.create_sse_stream(bus.get_history())

        # Verify stream format
        assert "event: stream_start" in stream
        assert "event: progress" in stream
        assert "event: stream_end" in stream

    def test_filtered_stream(self) -> None:
        """Should create filtered SSE stream."""
        bus = EventBus()
        mapper = EventMapper()

        # Filter out system messages
        mapper.register_filter(lambda e: e.event_type != EventType.SYSTEM_MESSAGE)

        events = [
            AgentDomainEvent(event_type=EventType.USER_MESSAGE),
            AgentDomainEvent(event_type=EventType.SYSTEM_MESSAGE),
            AgentDomainEvent(event_type=EventType.ASSISTANT_MESSAGE),
        ]

        stream = mapper.create_sse_stream(events)

        assert "user_message" in stream
        assert "system_message" not in stream
        assert "assistant_message" in stream
