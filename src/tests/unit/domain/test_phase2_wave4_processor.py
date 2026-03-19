"""Tests for Phase 2 Wave 4: SessionProcessor control channel integration."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from src.domain.events.agent_events import AgentErrorEvent
from src.domain.model.agent.tool_policy import ControlMessageType
from src.domain.ports.agent.control_channel_port import ControlMessage
from src.infrastructure.agent.processor.processor import (
    ProcessorConfig,
    SessionProcessor,
    ToolDefinition,
)


def _make_processor(
    *,
    control_channel: AsyncMock | None = None,
    run_id: str | None = None,
) -> SessionProcessor:
    config = ProcessorConfig(
        model="test-model",
        control_channel=control_channel,
        run_id=run_id,
    )
    dummy_tool = ToolDefinition(
        name="test_tool",
        description="noop",
        parameters={"type": "object", "properties": {}},
        execute=AsyncMock(return_value="ok"),
    )
    return SessionProcessor(config=config, tools=[dummy_tool])


def _make_control_channel() -> AsyncMock:
    channel = AsyncMock()
    channel.consume_control = AsyncMock(return_value=[])
    channel.check_control = AsyncMock(return_value=None)
    channel.send_control = AsyncMock(return_value=True)
    channel.cleanup = AsyncMock()
    return channel


@pytest.mark.unit
class TestCheckControlChannelNone:
    async def test_returns_empty_when_no_channel(self) -> None:
        proc = _make_processor(control_channel=None, run_id=None)
        result = await proc._check_control_channel([])  # pyright: ignore[reportPrivateUsage]
        assert result == []

    async def test_returns_empty_when_no_run_id(self) -> None:
        channel = _make_control_channel()
        proc = _make_processor(control_channel=channel, run_id=None)
        result = await proc._check_control_channel([])  # pyright: ignore[reportPrivateUsage]
        assert result == []
        channel.consume_control.assert_not_awaited()

    async def test_returns_empty_when_no_messages(self) -> None:
        channel = _make_control_channel()
        proc = _make_processor(control_channel=channel, run_id="run-1")
        result = await proc._check_control_channel([])  # pyright: ignore[reportPrivateUsage]
        assert result == []
        channel.consume_control.assert_awaited_once_with("run-1")


@pytest.mark.unit
class TestCheckControlChannelKill:
    async def test_kill_sets_abort_event(self) -> None:
        channel = _make_control_channel()
        kill_msg = ControlMessage(
            run_id="run-1",
            message_type=ControlMessageType.KILL,
            payload="timeout exceeded",
            sender_id="parent",
        )
        channel.consume_control.return_value = [kill_msg]

        proc = _make_processor(control_channel=channel, run_id="run-1")
        abort = asyncio.Event()
        proc._abort_event = abort  # pyright: ignore[reportPrivateUsage]

        events = await proc._check_control_channel([])  # pyright: ignore[reportPrivateUsage]

        assert len(events) == 1
        assert isinstance(events[0], AgentErrorEvent)
        assert events[0].code == "KILLED"
        assert "timeout exceeded" in events[0].message
        assert abort.is_set()

    async def test_kill_with_empty_payload_uses_default(self) -> None:
        channel = _make_control_channel()
        kill_msg = ControlMessage(
            run_id="run-1",
            message_type=ControlMessageType.KILL,
        )
        channel.consume_control.return_value = [kill_msg]

        proc = _make_processor(control_channel=channel, run_id="run-1")
        events = await proc._check_control_channel([])  # pyright: ignore[reportPrivateUsage]

        assert len(events) == 1
        assert events[0].message == "Killed by parent agent"  # type: ignore[union-attr]

    async def test_kill_preempts_steer(self) -> None:
        channel = _make_control_channel()
        steer_msg = ControlMessage(
            run_id="run-1",
            message_type=ControlMessageType.STEER,
            payload="focus on X",
        )
        kill_msg = ControlMessage(
            run_id="run-1",
            message_type=ControlMessageType.KILL,
        )
        channel.consume_control.return_value = [steer_msg, kill_msg]

        proc = _make_processor(control_channel=channel, run_id="run-1")
        messages: list[dict[str, str]] = []
        events = await proc._check_control_channel(messages)  # pyright: ignore[reportPrivateUsage]

        assert len(events) == 1
        assert isinstance(events[0], AgentErrorEvent)
        assert events[0].code == "KILLED"
        assert len(messages) == 1


@pytest.mark.unit
class TestCheckControlChannelSteer:
    async def test_steer_injects_system_message(self) -> None:
        channel = _make_control_channel()
        steer_msg = ControlMessage(
            run_id="run-1",
            message_type=ControlMessageType.STEER,
            payload="focus on error handling",
        )
        channel.consume_control.return_value = [steer_msg]

        proc = _make_processor(control_channel=channel, run_id="run-1")
        messages: list[dict[str, str]] = []
        events = await proc._check_control_channel(messages)  # pyright: ignore[reportPrivateUsage]

        assert events == []
        assert len(messages) == 1
        assert messages[0]["role"] == "system"
        assert "focus on error handling" in messages[0]["content"]

    async def test_multiple_steer_messages(self) -> None:
        channel = _make_control_channel()
        msgs = [
            ControlMessage(
                run_id="run-1",
                message_type=ControlMessageType.STEER,
                payload=f"instruction {i}",
            )
            for i in range(3)
        ]
        channel.consume_control.return_value = msgs

        proc = _make_processor(control_channel=channel, run_id="run-1")
        messages: list[dict[str, str]] = []
        events = await proc._check_control_channel(messages)  # pyright: ignore[reportPrivateUsage]

        assert events == []
        assert len(messages) == 3
        for i in range(3):
            assert f"instruction {i}" in messages[i]["content"]


@pytest.mark.unit
class TestCheckControlChannelPause:
    async def test_pause_then_resume(self) -> None:
        channel = _make_control_channel()
        pause_msg = ControlMessage(
            run_id="run-1",
            message_type=ControlMessageType.PAUSE,
        )
        channel.consume_control.return_value = [pause_msg]

        proc = _make_processor(control_channel=channel, run_id="run-1")

        resume_msg = ControlMessage(
            run_id="run-1",
            message_type=ControlMessageType.RESUME,
        )

        call_count = 0

        async def consume_side_effect(rid: str) -> list[ControlMessage]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [pause_msg]
            return [resume_msg]

        channel.consume_control = AsyncMock(side_effect=consume_side_effect)

        events = await proc._check_control_channel([])  # pyright: ignore[reportPrivateUsage]
        assert events == []

    async def test_pause_timeout_returns_error(self) -> None:
        channel = _make_control_channel()
        pause_msg = ControlMessage(
            run_id="run-1",
            message_type=ControlMessageType.PAUSE,
        )
        channel.consume_control.return_value = [pause_msg]

        proc = _make_processor(control_channel=channel, run_id="run-1")

        call_count = 0

        async def consume_never_resume(rid: str) -> list[ControlMessage]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [pause_msg]
            return []

        channel.consume_control = AsyncMock(side_effect=consume_never_resume)

        with patch("asyncio.sleep", new_callable=AsyncMock):
            events = await proc._wait_for_resume(timeout=2.0)  # pyright: ignore[reportPrivateUsage]

        assert events is False

    async def test_kill_during_pause(self) -> None:
        channel = _make_control_channel()
        proc = _make_processor(control_channel=channel, run_id="run-1")
        abort = asyncio.Event()
        proc._abort_event = abort  # pyright: ignore[reportPrivateUsage]

        kill_msg = ControlMessage(
            run_id="run-1",
            message_type=ControlMessageType.KILL,
            payload="urgent",
        )

        call_count = 0

        async def consume_with_kill(rid: str) -> list[ControlMessage]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return []
            return [kill_msg]

        channel.consume_control = AsyncMock(side_effect=consume_with_kill)

        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await proc._wait_for_resume(timeout=5.0)  # pyright: ignore[reportPrivateUsage]

        assert result is False
        assert abort.is_set()


@pytest.mark.unit
class TestCheckControlChannelError:
    async def test_exception_returns_empty(self) -> None:
        channel = _make_control_channel()
        channel.consume_control.side_effect = ConnectionError("redis down")

        proc = _make_processor(control_channel=channel, run_id="run-1")
        events = await proc._check_control_channel([])  # pyright: ignore[reportPrivateUsage]

        assert events == []


@pytest.mark.unit
class TestProcessorConfigControlFields:
    def test_config_defaults_none(self) -> None:
        config = ProcessorConfig(model="test")
        assert config.control_channel is None
        assert config.run_id is None

    def test_config_accepts_channel(self) -> None:
        channel = _make_control_channel()
        config = ProcessorConfig(model="test", control_channel=channel, run_id="run-x")
        assert config.control_channel is channel
        assert config.run_id == "run-x"


@pytest.mark.unit
class TestProcessorFactoryControlChannel:
    def test_factory_wires_control_channel(self) -> None:
        from src.domain.model.agent.subagent import AgentModel, AgentTrigger, SubAgent
        from src.infrastructure.agent.processor.factory import ProcessorFactory

        channel = _make_control_channel()
        factory = ProcessorFactory(
            base_model="test-model",
            control_channel=channel,
        )

        subagent = SubAgent(
            id="sa-1",
            tenant_id="t-1",
            name="test-agent",
            display_name="Test Agent",
            system_prompt="do stuff",
            trigger=AgentTrigger(description="test trigger"),
            model=AgentModel.INHERIT,
            temperature=0.0,
            max_tokens=1000,
            max_iterations=10,
            allowed_tools=[],
        )
        dummy_tool = ToolDefinition(
            name="t",
            description="t",
            parameters={"type": "object", "properties": {}},
            execute=AsyncMock(),
        )

        processor = factory.create_for_subagent(subagent, [dummy_tool], run_id="run-42")

        assert processor.config.control_channel is channel
        assert processor.config.run_id == "run-42"

    def test_factory_defaults_no_channel(self) -> None:
        from src.domain.model.agent.subagent import AgentModel, AgentTrigger, SubAgent
        from src.infrastructure.agent.processor.factory import ProcessorFactory

        factory = ProcessorFactory(base_model="test-model")
        subagent = SubAgent(
            id="sa-2",
            tenant_id="t-1",
            name="test",
            display_name="Test",
            system_prompt="do stuff",
            trigger=AgentTrigger(description="test trigger"),
            model=AgentModel.INHERIT,
            temperature=0.0,
            max_tokens=1000,
            max_iterations=10,
            allowed_tools=[],
        )
        dummy_tool = ToolDefinition(
            name="t",
            description="t",
            parameters={"type": "object", "properties": {}},
            execute=AsyncMock(),
        )

        processor = factory.create_for_subagent(subagent, [dummy_tool])

        assert processor.config.control_channel is None
        assert processor.config.run_id is None
