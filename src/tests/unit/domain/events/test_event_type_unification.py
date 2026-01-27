"""Tests for unified event type system (Phase 1).

This test verifies that:
1. AgentEventType is imported from a single source
2. Event type values are consistent across domain and persistence layers
3. All event types can be serialized/deserialized correctly
"""

import pytest

from src.domain.events.agent_events import AgentEventType


class TestEventTypeUnification:
    """Test that event types are unified across the codebase."""

    def test_persistence_imports_from_domain(self):
        """Persistence layer should import AgentEventType from domain events."""
        # Import from persistence layer - should be same as domain
        from src.domain.model.agent.agent_execution_event import AgentEventType as PersistenceEventType

        # They should be the same enum (same identity)
        assert AgentEventType is PersistenceEventType, \
            "PersistenceEventType should be imported from domain.events.agent_events"

    def test_all_common_event_types_exist(self):
        """Common event types should be defined."""
        common_types = [
            "message",
            "thought",
            "act",
            "observe",
            "work_plan",
            "step_start",
            "step_end",
            "complete",
            "error",
            "text_start",
            "text_delta",
            "text_end",
        ]

        for type_name in common_types:
            # Check if event type exists as value
            type_values = [et.value for et in AgentEventType]
            assert type_name in type_values, \
                f"AgentEventType missing value '{type_name}'"

    def test_all_domain_event_types_have_string_values(self):
        """All domain event types should have string values for serialization."""
        for event_type in AgentEventType:
            assert isinstance(event_type.value, str), \
                f"{event_type} value should be string, got {type(event_type.value)}"

    def test_event_type_values_are_serializable(self):
        """Event type values should be JSON serializable."""
        import json

        for event_type in AgentEventType:
            try:
                json.dumps(event_type.value)
            except (TypeError, ValueError) as e:
                pytest.fail(f"Event type {event_type} is not JSON serializable: {e}")

    def test_event_type_value_uniqueness(self):
        """All event type values should be unique."""
        values = [et.value for et in AgentEventType]
        assert len(values) == len(set(values)), \
            "Event type values should be unique"

    def test_frontend_event_types_filter_internal(self):
        """get_frontend_event_types should filter internal events."""
        from src.domain.events.agent_events import get_frontend_event_types

        frontend_types = get_frontend_event_types()

        # COMPACT_NEEDED should be filtered out
        assert AgentEventType.COMPACT_NEEDED.value not in frontend_types

        # Common events should be present
        assert AgentEventType.START.value in frontend_types
        assert AgentEventType.COMPLETE.value in frontend_types
        assert AgentEventType.ERROR.value in frontend_types


class TestAgentExecutionEventImport:
    """Test AgentExecutionEvent uses unified event types."""

    def test_from_domain_event_preserves_type(self):
        """from_domain_event should preserve domain event type."""
        from datetime import datetime
        from src.domain.events.agent_events import (
            AgentThoughtEvent,
            AgentActEvent,
        )
        from src.domain.model.agent.agent_execution_event import AgentExecutionEvent

        # Create domain events
        thought_event = AgentThoughtEvent(content="Test thought", thought_level="task")
        act_event = AgentActEvent(tool_name="test_tool", tool_input={}, call_id="test_id")

        # Convert to persistence events
        thought_persist = AgentExecutionEvent.from_domain_event(
            thought_event,
            conversation_id="conv_1",
            message_id="msg_1",
            sequence_number=1,
        )
        act_persist = AgentExecutionEvent.from_domain_event(
            act_event,
            conversation_id="conv_1",
            message_id="msg_1",
            sequence_number=2,
        )

        # Verify types match - use AgentEventType directly since it's imported
        from src.domain.events.agent_events import AgentEventType
        assert thought_persist.event_type == AgentEventType.THOUGHT.value
        assert act_persist.event_type == AgentEventType.ACT.value

    def test_to_sse_format_consistency(self):
        """to_sse_format should produce consistent output."""
        from datetime import datetime
        from src.domain.events.agent_events import (
            AgentThoughtEvent,
            AgentEventType,
        )
        from src.domain.model.agent.agent_execution_event import AgentExecutionEvent

        domain_event = AgentThoughtEvent(content="Test", thought_level="task")
        persist_event = AgentExecutionEvent.from_domain_event(
            domain_event,
            conversation_id="conv_1",
            message_id="msg_1",
        )

        sse_format = persist_event.to_sse_format()

        assert "type" in sse_format
        assert "data" in sse_format
        assert "timestamp" in sse_format
        assert sse_format["type"] == AgentEventType.THOUGHT.value
