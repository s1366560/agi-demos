"""Unit tests for LLMStream reasoning/text ordering."""

from types import SimpleNamespace

import pytest

from src.infrastructure.agent.core.llm_stream import LLMStream, StreamConfig, StreamEvent


def _stream() -> LLMStream:
    return LLMStream(StreamConfig(model="test-model"))


def _types(events: list[StreamEvent]) -> list[str]:
    return [event.type.value for event in events]


@pytest.mark.unit
def test_reasoning_closes_before_text() -> None:
    stream = _stream()

    events = [
        *stream._handle_reasoning_delta("thinking"),
        *stream._handle_content_delta("answer"),
        *stream._finalize_streams(),
    ]

    assert _types(events) == [
        "reasoning_start",
        "reasoning_delta",
        "reasoning_end",
        "text_start",
        "text_delta",
        "text_end",
    ]


@pytest.mark.unit
async def test_same_chunk_reasoning_precedes_text() -> None:
    stream = _stream()
    chunk = SimpleNamespace(
        choices=[
            SimpleNamespace(
                delta=SimpleNamespace(
                    reasoning_content="thinking",
                    content="answer",
                    tool_calls=None,
                ),
                finish_reason=None,
            )
        ],
        usage=None,
    )

    events = []
    async for event in stream._process_chunk(chunk):
        events.append(event)
    events.extend(stream._finalize_streams())

    assert _types(events) == [
        "reasoning_start",
        "reasoning_delta",
        "reasoning_end",
        "text_start",
        "text_delta",
        "text_end",
    ]


@pytest.mark.unit
def test_think_tag_reasoning_closes_before_text() -> None:
    stream = _stream()

    events = [
        *stream._handle_content_delta("<think>thinking</think>answer"),
        *stream._finalize_streams(),
    ]

    assert _types(events) == [
        "reasoning_start",
        "reasoning_delta",
        "reasoning_end",
        "text_start",
        "text_delta",
        "text_end",
    ]


@pytest.mark.unit
async def test_reasoning_closes_before_tool_call() -> None:
    stream = _stream()
    events = [*stream._handle_reasoning_delta("thinking")]
    chunk = SimpleNamespace(
        choices=[
            SimpleNamespace(
                delta=SimpleNamespace(
                    reasoning_content=None,
                    content=None,
                    tool_calls=[
                        SimpleNamespace(
                            index=0,
                            id="call-1",
                            function=SimpleNamespace(name="search", arguments='{"q":"x"}'),
                        )
                    ],
                ),
                finish_reason=None,
            )
        ],
        usage=None,
    )

    async for event in stream._process_chunk(chunk):
        events.append(event)

    assert _types(events) == [
        "reasoning_start",
        "reasoning_delta",
        "reasoning_end",
        "tool_call_start",
        "tool_call_delta",
    ]
