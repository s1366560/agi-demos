"""
Unit tests for EventConverter.

Tests the unified event conversion logic extracted from ReActAgent.
"""

import time
from dataclasses import dataclass
from typing import ClassVar
from unittest.mock import MagicMock

import pytest

from src.domain.events.agent_events import (
    AgentActEvent,
    AgentArtifactCreatedEvent,
    AgentCompleteEvent,
    AgentDomainEvent,
    AgentErrorEvent,
    AgentEventType,
    AgentObserveEvent,
    AgentThoughtEvent,
)
from src.infrastructure.agent.events.converter import (
    EventConverter,
    get_event_converter,
    set_event_converter,
)

# ============================================================
# Test Fixtures
# ============================================================


@pytest.fixture
def converter():
    """Create a fresh EventConverter instance."""
    return EventConverter(debug_logging=False)


@pytest.fixture
def debug_converter():
    """Create a EventConverter with debug logging."""
    return EventConverter(debug_logging=True)


@dataclass
class MockSkill:
    """Mock skill for testing."""

    id: str = "test-skill-001"
    name: str = "TestSkill"
    tools: list[str] = None

    def __post_init__(self):
        if self.tools is None:
            self.tools = ["tool1", "tool2", "tool3"]


@pytest.fixture
def mock_skill():
    """Create a mock skill."""
    return MockSkill()


# ============================================================
# Test Basic Event Conversion
# ============================================================


@pytest.mark.unit
class TestEventConverterBasic:
    """Test basic event conversion functionality."""

    def test_convert_thought_event(self, converter):
        """Test converting AgentThoughtEvent."""
        event = AgentThoughtEvent(
            content="Analyzing the user request...",
            thought_level="work",
            timestamp=time.time(),
        )

        result = converter.convert(event)

        assert result is not None
        assert result["type"] == AgentEventType.THOUGHT.value
        assert result["data"]["thought"] == "Analyzing the user request..."
        assert result["data"]["thought_level"] == "work"

    def test_convert_act_event(self, converter):
        """Test converting AgentActEvent."""
        event = AgentActEvent(
            tool_name="memory_search",
            tool_input={"query": "test query"},
            call_id="call-123",
            status="executing",
            timestamp=time.time(),
        )

        result = converter.convert(event)

        assert result is not None
        assert result["type"] == AgentEventType.ACT.value
        assert result["data"]["tool_name"] == "memory_search"
        assert result["data"]["tool_input"] == {"query": "test query"}
        assert result["data"]["call_id"] == "call-123"
        assert result["data"]["status"] == "executing"

    def test_convert_act_event_with_none_input(self, converter):
        """Test converting AgentActEvent with None tool_input."""
        event = AgentActEvent(
            tool_name="simple_tool",
            tool_input=None,
            call_id=None,
            status="executing",
            timestamp=time.time(),
        )

        result = converter.convert(event)

        assert result is not None
        assert result["data"]["tool_input"] == {}
        assert result["data"]["call_id"] == ""

    def test_convert_observe_event(self, converter):
        """Test converting AgentObserveEvent."""
        event = AgentObserveEvent(
            tool_name="memory_search",
            result="Found 3 relevant memories",
            error=None,
            duration_ms=150,
            status="success",
            timestamp=time.time(),
        )

        result = converter.convert(event)

        assert result is not None
        assert result["type"] == AgentEventType.OBSERVE.value
        # Backward compat: observation field
        assert result["data"]["observation"] == "Found 3 relevant memories"

    def test_convert_observe_event_with_error(self, converter):
        """Test converting AgentObserveEvent with error."""
        event = AgentObserveEvent(
            tool_name="failing_tool",
            result=None,
            error="Connection timeout",
            duration_ms=5000,
            status="error",
            timestamp=time.time(),
        )

        result = converter.convert(event)

        assert result is not None
        # When result is None, observation falls back to error
        assert result["data"]["observation"] == "Connection timeout"
        assert result["data"]["error"] == "Connection timeout"

    def test_convert_error_event(self, converter):
        """Test converting AgentErrorEvent."""
        event = AgentErrorEvent(
            message="Rate limit exceeded",
            code="RATE_LIMIT",
            recoverable=True,
            timestamp=time.time(),
        )

        result = converter.convert(event)

        assert result is not None
        assert result["type"] == AgentEventType.ERROR.value
        assert result["data"]["code"] == "RATE_LIMIT"

    def test_convert_error_event_with_none_code(self, converter):
        """Test converting AgentErrorEvent with None code."""
        event = AgentErrorEvent(
            message="Unknown error",
            code=None,
            recoverable=False,
            timestamp=time.time(),
        )

        result = converter.convert(event)

        assert result is not None
        assert result["data"]["code"] == "UNKNOWN"

    def test_convert_complete_event_returns_none(self, converter):
        """Test that COMPLETE events return None (handled separately)."""
        event = AgentCompleteEvent(
            final_response="Task completed successfully",
            tokens_used=1000,
            cost=0.05,
            timestamp=time.time(),
        )

        result = converter.convert(event)

        # COMPLETE is handled separately in stream()
        assert result is None


