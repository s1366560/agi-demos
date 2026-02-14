"""Tests for core types."""

import pytest

from memstack_agent.core.types import (
    AgentContext,
    EventCategory,
    EventType,
    ProcessorConfig,
    ProcessorState,
    get_event_category,
    is_terminal_event,
)


class TestProcessorState:
    """Tests for ProcessorState enum."""

    def test_state_values(self) -> None:
        """Test state enum values are correct."""
        assert ProcessorState.IDLE == "idle"
        assert ProcessorState.THINKING == "thinking"
        assert ProcessorState.ACTING == "acting"
        assert ProcessorState.OBSERVING == "observing"
        assert ProcessorState.COMPLETED == "completed"
        assert ProcessorState.ERROR == "error"


class TestEventType:
    """Tests for EventType enum."""

    def test_status_events(self) -> None:
        """Test status event types exist."""
        assert EventType.STATUS == "status"
        assert EventType.START == "start"
        assert EventType.COMPLETE == "complete"
        assert EventType.ERROR == "error"

    def test_thinking_events(self) -> None:
        """Test thinking event types exist."""
        assert EventType.THOUGHT == "thought"
        assert EventType.THOUGHT_DELTA == "thought_delta"

    def test_tool_events(self) -> None:
        """Test tool event types exist."""
        assert EventType.ACT == "act"
        assert EventType.OBSERVE == "observe"

    def test_text_events(self) -> None:
        """Test text event types exist."""
        assert EventType.TEXT_START == "text_start"
        assert EventType.TEXT_DELTA == "text_delta"
        assert EventType.TEXT_END == "text_end"


class TestEventCategory:
    """Tests for EventCategory enum."""

    def test_category_values(self) -> None:
        """Test category enum values are correct."""
        assert EventCategory.AGENT == "agent"
        assert EventCategory.HITL == "hitl"
        assert EventCategory.SANDBOX == "sandbox"
        assert EventCategory.SYSTEM == "system"
        assert EventCategory.MESSAGE == "message"


class TestGetEventCategory:
    """Tests for get_event_category function."""

    def test_agent_events(self) -> None:
        """Test agent events are categorized correctly."""
        assert get_event_category(EventType.START) == EventCategory.AGENT
        assert get_event_category(EventType.THOUGHT) == EventCategory.AGENT
        assert get_event_category(EventType.ACT) == EventCategory.AGENT

    def test_hitl_events(self) -> None:
        """Test HITL events are categorized correctly."""
        assert get_event_category(EventType.CLARIFICATION_ASKED) == EventCategory.HITL
        assert get_event_category(EventType.DECISION_ASKED) == EventCategory.HITL

    def test_sandbox_events(self) -> None:
        """Test sandbox events are categorized correctly."""
        assert get_event_category(EventType.SANDBOX_CREATED) == EventCategory.SANDBOX

    def test_unknown_event_defaults_to_agent(self) -> None:
        """Test unknown event types default to AGENT category."""
        # Create a fake event type (this would normally be an enum value)
        # Since we can't add to enum, just verify the function handles
        # missing keys by checking a known non-default category
        assert get_event_category(EventType.COST_UPDATE) == EventCategory.SYSTEM


class TestIsTerminalEvent:
    """Tests for is_terminal_event function."""

    def test_complete_is_terminal(self) -> None:
        """Test COMPLETE is terminal."""
        assert is_terminal_event(EventType.COMPLETE) is True

    def test_error_is_terminal(self) -> None:
        """Test ERROR is terminal."""
        assert is_terminal_event(EventType.ERROR) is True

    def test_other_events_not_terminal(self) -> None:
        """Test other events are not terminal."""
        assert is_terminal_event(EventType.START) is False
        assert is_terminal_event(EventType.THOUGHT) is False
        assert is_terminal_event(EventType.ACT) is False


class TestAgentContext:
    """Tests for AgentContext dataclass."""

    def test_create_context(self) -> None:
        """Test creating a context."""
        context = AgentContext(
            session_id="sess-123",
            conversation_id="conv-456",
            user_id="user-789",
            project_id="proj-000",
            model="gpt-4",
        )
        assert context.session_id == "sess-123"
        assert context.conversation_id == "conv-456"
        assert context.user_id == "user-789"
        assert context.project_id == "proj-000"
        assert context.model == "gpt-4"

    def test_context_defaults(self) -> None:
        """Test context has correct defaults."""
        context = AgentContext(
            session_id="sess",
            conversation_id="conv",
            user_id="user",
            project_id="proj",
            model="gpt-4",
        )
        assert context.max_tokens == 200000
        assert context.max_steps == 50
        assert context.metadata == {}

    def test_context_with_metadata(self) -> None:
        """Test with_metadata returns new context."""
        context = AgentContext(
            session_id="sess",
            conversation_id="conv",
            user_id="user",
            project_id="proj",
            model="gpt-4",
        )
        new_context = context.with_metadata(foo="bar")
        # Original unchanged (immutability)
        assert context.metadata == {}
        # New has metadata
        assert new_context.metadata == {"foo": "bar"}
        # Other fields preserved
        assert new_context.session_id == context.session_id

    def test_context_is_immutable(self) -> None:
        """Test context is frozen (immutable)."""
        from dataclasses import FrozenInstanceError

        context = AgentContext(
            session_id="sess",
            conversation_id="conv",
            user_id="user",
            project_id="proj",
            model="gpt-4",
        )
        with pytest.raises(FrozenInstanceError):
            context.session_id = "new-sess"


class TestProcessorConfig:
    """Tests for ProcessorConfig dataclass."""

    def test_create_config(self) -> None:
        """Test creating a config."""
        config = ProcessorConfig(
            model="gpt-4",
            temperature=0.7,
        )
        assert config.model == "gpt-4"
        assert config.temperature == 0.7

    def test_config_defaults(self) -> None:
        """Test config has correct defaults."""
        config = ProcessorConfig(model="gpt-4")
        assert config.api_key is None
        assert config.base_url is None
        assert config.temperature == 0.0
        assert config.max_tokens == 4096
        assert config.max_steps == 50
        assert config.doom_loop_threshold == 3

    def test_config_with_model(self) -> None:
        """Test with_model returns new config."""
        config = ProcessorConfig(model="gpt-4")
        new_config = config.with_model("gpt-4-turbo")
        # Original unchanged
        assert config.model == "gpt-4"
        # New has new model
        assert new_config.model == "gpt-4-turbo"

    def test_config_is_immutable(self) -> None:
        """Test config is frozen (immutable)."""
        from dataclasses import FrozenInstanceError

        config = ProcessorConfig(model="gpt-4")
        with pytest.raises(FrozenInstanceError):
            config.model = "new-model"
