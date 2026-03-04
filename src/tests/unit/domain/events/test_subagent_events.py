"""Tests for Phase 1 SubAgent event additions.

Covers the 5 new event types: SubAgentQueued, SubAgentKilled, SubAgentSteered,
SubAgentDepthLimited, SubAgentSessionUpdate.
"""

import json
import time

import pytest

from src.domain.events.agent_events import (
    SubAgentDepthLimitedEvent,
    SubAgentKilledEvent,
    SubAgentQueuedEvent,
    SubAgentSessionUpdateEvent,
    SubAgentSteeredEvent,
)
from src.domain.events.types import (
    EVENT_CATEGORIES,
    AgentEventType,
    EventCategory,
    get_frontend_event_types,
)
from src.infrastructure.agent.events.converter import EventConverter

# ---------------------------------------------------------------------------
# Test Class 1: AgentEventType enum values and category mappings
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSubAgentEventTypes:
    """Verify the 5 new SubAgent enum values, categories, and frontend exposure."""

    def test_subagent_queued_enum_value(self) -> None:
        assert AgentEventType.SUBAGENT_QUEUED.value == "subagent_queued"

    def test_subagent_killed_enum_value(self) -> None:
        assert AgentEventType.SUBAGENT_KILLED.value == "subagent_killed"

    def test_subagent_steered_enum_value(self) -> None:
        assert AgentEventType.SUBAGENT_STEERED.value == "subagent_steered"

    def test_subagent_depth_limited_enum_value(self) -> None:
        assert AgentEventType.SUBAGENT_DEPTH_LIMITED.value == "subagent_depth_limited"

    def test_subagent_session_update_enum_value(self) -> None:
        assert AgentEventType.SUBAGENT_SESSION_UPDATE.value == "subagent_session_update"

    def test_all_new_types_categorized_as_agent(self) -> None:
        new_types = [
            AgentEventType.SUBAGENT_QUEUED,
            AgentEventType.SUBAGENT_KILLED,
            AgentEventType.SUBAGENT_STEERED,
            AgentEventType.SUBAGENT_DEPTH_LIMITED,
            AgentEventType.SUBAGENT_SESSION_UPDATE,
        ]
        for event_type in new_types:
            assert event_type in EVENT_CATEGORIES, f"{event_type} missing from EVENT_CATEGORIES"
            assert EVENT_CATEGORIES[event_type] == EventCategory.AGENT, (
                f"{event_type} should map to EventCategory.AGENT"
            )

    def test_all_new_types_exposed_to_frontend(self) -> None:
        frontend_types = set(get_frontend_event_types())
        expected = {
            "subagent_queued",
            "subagent_killed",
            "subagent_steered",
            "subagent_depth_limited",
            "subagent_session_update",
        }
        missing = expected - frontend_types
        assert not missing, f"Missing from frontend event types: {missing}"


