"""Tests for the trace run digest builder + render + runtime injection."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from src.application.services.trace_digest_runtime import inject_trace_digest
from src.domain.model.trace.trace_run_digest import (
    CHURN_THRESHOLD,
    TraceEvent,
    TraceEventKind,
    TraceRunDigest,
    build_trace_run_digest,
)


@pytest.fixture
def base_time() -> datetime:
    return datetime(2026, 5, 6, 9, 0, tzinfo=UTC)


def _file(path: str, op: str, ts: datetime, *, kind: TraceEventKind = TraceEventKind.TOOL_RESULT) -> TraceEvent:
    return TraceEvent(
        kind=kind,
        timestamp=ts,
        tool_name="edit_file" if kind is TraceEventKind.TOOL_RESULT else None,
        success=True,
        file_path=path,
        operation=op,
    )


@pytest.mark.unit
class TestTraceRunDigestBuilder:
    def test_empty_events_returns_empty_digest(self) -> None:
        digest = build_trace_run_digest(session_id="s1", events=[])
        assert digest.total_events == 0
        assert digest.render() == ""

    def test_aggregates_file_touch_count_and_operations(self, base_time: datetime) -> None:
        events = [
            _file("src/foo.py", "read", base_time),
            _file("src/foo.py", "write", base_time + timedelta(seconds=1)),
            _file("src/bar.py", "read", base_time + timedelta(seconds=2)),
        ]
        digest = build_trace_run_digest(session_id="s1", events=events)
        assert digest.total_events == 3
        assert {f.path for f in digest.files_touched} == {"src/foo.py", "src/bar.py"}
        foo = next(f for f in digest.files_touched if f.path == "src/foo.py")
        assert foo.touch_count == 2
        assert "read" in foo.operations and "write" in foo.operations

    def test_tool_call_count_and_failures(self, base_time: datetime) -> None:
        events = [
            TraceEvent(
                kind=TraceEventKind.TOOL_CALL,
                timestamp=base_time,
                tool_name="grep",
            ),
            TraceEvent(
                kind=TraceEventKind.TOOL_RESULT,
                timestamp=base_time + timedelta(seconds=1),
                tool_name="grep",
                success=True,
            ),
            TraceEvent(
                kind=TraceEventKind.TOOL_CALL,
                timestamp=base_time + timedelta(seconds=2),
                tool_name="grep",
            ),
            TraceEvent(
                kind=TraceEventKind.TOOL_RESULT,
                timestamp=base_time + timedelta(seconds=3),
                tool_name="grep",
                success=False,
                summary="no matches",
            ),
        ]
        digest = build_trace_run_digest(session_id="s1", events=events)
        grep = next(t for t in digest.tool_calls if t.name == "grep")
        assert grep.count == 2
        assert grep.failures == 1
        assert digest.error_count == 1

    def test_verification_signal_detected_for_pytest_command(self, base_time: datetime) -> None:
        events = [
            TraceEvent(
                kind=TraceEventKind.TOOL_CALL,
                timestamp=base_time,
                tool_name="run_command",
                summary="uv run pytest src/tests/unit",
            ),
            TraceEvent(
                kind=TraceEventKind.TOOL_RESULT,
                timestamp=base_time + timedelta(seconds=1),
                tool_name="run_command",
                success=True,
                summary="14 passed",
            ),
        ]
        digest = build_trace_run_digest(session_id="s1", events=events)
        assert len(digest.verification_signals) == 1
        sig = digest.verification_signals[0]
        assert sig.passed is True
        assert "pytest" in sig.command

    def test_failed_verification_raises_confidence_flag(self, base_time: datetime) -> None:
        events = [
            TraceEvent(
                kind=TraceEventKind.TOOL_CALL,
                timestamp=base_time,
                tool_name="run_command",
                summary="npm run lint",
            ),
            TraceEvent(
                kind=TraceEventKind.TOOL_RESULT,
                timestamp=base_time + timedelta(seconds=1),
                tool_name="run_command",
                success=False,
                summary="3 errors",
            ),
        ]
        digest = build_trace_run_digest(session_id="s1", events=events)
        flags = " ".join(digest.confidence_flags)
        assert "verification" in flags.lower()

    def test_high_churn_file_marked(self, base_time: datetime) -> None:
        events = [
            _file("src/hot.py", "write", base_time + timedelta(seconds=i))
            for i in range(CHURN_THRESHOLD + 1)
        ]
        digest = build_trace_run_digest(session_id="s1", events=events)
        assert any(c.target == "src/hot.py" and c.target_type == "file" for c in digest.churn_markers)

    def test_render_emits_parent_run_digest_block(self, base_time: datetime) -> None:
        events = [
            _file("src/foo.py", "write", base_time),
            TraceEvent(
                kind=TraceEventKind.THOUGHT,
                timestamp=base_time + timedelta(seconds=1),
                summary="Plan: refactor before adding tests",
            ),
        ]
        digest = build_trace_run_digest(session_id="s1", events=events)
        rendered = digest.render()
        assert rendered.startswith("[Parent Run Digest]")
        assert "src/foo.py" in rendered
        assert "Plan: refactor" in rendered

    def test_keeps_only_last_three_thoughts(self, base_time: datetime) -> None:
        events = [
            TraceEvent(
                kind=TraceEventKind.THOUGHT,
                timestamp=base_time + timedelta(seconds=i),
                summary=f"thought-{i}",
            )
            for i in range(6)
        ]
        digest = build_trace_run_digest(session_id="s1", events=events)
        assert len(digest.key_thoughts) == 3
        assert digest.key_thoughts[-1] == "thought-5"


@pytest.mark.unit
class TestTraceDigestRuntimeInjection:
    def test_inject_appends_once(self) -> None:
        class P:
            def __init__(self) -> None:
                self._session_instructions: list[str] = []

        proc = P()
        # Build a non-empty digest via builder to get a renderable string.
        events = [
            TraceEvent(
                kind=TraceEventKind.TOOL_CALL,
                timestamp=datetime(2026, 5, 6, tzinfo=UTC),
                tool_name="grep",
                summary="grep foo src/",
            ),
        ]
        d2 = build_trace_run_digest(session_id="s", events=events)
        rendered = inject_trace_digest(proc, d2)
        assert rendered in proc._session_instructions
        # Idempotent
        inject_trace_digest(proc, d2)
        assert proc._session_instructions.count(rendered) == 1

    def test_empty_digest_does_not_inject(self) -> None:
        class P:
            def __init__(self) -> None:
                self._session_instructions: list[str] = []

        proc = P()
        empty = TraceRunDigest(session_id="s", total_events=0)
        rendered = inject_trace_digest(proc, empty)
        assert rendered == ""
        assert proc._session_instructions == []