# ============================================================
# Test Work Plan and Step Events
# ============================================================


# ============================================================
# Test Artifact Events
# ============================================================


@pytest.mark.unit
class TestEventConverterArtifact:
    """Test artifact event conversion."""

    def test_convert_artifact_created_event(self, converter):
        """Test converting AgentArtifactCreatedEvent."""
        event = AgentArtifactCreatedEvent(
            artifact_id="artifact-001",
            filename="chart.png",
            mime_type="image/png",
            category="image",
            size_bytes=15000,
            url="https://storage.example.com/artifacts/chart.png",
            preview_url="https://storage.example.com/artifacts/chart_preview.png",
            tool_execution_id="exec-001",
            source_tool="chart_generator",
            timestamp=time.time(),
        )

        result = converter.convert(event)

        assert result is not None
        assert result["type"] == AgentEventType.ARTIFACT_CREATED.value
        assert result["data"]["artifact_id"] == "artifact-001"
        assert result["data"]["filename"] == "chart.png"
        assert result["data"]["mime_type"] == "image/png"
        assert result["data"]["category"] == "image"
        assert result["data"]["size_bytes"] == 15000
        assert result["data"]["url"] == "https://storage.example.com/artifacts/chart.png"
        assert result["data"]["source_tool"] == "chart_generator"


# ============================================================
# Test Skill Event Conversion
# ============================================================


@pytest.mark.unit
class TestEventConverterSkill:
    """Test skill event conversion."""

    def test_convert_skill_thought_event(self, converter, mock_skill):
        """Test converting skill thought event."""
        event = AgentThoughtEvent(
            content="Executing skill step 1...",
            thought_level="skill",
            timestamp=time.time(),
        )

        result = converter.convert_skill_event(event, mock_skill, current_step=0)

        assert result is not None
        assert result["type"] == "thought"
        assert result["data"]["thought"] == "Executing skill step 1..."
        assert result["data"]["thought_level"] == "skill"
        assert result["data"]["skill_id"] == "test-skill-001"

    def test_convert_skill_act_event(self, converter, mock_skill):
        """Test converting skill act event."""
        event = AgentActEvent(
            tool_name="tool1",
            tool_input={"param": "value"},
            status="executing",
            timestamp=time.time(),
        )

        result = converter.convert_skill_event(event, mock_skill, current_step=0)

        assert result is not None
        assert result["type"] == "skill_tool_start"
        assert result["data"]["skill_id"] == "test-skill-001"
        assert result["data"]["skill_name"] == "TestSkill"
        assert result["data"]["tool_name"] == "tool1"
        assert result["data"]["step_index"] == 0
        assert result["data"]["total_steps"] == 3

    def test_convert_skill_observe_event(self, converter, mock_skill):
        """Test converting skill observe event."""
        event = AgentObserveEvent(
            tool_name="tool1",
            result="Tool executed successfully",
            error=None,
            duration_ms=100,
            status="success",
            timestamp=time.time(),
        )

        result = converter.convert_skill_event(event, mock_skill, current_step=0)

        assert result is not None
        assert result["type"] == "skill_tool_result"
        assert result["data"]["skill_id"] == "test-skill-001"
        assert result["data"]["result"] == "Tool executed successfully"
        assert result["data"]["duration_ms"] == 100

    def test_convert_skill_completion_returns_none(self, converter, mock_skill):
        """Test that skill completion events return None."""
        # Create a mock event with SKILL_EXECUTION_COMPLETE type
        event = MagicMock(spec=AgentDomainEvent)
        event.event_type = AgentEventType.SKILL_EXECUTION_COMPLETE
        event.timestamp = time.time()

        result = converter.convert_skill_event(event, mock_skill, current_step=2)

        assert result is None


# ============================================================
# Test Plan Event Conversion
# ============================================================


