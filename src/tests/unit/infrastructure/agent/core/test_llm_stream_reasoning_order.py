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


@pytest.mark.unit
def test_stream_requests_usage_and_preserves_explicit_provider_override() -> None:
    assert StreamConfig(model="test-model").to_litellm_kwargs()["stream_options"] == {
        "include_usage": True
    }
    assert StreamConfig(
        model="test-model", provider_options={"stream_options": {"include_usage": False}}
    ).to_litellm_kwargs()["stream_options"] == {"include_usage": False}


@pytest.mark.unit
@pytest.mark.parametrize("choices", [[], [SimpleNamespace(delta=None)]])
async def test_usage_only_chunk_is_preserved_without_a_content_choice(choices) -> None:
    stream = _stream()
    chunk = SimpleNamespace(
        choices=choices,
        usage=SimpleNamespace(prompt_tokens=123, completion_tokens=7),
    )
    assert [event async for event in stream._process_chunk(chunk)] == []
    assert stream._usage["input_tokens"] == 123
    assert stream._usage["output_tokens"] == 7


@pytest.mark.unit
@pytest.mark.parametrize(
    ("provider", "model", "wire_usage"),
    [
        ("anthropic", "claude-sonnet-4-5", False),
        ("minimax", "MiniMax-M3", True),
        ("openai", "gpt-4o", True),
    ],
)
def test_installed_adapter_maps_usage_option_for_its_native_protocol(
    provider: str, model: str, wire_usage: bool
) -> None:
    from litellm.utils import get_optional_params

    request = StreamConfig(model=model).to_litellm_kwargs()
    mapped = get_optional_params(
        model=model,
        custom_llm_provider=provider,
        stream=request["stream"],
        stream_options=request["stream_options"],
    )
    assert ("stream_options" in mapped) is wire_usage
    if wire_usage:
        assert mapped["stream_options"] == {"include_usage": True}


@pytest.mark.unit
@pytest.mark.parametrize("override", [None, False])
async def test_injected_client_requests_and_emits_usage(override: bool | None) -> None:
    captured = {}

    class Client:
        async def generate_stream(self, **kwargs):
            captured.update(kwargs)
            yield SimpleNamespace(
                choices=[], usage=SimpleNamespace(prompt_tokens=123, completion_tokens=7)
            )

    stream = LLMStream(
        StreamConfig(
            model="test-model",
            provider_options={}
            if override is None
            else {"stream_options": {"include_usage": override}},
        ),
        llm_client=Client(),
    )
    events = [event async for event in stream._generate_with_client([], "test-request")]
    assert captured["stream_options"] == {"include_usage": True if override is None else override}
    usage = next(event for event in events if event.type.value == "usage")
    assert usage.data["input_tokens"] == 123
    assert usage.data["output_tokens"] == 7
