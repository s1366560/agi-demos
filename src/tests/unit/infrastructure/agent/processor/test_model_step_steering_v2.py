"""Real Processor loop boundaries with local, interruptible model streams."""

import asyncio
from contextvars import ContextVar
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.domain.events.agent_events import (
    AgentCostUpdateEvent,
    AgentErrorEvent,
    SubAgentSteeredEvent,
)
from src.domain.model.agent.tool_policy import ControlMessageType
from src.domain.ports.agent.control_channel_port import ControlMessage
from src.infrastructure.agent.core.llm_stream import StreamEventType
from src.infrastructure.agent.processor.model_step_control_v2 import model_stream_control_v2
from src.infrastructure.agent.processor.processor import (
    ProcessorConfig,
    ProcessorResult,
    SessionProcessor,
    ToolDefinition,
)


def event(kind, **data):
    return SimpleNamespace(type=kind, data=data)


def setup_processor(monkeypatch):
    queue = []
    channel = AsyncMock()

    async def consume(_run_id):
        batch = list(queue)
        queue.clear()
        return batch

    channel.consume_control.side_effect = consume
    tool = AsyncMock(return_value="must not run")
    processor = SessionProcessor(
        config=ProcessorConfig(model="local-test", control_channel=channel, run_id="child"),
        tools=[ToolDefinition(name="write", description="write", parameters={}, execute=tool)],
    )
    processor._abort_event = asyncio.Event()
    monkeypatch.setattr(processor, "_try_intercept_command", AsyncMock(return_value=None))
    monkeypatch.setattr(
        processor, "_evaluate_goal_progress", AsyncMock(return_value=(ProcessorResult.COMPLETE, []))
    )

    async def complete(*_args):
        if False:
            yield None

    monkeypatch.setattr(processor, "_emit_completion_events", complete)
    return processor, queue, tool


def steer():
    return ControlMessage(
        run_id="child",
        message_type=ControlMessageType.STEER,
        payload="new instruction",
        conversation_id="conversation",
    )


@pytest.mark.unit
@pytest.mark.parametrize("long_stream", [False, True])
async def test_steer_cancels_old_model_before_commit_or_tools(monkeypatch, long_stream):
    processor, queue, tool = setup_processor(monkeypatch)
    entered, closed = asyncio.Event(), asyncio.Event()
    requests = []
    artifact_inputs = []
    artifact_generator = processor._emit_text_end_with_linked_artifacts

    async def artifacts(text):
        artifact_inputs.append(text)
        async for emitted in artifact_generator(text):
            yield emitted

    monkeypatch.setattr(processor, "_emit_text_end_with_linked_artifacts", artifacts)

    async def generate(_self, messages, **_kwargs):
        requests.append(list(messages))
        if len(requests) == 1:
            try:
                if long_stream:
                    yield event(StreamEventType.TOOL_CALL_START, call_id="old", name="write")
                    yield event(
                        StreamEventType.TOOL_CALL_END, call_id="old", name="write", arguments={}
                    )
                    yield event(StreamEventType.TEXT_END, full_text="old final")
                entered.set()
                while True:
                    await asyncio.sleep(0.02)
                    if long_stream:
                        yield event(StreamEventType.REASONING_DELTA, delta="partial")
            finally:
                closed.set()
        else:
            yield event(StreamEventType.TEXT_END, full_text="new final")
            yield event(StreamEventType.FINISH, reason="stop")

    monkeypatch.setattr("src.infrastructure.agent.processor.processor.LLMStream.generate", generate)
    messages = [{"role": "user", "content": "original"}]

    async def collect():
        return [e async for e in processor._run_native_loop("conversation", messages)]

    task = asyncio.create_task(collect())
    try:
        await asyncio.wait_for(entered.wait(), 1)
        queue.append(steer())
        events = await asyncio.wait_for(task, 1)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    assert closed.is_set()
    assert len(requests) == 2
    assert requests[1][-1]["content"].endswith("new instruction")
    assert any(isinstance(e, SubAgentSteeredEvent) for e in events)
    assert not any(isinstance(e, AgentErrorEvent) for e in events)
    assert not processor._abort_event.is_set()
    committed = [e["data"]["model_message"] for e in events if isinstance(e, dict)]
    assert committed == [{"role": "assistant", "content": "new final"}]
    assert artifact_inputs == ["new final"]
    tool.assert_not_awaited()


@pytest.mark.unit
async def test_control_at_model_end_discards_old_final(monkeypatch):
    processor, queue, tool = setup_processor(monkeypatch)
    requests = []

    async def generate(_self, messages, **_kwargs):
        requests.append(list(messages))
        if len(requests) == 1:
            yield event(StreamEventType.TEXT_END, full_text="old final")
            queue.append(steer())
        else:
            yield event(StreamEventType.TEXT_END, full_text="new final")
        yield event(StreamEventType.FINISH, reason="stop")

    monkeypatch.setattr("src.infrastructure.agent.processor.processor.LLMStream.generate", generate)
    events = [e async for e in processor._run_native_loop("conversation", [])]
    assert len(requests) == 2
    assert all(getattr(e, "full_text", None) != "old final" for e in events)
    assert not any(isinstance(e, AgentErrorEvent) for e in events)
    tool.assert_not_awaited()


@pytest.mark.unit
async def test_kill_wins_over_queued_steer(monkeypatch):
    processor, queue, _tool = setup_processor(monkeypatch)
    queue.extend([steer(), ControlMessage(run_id="child", message_type=ControlMessageType.KILL)])
    messages = []
    events = await processor._check_control_channel(messages)
    assert messages == []
    assert not any(isinstance(e, SubAgentSteeredEvent) for e in events)
    assert any(isinstance(e, AgentErrorEvent) and e.code == "KILLED" for e in events)


