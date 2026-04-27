"""Tests for historical tool execution backfill helpers."""

from __future__ import annotations

from types import SimpleNamespace

from src.application.services.tool_execution_backfill_service import (
    _apply_event_to_draft,
    _event_payload,
    _record_identity,
    _ToolRecordDraft,
)
from src.domain.ports.agent.tool_executor_port import ToolExecutionStatus


def _row(**overrides: object) -> SimpleNamespace:
    defaults = {
        "id": "event-1",
        "conversation_id": "conv-1",
        "message_id": "msg-1",
        "event_type": "act",
        "event_time_us": 1_000_000,
        "event_counter": 3,
        "correlation_id": "corr-1",
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_record_identity_uses_existing_tool_execution_id() -> None:
    row = _row()

    identity = _record_identity(
        row,  # type: ignore[arg-type]
        {
            "tool_execution_id": "ter-1",
            "call_id": "call-1",
            "tool_name": "bash",
        },
    )

    assert identity == ("ter-1", "msg-1", "call-1", "bash")


def test_record_identity_generates_stable_legacy_id() -> None:
    row = _row(message_id=None)
    payload = {"message_id": "msg-legacy", "call_id": "call-1", "tool_name": "bash"}

    first = _record_identity(row, payload)  # type: ignore[arg-type]
    second = _record_identity(row, payload)  # type: ignore[arg-type]

    assert first == second
    assert first is not None
    assert first[0].startswith("legacy-tool:")
    assert first[1:] == ("msg-legacy", "call-1", "bash")


def test_event_payload_accepts_nested_legacy_shape() -> None:
    payload = _event_payload({"data": {"call_id": "call-1", "tool_name": "bash"}})

    assert payload == {"call_id": "call-1", "tool_name": "bash"}


def test_apply_act_and_observe_events_to_draft() -> None:
    draft = _ToolRecordDraft(
        id="ter-1",
        conversation_id="conv-1",
        message_id="msg-1",
        call_id="call-1",
        tool_name="bash",
    )

    _apply_event_to_draft(
        draft,
        _row(event_type="act", event_time_us=1_000_000),  # type: ignore[arg-type]
        {"tool_input": {"command": "git status"}},
    )
    _apply_event_to_draft(
        draft,
        _row(event_type="observe", event_time_us=1_250_000, event_counter=4),  # type: ignore[arg-type]
        {"result": {"exit_code": 0}, "duration_ms": 25.9, "status": "success"},
    )

    assert draft.tool_input == {"command": "git status"}
    assert draft.status == ToolExecutionStatus.SUCCESS.value
    assert draft.tool_output == '{"exit_code": 0}'
    assert draft.duration_ms == 25
    assert draft.started_at is not None
    assert draft.completed_at is not None


def test_apply_failed_observe_sets_error() -> None:
    draft = _ToolRecordDraft(
        id="ter-1",
        conversation_id="conv-1",
        message_id="msg-1",
        call_id="call-1",
        tool_name="bash",
    )

    _apply_event_to_draft(
        draft,
        _row(event_type="observe", event_time_us=2_000_000),  # type: ignore[arg-type]
        {"error": "command failed", "status": "failed"},
    )

    assert draft.status == ToolExecutionStatus.FAILED.value
    assert draft.error == "command failed"


def test_apply_observe_strips_nul_bytes_from_text_output() -> None:
    draft = _ToolRecordDraft(
        id="ter-1",
        conversation_id="conv-1",
        message_id="msg-1",
        call_id="call-1",
        tool_name="bash",
    )

    _apply_event_to_draft(
        draft,
        _row(event_type="observe", event_time_us=2_000_000),  # type: ignore[arg-type]
        {"result": "hello\x00world", "status": "success"},
    )

    assert draft.tool_output == "helloworld"
