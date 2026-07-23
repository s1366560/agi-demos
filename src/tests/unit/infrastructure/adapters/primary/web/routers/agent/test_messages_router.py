from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from src.infrastructure.adapters.primary.web.routers.agent.messages import (
    _DISPLAYABLE_EVENTS,
    _build_completion_map,
    _build_timeline,
    _build_tool_exec_map,
)


@dataclass
class _StubEvent:
    event_type: str
    event_data: dict[str, Any]
    event_time_us: int = 1_000
    event_counter: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    message_id: str = "msg-1"


@dataclass
class _StubToolExecution:
    id: str
    message_id: str
    call_id: str
    tool_name: str
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_ms: int | None = None


def test_displayable_events_include_a2ui_action_asked() -> None:
    assert "a2ui_action_asked" in _DISPLAYABLE_EVENTS


def test_displayable_events_include_legacy_subagent_timeline_events() -> None:
    assert "subagent_session_spawned" in _DISPLAYABLE_EVENTS
    assert "subagent_run_completed" in _DISPLAYABLE_EVENTS
    assert "subagent_announce_giveup" in _DISPLAYABLE_EVENTS
    assert "chain_started" in _DISPLAYABLE_EVENTS


def test_displayable_events_include_persisted_act_delta() -> None:
    assert "act_delta" in _DISPLAYABLE_EVENTS


