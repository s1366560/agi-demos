"""Tests for SessionProcessor reasoning stream event mapping."""

from collections.abc import AsyncIterator
from typing import Any

import pytest

from src.infrastructure.agent.core.llm_stream import StreamEvent
from src.infrastructure.agent.processor.processor import ProcessorConfig, SessionProcessor


class _ReasoningThenTextStream:
    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        pass

    async def generate(self, *_args: Any, **_kwargs: Any) -> AsyncIterator[StreamEvent]:
        yield StreamEvent.reasoning_start()
        yield StreamEvent.reasoning_delta("thinking")
        yield StreamEvent.reasoning_end("thinking")
        yield StreamEvent.text_start()
        yield StreamEvent.text_delta("answer")
        yield StreamEvent.text_end("answer")
        yield StreamEvent.finish("stop")


@pytest.mark.unit
async def test_process_step_maps_reasoning_start_before_text(monkeypatch) -> None:
    monkeypatch.setattr(
        "src.infrastructure.agent.processor.processor.LLMStream",
        _ReasoningThenTextStream,
    )
    processor = SessionProcessor(config=ProcessorConfig(model="test-model"), tools=[])

    events = [
        event
        async for event in processor._process_step(
            "session-1",
            [{"role": "user", "content": "hi"}],
        )
    ]

    event_names = [event.__class__.__name__ for event in events[:6]]
    assert event_names == [
        "AgentThoughtStartEvent",
        "AgentThoughtDeltaEvent",
        "AgentThoughtEvent",
        "AgentTextStartEvent",
        "AgentTextDeltaEvent",
        "AgentTextEndEvent",
    ]
