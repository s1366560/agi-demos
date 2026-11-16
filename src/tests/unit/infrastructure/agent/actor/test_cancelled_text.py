"""Cancellation snapshots retain only unfinished protocol text blocks."""

from copy import deepcopy

import pytest

from src.domain.events.agent_events import (
    AgentTextDeltaEvent,
    AgentTextStartEvent,
)
from src.infrastructure.agent.actor.cancelled_text import cancelled_text_end_events
from src.infrastructure.agent.events.converter import EventConverter

pytestmark = pytest.mark.unit


def event(kind, **payload):
    return {"type": kind, "data": payload}


def texts(events):
    return [snapshot["data"]["full_text"] for snapshot in cancelled_text_end_events(events)]


def test_actual_converter_events_retain_unfinished_text_without_message_id():
    converter = EventConverter()
    events = [
        converter.convert(domain_event, agent_id="agent-a")
        for domain_event in (
            AgentTextStartEvent(),
            AgentTextDeltaEvent(delta="  first"),
            AgentTextDeltaEvent(delta="\nsecond"),
        )
    ]
    snapshots = cancelled_text_end_events(events)
    assert snapshots == [
        {
            "type": "text_end",
            "data": {
                "agent_id": "agent-a",
                "full_text": "  first\nsecond",
                "partial": True,
                "status": "cancelled",
            },
        }
    ]
    assert cancelled_text_end_events([*events, *snapshots]) == []


def test_completed_blocks_and_non_text_events_never_become_partial_answers():
    assert (
        texts(
            [
                event("text_start"),
                event("text_delta", delta="complete"),
                event("text_end", full_text="complete"),
                event("thought_delta", delta="private reasoning"),
                event("act_delta", delta="tool arguments"),
                event("text_start"),
            ]
        )
        == []
    )


def test_multiple_deferred_blocks_close_fifo_without_repeating_completed_text():
    events = [
        event("text_start"),
        event("text_delta", delta="first"),
        event("text_start"),
        event("text_delta", delta="second"),
    ]
    assert texts(events) == ["first", "second"]
    assert texts([*events, event("text_end", full_text="first")]) == ["second"]
    assert (
        texts(
            [*events, event("text_end", full_text="first"), event("text_end", full_text="second")]
        )
        == []
    )


def test_interleaved_streams_and_runs_have_independent_structural_boundaries():
    events = [
        event("text_start", run_id="run-a", stream_id="stream-a"),
        event("text_delta", run_id="run-a", stream_id="stream-a", delta="A"),
        event("text_start", run_id="run-b", stream_id="stream-a"),
        event("text_delta", run_id="run-b", stream_id="stream-a", delta="B"),
        event("text_start", run_id="run-a", stream_id="stream-b"),
        event("text_delta", run_id="run-a", stream_id="stream-b", delta="C"),
        event("text_end", run_id="run-b", stream_id="stream-a", full_text="B"),
        event("text_delta", run_id="run-a", stream_id="stream-a", delta="D"),
    ]
    assert texts(events) == ["AD", "C"]


def test_delta_only_stream_preserves_generation_without_mutating_original_events():
    generation = {"generation": 7, "nested": {"version": "same"}}
    events = [
        event("text_delta", delta="partial", message_id="message-a", plugin_generation=generation)
    ]
    original = deepcopy(events)
    snapshots = cancelled_text_end_events(events)
    assert snapshots[0]["data"]["message_id"] == "message-a"
    assert snapshots[0]["data"]["plugin_generation"] == generation
    snapshots[0]["data"]["plugin_generation"]["nested"]["version"] = "changed"
    assert events == original


def test_exact_cursor_duplicates_are_not_appended_twice():
    first = {**event("text_delta", delta="first"), "event_time_us": 100, "event_counter": 0}
    second = {**event("text_delta", delta="second"), "event_time_us": 100, "event_counter": 1}
    assert texts([first, first, second]) == ["firstsecond"]
    assert texts([event("text_delta", delta="  \n")]) == []


def test_generation_first_attached_to_delta_is_preserved():
    snapshot = cancelled_text_end_events(
        [
            event("text_start"),
            event("text_delta", delta="body", plugin_generation={"generation": 9}),
        ]
    )[0]
    assert snapshot["data"]["plugin_generation"] == {"generation": 9}