def test_build_timeline_replays_latest_act_delta_as_act() -> None:
    timeline = _build_timeline(
        events=[
            _StubEvent(
                event_type="act_delta",
                event_data={
                    "tool_name": "workspace_submit_supervisor_decision",
                    "call_id": "call-1",
                    "arguments_fragment": '{"action":',
                    "accumulated_arguments": '{"action":',
                    "status": "preparing",
                },
                event_time_us=1_000,
            ),
            _StubEvent(
                event_type="act_delta",
                event_data={
                    "tool_name": "workspace_submit_supervisor_decision",
                    "call_id": "call-1",
                    "arguments_fragment": ' "accept_node"}',
                    "accumulated_arguments": '{"action": "accept_node"}',
                    "status": "preparing",
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
            "id": "act_delta-2000-0",
            "type": "act",
            "eventTimeUs": 2_000,
            "eventCounter": 0,
            "timestamp": 2,
            "toolName": "workspace_submit_supervisor_decision",
            "toolInput": {"action": "accept_node"},
            "execution_id": "call-1",
            "metadata": {
                "sourceEventType": "act_delta",
                "status": "preparing",
                "synthesizeObserve": True,
            },
        },
        {
            "id": "observe-act_delta-2000-0",
            "type": "observe",
            "eventTimeUs": 2_000,
            "eventCounter": 0,
            "timestamp": 2,
            "toolName": "workspace_submit_supervisor_decision",
            "toolOutput": '{"action": "accept_node"}',
            "isError": False,
            "execution_id": "call-1",
            "metadata": {
                "sourceEventType": "synthetic_observe",
                "status": "preparing",
                "synthesizeObserve": True,
            },
        },
    ]


def test_build_timeline_passes_through_tool_display_and_file_metadata() -> None:
    display = {"title": "Read app.py", "summary": "Inspect the app entry point"}
    file_metadata = {
        "operation": "read",
        "paths": [{"path": "/workspace/src/app.py", "relativePath": "src/app.py"}],
    }

    timeline = _build_timeline(
        events=[
            _StubEvent(
                event_type="act",
                event_data={
                    "tool_name": "read",
                    "tool_input": {"file_path": "src/app.py"},
                    "display": display,
                    "fileMetadata": file_metadata,
                    "tool_execution_id": "exec-1",
                },
                event_time_us=1_000,
            ),
            _StubEvent(
                event_type="observe",
                event_data={
                    "tool_name": "read",
                    "observation": "content",
                    "display": display,
                    "file_metadata": file_metadata,
                    "tool_execution_id": "exec-1",
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

    assert timeline[0]["display"] == display
    assert timeline[0]["fileMetadata"] == file_metadata
    assert timeline[1]["display"] == display
    assert timeline[1]["fileMetadata"] == file_metadata


def test_build_timeline_drops_invalid_tool_display_shapes() -> None:
    timeline = _build_timeline(
        events=[
            _StubEvent(
                event_type="act",
                event_data={
                    "tool_name": "read",
                    "tool_input": {"file_path": "src/app.py"},
                    "display": "not an object",
                    "fileMetadata": ["not", "an", "object"],
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

    assert "display" not in timeline[0]
    assert "fileMetadata" not in timeline[0]


def test_build_timeline_repairs_truncated_act_delta_json_prefix() -> None:
    timeline = _build_timeline(
        events=[
            _StubEvent(
                event_type="act_delta",
                event_data={
                    "tool_name": "workspace_submit_supervisor_decision",
                    "call_id": "call-1",
                    "arguments_fragment": '"feedback_items": []',
                    "accumulated_arguments": (
                        '{"action": "accept_node", "feedback_items": [], '
                        '"retry_not_before_seconds": null'
                    ),
                    "status": "preparing",
                },
                event_time_us=1_000,
            ),
        ],
        tool_exec_map={},
        hitl_answered_map={},
        hitl_status_map={},
        artifact_ready_map={},
        artifact_error_map={},
        completion_map={},
    )

    assert timeline[0]["toolInput"] == {
        "action": "accept_node",
        "feedback_items": [],
        "retry_not_before_seconds": None,
    }
    assert timeline[1]["type"] == "observe"
    assert timeline[1]["isError"] is False


def test_build_timeline_trims_dangling_top_level_act_delta_field() -> None:
    timeline = _build_timeline(
        events=[
            _StubEvent(
                event_type="act_delta",
                event_data={
                    "tool_name": "workspace_submit_verification_judgment",
                    "call_id": "call-1",
                    "arguments_fragment": '"satisfied_guard_failures": ',
                    "accumulated_arguments": (
                        '{"verdict": "accepted", "failed_criteria": [], '
                        '"satisfied_guard_failures": '
                    ),
                    "status": "preparing",
                },
                event_time_us=1_000,
            ),
        ],
        tool_exec_map={},
        hitl_answered_map={},
        hitl_status_map={},
        artifact_ready_map={},
        artifact_error_map={},
        completion_map={},
    )

    assert timeline[0]["toolInput"] == {
        "verdict": "accepted",
        "failed_criteria": [],
    }
    assert timeline[1]["type"] == "observe"
    assert timeline[1]["execution_id"] == "call-1"


def test_build_timeline_skips_act_delta_when_full_act_exists_for_same_call() -> None:
    timeline = _build_timeline(
        events=[
            _StubEvent(
                event_type="act_delta",
                event_data={
                    "tool_name": "bash",
                    "call_id": "call-1",
                    "accumulated_arguments": '{"command": "echo hi"}',
                    "status": "preparing",
                },
                event_time_us=1_000,
            ),
            _StubEvent(
                event_type="act",
                event_data={
                    "tool_name": "bash",
                    "tool_input": {"command": "echo hi"},
                    "call_id": "call-1",
                },
                event_time_us=2_000,
            ),
            _StubEvent(
                event_type="observe",
                event_data={
                    "tool_name": "bash",
                    "observation": "hi",
                    "call_id": "call-1",
                    "is_error": False,
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

    assert [(item["type"], item.get("execution_id")) for item in timeline] == [
        ("act", "call-1"),
        ("observe", "call-1"),
    ]


def test_build_timeline_keeps_same_tool_calls_separate_by_execution_id() -> None:
    timeline = _build_timeline(
        events=[
            _StubEvent(
                event_type="act",
                event_data={
                    "tool_name": "bash",
                    "tool_input": {"command": "echo first"},
                    "call_id": "call-1",
                },
                event_time_us=1_000,
            ),
            _StubEvent(
                event_type="observe",
                event_data={
                    "tool_name": "bash",
                    "observation": "first",
                    "call_id": "call-1",
                    "is_error": False,
                },
                event_time_us=2_000,
            ),
            _StubEvent(
                event_type="act",
                event_data={
                    "tool_name": "bash",
                    "tool_input": {"command": "echo second"},
                    "tool_execution_id": "exec-2",
                    "call_id": "call-2",
                },
                event_time_us=3_000,
            ),
            _StubEvent(
                event_type="observe",
                event_data={
                    "tool_name": "bash",
                    "observation": "second",
                    "tool_execution_id": "exec-2",
                    "call_id": "call-2",
                    "is_error": False,
                },
                event_time_us=4_000,
            ),
        ],
        tool_exec_map={},
        hitl_answered_map={},
        hitl_status_map={},
        artifact_ready_map={},
        artifact_error_map={},
        completion_map={},
    )

    assert [(item["type"], item.get("execution_id")) for item in timeline] == [
        ("act", "call-1"),
        ("observe", "call-1"),
        ("act", "exec-2"),
        ("observe", "exec-2"),
    ]
    assert timeline[0]["toolInput"] == {"command": "echo first"}
    assert timeline[2]["toolInput"] == {"command": "echo second"}


def test_build_timeline_uses_tool_execution_record_id_for_act_matching() -> None:
    now = datetime(2026, 6, 3, tzinfo=UTC)
    timeline = _build_timeline(
        events=[
            _StubEvent(
                event_type="act",
                event_data={
                    "tool_name": "bash",
                    "tool_input": {"command": "echo hi"},
                    "call_id": "call-1",
                },
                event_time_us=1_000,
            ),
            _StubEvent(
                event_type="observe",
                event_data={
                    "tool_name": "bash",
                    "observation": "hi",
                    "tool_execution_id": "exec-1",
                    "call_id": "call-1",
                    "is_error": False,
                },
                event_time_us=2_000,
            ),
        ],
        tool_exec_map=_build_tool_exec_map(
            [
                _StubToolExecution(
                    id="exec-1",
                    message_id="msg-1",
                    call_id="call-1",
                    tool_name="bash",
                    started_at=now,
                    completed_at=now,
                    duration_ms=7,
                )
            ]
        ),
        hitl_answered_map={},
        hitl_status_map={},
        artifact_ready_map={},
        artifact_error_map={},
        completion_map={},
    )

    assert timeline[0]["execution_id"] == "exec-1"
    assert timeline[0]["execution"] == {
        "startTime": now.timestamp() * 1000,
        "endTime": now.timestamp() * 1000,
        "duration": 7,
    }
    assert timeline[1]["execution_id"] == "exec-1"


def test_build_timeline_replays_terminal_act_delta_after_prior_same_tool_act() -> None:
    timeline = _build_timeline(
        events=[
            _StubEvent(
                event_type="act",
                event_data={
                    "tool_name": "workspace_submit_verification_judgment",
                    "tool_input": {"verdict": "rejected"},
                    "call_id": "call-prior",
                },
                event_time_us=1_000,
            ),
            _StubEvent(
                event_type="observe",
                event_data={
                    "tool_name": "workspace_submit_verification_judgment",
                    "observation": "prior complete",
                    "call_id": "call-prior",
                    "is_error": False,
                },
                event_time_us=2_000,
            ),
            _StubEvent(
                event_type="act_delta",
                event_data={
                    "tool_name": "workspace_submit_verification_judgment",
                    "call_id": "call-final",
                    "arguments_fragment": '{"verdict": "accepted"}',
                    "accumulated_arguments": '{"verdict": "accepted"}',
                    "status": "preparing",
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

    assert [(item["type"], item.get("execution_id")) for item in timeline] == [
        ("act", "call-prior"),
        ("observe", "call-prior"),
        ("act", "call-final"),
        ("observe", "call-final"),
    ]
    assert timeline[2]["toolInput"] == {"verdict": "accepted"}


def test_build_timeline_extracts_execution_id_by_precedence() -> None:
    timeline = _build_timeline(
        events=[
            _StubEvent(
                event_type="act",
                event_data={
                    "tool_name": "bash",
                    "tool_input": {"command": "echo hi"},
                    "tool_execution_id": "exec-1",
                    "execution_id": "legacy-exec",
                    "call_id": "call-1",
                },
                event_time_us=1_000,
            ),
            _StubEvent(
                event_type="observe",
                event_data={
                    "tool_name": "bash",
                    "observation": "hi",
                    "execution_id": "legacy-exec",
                    "call_id": "call-1",
                    "is_error": False,
                },
                event_time_us=2_000,
            ),
            _StubEvent(
                event_type="act_delta",
                event_data={
                    "tool_name": "workspace_submit_supervisor_decision",
                    "call_id": "call-final",
                    "accumulated_arguments": '{"action": "accept_node"}',
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

    assert timeline[0]["execution_id"] == "exec-1"
    assert timeline[1]["execution_id"] == "legacy-exec"
    assert timeline[2]["execution_id"] == "call-final"


def test_build_tool_exec_map_prefers_per_call_identity_over_tool_name() -> None:
    now = datetime(2026, 6, 3, tzinfo=UTC)
    tool_exec_map = _build_tool_exec_map(
        [
            _StubToolExecution(
                id="exec-1",
                message_id="msg-1",
                call_id="call-1",
                tool_name="bash",
                started_at=now,
                completed_at=now,
                duration_ms=10,
            ),
            _StubToolExecution(
                id="exec-2",
                message_id="msg-1",
                call_id="call-2",
                tool_name="bash",
                started_at=now,
                completed_at=now,
                duration_ms=20,
            ),
        ]
    )

    assert tool_exec_map["msg-1:call-1"]["duration"] == 10
    assert tool_exec_map["msg-1:exec-2"]["duration"] == 20
    assert tool_exec_map["msg-1:bash"]["duration"] == 10


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
                    "surface_data": {
                        "allowed_actions": [
                            {
                                "source_component_id": "button-1",
                                "action_name": "approve",
                            }
                        ],
                        "context": {"must_not_leak": True},
                        "components": "sensitive surface body",
                    },
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
            "allowed_actions": [{"source_component_id": "button-1", "action_name": "approve"}],
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


def test_build_timeline_replays_extended_subagent_lifecycle_for_desktop_history() -> None:
    subagent_events = [
        (
            "subagent_spawning",
            {"run_id": "run-1", "subagent_name": "Verifier", "spawn_mode": "run"},
        ),
        (
            "subagent_delegation",
            {
                "to_subagent_id": "verifier",
                "to_subagent_name": "Verifier",
                "trigger_type": "semantic",
                "task_description": "Verify the release evidence",
            },
        ),
        (
            "subagent_retry",
            {"subagent_id": "verifier", "subagent_name": "Verifier", "attempt": 2},
        ),
        (
            "subagent_doom_loop",
            {
                "subagent_id": "verifier",
                "subagent_name": "Verifier",
                "reason": "Repeated terminal invocation",
            },
        ),
        (
            "subagent_spawn_rejected",
            {"subagent_name": "Verifier", "rejection_reason": "Concurrency limit"},
        ),
        (
            "subagent_orphan_detected",
            {"run_id": "run-1", "subagent_name": "Verifier", "reason": "parent_gone"},
        ),
        (
            "subagent_announce_sent",
            {"agent_id": "verifier", "session_id": "session-1", "parent_agent_id": "main"},
        ),
        (
            "subagent_announce_received",
            {"agent_id": "main", "session_id": "session-1", "from_agent_id": "verifier"},
        ),
        (
            "subagent_announce_expired",
            {"agent_id": "verifier", "session_id": "session-1", "attempts": 3},
        ),
    ]
    assert {event_type for event_type, _ in subagent_events} <= _DISPLAYABLE_EVENTS
    timeline = _build_timeline(
        events=[
            _StubEvent(event_type=event_type, event_data=data, event_time_us=index * 1_000)
            for index, (event_type, data) in enumerate(subagent_events, start=1)
        ],
        tool_exec_map={},
        hitl_answered_map={},
        hitl_status_map={},
        artifact_ready_map={},
        artifact_error_map={},
        completion_map={},
    )

    assert [item["type"] for item in timeline] == [event_type for event_type, _ in subagent_events]
    assert [item["payload"] for item in timeline] == [data for _, data in subagent_events]


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


def test_build_timeline_replays_complete_skill_execution_for_desktop_history() -> None:
    skill_events = [
        (
            "skill_matched",
            {
                "skill_id": "release-guard",
                "skill_name": "Release guard",
                "tools": ["read_file", "shell_command"],
                "match_score": 0.96,
                "execution_mode": "direct",
            },
        ),
        (
            "skill_execution_start",
            {
                "skill_id": "release-guard",
                "skill_name": "Release guard",
                "tools": ["read_file", "shell_command"],
                "query": "Run release checks",
                "total_steps": 2,
            },
        ),
        (
            "skill_tool_start",
            {
                "skill_id": "release-guard",
                "skill_name": "Release guard",
                "tool_name": "shell_command",
                "tool_input": {"command": "pnpm test"},
                "step_index": 1,
                "total_steps": 2,
                "status": "running",
            },
        ),
        (
            "skill_tool_result",
            {
                "skill_id": "release-guard",
                "skill_name": "Release guard",
                "tool_name": "shell_command",
                "result": "All release checks passed",
                "duration_ms": 812,
                "step_index": 1,
                "total_steps": 2,
                "status": "completed",
            },
        ),
        (
            "skill_execution_complete",
            {
                "skill_id": "release-guard",
                "skill_name": "Release guard",
                "success": True,
                "summary": "Release checks passed with complete evidence.",
                "tool_results": [
                    {"tool_name": "read_file", "status": "completed"},
                    {"tool_name": "shell_command", "status": "completed"},
                ],
                "execution_time_ms": 1240,
            },
        ),
        (
            "skill_fallback",
            {
                "skill_id": "dependency-auditor",
                "skill_name": "Dependency auditor",
                "reason": "runtime_unavailable",
            },
        ),
    ]
    assert {event_type for event_type, _ in skill_events} <= _DISPLAYABLE_EVENTS
    timeline = _build_timeline(
        events=[
            _StubEvent(event_type=event_type, event_data=data, event_time_us=index * 1_000)
            for index, (event_type, data) in enumerate(skill_events, start=1)
        ],
        tool_exec_map={},
        hitl_answered_map={},
        hitl_status_map={},
        artifact_ready_map={},
        artifact_error_map={},
        completion_map={},
    )

    assert [item["type"] for item in timeline] == [event_type for event_type, _ in skill_events]
    assert [item["payload"] for item in timeline] == [data for _, data in skill_events]


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
