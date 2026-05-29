from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from src.infrastructure.adapters.primary.web.routers.agent.messages import (
    _DISPLAYABLE_EVENTS,
    _build_completion_map,
    _build_timeline,
)


@dataclass
class _StubEvent:
    event_type: str
    event_data: dict[str, Any]
    event_time_us: int = 1_000
    event_counter: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    message_id: str = "msg-1"


def test_displayable_events_include_a2ui_action_asked() -> None:
    assert "a2ui_action_asked" in _DISPLAYABLE_EVENTS


def test_displayable_events_include_legacy_subagent_timeline_events() -> None:
    assert "subagent_session_spawned" in _DISPLAYABLE_EVENTS
    assert "subagent_run_completed" in _DISPLAYABLE_EVENTS
    assert "subagent_announce_giveup" in _DISPLAYABLE_EVENTS
    assert "chain_started" in _DISPLAYABLE_EVENTS


def test_build_timeline_includes_a2ui_action_asked() -> None:
    timeline = _build_timeline(
        events=[
            _StubEvent(
                event_type="a2ui_action_asked",
                event_data={
                    "request_id": "hitl-req-1",
                    "block_id": "block-1",
                    "title": "Review",
                    "timeout_seconds": 300,
                },
            )
        ],
        tool_exec_map={},
        hitl_answered_map={},
        hitl_status_map={"hitl-req-1": {"status": "completed"}},
        artifact_ready_map={},
        artifact_error_map={},
        completion_map={},
    )

    assert timeline == [
        {
            "id": "a2ui_action_asked-1000-0",
            "type": "a2ui_action_asked",
            "eventTimeUs": 1_000,
            "eventCounter": 0,
            "timestamp": 1,
            "request_id": "hitl-req-1",
            "block_id": "block-1",
            "title": "Review",
            "timeout_seconds": 300,
            "status": "completed",
            "answered": True,
        }
    ]


def test_build_timeline_preserves_canvas_updated_payload_shape() -> None:
    timeline = _build_timeline(
        events=[
            _StubEvent(
                event_type="canvas_updated",
                event_data={
                    "action": "updated",
                    "block_id": "block-chart-1",
                    "block": {
                        "id": "block-chart-1",
                        "block_type": "chart",
                        "title": "Sales Chart",
                        "content": '{"labels":["Jan"],"datasets":[{"label":"Sales","data":[12]}]}',
                        "metadata": {"mime_type": "application/json"},
                        "version": 2,
                    },
                },
            )
        ],
        tool_exec_map={},
        hitl_answered_map={},
        hitl_status_map={},
        artifact_ready_map={},
        artifact_error_map={},
        completion_map={},
    )

    assert timeline == [
        {
            "id": "canvas_updated-1000-0",
            "type": "canvas_updated",
            "eventTimeUs": 1_000,
            "eventCounter": 0,
            "timestamp": 1,
            "action": "updated",
            "block_id": "block-chart-1",
            "block": {
                "id": "block-chart-1",
                "block_type": "chart",
                "title": "Sales Chart",
                "content": '{"labels":["Jan"],"datasets":[{"label":"Sales","data":[12]}]}',
                "metadata": {"mime_type": "application/json"},
                "version": 2,
            },
        }
    ]


def test_build_timeline_merges_complete_metadata_into_assistant_message() -> None:
    assistant_event = _StubEvent(
        event_type="assistant_message",
        event_data={
            "message_id": "assistant-1",
            "content": "Done",
            "role": "assistant",
        },
        message_id="msg-assistant-1",
    )
    timeline = _build_timeline(
        events=[assistant_event],
        tool_exec_map={},
        hitl_answered_map={},
        hitl_status_map={},
        artifact_ready_map={},
        artifact_error_map={},
        completion_map={
            "assistant_message-1000-0": {
                "trace_url": "https://trace.example/1",
                "execution_summary": {"step_count": 2, "artifact_count": 1},
                "artifacts": [{"url": "https://artifact.example/1"}],
            }
        },
    )

    assert timeline[0]["artifacts"] == [{"url": "https://artifact.example/1"}]
    assert timeline[0]["metadata"] == {
        "traceUrl": "https://trace.example/1",
        "executionSummary": {"step_count": 2, "artifact_count": 1},
    }


