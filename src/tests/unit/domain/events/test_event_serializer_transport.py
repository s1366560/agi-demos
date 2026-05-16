"""Transport serialization coverage for domain agent events."""

from __future__ import annotations

import pytest

from src.domain.events.agent_events import AgentStatusEvent, AgentTextDeltaEvent, AgentThoughtEvent
from src.domain.events.event_serializer import EventSerializer, serialize_event
from src.domain.events.types import AgentEventType

pytestmark = pytest.mark.unit


def test_event_serializer_to_dict_adds_transport_metadata() -> None:
    event = AgentThoughtEvent(content="checking", thought_level="task", timestamp=123.5)

    payload = EventSerializer.to_dict(
        event,
        message_id="msg-1",
        event_time_us=123500000,
        event_counter=2,
    )

    assert payload == {
        "type": "thought",
        "data": {
            "content": "checking",
            "thought_level": "task",
            "step_index": None,
            "message_id": "msg-1",
        },
        "timestamp": 123.5,
        "event_time_us": 123500000,
        "event_counter": 2,
    }


def test_event_serializer_batch_and_wrapper() -> None:
    first = AgentTextDeltaEvent(delta="a", timestamp=1.0)
    second = AgentTextDeltaEvent(delta="b", timestamp=2.0)

    batch = EventSerializer.to_dict_batch(
        [
            (first, "m1", 100, 0),
            (second, None, 101, 1),
        ]
    )

    assert batch[0]["data"]["message_id"] == "m1"
    assert batch[1]["data"] == {"delta": "b"}
    assert serialize_event(first)["type"] == "text_delta"


def test_event_type_helpers_exclude_internal_events_from_public_list() -> None:
    public_types = EventSerializer.get_public_event_types()

    assert EventSerializer.get_event_type_value(AgentEventType.THOUGHT) == "thought"
    assert "thought" in EventSerializer.get_all_event_types()
    assert AgentStatusEvent(status="running", timestamp=1.0).event_type.value == "status"
    assert "status" not in public_types
    assert "retry" not in public_types
    assert "compact_needed" not in public_types
    assert "text_delta" in public_types
