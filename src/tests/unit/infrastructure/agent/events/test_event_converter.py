"""
Unit tests for EventConverter.

Tests the unified event conversion logic extracted from ReActAgent.
"""

import time

import pytest

from src.domain.events.agent_events import (
    AgentActEvent,
    AgentArtifactCreatedEvent,
    AgentCompleteEvent,
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
