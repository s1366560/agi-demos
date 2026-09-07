"""V2 model-message commit invariants for ``SessionProcessor``."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from src.infrastructure.agent.actor.execution import _extract_event_side_effects
from src.infrastructure.agent.core.llm_stream import StreamEventType
from src.infrastructure.agent.core.message import ToolState
from src.infrastructure.agent.processor.processor import ProcessorConfig, SessionProcessor
from src.infrastructure.plugins.v2.session_event_log import MODEL_MESSAGE_COMMITTED_EVENT_V2


def _stream_event(event_type: StreamEventType, **data: Any) -> SimpleNamespace:
    return SimpleNamespace(type=event_type, data=data)


def _committed_messages(events: list[Any]) -> list[dict[str, Any]]:
    return [
        event["data"]["model_message"]
        for event in events
        if isinstance(event, dict) and event.get("type") == MODEL_MESSAGE_COMMITTED_EVENT_V2
    ]


async def _collect_step(processor: SessionProcessor) -> list[Any]:
    return [
        event
        async for event in processor._process_step(
            "session-1",
            [{"role": "user", "content": "run"}],
        )
    ]


@pytest.mark.unit
async def test_text_only_step_commits_exact_assistant_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_generate(_self: Any, _messages: list[dict[str, Any]], **_kwargs: Any):
        yield _stream_event(StreamEventType.TEXT_END, full_text="Done.")
        yield _stream_event(StreamEventType.FINISH, reason="stop")

    monkeypatch.setattr(
        "src.infrastructure.agent.processor.processor.LLMStream.generate",
        fake_generate,
    )
    processor = SessionProcessor(config=ProcessorConfig(model="test-model"), tools=[])

    events = await _collect_step(processor)

    assert _committed_messages(events) == [{"role": "assistant", "content": "Done."}]


@pytest.mark.unit
async def test_tool_step_commits_assistant_then_ordered_success_and_error_messages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_generate(_self: Any, _messages: list[dict[str, Any]], **_kwargs: Any):
        for call_id, tool_name, arguments in (
            ("call-1", "first_tool", {"value": 1}),
            ("call-2", "second_tool", {"value": 2}),
        ):
            yield _stream_event(
                StreamEventType.TOOL_CALL_START,
                call_id=call_id,
                name=tool_name,
            )
            yield _stream_event(
                StreamEventType.TOOL_CALL_END,
                call_id=call_id,
                name=tool_name,
                arguments=arguments,
            )
        yield _stream_event(StreamEventType.FINISH, reason="tool_calls")

    monkeypatch.setattr(
        "src.infrastructure.agent.processor.processor.LLMStream.generate",
        fake_generate,
    )
    processor = SessionProcessor(config=ProcessorConfig(model="test-model"), tools=[])

    async def fake_execute_tool(
        _session_id: str,
        call_id: str,
        _tool_name: str,
        _arguments: dict[str, Any],
    ):
        part = processor._pending_tool_calls[call_id]
        if call_id == "call-1":
            part.status = ToolState.COMPLETED
            part.output = "first result"
        else:
            part.status = ToolState.ERROR
            part.error = "second failed"
        if False:
            yield None

    processor._execute_tool = fake_execute_tool  # type: ignore[assignment]

    events = await _collect_step(processor)
    committed = _committed_messages(events)
    next_step_messages: list[dict[str, Any]] = []
    processor._append_tool_results_to_messages(next_step_messages)

    assert committed == next_step_messages
    assert committed == [
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call-1",
                    "type": "function",
                    "function": {"name": "first_tool", "arguments": '{"value": 1}'},
                },
                {
                    "id": "call-2",
                    "type": "function",
                    "function": {"name": "second_tool", "arguments": '{"value": 2}'},
                },
            ],
        },
        {"role": "tool", "tool_call_id": "call-1", "content": "first result"},
        {"role": "tool", "tool_call_id": "call-2", "content": "Error: second failed"},
    ]


@pytest.mark.unit
async def test_retry_discards_partial_attempt_and_commits_success_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = 0

    async def fake_generate(_self: Any, _messages: list[dict[str, Any]], **_kwargs: Any):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            yield _stream_event(StreamEventType.TEXT_END, full_text="partial")
            raise TimeoutError("temporary timeout")
        yield _stream_event(StreamEventType.TEXT_END, full_text="recovered")
        yield _stream_event(StreamEventType.FINISH, reason="stop")

    monkeypatch.setattr(
        "src.infrastructure.agent.processor.processor.LLMStream.generate",
        fake_generate,
    )
    monkeypatch.setattr("src.infrastructure.agent.processor.processor.asyncio.sleep", _no_sleep)
    processor = SessionProcessor(
        config=ProcessorConfig(model="test-model", max_attempts=2),
        tools=[],
    )
    processor.retry_policy.calculate_delay = lambda _attempt, _error: 0

    events = await _collect_step(processor)

    assert attempts == 2
    assert _committed_messages(events) == [{"role": "assistant", "content": "recovered"}]


async def _no_sleep(_delay: float) -> None:
    return None


@pytest.mark.unit
async def test_hitl_wait_starts_only_after_assistant_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_generate(_self: Any, _messages: list[dict[str, Any]], **_kwargs: Any):
        yield _stream_event(
            StreamEventType.TOOL_CALL_START,
            call_id="hitl-1",
            name="ask_clarification",
        )
        yield _stream_event(
            StreamEventType.TOOL_CALL_END,
            call_id="hitl-1",
            name="ask_clarification",
            arguments={"question": "Proceed?"},
        )
        yield _stream_event(StreamEventType.FINISH, reason="tool_calls")

    monkeypatch.setattr(
        "src.infrastructure.agent.processor.processor.LLMStream.generate",
        fake_generate,
    )
    processor = SessionProcessor(config=ProcessorConfig(model="test-model"), tools=[])
    wait_started = asyncio.Event()
    release_wait = asyncio.Event()

    async def fake_execute_tool(
        _session_id: str,
        call_id: str,
        _tool_name: str,
        _arguments: dict[str, Any],
    ):
        wait_started.set()
        await release_wait.wait()
        part = processor._pending_tool_calls[call_id]
        part.status = ToolState.COMPLETED
        part.output = "yes"
        if False:
            yield None

    processor._execute_tool = fake_execute_tool  # type: ignore[assignment]
    observed: list[Any] = []

    async def collect() -> None:
        async for event in processor._process_step(
            "session-1",
            [{"role": "user", "content": "run"}],
        ):
            observed.append(event)

    collector = asyncio.create_task(collect())
    await asyncio.wait_for(wait_started.wait(), timeout=1)
    try:
        assert _committed_messages(observed) == [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "hitl-1",
                        "type": "function",
                        "function": {
                            "name": "ask_clarification",
                            "arguments": '{"question": "Proceed?"}',
                        },
                    }
                ],
            }
        ]
    finally:
        release_wait.set()
        await collector


@pytest.mark.unit
def test_model_message_commit_requests_immediate_actor_flush() -> None:
    side_effects = _extract_event_side_effects(
        {
            "type": MODEL_MESSAGE_COMMITTED_EVENT_V2,
            "data": {"model_message": {"role": "assistant", "content": "Done."}},
        }
    )

    assert side_effects.should_flush_events is True