@pytest.mark.unit
class TestEventConverterPlan:
    """Test plan event conversion."""

    def test_convert_plan_execution_start(self, converter):
        """Test converting plan execution start event."""
        event = {
            "type": "PLAN_EXECUTION_START",
            "data": {"plan_id": "plan-001", "total_steps": 3},
        }

        result = converter.convert_plan_event(event)

        assert result["type"] == "plan_execution_start"
        assert result["data"]["plan_id"] == "plan-001"
        assert "timestamp" in result

    def test_convert_plan_step_complete(self, converter):
        """Test converting plan step complete event."""
        event = {
            "type": "PLAN_STEP_COMPLETE",
            "data": {"step_index": 1, "result": "Step completed"},
        }

        result = converter.convert_plan_event(event)

        assert result["type"] == "plan_step_complete"
        assert result["data"]["step_index"] == 1

    def test_convert_unknown_plan_event(self, converter):
        """Test converting unknown plan event type."""
        event = {
            "type": "CUSTOM_EVENT",
            "data": {"custom": "data"},
        }

        result = converter.convert_plan_event(event)

        # Unknown types are lowercased
        assert result["type"] == "custom_event"


# ============================================================
# Test Singleton Functions
# ============================================================


@pytest.mark.unit
class TestEventConverterSingleton:
    """Test singleton functions."""

    def test_get_event_converter_returns_instance(self):
        """Test that get_event_converter returns an instance."""
        converter = get_event_converter()
        assert isinstance(converter, EventConverter)

    def test_get_event_converter_returns_same_instance(self):
        """Test that get_event_converter returns the same instance."""
        converter1 = get_event_converter()
        converter2 = get_event_converter()
        assert converter1 is converter2

    def test_set_event_converter(self):
        """Test setting custom event converter."""
        custom_converter = EventConverter(debug_logging=True)
        set_event_converter(custom_converter)

        result = get_event_converter()
        assert result is custom_converter

        # Cleanup
        set_event_converter(EventConverter())


# ============================================================
# Test Edge Cases
# ============================================================


@pytest.mark.unit
class TestEventConverterEdgeCases:
    """Test edge cases and error handling."""

    def test_convert_with_debug_logging(self, debug_converter, caplog):
        """Test that debug logging works."""
        import logging

        caplog.set_level(logging.INFO)

        event = AgentThoughtEvent(
            content="Test thought",
            thought_level="task",
            timestamp=time.time(),
        )

        debug_converter.convert(event)

        # Debug logging should produce output
        assert any("EventConverter" in record.message for record in caplog.records)

    def test_convert_observe_with_both_result_and_error(self, converter):
        """Test observe event with both result and error."""
        event = AgentObserveEvent(
            tool_name="mixed_tool",
            result="Partial result",
            error="Warning: some issues",
            duration_ms=200,
            status="partial",
            timestamp=time.time(),
        )

        result = converter.convert(event)

        # Result takes precedence
        assert result["data"]["observation"] == "Partial result"
        # Error is also included
        assert result["data"]["error"] == "Warning: some issues"

    def test_skill_event_with_none_tool_input(self, converter, mock_skill):
        """Test skill act event with None tool_input."""
        event = AgentActEvent(
            tool_name="simple_tool",
            tool_input=None,
            status="executing",
            timestamp=time.time(),
        )

        result = converter.convert_skill_event(event, mock_skill, current_step=1)

        assert result is not None
        assert result["data"]["tool_input"] == {}

    def test_skill_observe_with_none_duration(self, converter, mock_skill):
        """Test skill observe event with None duration_ms."""
        event = AgentObserveEvent(
            tool_name="fast_tool",
            result="Done",
            error=None,
            duration_ms=None,
            status="success",
            timestamp=time.time(),
        )

        result = converter.convert_skill_event(event, mock_skill, current_step=0)

        assert result is not None
        assert result["data"]["duration_ms"] == 0


# ============================================================
# Test Protocol Compliance
# ============================================================


@pytest.mark.unit
class TestSkillLikeProtocol:
    """Test SkillLike protocol compliance."""

    def test_mock_skill_implements_protocol(self, mock_skill):
        """Test that MockSkill implements SkillLike protocol."""
        # Protocol attributes
        assert hasattr(mock_skill, "id")
        assert hasattr(mock_skill, "name")
        assert hasattr(mock_skill, "tools")

        # Check types
        assert isinstance(mock_skill.id, str)
        assert isinstance(mock_skill.name, str)
        assert isinstance(mock_skill.tools, list)

    def test_custom_skill_object_works(self, converter):
        """Test that any object with required attributes works."""

        class CustomSkill:
            id = "custom-001"
            name = "CustomSkill"
            tools: ClassVar[list] = ["a", "b"]

        skill = CustomSkill()
        event = AgentActEvent(
            tool_name="a",
            tool_input={},
            status="executing",
            timestamp=time.time(),
        )

        result = converter.convert_skill_event(event, skill, current_step=0)

        assert result is not None
        assert result["data"]["skill_id"] == "custom-001"
        assert result["data"]["total_steps"] == 2
