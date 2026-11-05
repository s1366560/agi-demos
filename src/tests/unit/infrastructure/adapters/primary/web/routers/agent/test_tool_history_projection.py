"""Tool history joins drafts to calls without merging independent executions."""

from types import SimpleNamespace

import pytest

from src.infrastructure.adapters.primary.web.routers.agent.messages import (
    _build_timeline,
    _build_tool_exec_map,
)

pytestmark = pytest.mark.unit


def _event(kind, time, *, message="message", call="call", execution=None):
    data = {"tool_name": "bash", "call_id": call, "tool_input": {"command": "true"}}
    if execution:
        data["tool_execution_id"] = execution
    return SimpleNamespace(
        event_type=kind,
        event_data=data,
        message_id=message,
        event_time_us=time,
        event_counter=0,
    )


def _timeline(events, executions=None):
    return _build_timeline(events, executions or {}, {}, {}, {}, {}, {})


def test_draft_call_identity_matches_full_act_with_distinct_execution_id():
    timeline = _timeline([_event("act_delta", 1), _event("act", 2, execution="execution")])
    assert len(timeline) == 1
    assert timeline[0]["execution_id"] == "execution"
    assert timeline[0]["call_id"] == "call"
    assert timeline[0]["message_id"] == "message"


def test_draft_with_explicit_execution_id_does_not_merge_another_execution():
    timeline = _timeline(
        [
            _event("act_delta", 1, execution="pending"),
            _event("act", 2, execution="completed"),
        ]
    )
    assert [item["execution_id"] for item in timeline] == ["pending", "completed"]


def test_draft_call_id_fallback_merges_but_all_full_executions_remain():
    timeline = _timeline(
        [
            _event("act_delta", 1, execution="call"),
            _event("act", 2, execution="first"),
            _event("act", 3, execution="second"),
        ]
    )
    assert [item["execution_id"] for item in timeline] == ["first", "second"]


def test_call_identity_is_scoped_to_message_and_observe_preserves_it():
    timeline = _timeline(
        [
            _event("act_delta", 1, message="earlier"),
            _event("act", 2, execution="execution"),
            _event("observe", 3, execution="execution"),
        ]
    )
    assert len(timeline) == 3
    assert [item["message_id"] for item in timeline] == ["earlier", "message", "message"]
    assert timeline[-1]["call_id"] == "call"


def test_latest_draft_only_replaces_same_call_and_execution():
    timeline = _timeline(
        [
            _event("act_delta", 1, execution="first"),
            _event("act_delta", 2, execution="second"),
            _event("act_delta", 3, execution="first"),
        ]
    )
    assert [item["eventTimeUs"] for item in timeline] == [2, 3]


def test_unmatched_call_does_not_inherit_other_execution_via_tool_name():
    executions = _build_tool_exec_map(
        [
            SimpleNamespace(
                id="other-execution",
                message_id="message",
                call_id="other-call",
                tool_name="bash",
                started_at=None,
                completed_at=None,
                duration_ms=99,
            )
        ]
    )
    timeline = _timeline(
        [_event("act", 1, execution="execution"), _event("act", 2, call="bash")], executions
    )
    assert timeline[0]["execution_id"] == "execution"
    assert "execution" not in timeline[0]
    assert timeline[1]["execution_id"] == "bash"
    assert "execution" not in timeline[1]


@pytest.mark.parametrize("status", ["success", "failed", "cancelled"])
def test_terminal_tool_record_projects_exact_call_status_and_error(status):
    executions = _build_tool_exec_map(
        [
            SimpleNamespace(
                id="execution",
                message_id="message",
                call_id="call",
                tool_name="bash",
                started_at=None,
                completed_at=None,
                duration_ms=10,
                status=status,
                error="record error" if status != "success" else None,
            )
        ]
    )
    timeline = _timeline(
        [
            _event("act", 1),
            _event("act", 2, message="another-message"),
            _event("act", 3, call=None),
        ],
        executions,
    )
    assert timeline[0]["execution"]["status"] == status
    assert timeline[0]["execution_id"] == "execution"
    if status != "success":
        assert timeline[0]["execution"]["error"] == "record error"
    assert "execution" not in timeline[1]
    assert "status" not in timeline[2]["execution"]
    assert "error" not in timeline[2]["execution"]
