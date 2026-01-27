"""Unit tests for TITLE_GENERATED event type.

This module tests the title_generated event following TDD principles:
1. Tests are written first (RED)
2. Implementation follows (GREEN)
3. Code is refactored for quality (REFACTOR)
"""

import pytest

from src.domain.events.agent_events import (
    AgentEventType,
    AgentTitleGeneratedEvent,
    get_frontend_event_types,
)


class TestTitleGeneratedEvent:
    """Test suite for AgentTitleGeneratedEvent domain event."""

    def test_title_generated_event_type_exists(self):
        """Test that TITLE_GENERATED event type is defined."""
        # This test will fail until we add TITLE_GENERATED to AgentEventType
        assert hasattr(AgentEventType, "TITLE_GENERATED")

    def test_title_generated_event_value(self):
        """Test that TITLE_GENERATED has the correct string value."""
        assert AgentEventType.TITLE_GENERATED.value == "title_generated"

    def test_title_generated_event_class_exists(self):
        """Test that AgentTitleGeneratedEvent class is defined."""
        assert AgentTitleGeneratedEvent is not None

    def test_title_generated_event_creation(self):
        """Test creating a TITLE_GENERATED event with valid data."""
        event = AgentTitleGeneratedEvent(
            conversation_id="conv-123",
            title="Help with Python Coding",
        )

        assert event.event_type == AgentEventType.TITLE_GENERATED
        assert event.conversation_id == "conv-123"
        assert event.title == "Help with Python Coding"
        assert event.timestamp > 0

    def test_title_generated_event_to_event_dict(self):
        """Test serialization of TITLE_GENERATED event to SSE format."""
        event = AgentTitleGeneratedEvent(
            conversation_id="conv-123",
            title="Help with Python",
        )

        event_dict = event.to_event_dict()

        assert event_dict["type"] == "title_generated"
        assert event_dict["data"]["conversation_id"] == "conv-123"
        assert event_dict["data"]["title"] == "Help with Python"
        assert "timestamp" in event_dict

    def test_title_generated_event_is_frozen(self):
        """Test that TITLE_GENERATED events are immutable."""
        event = AgentTitleGeneratedEvent(
            conversation_id="conv-123",
            title="Test Title",
        )

        # Attempting to modify should raise an error
        with pytest.raises(Exception):  # ValidationError or similar
            event.conversation_id = "new-conv"

    def test_title_generated_event_in_frontend_types(self):
        """Test that TITLE_GENERATED is included in frontend event types."""
        frontend_types = get_frontend_event_types()
        assert "title_generated" in frontend_types

    def test_title_generated_event_with_optional_fields(self):
        """Test TITLE_GENERATED event with all optional fields."""
        event = AgentTitleGeneratedEvent(
            conversation_id="conv-123",
            title="AI Discussion",
            message_id="msg-456",
            generated_by="llm",
        )

        assert event.message_id == "msg-456"
        assert event.generated_by == "llm"

    def test_title_generated_event_defaults(self):
        """Test TITLE_GENERATED event default values."""
        event = AgentTitleGeneratedEvent(
            conversation_id="conv-123",
            title="Default Title",
        )

        # Optional fields should have defaults
        assert event.message_id is None
        assert event.generated_by == "llm"  # Expected default