def test_build_completion_map_targets_only_last_assistant_message_for_turn() -> None:
    first_assistant = _StubEvent(
        event_type="assistant_message",
        event_data={"content": "First", "role": "assistant"},
        event_time_us=1_000,
        event_counter=0,
        message_id="turn-1",
    )
    second_assistant = _StubEvent(
        event_type="assistant_message",
        event_data={"content": "Final", "role": "assistant"},
        event_time_us=2_000,
        event_counter=0,
        message_id="turn-1",
    )
    completion_map = _build_completion_map(
        {
            "turn-1": [
                first_assistant,
                second_assistant,
                _StubEvent(
                    event_type="complete",
                    event_data={"trace_url": "https://trace.example/2"},
                    event_time_us=3_000,
                    event_counter=0,
                    message_id="turn-1",
                ),
            ]
        }
    )

    timeline = _build_timeline(
        events=[first_assistant, second_assistant],
        tool_exec_map={},
        hitl_answered_map={},
        hitl_status_map={},
        artifact_ready_map={},
        artifact_error_map={},
        completion_map=completion_map,
    )

    assert "metadata" not in timeline[0]
    assert timeline[1]["metadata"] == {"traceUrl": "https://trace.example/2"}


def test_build_timeline_replays_subagent_lifecycle_events() -> None:
    timeline = _build_timeline(
        events=[
            _StubEvent(
                event_type="subagent_started",
                event_data={
                    "subagent_id": "agent-1",
                    "subagent_name": "Verifier",
                    "task": "Check the result",
                },
                event_time_us=1_000,
            ),
            _StubEvent(
                event_type="subagent_completed",
                event_data={
                    "subagent_id": "agent-1",
                    "subagent_name": "Verifier",
                    "summary": "Looks good",
                    "tokens_used": 42,
                    "execution_time_ms": 1200,
                    "success": True,
                },
                event_time_us=2_000,
            ),
        ],
        tool_exec_map={},
        hitl_answered_map={},
        hitl_status_map={},
        artifact_ready_map={},
        artifact_error_map={},
        completion_map={},
    )

    assert timeline == [
        {
            "id": "subagent_started-1000-0",
            "type": "subagent_started",
            "eventTimeUs": 1_000,
            "eventCounter": 0,
            "timestamp": 1,
            "subagentId": "agent-1",
            "subagentName": "Verifier",
            "task": "Check the result",
        },
        {
            "id": "subagent_completed-2000-0",
            "type": "subagent_completed",
            "eventTimeUs": 2_000,
            "eventCounter": 0,
            "timestamp": 2,
            "subagentId": "agent-1",
            "subagentName": "Verifier",
            "summary": "Looks good",
            "tokensUsed": 42,
            "executionTimeMs": 1200,
            "success": True,
        },
    ]


