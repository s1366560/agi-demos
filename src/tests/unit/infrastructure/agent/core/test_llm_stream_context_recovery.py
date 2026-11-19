"""A provider input overflow may retry only a fresh, unobserved model stream."""

from copy import deepcopy

import pytest

from src.infrastructure.agent.core.llm_stream import LLMStream, StreamConfig, StreamEvent


class InputOverflow(Exception):
    code = "context_length_exceeded"


@pytest.mark.unit
@pytest.mark.parametrize(
    ("partial", "repeated", "expected"),
    [
        (False, False, ["text_delta"]),
        (True, False, ["text_delta", "error"]),
        (False, True, ["error"]),
    ],
)
async def test_recover_only_before_first_event(monkeypatch, partial, repeated, expected):
    stream = LLMStream(StreamConfig(model="test-model"))
    seen = []

    async def provider(messages, *_):
        seen.append(messages)
        if partial or (len(seen) > 1 and not repeated):
            yield StreamEvent.text_delta("token")
        if len(seen) == 1 or repeated:
            raise InputOverflow()

    monkeypatch.setattr(stream, "_generate_direct", provider)
    messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "old"},
        *[{"role": "assistant", "content": "history"} for _ in range(24)],
        {"role": "developer", "content": "instruction"},
        {"role": "user", "content": "current"},
        {"role": "assistant", "tool_calls": [{"id": "call1"}]},
        {"role": "tool", "tool_call_id": "call1", "content": "x" * 2000},
    ]
    original = deepcopy(messages)
    assert [event.type.value async for event in stream.generate(messages)] == expected
    assert original == messages
    assert len(seen) == (1 if partial else 2)
    if not partial:
        assert seen[1][:-1] == [messages[0], *messages[-4:-1]]
        assert seen[1][-1]["tool_call_id"] == "call1"
        assert len(seen[1][-1]["content"]) < len(messages[-1]["content"])


@pytest.mark.unit
async def test_overflow_without_reducible_input_is_terminal(monkeypatch):
    stream = LLMStream(StreamConfig(model="test-model"))
    attempts = []

    async def provider(messages, *_):
        attempts.append(messages)
        raise InputOverflow()
        yield

    monkeypatch.setattr(stream, "_generate_direct", provider)
    assert [
        event.type.value async for event in stream.generate([{"role": "user", "content": "x"}])
    ] == ["error"]
    assert len(attempts) == 1
