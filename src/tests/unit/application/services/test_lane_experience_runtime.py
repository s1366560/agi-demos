"""Tests for the lane-experience → processor integration shim."""

from __future__ import annotations

import pytest

from src.application.services.lane_experience_runtime import inject_lane_jit_context
from src.application.services.lane_experience_service import LaneJitContext


class _StubProcessor:
    """Mimics the public ``add_runtime_guidance`` contract on ``SessionProcessor``."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def add_runtime_guidance(self, text: str) -> bool:
        cleaned = text.strip()
        if not cleaned or cleaned in self.calls:
            return False
        self.calls.append(cleaned)
        return True


def _ctx(headline: str = "Lane 'Todo' just received the card.") -> LaneJitContext:
    return LaneJitContext(
        lane_id="todo",
        headline=headline,
        bullets=("bounce dev->todo x2",),
    )


@pytest.mark.asyncio
async def test_inject_appends_rendered_guidance() -> None:
    proc = _StubProcessor()
    rendered = await inject_lane_jit_context(proc, _ctx())
    assert rendered.startswith("Lane 'Todo'")
    assert proc.calls == [rendered]


@pytest.mark.asyncio
async def test_inject_is_idempotent() -> None:
    proc = _StubProcessor()
    ctx = _ctx()
    await inject_lane_jit_context(proc, ctx)
    await inject_lane_jit_context(proc, ctx)
    assert len(proc.calls) == 1


@pytest.mark.asyncio
async def test_inject_allows_distinct_guidance_blocks() -> None:
    proc = _StubProcessor()
    await inject_lane_jit_context(proc, _ctx("Lane 'Todo' just received the card."))
    await inject_lane_jit_context(proc, _ctx("Lane 'Dev' just received the card."))
    assert len(proc.calls) == 2
