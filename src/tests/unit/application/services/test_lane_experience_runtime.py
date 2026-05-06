"""Tests for the lane-experience → processor integration shim."""

from __future__ import annotations

from src.application.services.lane_experience_runtime import inject_lane_jit_context
from src.application.services.lane_experience_service import LaneJitContext


class _StubProcessor:
    def __init__(self) -> None:
        self._session_instructions: list[str] = []


def _ctx(headline: str = "Lane 'Todo' just received the card.") -> LaneJitContext:
    return LaneJitContext(
        lane_id="todo",
        headline=headline,
        bullets=("bounce dev->todo x2",),
    )


def test_inject_appends_rendered_guidance() -> None:
    proc = _StubProcessor()
    rendered = inject_lane_jit_context(proc, _ctx())
    assert rendered.startswith("Lane 'Todo'")
    assert proc._session_instructions == [rendered]


def test_inject_is_idempotent() -> None:
    proc = _StubProcessor()
    ctx = _ctx()
    inject_lane_jit_context(proc, ctx)
    inject_lane_jit_context(proc, ctx)
    assert len(proc._session_instructions) == 1


def test_inject_allows_distinct_guidance_blocks() -> None:
    proc = _StubProcessor()
    inject_lane_jit_context(proc, _ctx("Lane 'Todo' just received the card."))
    inject_lane_jit_context(proc, _ctx("Lane 'Dev' just received the card."))
    assert len(proc._session_instructions) == 2