@pytest.mark.unit
async def test_model_generator_context_and_cancellation_are_operation_owned():
    context = ContextVar("model-test-scope", default="outside")
    started, closed = asyncio.Event(), asyncio.Event()

    async def stream():
        token = context.set("inside")
        try:
            yield "first"
            assert context.get() == "inside"
            started.set()
            await asyncio.Event().wait()
        finally:
            context.reset(token)
            closed.set()

    async def collect():
        return [item async for item in model_stream_control_v2(stream(), AsyncMock())]

    task = asyncio.create_task(collect())
    await asyncio.wait_for(started.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert closed.is_set()
    assert context.get() == "outside"


@pytest.mark.unit
async def test_owner_kill_uses_runner_cancellation_path(monkeypatch):
    processor, queue, _tool = setup_processor(monkeypatch)
    processor.config.subagent_owner_required = True
    queue.extend([steer(), ControlMessage(run_id="child", message_type=ControlMessageType.KILL)])
    messages = []
    with pytest.raises(asyncio.CancelledError):
        await processor._poll_model_control_v2(messages)
    assert messages == []


@pytest.mark.unit
async def test_steer_interrupts_goal_judge_wait_and_redecides(monkeypatch):
    processor, queue, tool = setup_processor(monkeypatch)
    entered, closed = asyncio.Event(), asyncio.Event()
    requests = []

    async def generate(_self, messages, **_kwargs):
        requests.append(list(messages))
        if len(requests) == 1:
            yield event(StreamEventType.TOOL_CALL_START, call_id="completed-call", name="write")
            yield event(
                StreamEventType.TOOL_CALL_END,
                call_id="completed-call",
                name="write",
                arguments={},
            )
        yield event(StreamEventType.TEXT_END, full_text="response")
        yield event(StreamEventType.FINISH, reason="stop")

    async def judge(*_args):
        if len(requests) == 1:
            try:
                entered.set()
                await asyncio.Event().wait()
            finally:
                closed.set()
        return ProcessorResult.COMPLETE, []

    monkeypatch.setattr("src.infrastructure.agent.processor.processor.LLMStream.generate", generate)
    monkeypatch.setattr(processor, "_evaluate_goal_progress", judge)

    async def collect():
        return [e async for e in processor._run_native_loop("conversation", [])]

    task = asyncio.create_task(collect())
    try:
        await asyncio.wait_for(entered.wait(), 1)
        queue.append(steer())
        await asyncio.wait_for(task, 1)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    assert closed.is_set()
    assert len(requests) == 2
    assert requests[1][-1]["content"].endswith("new instruction")
    assert [message["role"] for message in requests[1]] == ["assistant", "tool", "system"]
    assert requests[1][0]["tool_calls"][0]["id"] == "completed-call"
    assert requests[1][1]["tool_call_id"] == "completed-call"
    tool.assert_awaited_once()


@pytest.mark.unit
@pytest.mark.parametrize("usage_delivered", [False, True])
@pytest.mark.parametrize("usage_known", [False, True])
async def test_interrupted_known_usage_is_accounted_once(monkeypatch, usage_delivered, usage_known):
    processor, queue, _tool = setup_processor(monkeypatch)
    attempts = 0

    async def generate(stream, _messages, **_kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            if usage_known:
                chunk = SimpleNamespace(
                    usage=SimpleNamespace(prompt_tokens=123, completion_tokens=17), choices=[]
                )
                async for emitted in stream._process_chunk(chunk):
                    yield emitted
            stream._in_text = True
            stream._text_buffer = "old final"
            async for emitted in stream._finalize():
                yield emitted
                interrupt_here = (
                    emitted.type == StreamEventType.USAGE
                    if usage_delivered and usage_known
                    else emitted.type == StreamEventType.TEXT_END
                )
                if interrupt_here:
                    queue.append(steer())
                    await asyncio.Event().wait()
        else:
            yield event(StreamEventType.TEXT_END, full_text="new final")
            yield event(StreamEventType.FINISH, reason="stop")

    monkeypatch.setattr("src.infrastructure.agent.processor.processor.LLMStream.generate", generate)
    events = await asyncio.wait_for(_collect_native(processor), 1)
    usage = processor.cost_tracker.total_tokens
    assert (usage.input, usage.output) == ((123, 17) if usage_known else (0, 0))
    costs = [emitted for emitted in events if isinstance(emitted, AgentCostUpdateEvent)]
    assert len(costs) == (1 if usage_known else 0)
    assert attempts == 2
    assert all(getattr(emitted, "full_text", None) != "old final" for emitted in events)


async def _collect_native(processor):
    return [emitted async for emitted in processor._run_native_loop("conversation", [])]


@pytest.mark.unit
async def test_owner_cancellation_retains_reported_usage_and_still_propagates(monkeypatch):
    processor, _queue, _tool = setup_processor(monkeypatch)
    entered = asyncio.Event()
    events = []

    async def generate(stream, _messages, **_kwargs):
        chunk = SimpleNamespace(
            usage=SimpleNamespace(prompt_tokens=123, completion_tokens=17), choices=[]
        )
        async for emitted in stream._process_chunk(chunk):
            yield emitted
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr("src.infrastructure.agent.processor.processor.LLMStream.generate", generate)

    async def collect():
        async for emitted in processor._run_native_loop("conversation", []):
            events.append(emitted)

    task = asyncio.create_task(collect())
    await asyncio.wait_for(entered.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    usage = processor.cost_tracker.total_tokens
    assert (usage.input, usage.output) == (123, 17)
    assert sum(isinstance(emitted, AgentCostUpdateEvent) for emitted in events) == 1