def test_build_timeline_replays_sessionized_subagent_events() -> None:
    timeline = _build_timeline(
        events=[
            _StubEvent(
                event_type="subagent_session_spawned",
                event_data={
                    "conversation_id": "conv-child",
                    "run_id": "run-1",
                    "subagent_name": "Researcher",
                },
                event_time_us=1_000,
            ),
            _StubEvent(
                event_type="subagent_run_failed",
                event_data={
                    "run_id": "run-1",
                    "subagent_name": "Researcher",
                    "task": "Gather docs",
                    "status": "failed",
                    "error": "No browser tool",
                    "execution_time_ms": 99,
                    "tokens_used": 7,
                },
                event_time_us=2_000,
            ),
            _StubEvent(
                event_type="subagent_announce_giveup",
                event_data={
                    "conversation_id": "conv-child",
                    "run_id": "run-1",
                    "subagent_name": "Researcher",
                    "attempts": 3,
                    "error": "Parent unavailable",
                },
                event_time_us=3_000,
            ),
        ],
        tool_exec_map={},
        hitl_answered_map={},
        hitl_status_map={},
        artifact_ready_map={},
        artifact_error_map={},
        completion_map={},
    )

    assert timeline[0] == {
        "id": "subagent_session_spawned-1000-0",
        "type": "subagent_session_spawned",
        "eventTimeUs": 1_000,
        "eventCounter": 0,
        "timestamp": 1,
        "conversationId": "conv-child",
        "subagentId": "run-1",
        "subagentName": "Researcher",
    }
    assert timeline[1]["type"] == "subagent_run_failed"
    assert timeline[1]["subagentId"] == "run-1"
    assert timeline[1]["status"] == "failed"
    assert timeline[1]["error"] == "No browser tool"
    assert timeline[1]["executionTimeMs"] == 99
    assert timeline[1]["tokensUsed"] == 7
    assert timeline[2]["type"] == "subagent_announce_giveup"
    assert timeline[2]["attempts"] == 3
    assert timeline[2]["error"] == "Parent unavailable"


def test_build_timeline_replays_orchestration_events() -> None:
    timeline = _build_timeline(
        events=[
            _StubEvent(
                event_type="parallel_started",
                event_data={
                    "task_count": 2,
                    "subtasks": [{"subagent_name": "A", "task": "One"}],
                },
                event_time_us=1_000,
            ),
            _StubEvent(
                event_type="chain_step_started",
                event_data={
                    "step_index": 1,
                    "step_name": "Review",
                    "subagent_name": "Critic",
                },
                event_time_us=2_000,
            ),
            _StubEvent(
                event_type="background_launched",
                event_data={
                    "execution_id": "exec-1",
                    "subagent_name": "Worker",
                    "task": "Long task",
                },
                event_time_us=3_000,
            ),
        ],
        tool_exec_map={},
        hitl_answered_map={},
        hitl_status_map={},
        artifact_ready_map={},
        artifact_error_map={},
        completion_map={},
    )

    assert timeline[0]["taskCount"] == 2
    assert timeline[0]["subtasks"] == [{"subagent_name": "A", "task": "One"}]
    assert timeline[1]["type"] == "chain_step_started"
    assert timeline[1]["stepIndex"] == 1
    assert timeline[1]["stepName"] == "Review"
    assert timeline[1]["subagentName"] == "Critic"
    assert timeline[2]["type"] == "background_launched"
    assert timeline[2]["executionId"] == "exec-1"
    assert timeline[2]["subagentName"] == "Worker"


def test_build_timeline_does_not_attach_completion_to_earlier_visible_assistant() -> None:
    first_assistant = _StubEvent(
        event_type="assistant_message",
        event_data={"content": "First", "role": "assistant"},
        event_time_us=1_000,
        event_counter=0,
        message_id="turn-1",
    )
    second_assistant = _StubEvent(
        event_type="assistant_message",
        event_data={"content": "Final", "role": "assistant"},
        event_time_us=2_000,
        event_counter=0,
        message_id="turn-1",
    )
    completion_map = _build_completion_map(
        {
            "turn-1": [
                first_assistant,
                second_assistant,
                _StubEvent(
                    event_type="complete",
                    event_data={"trace_url": "https://trace.example/3"},
                    event_time_us=3_000,
                    event_counter=0,
                    message_id="turn-1",
                ),
            ]
        }
    )

    timeline = _build_timeline(
        events=[first_assistant],
        tool_exec_map={},
        hitl_answered_map={},
        hitl_status_map={},
        artifact_ready_map={},
        artifact_error_map={},
        completion_map=completion_map,
    )

    assert "metadata" not in timeline[0]