# ---------------------------------------------------------------------------
# Test Class 2: Domain event serialization via to_event_dict()
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSubAgentDomainEvents:
    """Verify to_event_dict() output for each of the 5 new event classes."""

    # -- SubAgentQueuedEvent ------------------------------------------------

    def test_queued_event_type(self) -> None:
        event = SubAgentQueuedEvent(
            subagent_id="sa-1",
            subagent_name="researcher",
            queue_position=3,
            reason="concurrency_limit",
        )
        event_dict = event.to_event_dict()
        assert event_dict["type"] == "subagent_queued"

    def test_queued_event_data_fields(self) -> None:
        event = SubAgentQueuedEvent(
            subagent_id="sa-1",
            subagent_name="researcher",
            queue_position=3,
            reason="concurrency_limit",
        )
        event_dict = event.to_event_dict()
        assert event_dict["data"]["subagent_id"] == "sa-1"
        assert event_dict["data"]["queue_position"] == 3
        assert event_dict["data"]["reason"] == "concurrency_limit"

    def test_queued_event_defaults(self) -> None:
        event = SubAgentQueuedEvent(
            subagent_id="sa-1",
            subagent_name="researcher",
        )
        event_dict = event.to_event_dict()
        assert event_dict["data"]["queue_position"] == 0
        assert event_dict["data"]["reason"] == ""

    # -- SubAgentKilledEvent ------------------------------------------------

    def test_killed_event_type(self) -> None:
        event = SubAgentKilledEvent(
            subagent_id="sa-2",
            subagent_name="coder",
            kill_reason="timeout",
        )
        event_dict = event.to_event_dict()
        assert event_dict["type"] == "subagent_killed"

    def test_killed_event_data_fields(self) -> None:
        event = SubAgentKilledEvent(
            subagent_id="sa-2",
            subagent_name="coder",
            kill_reason="timeout",
        )
        event_dict = event.to_event_dict()
        assert event_dict["data"]["kill_reason"] == "timeout"

    # -- SubAgentSteeredEvent -----------------------------------------------

    def test_steered_event_type(self) -> None:
        event = SubAgentSteeredEvent(
            subagent_id="sa-3",
            subagent_name="planner",
            instruction="Focus on security",
        )
        event_dict = event.to_event_dict()
        assert event_dict["type"] == "subagent_steered"

    def test_steered_event_data_fields(self) -> None:
        event = SubAgentSteeredEvent(
            subagent_id="sa-3",
            subagent_name="planner",
            instruction="Focus on security",
        )
        event_dict = event.to_event_dict()
        assert event_dict["data"]["instruction"] == "Focus on security"

    # -- SubAgentDepthLimitedEvent ------------------------------------------

    def test_depth_limited_event_type(self) -> None:
        event = SubAgentDepthLimitedEvent(
            subagent_name="nested-agent",
            current_depth=3,
            max_depth=2,
            parent_subagent_name="parent-agent",
        )
        event_dict = event.to_event_dict()
        assert event_dict["type"] == "subagent_depth_limited"

    def test_depth_limited_event_data_fields(self) -> None:
        event = SubAgentDepthLimitedEvent(
            subagent_name="nested-agent",
            current_depth=3,
            max_depth=2,
            parent_subagent_name="parent-agent",
        )
        event_dict = event.to_event_dict()
        assert event_dict["data"]["current_depth"] == 3
        assert event_dict["data"]["max_depth"] == 2
        assert event_dict["data"]["parent_subagent_name"] == "parent-agent"

    def test_depth_limited_event_defaults(self) -> None:
        event = SubAgentDepthLimitedEvent(
            subagent_name="nested-agent",
            current_depth=3,
            max_depth=2,
        )
        event_dict = event.to_event_dict()
        assert event_dict["data"]["parent_subagent_name"] == ""

    # -- SubAgentSessionUpdateEvent -----------------------------------------

    def test_session_update_event_type(self) -> None:
        event = SubAgentSessionUpdateEvent(
            subagent_id="sa-5",
            subagent_name="analyzer",
            progress=75,
            status_message="Processing data",
            tokens_used=1500,
            tool_calls_count=3,
        )
        event_dict = event.to_event_dict()
        assert event_dict["type"] == "subagent_session_update"

    def test_session_update_event_data_fields(self) -> None:
        event = SubAgentSessionUpdateEvent(
            subagent_id="sa-5",
            subagent_name="analyzer",
            progress=75,
            status_message="Processing data",
            tokens_used=1500,
            tool_calls_count=3,
        )
        event_dict = event.to_event_dict()
        assert event_dict["data"]["progress"] == 75
        assert event_dict["data"]["tokens_used"] == 1500

    def test_session_update_event_defaults(self) -> None:
        event = SubAgentSessionUpdateEvent(
            subagent_id="sa-5",
            subagent_name="analyzer",
        )
        event_dict = event.to_event_dict()
        assert event_dict["data"]["progress"] == 0
        assert event_dict["data"]["status_message"] == ""
        assert event_dict["data"]["tokens_used"] == 0
        assert event_dict["data"]["tool_calls_count"] == 0

    # -- Cross-cutting checks -----------------------------------------------

    def test_all_events_have_required_top_level_keys(self) -> None:
        events = [
            SubAgentQueuedEvent(
                subagent_id="sa-1", subagent_name="a", queue_position=1, reason="r"
            ),
            SubAgentKilledEvent(subagent_id="sa-2", subagent_name="b", kill_reason="timeout"),
            SubAgentSteeredEvent(subagent_id="sa-3", subagent_name="c", instruction="i"),
            SubAgentDepthLimitedEvent(
                subagent_name="d", current_depth=1, max_depth=2, parent_subagent_name="p"
            ),
            SubAgentSessionUpdateEvent(
                subagent_id="sa-5", subagent_name="e", progress=50, tokens_used=100
            ),
        ]
        for event in events:
            event_dict = event.to_event_dict()
            assert "type" in event_dict, f"{type(event).__name__} missing 'type'"
            assert "data" in event_dict, f"{type(event).__name__} missing 'data'"
            assert "timestamp" in event_dict, f"{type(event).__name__} missing 'timestamp'"

    def test_event_type_and_timestamp_not_in_data(self) -> None:
        events = [
            SubAgentQueuedEvent(subagent_id="sa-1", subagent_name="a"),
            SubAgentKilledEvent(subagent_id="sa-2", subagent_name="b", kill_reason="timeout"),
            SubAgentSteeredEvent(subagent_id="sa-3", subagent_name="c", instruction="i"),
            SubAgentDepthLimitedEvent(subagent_name="d", current_depth=1, max_depth=2),
            SubAgentSessionUpdateEvent(subagent_id="sa-5", subagent_name="e"),
        ]
        for event in events:
            data = event.to_event_dict()["data"]
            assert "event_type" not in data, f"{type(event).__name__} leaks event_type into data"
            assert "timestamp" not in data, f"{type(event).__name__} leaks timestamp into data"

    def test_all_events_json_serializable(self) -> None:
        events = [
            SubAgentQueuedEvent(
                subagent_id="sa-1", subagent_name="a", queue_position=1, reason="r"
            ),
            SubAgentKilledEvent(subagent_id="sa-2", subagent_name="b", kill_reason="timeout"),
            SubAgentSteeredEvent(subagent_id="sa-3", subagent_name="c", instruction="i"),
            SubAgentDepthLimitedEvent(subagent_name="d", current_depth=1, max_depth=2),
            SubAgentSessionUpdateEvent(subagent_id="sa-5", subagent_name="e"),
        ]
        for event in events:
            event_dict = event.to_event_dict()
            try:
                json.dumps(event_dict)
            except (TypeError, ValueError) as e:
                pytest.fail(f"{type(event).__name__} is not JSON serializable: {e}")


# ---------------------------------------------------------------------------
# Test Class 3: EventConverter pass-through for the 5 new events
# ---------------------------------------------------------------------------


@pytest.fixture
def converter() -> EventConverter:
    return EventConverter(debug_logging=False)


@pytest.mark.unit
class TestEventConverter:
    """Verify EventConverter.convert() handles the 5 new SubAgent events."""

    def test_convert_queued_event_not_none(self, converter: EventConverter) -> None:
        event = SubAgentQueuedEvent(
            subagent_id="sa-1",
            subagent_name="researcher",
            queue_position=3,
            reason="concurrency_limit",
            timestamp=time.time(),
        )
        result = converter.convert(event)
        assert result is not None

    def test_convert_queued_event_matches_to_event_dict(self, converter: EventConverter) -> None:
        event = SubAgentQueuedEvent(
            subagent_id="sa-1",
            subagent_name="researcher",
            queue_position=3,
            reason="concurrency_limit",
            timestamp=time.time(),
        )
        result = converter.convert(event)
        expected = event.to_event_dict()
        assert result is not None
        assert result["type"] == expected["type"]
        assert result["data"] == expected["data"]

    def test_convert_killed_event_not_none(self, converter: EventConverter) -> None:
        event = SubAgentKilledEvent(
            subagent_id="sa-2",
            subagent_name="coder",
            kill_reason="timeout",
            timestamp=time.time(),
        )
        result = converter.convert(event)
        assert result is not None

    def test_convert_killed_event_matches_to_event_dict(self, converter: EventConverter) -> None:
        event = SubAgentKilledEvent(
            subagent_id="sa-2",
            subagent_name="coder",
            kill_reason="timeout",
            timestamp=time.time(),
        )
        result = converter.convert(event)
        expected = event.to_event_dict()
        assert result is not None
        assert result["type"] == expected["type"]
        assert result["data"] == expected["data"]

    def test_convert_steered_event_not_none(self, converter: EventConverter) -> None:
        event = SubAgentSteeredEvent(
            subagent_id="sa-3",
            subagent_name="planner",
            instruction="Focus on security",
            timestamp=time.time(),
        )
        result = converter.convert(event)
        assert result is not None

    def test_convert_steered_event_matches_to_event_dict(self, converter: EventConverter) -> None:
        event = SubAgentSteeredEvent(
            subagent_id="sa-3",
            subagent_name="planner",
            instruction="Focus on security",
            timestamp=time.time(),
        )
        result = converter.convert(event)
        expected = event.to_event_dict()
        assert result is not None
        assert result["type"] == expected["type"]
        assert result["data"] == expected["data"]

    def test_convert_depth_limited_event_not_none(self, converter: EventConverter) -> None:
        event = SubAgentDepthLimitedEvent(
            subagent_name="nested-agent",
            current_depth=3,
            max_depth=2,
            parent_subagent_name="parent-agent",
            timestamp=time.time(),
        )
        result = converter.convert(event)
        assert result is not None

    def test_convert_depth_limited_event_matches_to_event_dict(
        self, converter: EventConverter
    ) -> None:
        event = SubAgentDepthLimitedEvent(
            subagent_name="nested-agent",
            current_depth=3,
            max_depth=2,
            parent_subagent_name="parent-agent",
            timestamp=time.time(),
        )
        result = converter.convert(event)
        expected = event.to_event_dict()
        assert result is not None
        assert result["type"] == expected["type"]
        assert result["data"] == expected["data"]

    def test_convert_session_update_event_not_none(self, converter: EventConverter) -> None:
        event = SubAgentSessionUpdateEvent(
            subagent_id="sa-5",
            subagent_name="analyzer",
            progress=75,
            status_message="Processing data",
            tokens_used=1500,
            tool_calls_count=3,
            timestamp=time.time(),
        )
        result = converter.convert(event)
        assert result is not None

    def test_convert_session_update_event_matches_to_event_dict(
        self, converter: EventConverter
    ) -> None:
        event = SubAgentSessionUpdateEvent(
            subagent_id="sa-5",
            subagent_name="analyzer",
            progress=75,
            status_message="Processing data",
            tokens_used=1500,
            tool_calls_count=3,
            timestamp=time.time(),
        )
        result = converter.convert(event)
        expected = event.to_event_dict()
        assert result is not None
        assert result["type"] == expected["type"]
        assert result["data"] == expected["data"]

    def test_convert_all_new_events_preserve_type_field(self, converter: EventConverter) -> None:
        events = [
            SubAgentQueuedEvent(subagent_id="sa-1", subagent_name="a", timestamp=time.time()),
            SubAgentKilledEvent(
                subagent_id="sa-2", subagent_name="b", kill_reason="timeout", timestamp=time.time()
            ),
            SubAgentSteeredEvent(
                subagent_id="sa-3", subagent_name="c", instruction="i", timestamp=time.time()
            ),
            SubAgentDepthLimitedEvent(
                subagent_name="d", current_depth=1, max_depth=2, timestamp=time.time()
            ),
            SubAgentSessionUpdateEvent(
                subagent_id="sa-5", subagent_name="e", timestamp=time.time()
            ),
        ]
        expected_types = [
            "subagent_queued",
            "subagent_killed",
            "subagent_steered",
            "subagent_depth_limited",
            "subagent_session_update",
        ]
        for event, expected_type in zip(events, expected_types, strict=True):
            result = converter.convert(event)
            assert result is not None
            assert result["type"] == expected_type, (
                f"{type(event).__name__}: expected type={expected_type}, got {result['type']}"
            )
